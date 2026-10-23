"""Bounded OpenRouter dictionary embeddings; no generation and no implicit retry."""
from __future__ import annotations
import contextlib, fcntl, json, math, os, subprocess, sys, time, uuid, threading
from pathlib import Path
import process_song_gemini as transport_helpers

MODEL = 'google/gemini-embedding-001'
DIMENSIONS = 768
MAX_INPUT_BYTES = 2048
PRICE_PER_TOKEN = .15 / 1_000_000
URL = 'https://openrouter.ai/api/v1/embeddings'


_LOCKS = {}
_LOCKS_GUARD = threading.Lock()

@contextlib.contextmanager
def file_lock(path):
    path=Path(path).resolve();path.parent.mkdir(parents=True,exist_ok=True)
    with _LOCKS_GUARD: local=_LOCKS.setdefault(str(path),threading.RLock())
    with local, open(path,'a') as lock:
        os.chmod(path,0o600);fcntl.flock(lock,fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(lock,fcntl.LOCK_UN)

def validate_response(result, count, dimensions):
    if not isinstance(result, dict) or result.get('model') not in {MODEL, 'gemini-embedding-001'}:
        raise ValueError('embedding response model differs from requested space')
    rows = result.get('data')
    if not isinstance(rows, list) or len(rows) != count:
        raise ValueError('embedding response cardinality differs')
    by_index = {}
    for row in rows:
        if not isinstance(row, dict) or type(row.get('index')) is not int or row['index'] in by_index:
            raise ValueError('embedding response has invalid or duplicate index')
        vector = row.get('embedding')
        validate_vector(vector, dimensions)
        by_index[row['index']] = vector
    if set(by_index) != set(range(count)):
        raise ValueError('embedding response indices differ from inputs')
    return [by_index[index] for index in range(count)]


def validate_vector(vector, dimensions):
    if (not isinstance(vector, list) or len(vector) != dimensions
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in vector)
            or not any(vector)):
        raise ValueError('embedding vector must be finite, nonzero and in the declared dimension')


def http_transport(payload, response_path, timeout):
    deadline=time.monotonic()+timeout
    key = transport_helpers._secure_key('OPENROUTER_API_KEY', 'OPENROUTER_API_KEY_FILE',
        transport_helpers.DEFAULT_KEY, 'OpenRouter')
    job = {'url': URL, 'payload': payload,
           'headers': transport_helpers.request_headers('openrouter', key),
           'response_path': str(response_path), 'timeout': timeout}
    remaining=deadline-time.monotonic()
    if remaining<=0:raise TimeoutError('embedding deadline expired before worker launch')
    job['timeout']=remaining
    worker = subprocess.Popen([sys.executable, '-c', transport_helpers._BOUNDED_HTTP_WORKER],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        stdout, _ = worker.communicate(json.dumps(job).encode(), timeout=max(.001,deadline-time.monotonic()))
        if worker.returncode:
            raise RuntimeError('embedding worker failed; upstream outcome may be unknown')
        status = json.loads(stdout)['http_status']
        if status != 200:
            raise RuntimeError(f'embedding HTTP {status}; exact response retained')
        return json.loads(response_path.read_bytes())
    finally:
        if worker.poll() is None:
            worker.kill(); worker.communicate()


class EmbeddingClient:
    def __init__(self, ledger, *, budget_usd, max_calls, deadline_at, transport=None):
        if (type(budget_usd) not in (int,float) or not math.isfinite(budget_usd) or budget_usd <= 0
                or type(max_calls) is not int or max_calls <= 0
                or type(deadline_at) not in (int,float) or not math.isfinite(deadline_at)):
            raise ValueError('embedding dispatch needs positive budget/call cap and absolute deadline')
        self.ledger = Path(ledger).resolve(); self.budget = budget_usd
        self.max_calls = max_calls; self.transport = transport or http_transport; self.deadline=deadline_at
        with file_lock(self.ledger.with_suffix(self.ledger.suffix+'.dispatch.lock')):
            with self._locked_ledger() as state:
                if (state.get('embedding_model', MODEL) != MODEL or state.get('max_calls', max_calls) != max_calls
                        or any(row.get('model') != MODEL for row in state['requests'])):
                    raise RuntimeError('embedding ledger model/call allowance changed')
                self.deadline = min(deadline_at, state.get('deadline_at', deadline_at))
                state.update(embedding_model=MODEL, max_calls=max_calls, deadline_at=self.deadline)
                self._hold_unfinished(state)

    @staticmethod
    def _hold_unfinished(state):
        for row in state['requests']:
            if row.get('status') in {'reserved','dispatched'}:
                state['blocked']=True
                row.update(status='unknown-outcome',error='Prior process left unfinished request; explicit reconciliation required')

    @contextlib.contextmanager
    def _locked_ledger(self):
        with file_lock(self.ledger.with_suffix(self.ledger.suffix+'.lock')):
            if self.ledger.exists():
                state=json.loads(self.ledger.read_text())
                if (state.get('version')!=1 or state.get('kind')!='bhakti-embedding'
                        or state.get('budget_usd')!=self.budget or state.get('embedding_model')!=MODEL
                        or state.get('dimensions')!=DIMENSIONS or state.get('max_calls')!=self.max_calls
                        or not isinstance(state.get('requests'),list)
                        or type(state.get('deadline_at')) not in (int,float) or not math.isfinite(state['deadline_at'])):
                    raise RuntimeError('embedding ledger identity/allowance differs; review before reuse')
            else:
                state={'version':1,'kind':'bhakti-embedding','budget_usd':self.budget,
                       'embedding_model':MODEL,'dimensions':DIMENSIONS,'max_calls':self.max_calls,
                       'deadline_at':self.deadline,'requests':[],'blocked':False}
            self.deadline=min(self.deadline,state['deadline_at'])
            yield state
            transport_helpers._private_json(self.ledger,state)

    def embed(self, texts):
        # This separate cross-process gate spans dispatch and outcome. A waiting
        # caller observes the first failure's blocked ledger before it can send.
        with file_lock(self.ledger.with_suffix(self.ledger.suffix+'.dispatch.lock')):
            return self._embed(texts)

    def _embed(self, texts):
        # A previously constructed client can also outlive an interrupted sibling.
        with self._locked_ledger() as state:
            self._hold_unfinished(state)
        if (not isinstance(texts, list) or not 1 <= len(texts) <= 16
                or any(not isinstance(text, str) or not text.strip()
                       or len(text.encode('utf-8')) > MAX_INPUT_BYTES for text in texts)):
            raise ValueError('embedding batch needs 1–16 nonempty inputs of at most2048 UTF8bytes; never truncate')
        payload = {'model': MODEL, 'input': texts, 'dimensions': DIMENSIONS, 'encoding_format': 'float',
                   'provider': {'only': ['google-vertex'], 'allow_fallbacks': False,
                                'max_price': {'prompt': .15}}}
        token_bound = sum(len(text.encode('utf-8')) for text in texts) + 512 * len(texts)
        reservation = math.ceil(token_bound * PRICE_PER_TOKEN * 1e10) / 1e10
        request_id = uuid.uuid4().hex
        artifacts = self.ledger.parent / (self.ledger.stem + '-responses')
        artifacts.mkdir(mode=0o700, parents=True, exist_ok=True)
        response_path = artifacts / (request_id + '.response.json')
        with self._locked_ledger() as state:
            if state.get('blocked') or time.time() >= self.deadline:
                raise RuntimeError('embedding run blocked or absolute deadline expired')
            if len(state['requests']) >= self.max_calls:
                raise RuntimeError('embedding request cap reached before dispatch')
            committed = sum(row.get('reported_cost_usd', row['reservation_usd']) for row in state['requests'])
            if committed + reservation > self.budget:
                raise RuntimeError('embedding budget exhausted before dispatch')
            state['requests'].append({'id':request_id, 'status':'reserved','model':MODEL,
                'reservation_usd':reservation,'input_token_upper_bound':token_bound,
                'response_path':str(response_path),'started_at':time.time()})
        try:
            transport_helpers._private_json(artifacts / (request_id + '.request.json'), payload)
            with self._locked_ledger() as state:
                if state.get('blocked') or time.time() >= self.deadline:
                    raise RuntimeError('embedding run blocked before send')
                next(row for row in state['requests'] if row['id']==request_id)['status']='dispatched'
            remaining=min(60,self.deadline-time.time())
            if remaining<=0:raise RuntimeError('embedding deadline expired before transport')
            result = self.transport(payload, response_path, remaining)
            # Billing evidence is independent of vector/schema validity. Preserve it
            # even when the exact raw response subsequently fails qualification.
            usage=result.get('usage',{}) if isinstance(result,dict) else {}
            if isinstance(usage,dict):
                with self._locked_ledger() as state:
                    row=next(row for row in state['requests'] if row['id']==request_id)
                    row['usage']=usage
                    cost=usage.get('cost')
                    if type(cost) in (int,float) and math.isfinite(cost) and cost>=0:row['reported_cost_usd']=cost
            # A test transport also writes this exact artifact; real HTTP worker persists raw bytes first.
            vectors = validate_response(result, len(texts), DIMENSIONS)
            if time.time() >= self.deadline:
                raise RuntimeError('embedding completed after absolute deadline; result retained')
            with self._locked_ledger() as state:
                row = next(row for row in state['requests'] if row['id']==request_id)
                row.update(status='validated', completed_at=time.time())
            return vectors
        except Exception as exc:
            with self._locked_ledger() as state:
                state['blocked']=True
                next(row for row in state['requests'] if row['id']==request_id).update(
                    status='unknown-outcome' if not response_path.exists() else 'invalid-response',
                    error=type(exc).__name__)
            raise RuntimeError('embedding request failed; evidence/reservation retained and run blocked') from exc

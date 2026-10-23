"""One bounded spending/deadline context for production intake workers.

The Gemini client owns reservations and charges. This module owns only stable
run identity, existing-limit validation and the process environment lifecycle.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import time
import uuid
from typing import Any

import bhakti_model_routes as routes
import process_song_gemini as gemini
import resolve_youtube_music_audio as ytmusic

_ENV_KEYS = ('BHAKTI_API_RUN_LEDGER', 'BHAKTI_API_RUN_BUDGET_USD', 'BHAKTI_API_RUN_MAX_CALLS')
_OWNER = threading.Lock()
_DEFAULT_BUDGET = 1.0
_DEFAULT_CALLS = 128
_DEFAULT_SECONDS = 1800.0


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f'invalid intake state: {path.name}')
    return value


def _private(path: Path, root: Path) -> None:
    if path.is_relative_to(root) and '.transcription' not in path.relative_to(root).parts:
        raise ValueError('intake run state must be private, outside public source paths')


def _positive(value: Any, name: str, *, integer: bool = False) -> float | int:
    if isinstance(value, bool):
        raise ValueError(f'{name} must be positive')
    try:
        result = int(value) if integer else float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{name} must be positive') from exc
    if (not math.isfinite(result) or result <= 0
            or (integer and str(result) != str(value))):
        raise ValueError(f'{name} must be a positive {"integer" if integer else "number"}')
    return result


def _inputs(root: Path, jobs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    frozen, references = [], []
    for job in sorted(jobs, key=lambda row: row['slug']):
        value = ytmusic.canonicalize_reference(str(job['source']))
        row = dict(job)
        path = Path(value).expanduser()
        # Match existing intake: a non-URL that is not a local file is a
        # supported resolver query, not an erroneous local-file requirement.
        if not value.startswith(('https://', 'http://')) and path.exists():
            path = path.resolve()
            if not path.is_file():
                raise ValueError(f'intake source is not a file: {job["slug"]}')
            value = str(path)
            original = path
            owned = root / 'songs' / job['slug']
            if path.parent == owned and path.name.startswith('audio.'):
                manifest = _read(owned / '.transcription' / 'trim-originals.json')
                if manifest:
                    source = next((item for item in manifest.get('sources', [])
                                   if item.get('src') == path.name), None)
                    original = owned / '.transcription' / 'original-audio' / path.name
                    if (manifest.get('version') != 2 or not source or not original.is_file()
                            or hashlib.sha256(original.read_bytes()).hexdigest() != source.get('sha256')):
                        raise ValueError('preserved intake source identity changed')
            row['source_sha256'] = hashlib.sha256(original.read_bytes()).hexdigest()
        row['source'] = value
        frozen.append(row)
        references.append({'slug': job['slug'], 'source': value})
    return frozen, references


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


_UNSETTLED = {'reserved', 'dispatched', 'response-received', 'unknown-outcome'}


def _receipt(record: dict[str, Any]) -> dict[str, Any]:
    # This is a retained-history receipt, never an independent spend counter.
    # Unsettled rows can be reconciled; their immutable reservation identities
    # remain bound while finalized rows must be preserved in full.
    return {'ledger_id': record.get('intake_ledger_id'), 'prefix': [
        {'identity': _hash({key: row[key] for key in (
            'id', 'model', 'reservation_usd', 'started_at', 'input_bytes_bound',
            'max_tokens', 'unit_context') if key in row}),
         'settled': None if row.get('status') in _UNSETTLED else _hash(row)}
        for row in record.get('requests', [])]}


def _check_receipt(receipt: dict[str, Any], record: dict[str, Any]) -> None:
    current = _receipt(record)
    if receipt.get('ledger_id') != current['ledger_id']:
        raise ValueError('intake ledger identity changed; no spending reset')
    prefix = receipt.get('prefix')
    if not isinstance(prefix, list) or len(current['prefix']) < len(prefix):
        raise ValueError('intake ledger history was removed; no spending reset')
    for old, new in zip(prefix, current['prefix']):
        if (old.get('identity') != new['identity']
                or (old.get('settled') is not None and old['settled'] != new['settled'])):
            raise ValueError('intake ledger retained history changed; no spending reset')


def _check_ledger(record: dict[str, Any]) -> None:
    if not record:
        return
    if record.get('version') != 1 or record.get('blocked'):
        raise ValueError('bounded intake ledger is blocked or incompatible; preserve existing evidence')
    requests = record.get('requests')
    if not isinstance(requests, list):
        raise ValueError('invalid existing intake ledger requests')
    for request in requests:
        if not isinstance(request, dict) or request.get('status') in _UNSETTLED:
            raise ValueError('unsettled request requires reconciliation before intake resume')
        charge = request.get('reported_cost_usd', request.get('reservation_usd'))
        if type(charge) not in (float, int) or not math.isfinite(charge) or charge < 0:
            raise ValueError('invalid existing intake charge')
    if record.get('max_calls') is None and requests:
        raise ValueError('used unlimited ledger needs explicit reconciliation; cannot reset its call limit')


@contextmanager
def bounded_intake_run(root: Path, jobs: list[dict[str, Any]], options: Any):
    """Set up once before all workers; never renew a resumed allowance."""
    if getattr(options, 'generate_only', False):
        yield None
        return
    if not _OWNER.acquire(blocking=False):
        raise ValueError('another intake owns this process environment')
    previous = {key: os.environ.get(key) for key in _ENV_KEYS}
    old_options = {key: getattr(options, key, None) for key in ('unit_deadline_at', 'boundary_deadline_at', 'timing_deadline_at')}
    try:
        if getattr(options, 'economy', False) or str(options.model).endswith(':batch'):
            raise ValueError('bounded intake does not yet support text Batch accounting; --economy was not dispatched')
        if gemini.provider_name() != 'openrouter':
            raise ValueError('bounded audio intake requires the OpenRouter provider')
        routes.model_pricing(gemini.batch_base_model(options.model), 0)
        root = root.resolve()
        frozen, references = _inputs(root, jobs)
        configured = previous['BHAKTI_API_RUN_LEDGER']
        ledger = Path(configured).expanduser().resolve() if configured else None
        reference_hash = hashlib.sha256(json.dumps(references, sort_keys=True).encode()).hexdigest()
        default_dir = ledger.parent / (ledger.stem + '-intake-run') if ledger else root / '.transcription' / 'intake-runs' / reference_hash
        state_dir = Path(getattr(options, 'run_dir', None) or default_dir).expanduser().resolve()
        ledger = ledger or state_dir / 'api-ledger.json'
        _private(state_dir, root)
        _private(ledger, root)
        state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (state_dir / '.execution.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError('another coordinator owns this intake run') from exc
            try:
                run_path = state_dir / 'run.json'
                prior = _read(run_path)
                if prior and not ledger.is_file():
                    raise ValueError('intake ledger is missing; retained run cannot renew its allowance')
                existing = _read(ledger)
                _check_ledger(existing)
                if prior:
                    receipt = prior.get('ledger_receipt')
                    if not isinstance(receipt, dict) or not receipt.get('ledger_id'):
                        raise ValueError('intake run lacks ledger identity evidence; reconciliation required')
                    _check_receipt(receipt, existing)
                observed_receipt = _receipt(existing)
                old_identity = prior.get('identity', {})
                limits = {}
                for key, env_key, default, integer in (
                        ('budget_usd', 'BHAKTI_API_RUN_BUDGET_USD', _DEFAULT_BUDGET, False),
                        ('max_calls', 'BHAKTI_API_RUN_MAX_CALLS', _DEFAULT_CALLS, True)):
                    stored = existing.get(key, old_identity.get(key))
                    explicit = getattr(options, key, None)
                    env_value = previous[env_key]
                    chosen = explicit if explicit is not None else env_value if env_value is not None else stored if stored is not None else default
                    chosen = _positive(chosen, key, integer=integer)
                    for authoritative in (stored, env_value, old_identity.get(key)):
                        if authoritative is not None and _positive(authoritative, key, integer=integer) != chosen:
                            raise ValueError(f'intake {key} differs from the existing limit; no spending reset')
                    limits[key] = chosen
                requested_seconds = getattr(options, 'deadline_seconds', None)
                seconds = _positive(_DEFAULT_SECONDS if requested_seconds is None else requested_seconds, 'deadline_seconds')
                identity = {'version': 1, 'ledger': str(ledger), 'jobs': frozen, 'model': options.model,
                            'source_witness_audit': bool(getattr(options, 'source_witness_audit', False)),
                            'refresh_timing': bool(getattr(options, 'refresh_timing', False)),
                            'force': bool(getattr(options, 'force', False)),
                            'semantic_repair_rounds': getattr(options, 'semantic_repair_rounds', 2), **limits}
                if prior and (prior.get('version') != 1 or old_identity != identity):
                    raise ValueError('frozen intake inputs or limits changed; existing evidence retained')
                deadlines = [time.time() + seconds]
                for value in (prior.get('deadline_at'), existing.get('deadline_at')):
                    if value is not None:
                        deadlines.append(_positive(value, 'absolute deadline'))
                deadline = min(deadlines)
                if deadline <= time.time():
                    raise ValueError('intake absolute deadline exhausted; resume cannot extend it')
                requests = existing.get('requests', [])
                if len(requests) >= limits['max_calls'] or sum(row.get('reported_cost_usd', row['reservation_usd']) for row in requests) >= limits['budget_usd']:
                    raise ValueError('intake budget or call allowance exhausted; existing ledger retained')
                os.environ['BHAKTI_API_RUN_LEDGER'] = str(ledger)
                os.environ['BHAKTI_API_RUN_BUDGET_USD'] = str(limits['budget_usd'])
                # Initialize a finite cap on a new/unused ledger under its own
                # existing lock; never rewrite a used unlimited ledger.
                os.environ.pop('BHAKTI_API_RUN_MAX_CALLS', None)
                with gemini._locked_run_ledger(ledger, limits['budget_usd']) as record:
                    _check_ledger(record)
                    _check_receipt(observed_receipt, record)
                    if prior:
                        _check_receipt(prior['ledger_receipt'], record)
                    current_limit = record.get('max_calls')
                    if current_limit is not None and current_limit != limits['max_calls']:
                        raise ValueError('authoritative intake call limit changed before lock; not widening it')
                    if len(record['requests']) >= limits['max_calls'] or sum(
                            row.get('reported_cost_usd', row['reservation_usd']) for row in record['requests']) >= limits['budget_usd']:
                        raise ValueError('intake allowance exhausted before lock acquisition')
                    record['max_calls'] = limits['max_calls']
                    record['deadline_at'] = min(deadline, _positive(record.get('deadline_at', deadline), 'absolute deadline'))
                    deadline = record['deadline_at']
                    if deadline <= time.time():
                        raise ValueError('intake absolute deadline exhausted before lock acquisition')
                    record.setdefault('intake_ledger_id', uuid.uuid4().hex)
                    receipt = _receipt(record)
                os.environ['BHAKTI_API_RUN_MAX_CALLS'] = str(limits['max_calls'])
                run = {'version': 1, 'identity': identity, 'deadline_at': deadline, 'ledger_receipt': receipt}
                if run != prior:
                    routes.atomic_json(run_path, run)
                for key in old_options:
                    setattr(options, key, min(deadline, old_options[key]) if old_options[key] is not None else deadline)
                try:
                    yield {'state_dir': str(state_dir), 'ledger': str(ledger), 'deadline_at': deadline, **limits}
                finally:
                    # Workers have joined even on coordinator exceptions. Bind
                    # every observed row before the next resume. A hard process
                    # kill before this checkpoint cannot attest unseen rows;
                    # it still cannot recreate a ledger with a new identity.
                    if not ledger.is_file():
                        raise ValueError('intake ledger vanished during execution; preserve run evidence')
                    with gemini._locked_run_ledger(ledger, limits['budget_usd']) as record:
                        _check_receipt(run['ledger_receipt'], record)
                        run['ledger_receipt'] = _receipt(record)
                        routes.atomic_json(run_path, run)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for key, value in old_options.items():
            if value is None:
                options.__dict__.pop(key, None)
            else:
                setattr(options, key, value)
        _OWNER.release()

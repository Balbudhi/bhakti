"""Persisted, bounded stage-level Flash→Pro escalation.

The stage owns source grounding and independent review. This module chooses a
model exactly once per attempt and never declares a failed artifact acceptable.
One coordinator owns each unit identity; the shared transport ledger serializes
money across all units and processes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Callable
import uuid

FLASH_MODEL='google/gemini-3.7-flash'
PRO_MODEL='google/gemini-3.1-pro-preview'
ROUTE_VERSION=1


class RunFatal(RuntimeError):
    def __init__(self, reason: str, *, state_path: Path | None = None):
        self.reason=reason;self.state_path=state_path
        super().__init__(reason)


class QualityFailure(RuntimeError):
    def __init__(self, issues: list[dict[str, Any]]):
        self.issues=issues
        super().__init__('stage quality validation failed')


class UnitTransportFailure(RuntimeError):
    def __init__(self, category: str, *, request_id: str | None = None,
                 worker_terminated: bool = False, detail: str = ''):
        self.category=category;self.request_id=request_id
        self.worker_terminated=worker_terminated;self.detail=detail
        super().__init__(category + (': '+detail if detail else ''))


class UnitUnresolved(RuntimeError):
    def __init__(self, unit_id: str, reason: str, issues: list[dict[str, Any]], state_path: Path):
        self.unit_id=unit_id;self.reason=reason;self.issues=issues;self.state_path=state_path
        super().__init__(f'{unit_id}: {reason}')


@dataclass(frozen=True)
class EscalationPolicy:
    quality_failure: bool = True
    transient_transport: bool = True
    unknown_outcome: bool = True
    flash_time_share: float = .5
    call_timeout_seconds: float = 600.

    def __post_init__(self):
        if any(type(value) is not bool for value in (self.quality_failure,self.transient_transport,self.unknown_outcome)):
            raise RunFatal('invalid escalation policy booleans')
        if (not math.isfinite(self.flash_time_share) or not 0<self.flash_time_share<1
                or not math.isfinite(self.call_timeout_seconds) or not 0<self.call_timeout_seconds<=600):
            raise RunFatal('invalid escalation time allowance')


@dataclass(frozen=True)
class AttemptContext:
    model: str
    attempt_dir: Path
    unit_id: str
    attempt_id: str
    input_fingerprint: str
    dependency_fingerprint: str
    deadline_at: float
    unit_deadline_at: float
    call_timeout_seconds: float
    transport_context: dict[str, Any]


def model_pricing(model: str, input_token_upper_bound: int) -> dict[str, Any]:
    if type(input_token_upper_bound) is not int or input_token_upper_bound<0:
        raise RunFatal('invalid input token upper bound')
    if model==FLASH_MODEL:return {'prompt':.75,'completion':3.75,'tier':'standard'}
    if model==PRO_MODEL:
        return ({'prompt':4.,'completion':18.,'tier':'long-context'} if input_token_upper_bound>=200000
                else {'prompt':2.,'completion':12.,'tier':'standard'})
    raise RunFatal('unsupported bounded model route: '+str(model))


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix='.route-',delete=False) as handle:
            temporary=Path(handle.name)
            json.dump(value,handle,ensure_ascii=False,indent=2,allow_nan=False)
            handle.write('\n');handle.flush();os.fsync(handle.fileno())
        temporary.replace(path)
    except (OSError,ValueError,TypeError) as exc:
        raise RunFatal('route evidence persistence failed: '+type(exc).__name__,state_path=path) from exc
    finally:
        if temporary:temporary.unlink(missing_ok=True)


def _read(path: Path) -> dict:
    try:
        value=json.loads(path.read_text())
        if not isinstance(value,dict):raise ValueError('not object')
        return value
    except (OSError,ValueError) as exc:
        raise RunFatal('route state integrity failure',state_path=path) from exc


def _issues(value: Any) -> list[dict[str,Any]]:
    if not isinstance(value,list) or any(not isinstance(row,dict) or not isinstance(row.get('kind'),str)
            or not row['kind'].strip() or not isinstance(row.get('detail'),str) or not row['detail'].strip() for row in value):
        raise RunFatal('stage validator must return typed issues with kind and detail')
    return value


def _budget_healthy() -> None:
    path=os.environ.get('BHAKTI_API_RUN_LEDGER')
    if not path:return  # A pure/offline executor is allowed; transport requires it.
    try:
        budget=float(os.environ.get('BHAKTI_API_RUN_BUDGET_USD','0'))
        if not math.isfinite(budget) or budget<=0:raise ValueError('budget')
        if not Path(path).exists():return
        ledger=json.loads(Path(path).read_text())
        if ledger.get('version')!=1 or ledger.get('budget_usd')!=budget or ledger.get('blocked'):
            raise ValueError('blocked or invalid ledger')
        costs=[row.get('reported_cost_usd',row['reservation_usd']) for row in ledger['requests']]
        if any(type(cost) not in (int,float) or not math.isfinite(cost) or cost<0 for cost in costs):raise ValueError('cost')
        if sum(costs)>=budget:raise RunFatal('budget_exhausted')
    except RunFatal:raise
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise RunFatal('global budget/ledger is not healthy') from exc


def validate_transport_context(context: dict[str, Any], model: str) -> dict[str, Any]:
    if not isinstance(context,dict):raise RunFatal('invalid unit transport context')
    try:
        path=Path(context['state_path'])
        state=_read(path)
        attempt=next(row for row in state['attempts'] if row['attempt_id']==context['attempt_id'])
        if (context.get('version')!=ROUTE_VERSION or state.get('version')!=ROUTE_VERSION
                or state.get('status')!='running' or attempt.get('status')!='running'
                or model!=context.get('model') or model!=attempt.get('model')
                or context.get('unit_id')!=state.get('unit_id')
                or context.get('input_fingerprint')!=state.get('input_fingerprint')
                or context.get('dependency_fingerprint')!=state.get('dependency_fingerprint')
                or context.get('deadline_at')!=attempt.get('deadline_at')):
            raise RunFatal('unit transport context does not match active attempt')
        return context
    except (KeyError,TypeError,StopIteration) as exc:
        raise RunFatal('invalid or missing unit attempt context') from exc


def run_unit(state_dir: Path, unit_id: str, input_fingerprint: str,
             execute: Callable[[AttemptContext],dict], validate: Callable[[dict],list[dict]], *,
             deadline_at: float, dependency_fingerprint: str | None = None,
             base_model: str = FLASH_MODEL, pro_model: str = PRO_MODEL,
             policy: EscalationPolicy = EscalationPolicy()) -> dict:
    model_pricing(base_model,0);model_pricing(pro_model,0)
    if not isinstance(policy,EscalationPolicy):raise RunFatal('typed escalation policy required')
    dependency_fingerprint=dependency_fingerprint or input_fingerprint
    if any(not isinstance(value,str) or not value for value in (unit_id,input_fingerprint,dependency_fingerprint)):
        raise RunFatal('unit and input/dependency fingerprints required')
    if not math.isfinite(deadline_at):raise RunFatal('invalid unit deadline')
    identity={'version':ROUTE_VERSION,'unit_id':unit_id,'input_fingerprint':input_fingerprint,
              'dependency_fingerprint':dependency_fingerprint,'base_model':base_model,'pro_model':pro_model,
              'policy':asdict(policy)}
    directory=Path(state_dir)/_digest(identity);state_path=directory/'route-state.json'
    if state_path.exists():
        state=_read(state_path)
        if any(state.get(key)!=value for key,value in identity.items()):raise RunFatal('route identity mismatch',state_path=state_path)
        if state.get('status')=='accepted':
            result=_read(directory/'accepted-result.json')
            if _digest(result)!=state.get('accepted_sha256'):raise RunFatal('accepted result digest mismatch',state_path=state_path)
            return result
        if state.get('status')=='run-fatal':raise RunFatal(state.get('reason','previous run-fatal'),state_path=state_path)
        if state.get('status')=='unresolved':raise UnitUnresolved(unit_id,state.get('reason','unresolved'),state.get('issues',[]),state_path)
        if any(row.get('status')=='running' for row in state.get('attempts',[])):
            raise UnitUnresolved(unit_id,'interrupted attempt requires evidence/liveness reconciliation',[],state_path)
        state['deadline_at']=min(state['deadline_at'],deadline_at)
        state['flash_deadline_at']=min(state['flash_deadline_at'],state['deadline_at'])
    else:
        now=time.time()
        if deadline_at<=now:raise UnitUnresolved(unit_id,'unit deadline exhausted',[],state_path)
        state={**identity,'status':'ready','deadline_at':deadline_at,
               'flash_deadline_at':now+(deadline_at-now)*policy.flash_time_share,'attempts':[]}
        atomic_json(state_path,state)
    models=[base_model]+([pro_model] if pro_model!=base_model else [])
    while len(state['attempts'])<len(models):
        if time.time()>=state['deadline_at']:
            state.update(status='unresolved',reason='unit deadline exhausted');atomic_json(state_path,state)
            raise UnitUnresolved(unit_id,state['reason'],state.get('issues',[]),state_path)
        try:_budget_healthy()
        except RunFatal as exc:
            state.update(status='run-fatal',reason=exc.reason);atomic_json(state_path,state);raise
        index=len(state['attempts']);model=models[index]
        cutoff=state['flash_deadline_at'] if index==0 and len(models)>1 else state['deadline_at']
        if cutoff<=time.time():
            # No paid Flash was dispatched; do not invent a quality failure to
            # spend Pro. The unit needs a new explicitly budgeted invocation.
            state.update(status='unresolved',reason='attempt allowance expired before dispatch');atomic_json(state_path,state)
            raise UnitUnresolved(unit_id,state['reason'],[],state_path)
        attempt_id=uuid.uuid4().hex;attempt_dir=directory/('flash' if index==0 else 'pro')
        try:attempt_dir.mkdir(parents=True,exist_ok=True)
        except OSError as exc:
            raise RunFatal('attempt directory creation failed',state_path=state_path) from exc
        record={'attempt_id':attempt_id,'model':model,'status':'running','deadline_at':cutoff,'started_at':time.time()}
        state['attempts'].append(record);state['status']='running';atomic_json(state_path,state)
        context={'version':ROUTE_VERSION,'state_path':str(state_path.resolve()),'unit_id':unit_id,
                 'attempt_id':attempt_id,'input_fingerprint':input_fingerprint,'dependency_fingerprint':dependency_fingerprint,
                 'model':model,'deadline_at':cutoff}
        ctx=AttemptContext(model,attempt_dir,unit_id,attempt_id,input_fingerprint,dependency_fingerprint,
                           cutoff,state['deadline_at'],policy.call_timeout_seconds,context)
        eligible=False;issues=[]
        try:
            candidate=execute(ctx)
            if not isinstance(candidate,dict):raise RunFatal('stage executor must return artifact object')
            atomic_json(attempt_dir/'candidate.json',candidate)
            issues=_issues(validate(copy.deepcopy(candidate)))
            if issues:raise QualityFailure(issues)
            atomic_json(directory/'accepted-result.json',candidate)
            record.update(status='accepted',finished_at=time.time(),candidate_sha256=_digest(candidate))
            state.update(status='accepted',accepted_sha256=_digest(candidate),accepted_model=model)
            atomic_json(state_path,state)
            return candidate
        except QualityFailure as exc:
            issues=_issues(exc.issues)
            if not issues:raise RunFatal('empty quality failure') from exc
            record.update(status='quality-failed',issues=issues,finished_at=time.time())
            eligible=policy.quality_failure and not any(row['kind'] in {'locked_baseline_conflict','missing_source_evidence'} for row in issues)
            reason='quality failure'
        except UnitTransportFailure as exc:
            record.update(status='transport-failed',category=exc.category,request_id=exc.request_id,
                          worker_terminated=exc.worker_terminated,detail=exc.detail,finished_at=time.time())
            if exc.category=='unknown-outcome':eligible=policy.unknown_outcome and exc.worker_terminated
            else:eligible=policy.transient_transport and exc.category in {'http-transient','invalid-model-output','attempt-deadline'}
            reason=exc.category
        except RunFatal as exc:
            record.update(status='run-fatal',reason=exc.reason,finished_at=time.time())
            state.update(status='run-fatal',reason=exc.reason);atomic_json(state_path,state);raise
        except Exception as exc:
            record.update(status='integration-failed',reason=type(exc).__name__,finished_at=time.time())
            reason='unclassified stage exception: '+type(exc).__name__;eligible=False
        state['issues']=issues;state['reason']=reason
        if not eligible or len(state['attempts'])>=len(models):
            state['status']='unresolved';atomic_json(state_path,state)
            raise UnitUnresolved(unit_id,reason,issues,state_path)
        state['status']='escalating';atomic_json(state_path,state)
    raise UnitUnresolved(unit_id,'attempts exhausted',state.get('issues',[]),state_path)

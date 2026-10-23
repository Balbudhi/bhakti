"""Read-only reconciliation of pre-contract source-audio observations.

No provider calls and no legacy writes. Missing evidence is a hold, never a new
paid allowance. Only exact supported historical requests may be adopted.
"""
from __future__ import annotations
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import bhakti_legacy_audio_contract as legacy
import bhakti_model_routes as routes
import process_song_gemini as client


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class LegacyHold(ValueError):
    pass


def _inside(path, root):
    path=Path(path).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise LegacyHold('legacy evidence path leaves its private root')
    return path


def index_history(route_dir, slug, *, ledger_paths=()):
    """Index known history before filtering untrusted state identifiers."""
    root=Path(route_dir).resolve();old_paths=set();new_paths=set();validated={}
    prefix=slug+':source-observation:'
    def bind(path, expected_unit):
        bound=_inside(path,root)
        if not bound.is_file():raise LegacyHold('legacy paid route evidence is missing')
        if bound not in validated:validated[bound]=routes.read_unit_cache(bound)['state']
        state=validated[bound]
        if state['unit_id']!=expected_unit:
            raise LegacyHold('legacy receipt/ledger refers to a different source unit')
        return bound,state

    folder=root/'source-observations'
    for pattern, target in [(f'*/{slug}-source-observed.json',old_paths),
                            (f'*/*/{slug}-source-observed.json',new_paths)]:
        for receipt in folder.glob(pattern):
            record=json.loads(receipt.read_text())
            if not isinstance(record,dict) or record.get('result_digest') != digest(record.get('result')):
                raise LegacyHold('legacy/new observation receipt digest mismatch')
            result=record['result']
            refs=[(r.get('route_state_path'),r.get('unit',{}).get('id'))
                  for r in result.get('unit_results',[])]
            refs += [(r.get('state_path'),r.get('unit_id')) for r in result.get('issues',[])]
            for path,unit in refs:
                if not isinstance(path,str) or not isinstance(unit,str) or not unit:
                    raise LegacyHold('legacy receipt lacks exact route/unit evidence')
                bound,_=bind(path,prefix+unit)
                target.add(bound)
    # A deleted receipt/state cannot erase a charge still recorded in the ledger.
    paths=[os.environ.get('BHAKTI_API_RUN_LEDGER'),root.parent/'api-ledger.json',*ledger_paths]
    for ledger_path in dict.fromkeys(Path(p).resolve() for p in paths if p):
        if not ledger_path.is_file():continue
        ledger=json.loads(ledger_path.read_text())
        for row in ledger.get('requests',[]):
            context=row.get('unit_context') or {}
            if not str(context.get('unit_id','')).startswith(prefix):continue
            path=context.get('state_path')
            if not isinstance(path,str):raise LegacyHold('legacy ledger lacks its paid route path')
            _,state=bind(path,context['unit_id'])
            if any(context.get(k)!=state.get(k) for k in ('input_fingerprint','dependency_fingerprint')):
                raise LegacyHold('legacy ledger identity differs from paid route')
            attempts=[a for a in state.get('attempts',[]) if a.get('attempt_id')==context.get('attempt_id')]
            if len(attempts)!=1 or attempts[0].get('model')!=context.get('model'):
                raise LegacyHold('legacy ledger paid attempt differs from route history')
    for path in root.glob('*/route-state.json'):
        bound=path.resolve()
        if bound in validated:continue
        state=json.loads(path.read_text())
        if isinstance(state,dict) and str(state.get('unit_id','')).startswith(prefix):
            validated[bound]=routes.read_unit_cache(bound)['state']
    return {'states':list(validated.items()),'old_paths':old_paths,'new_paths':new_paths}


def _request_evidence(ledger_paths, state_path, state, result):
    accepted=[a for a in state.get('attempts',[]) if a.get('status')=='accepted']
    if len(accepted)!=1:raise LegacyHold('legacy accepted attempt is ambiguous')
    attempt=accepted[0];matches=[]
    for path in dict.fromkeys(Path(p).resolve() for p in ledger_paths):
        if not path.is_file():continue
        ledger=json.loads(path.read_text())
        for row in ledger.get('requests',[]):
            context=row.get('unit_context') or {}
            if context.get('state_path')==str(state_path) and context.get('attempt_id')==attempt.get('attempt_id'):
                matches.append((path,row))
    if len(matches)!=1:raise LegacyHold('legacy request proof missing or ambiguous; reconcile saved ledger')
    ledger_path,row=matches[0];context=row['unit_context']
    if (row.get('status')!='parsed' or row.get('model')!=attempt.get('model')
            or context.get('model')!=attempt.get('model')
            or any(context.get(k)!=state.get(k) for k in ('unit_id','input_fingerprint','dependency_fingerprint'))):
        raise LegacyHold('legacy ledger request does not match accepted route')
    response=_inside(row['response_path'],ledger_path.parent)
    request=response.with_name(response.name.replace('.response.json','.request.json'))
    if not request.is_file() or not response.is_file():raise LegacyHold('legacy request/response proof missing')
    sent=json.loads(request.read_text());received=json.loads(response.read_text())
    try:packet=client.parse_json_packet(received['choices'][0]['message']['content'])
    except (ValueError,KeyError,IndexError,TypeError,RuntimeError) as exc:raise LegacyHold('legacy response proof is malformed') from exc
    if (packet!=result['segment_audits'][0]['audit']['packet']
            or received.get('model')!=attempt['model'] or sent.get('model')!=attempt['model']):
        raise LegacyHold('legacy response differs from accepted observation')
    return sent,{'request_path':str(request),'request_sha256':_hash(request),
                 'response_path':str(response),'response_sha256':_hash(response),
                 'ledger_path':str(ledger_path),'request_id':row['id']}


def _expected_payload(request, model, audio, segment):
    codec=request['clip'];precision=codec['seek_precision']
    with tempfile.TemporaryDirectory(prefix='bhakti-legacy-proof-') as folder:
        clip=Path(folder)/'clip.m4a'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-ss',f"{segment['clip_start']:.{precision}f}",
            '-i',str(audio),'-t',f"{segment['clip_end']-segment['clip_start']:.{precision}f}",'-vn',
            '-c:a',codec['codec'],'-b:a',codec['bitrate'],str(clip)],check=True)
        encoded,fmt=client.encoded_audio(clip,'openrouter')
    return {'model':model,'temperature':0,'messages':[{'role':'user','content':[
        {'type':'text','text':request['prompt']},
        {'type':'input_audio','input_audio':{'format':fmt,'data':{
            'base64_sha256':hashlib.sha256(encoded.encode()).hexdigest(),'base64_bytes':len(encoded)}}}]}],
        'response_format':{'type':'json_schema','json_schema':{'name':request['schema_name'],'strict':True,'schema':request['response_schema']}},
        'reasoning':{'effort':request['reasoning_effort']},'max_tokens':request['max_completion_tokens']}


def lookup(*, history, unit_id, unit, draft, source_context, source_identity, duration,
           request, witness, audio, route_dir, base_model, pro_model, current_fingerprint,
           current_dependency, ledger_paths=()):
    current_path=routes.unit_state_path(route_dir,unit_id,current_fingerprint,
        dependency_fingerprint=current_dependency,base_model=base_model,pro_model=pro_model)
    if current_path.is_file():return None
    old_dependency=digest({'version':1,'pipeline_sha256':legacy.PIPELINE_SHA,
        'adapter_sha256':legacy.ADAPTER_SHA,'witness':witness})
    matches=[]
    for path,unverified in history['states']:
        if unverified.get('unit_id')!=unit_id:continue
        dependency=unverified.get('dependency_fingerprint')
        is_old=path in history['old_paths'] or dependency==old_dependency
        if not is_old and path in history['new_paths']:continue
        # Unknown orphan history could be an interrupted paid legacy unit.
        cached=routes.read_unit_cache(path);state=cached['state']
        expected=digest({'unit':unit,'draft':draft,'source_identity':source_identity,
            'duration':duration,'dependency':dependency})
        if state['input_fingerprint']!=expected:continue
        if state['base_model']!=base_model or state['pro_model']!=pro_model:continue
        if dependency!=old_dependency:raise LegacyHold('legacy observation contract is unproven; reconcile history before spending')
        if state.get('policy')!=asdict(routes.EscalationPolicy()):
            raise LegacyHold('legacy route policy changed; reconcile paid attempt history')
        if state['status']!='accepted':raise LegacyHold('legacy observation is '+state['status']+'; preserve and reconcile its attempt history')
        result=cached['result']
        paths=[os.environ.get('BHAKTI_API_RUN_LEDGER'),Path(route_dir).parent/'api-ledger.json',*ledger_paths]
        sent,proof=_request_evidence([p for p in paths if p],path,state,result)
        segment={'index':unit['segment_index'],**{k:unit[k] for k in ('clip_start','clip_end','core_start','core_end')}}
        historical=legacy.audio_audit_request_contract(draft,segment,witness=witness['snapshot'],source_context=source_context)
        expected_payload=_expected_payload(historical,state['accepted_model'],audio,segment)
        if {k:v for k,v in sent.items() if k!='provider'}!=expected_payload:
            raise LegacyHold('legacy retained request/audio proof differs from supported contract')
        # Proven old request differs from deliberate current stage contract: new
        # request is warranted; old result remains untouched and is not adopted.
        if historical!=request:continue
        proof.update(version=1,route_state_path=str(path),route_state_sha256=_hash(path),
                     accepted_sha256=state['accepted_sha256'],request_contract_sha256=digest(request))
        matches.append({'result':result,'input_fingerprint':state['input_fingerprint'],
                        'route_state_path':str(path),'legacy_compatibility':proof})
    if len(matches)>1:raise LegacyHold('multiple compatible legacy observations; reconcile before adopting')
    return matches[0] if matches else None

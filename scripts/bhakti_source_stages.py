"""Bounded source operations shared by new intake and missing-reader repair.

The router owns attempts and uncertain outcomes; the provider client owns cost.
Public stage artifacts are projections of validated, retained routed results.
"""
from __future__ import annotations
import copy
import hashlib
import json
import time
from pathlib import Path

import bhakti_model_routes as routes
import bhakti_lexical_retrieval as lexical


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def normalized_source_result(value):
    """Carry a model's explicit line language into the existing reader field."""
    result=copy.deepcopy(value)
    packet=result.get('packet',{}) if isinstance(result,dict) else {}
    if not isinstance(packet,dict):return result
    for field in ('lines','verified_lines'):
        for row in packet.get(field,[]) if isinstance(packet.get(field,[]),list) else []:
            if not isinstance(row,dict):continue
            code=lexical.language(row.get('language'))
            if code and not row.get('sourceLanguage'):
                row['sourceLanguage']=code
    return result


def source_errors(result, *, audited):
    packet = result.get('packet') if isinstance(result, dict) else None
    if not isinstance(packet, dict):
        return [{'kind':'source_structure', 'detail':'source response lacks a packet'}]
    lines = packet.get('verified_lines' if audited else 'lines')
    order = packet.get('performance_order')
    errors = []
    if not isinstance(lines, list) or not lines or not isinstance(order, list) or not order:
        return [{'kind':'source_structure','detail':'source response lacks definitions or performed order'}]
    ids = set()
    for row in lines:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'].strip() or row['id'] in ids:
            errors.append('source definition has a missing or duplicate ID'); continue
        ids.add(row['id'])
        kind = row.get('kind')
        if not isinstance(kind,str) or kind not in {'invocation','refrain','verse','bridge','closing','spoken','instrumental','uncertain'}:
            errors.append('source definition has an unknown section kind')
        if kind != 'instrumental' and any(not isinstance(row.get(k),str) or not row[k].strip() for k in ('source_text','roman')):
            errors.append('vocal source definition lacks text or romanization')
        if audited and kind == 'uncertain':
            errors.append('audited source still has an uncertain section')
        if 'language' in row and not isinstance(row['language'], str):
            errors.append('source language must be text')
        if row.get('language') and row.get('sourceLanguage') and lexical.language(row['language']) != lexical.language(row['sourceLanguage']):
            errors.append('source has incompatible explicit line languages')
    counts = {}; used = set()
    for row in order:
        lid = row.get('line_id') if isinstance(row, dict) else None
        if not isinstance(lid,str) or lid not in ids:
            errors.append('source occurrence references an unknown definition'); continue
        counts[lid] = counts.get(lid,0)+1; used.add(lid)
        if type(row.get('occurrence')) is not int or row['occurrence'] != counts[lid]:
            errors.append('source occurrence count differs from complete performed order')
    if used != ids:
        errors.append('source definitions are missing from the performed order')
    uncertainty = packet.get('uncertainties')
    if not isinstance(uncertainty,list) or any(not isinstance(item,str) for item in uncertainty):
        errors.append('source uncertainty must be an explicit list')
    elif audited and uncertainty:
        errors.append('audited source uncertainty: ' + '; '.join(uncertainty))
    return [{'kind':'source_structure' if 'uncertainty' not in error else 'source_uncertainty','detail':error} for error in errors]


def _state_identity(pipeline, song_dir, audio, stage, inputs, options):
    return digest({'version':1,'stage':stage,'audio_sha256':hashlib.sha256(audio.read_bytes()).hexdigest(),
        'trim':pipeline.read_packet(song_dir/'.transcription/trim-applied.json') or {},
        'inputs':inputs,'request':options.source_stage_request,
        'models':{'base':pipeline.gemini.batch_base_model(options.model),
                  'pro':getattr(options,'pro_model',routes.PRO_MODEL)}})


def _prior_high_identity(pipeline, song_dir, audio, stage, inputs, options):
    """Only accepted evidence for the otherwise identical old request may survive."""
    if options.source_stage_request.get('reasoning_effort') != 'medium':
        return None
    prior = copy.copy(options)
    prior.source_stage_request = {**options.source_stage_request, 'reasoning_effort': 'high'}
    return _state_identity(pipeline, song_dir, audio, stage, inputs, prior)


def _checked_projection(artifact, fingerprint, *, prior_fingerprint=None):
    declaration = artifact.get('_source_route')
    if not isinstance(declaration,dict):
        return None
    saved_fingerprint = declaration.get('input_fingerprint')
    if saved_fingerprint != fingerprint and not (prior_fingerprint and saved_fingerprint == prior_fingerprint):
        raise ValueError('saved source stage inputs changed; preserve original evidence for scoped repair')
    state = Path(declaration['state_path'])
    cached = routes.read_unit_cache(state)
    value = cached['result']
    if (cached['state']['status'] != 'accepted'
            or cached['state']['input_fingerprint'] != saved_fingerprint
            or digest(value) != declaration.get('result_digest')
            or {k:v for k,v in artifact.items() if k != '_source_route'} != value):
        raise ValueError('saved source stage no longer matches its routed evidence')
    return artifact


def _run(pipeline, song_dir, audio, stage, inputs, options, execute):
    filename = '02-transcript-audit.json' if stage == 'audit' else '01-transcript.json'
    target = song_dir/'.transcription/pipeline'/filename
    fingerprint = _state_identity(pipeline,song_dir,audio,stage,inputs,options)
    existing = pipeline.read_packet(target)
    if existing:
        projected = _checked_projection(existing, fingerprint,
            prior_fingerprint=_prior_high_identity(pipeline, song_dir, audio, stage, inputs, options))
        if projected is not None:
            errors=source_errors(projected,audited=stage=='audit')
            if errors:raise ValueError('saved source stage fails current source contract')
            return projected
        # An old first pass is only a working draft. Its independent new audit
        # hears the current recording and must establish the complete source.
        if stage == 'transcript' and not source_errors(existing,audited=False):
            return existing
        legacy = target.parent/'source-legacy'/hashlib.sha256(target.read_bytes()).hexdigest()/filename
        if not legacy.exists():
            legacy.parent.mkdir(parents=True,exist_ok=True);legacy.write_bytes(target.read_bytes())
    deadline = getattr(options,'unit_deadline_at',None)
    if deadline is None or deadline <= time.time():
        raise ValueError('bounded source stage needs an active run deadline')
    state_dir = song_dir/'.transcription/pipeline/source-stages'
    unit_id = 'source:'+stage+':whole'
    def routed(context):
        local=copy.copy(options)
        local.model=context.model;local.force=True
        local.unit_context=context.transport_context;local.unit_deadline_at=context.deadline_at
        local.timeout=context.call_timeout_seconds
        local.source_stage_target=context.attempt_dir/filename
        return normalized_source_result(execute(local))
    result=routes.run_unit(state_dir,unit_id,fingerprint,routed,
        lambda value:source_errors(value,audited=stage=='audit'),deadline_at=deadline,
        base_model=pipeline.gemini.batch_base_model(options.model),
        pro_model=getattr(options,'pro_model',routes.PRO_MODEL))
    if source_errors(result,audited=stage=='audit'):
        raise ValueError('cached routed source fails the current source contract')
    state=routes.unit_state_path(state_dir,unit_id,fingerprint,
        base_model=pipeline.gemini.batch_base_model(options.model),pro_model=getattr(options,'pro_model',routes.PRO_MODEL))
    projected={**result,'_source_route':{'state_path':str(state),'input_fingerprint':fingerprint,'result_digest':digest(result)}}
    routes.atomic_json(target,projected)
    return projected


def transcript(pipeline,song_dir,source,audio,options):
    if pipeline.gemini.duration_seconds(audio)>900:
        # Segment-level routing is the next reviewed dependency, not a
        # whole-recording wrapper that would replay successful segments.
        result=pipeline.transcribe_long_audio(song_dir,source,audio,options)
        pipeline.write_json(song_dir/'.transcription/pipeline/01-transcript.json',result)
        return result
    local=copy.copy(options);local.source_stage_request=pipeline.transcript_request_contract(source)
    return _run(pipeline,song_dir,audio,'transcript',source,local,
                lambda local:pipeline._transcript_once(song_dir,source,audio,local))


def audit(pipeline,song_dir,raw,audio,options):
    if raw.get('packet',{}).get('segmented'):
        result=pipeline.audit_long_transcript(song_dir,raw,audio,options)
        pipeline.write_json(song_dir/'.transcription/pipeline/02-transcript-audit.json',result)
        return result
    if source_errors(raw,audited=False):
        raise ValueError('independent audit needs a structurally valid first draft')
    witness=pipeline.source_witness.acquire(song_dir,song_dir.name)
    local=copy.copy(options);local.source_witness_snapshot=copy.deepcopy(witness)
    local.source_draft_untrusted=not isinstance(raw.get('_source_route'),dict)
    local.source_stage_request=pipeline.audited_source_request_contract(raw,witness,
        untrusted_draft=local.source_draft_untrusted)
    return _run(pipeline,song_dir,audio,'audit',{'draft':raw['packet'],'witness':witness,
                'untrusted_draft':local.source_draft_untrusted},local,
                lambda routed:pipeline._audit_transcript_once(song_dir,raw,audio,routed))


def segment_request(pipeline,song_dir,audio,clip,stage,segment,request,options,*,cached=None,extra_validator=None,allow_legacy_draft=True):
    """Route one exact source segment; successful peers never share retries."""
    local=copy.copy(options);local.source_stage_request=copy.deepcopy(request)
    fingerprint=_state_identity(pipeline,song_dir,audio,stage,{'segment':segment},local)
    audited=stage=='audit-segment'
    def validate(value):
        check=copy.deepcopy(value)
        if audited and isinstance(check,dict) and isinstance(check.get('packet'),dict):
            check['packet']['verified_lines']=check['packet'].get('lines')
        errors=source_errors(check,audited=audited)
        if not errors and extra_validator is not None:
            try:extra_validator(value)
            except (ValueError,RuntimeError) as exc:errors.append({'kind':'source_structure','detail':str(exc)})
        return errors
    if cached:
        projected=_checked_projection(cached, fingerprint,
            prior_fingerprint=_prior_high_identity(pipeline, song_dir, audio, stage, {'segment':segment}, local))
        if projected is not None:
            if validate(projected):raise ValueError('saved source segment fails current source contract')
            return projected
        if not audited and allow_legacy_draft and not validate(cached):
            return cached
    deadline=getattr(options,'unit_deadline_at',None)
    if deadline is None or deadline<=time.time():raise ValueError('bounded source segment needs an active deadline')
    state_dir=song_dir/'.transcription/pipeline/source-stages'
    unit_id=f"source:{stage}:segment-{segment['index']}"
    def execute(context):
        routed=copy.copy(local);routed.model=context.model
        routed.timeout=context.call_timeout_seconds;routed.unit_deadline_at=context.deadline_at
        routed.unit_context=context.transport_context
        result=pipeline.source_request_call(local.source_stage_request,clip,routed)
        return normalized_source_result(result)
    result=routes.run_unit(state_dir,unit_id,fingerprint,execute,validate,deadline_at=deadline,
        base_model=pipeline.gemini.batch_base_model(options.model),pro_model=getattr(options,'pro_model',routes.PRO_MODEL))
    if validate(result):raise ValueError('cached source segment has unresolved source uncertainty')
    state=routes.unit_state_path(state_dir,unit_id,fingerprint,
        base_model=pipeline.gemini.batch_base_model(options.model),pro_model=getattr(options,'pro_model',routes.PRO_MODEL))
    return {**result,'_source_route':{'state_path':str(state),'input_fingerprint':fingerprint,'result_digest':digest(result)}}

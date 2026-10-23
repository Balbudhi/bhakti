"""Compact legacy v1 producer for migration tests (no Git dependency).

Reproduces ee2714a6 identity/receipt layout. Actual requests use the frozen
historical contract, real audio encoder, router, HTTP worker and ledger writer.
This fixture was checked against the pinned original producer before replacing
that temporary test scaffold; it does not certify model hearing quality.
"""
import copy
from unittest.mock import patch
import bhakti_legacy_audio_contract as legacy
import bhakti_model_routes as routes
import bhakti_library_pass as library


def produce(f, pipeline, adapter):
    route_dir=f.route.resolve()
    flags=copy.deepcopy(f.options.source_review_flags)
    evidence=adapter.collect_source_evidence(f.song,f.reader,flags=flags,coverage_requested=False)
    plan=adapter.plan_audio_review(f.reader,source_evidence=evidence,flags=flags,duration_seconds=evidence['duration_seconds'])
    units=adapter.materialize_source_units(plan,evidence,duration_seconds=evidence['duration_seconds'])
    prepared,duration,witness=adapter._prepare_audio_observations(song_dir=f.song,units=units,
        audio=f.song/'audio.m4a',source_identity=evidence['identity'],deadline_at=f.deadline)
    witness_path=pipeline.source_witness.cache_path(f.song)
    receipt_identity=adapter.digest({'version':1,'source':evidence['identity'],'duration':duration,
        'intervals':evidence['routing_intervals'],'flags':flags,'coverage_requested':False,
        'artifacts':{name:value['sha256'] if value else None for name,value in evidence['artifacts'].items()},
        'witness':{'record':witness['record'],'sha256':adapter.file_hash(witness_path) if witness_path.is_file() else None},
        'models':{'base':f.options.model,'pro':f.options.pro_model},
        'adapter':legacy.ADAPTER_SHA,'pipeline':legacy.PIPELINE_SHA})
    folder=route_dir/'source-observations'/receipt_identity
    adapter.atomic_json(folder/'routing-plan.json',{'input_fingerprint':receipt_identity,'units':units,'digest':adapter.digest(units)})
    observed=[];issues=[]
    for unit,draft,source_context,_ in prepared:
        dependency=adapter.digest({'version':1,'pipeline_sha256':legacy.PIPELINE_SHA,'adapter_sha256':legacy.ADAPTER_SHA,'witness':witness})
        fingerprint=adapter.digest({'unit':unit,'draft':draft,'source_identity':evidence['identity'],'duration':duration,'dependency':dependency})
        unit_id=f.slug+':source-observation:'+unit['id']
        def execute(ctx):
            local=library.route_options(f.options,ctx);local.source_witness_audit=False
            segment={'index':unit['segment_index'],**{k:unit[k] for k in ('clip_start','clip_end','core_start','core_end')}}
            raw={'packet':{'segments':[{'segment':segment,'transcript':draft}],'source_first_witness':False}}
            with patch.object(pipeline,'audio_audit_request_contract',side_effect=legacy.audio_audit_request_contract):
                return pipeline.audit_long_transcript(ctx.attempt_dir/'songs'/f.slug,raw,f.song/'audio.m4a',local,
                    observation_context={'witness':witness['snapshot'],'source_context':source_context})
        try:
            result=routes.run_unit(route_dir,unit_id,fingerprint,execute,lambda result:adapter._observation_errors(unit,result),
                deadline_at=f.deadline,dependency_fingerprint=dependency,base_model=f.options.model,pro_model=f.options.pro_model)
            state=routes.unit_state_path(route_dir,unit_id,fingerprint,dependency_fingerprint=dependency,base_model=f.options.model,pro_model=f.options.pro_model)
            observed.append({'unit':unit,'result':result,'input_fingerprint':fingerprint,'route_state_path':str(state)})
        except routes.UnitUnresolved as exc:
            issues.append({'unit_id':unit['id'],'reason':exc.reason,'issues':exc.issues,'state_path':str(exc.state_path)})
    result={'status':'unresolved' if issues else 'observed','unit_results':observed,'issues':issues,
        'input_fingerprint':receipt_identity,'units':units,'remaining_obligations':['source-adjudication','coverage','timing']}
    receipt=folder/(f.slug+'-source-observed.json')
    adapter.atomic_json(receipt,{'version':1,'input_fingerprint':receipt_identity,'result':result,'result_digest':adapter.digest(result)})
    return {**result,'receipt_path':str(receipt)}

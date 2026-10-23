#!/usr/bin/env python3
"""Prepare or run persistent, private comparisons through production text stages.

No publication, audio certification, owner overwrite, or automatic quality score.
"""
from __future__ import annotations
import argparse
import contextlib
import fcntl
import importlib
import copy
import hashlib
import json
import math
import os
import subprocess
import time
from pathlib import Path

import bhakti_pipeline as pipeline
import bhakti_library_pass as library
import editorial_baselines
import prepare_library_review as prepare
import process_song_gemini as gemini

ROOT = pipeline.ROOT
CASES = [
    dict(id='koi-owner',slug='koi-hor-nahi',origin='working',mode='generation',owner_reference=True,
         target_ids=['refrain','v1a','v1b'],excerpt_start=0,excerpt_end=5),
    dict(id='arunachala-owner',slug='arunachala-akshara-mana-malai',origin='working',mode='generation',owner_reference=True,
         target_ids=['line-004','line-005'],excerpt_start=0,excerpt_end=9),
    dict(id='rehna-bad',slug='rehna-nahi-isa-desa',origin='c043b7f6^',mode='diagnostic',target_ids=['verse-3-line-2']),
    dict(id='rehna-clean',slug='rehna-nahi-isa-desa',origin='working',mode='diagnostic',target_ids=['verse-3-line-2']),
    dict(id='guna-bad',slug='aarti-gajvadan-vinayak-ki',origin='ee2714a6',mode='diagnostic',target_ids=['v1-2']),
    dict(id='guna-candidate',slug='aarti-gajvadan-vinayak-ki',origin='working',mode='diagnostic',target_ids=['v1-2']),
    dict(id='mapping-bad',slug='data-ek-sai',origin='ee2714a6',mode='diagnostic',target_ids=['pag-pag-par-sai']),
    dict(id='mapping-candidate',slug='data-ek-sai',origin='working',mode='diagnostic',target_ids=['pag-pag-par-sai']),
]

def write(path, value):
    pipeline.semantic_write_json(Path(path),value)

def digest(value):
    return prepare.json_digest(value)

def prepare_benchmark(root, output_dir, *, cases=None):
    root=Path(root); output=Path(output_dir); cases=copy.deepcopy(CASES if cases is None else cases)
    manifest_path=output/'manifest.json'; old=library.read_json(manifest_path)
    records=[]; readers={}
    for case in cases:
        if any(Path(case[key]).name!=case[key] or case[key] in ('','.','..') for key in ('id','slug')):
            raise ValueError('invalid case ID or slug')
        path=root/'songs'/case['slug']/'data.js'
        if case.get('origin','working')=='working': raw=path.read_bytes(); revision=None
        else:
            revision=subprocess.check_output(['git','rev-parse',case['origin']],cwd=root,text=True).strip()
            raw=subprocess.check_output(['git','show',f'{revision}:songs/{case["slug"]}/data.js'],cwd=root)
        reader=prepare.load_javascript(raw)
        if any(key not in reader['SONG_LINES'] for key in case['target_ids']):
            raise ValueError('benchmark target missing')
        if case.get('owner_reference'):
            editorial_baselines.assert_english_preserved(case['slug'],reader['SONG_LINES'],root=root)
        readers[case['id']]=reader
        records.append({**case,'source_sha256':hashlib.sha256(raw).hexdigest(),'origin_commit':revision,
            'reader_digest':digest(reader),'reader':f'corpus/{case["id"]}.reader.json',
            'languages':reader.get('SONG_META',{}).get('languages',[])})
    manifest={'version':1,'cases':records}
    if old is not None:
        if old!=manifest:
            write(output/'source-changes.json',{'frozen':old,'observed':manifest})
            raise ValueError('benchmark source changed; frozen snapshots retained')
        for case in records:
            stored=library.read_json(output/case['reader'])
            if stored is None or digest(stored)!=case['reader_digest']:
                raise ValueError('frozen benchmark snapshot missing or changed')
        return old
    for case in records: write(output/case['reader'],readers[case['id']])
    write(manifest_path,manifest)
    return manifest

def index_rows(packet, key, expected):
    rows=packet.get('packet',{}).get(key)
    if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows):
        raise ValueError('invalid '+key+' output')
    ids=[r.get('id') for r in rows]
    if any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids) or any(i not in ids for i in expected):
        raise ValueError('missing or duplicate '+key+' target')
    return {row['id']:row for row in rows}

def comparison_record(case, reader, glosses, translations):
    outputs=index_rows(translations,'translations',case['target_ids'])
    gloss_rows=index_rows(glosses,'glosses',case['target_ids'])
    rows=[]
    for key in case['target_ids']:
        original=reader['SONG_LINES'][key]; candidate=outputs[key]
        if not isinstance(candidate.get('literal_english'),str) or not isinstance(candidate.get('segments'),list):
            raise ValueError('malformed English output')
        rows.append({'id':key,'source':original['source'],'roman':original['roman'],
            'original_english':editorial_baselines.plain_english(original['english']),
            'original_markup':original['english'],'proposed_english':candidate['literal_english'],
            'proposed_segments':candidate['segments'],'original_glosses':original['words'],
            'proposed_glosses':gloss_rows[key]['word_glosses'],
            'sense_decisions':gloss_rows[key].get('sense_decisions',[]),
            'independent_review':candidate.get('independent_review'),
            'material_alternatives':candidate.get('material_alternatives',[])})
    return {'case_id':case['id'],'semantic_status':'not-reviewed','comparison_only':True,
            'owner_reference':bool(case.get('owner_reference')),'calibration_limitation': 'Production prompts contain some owner-reference examples; this is not an unseen generalization test. Aruṇācala wordplay/cave clauses and the contextual guṇa and mapping controls are not quoted prompt examples.','lines':rows}

def options_for(case, reader, options):
    local=copy.copy(options); local.force=False; local.source_slug=case['slug']
    source,_,_=library.reader_evidence(reader)
    local.semantic_full_source=source
    local.semantic_performance_order=copy.deepcopy(reader['SONG_SEQUENCE'])
    return source,local

def run_generation_case(case, snapshot, output_dir, options):
    source,local=options_for(case,snapshot,options)
    start,end=case['excerpt_start'],case['excerpt_end']
    if type(start) is not int or type(end) is not int or not 0<=start<end<=len(snapshot['SONG_SEQUENCE']):
        raise ValueError('invalid contiguous excerpt')
    order=copy.deepcopy(snapshot['SONG_SEQUENCE'][start:end]); ids=list(dict.fromkeys(e['ref'] for e in order))
    if not set(case['target_ids'])<=set(ids): raise ValueError('target outside excerpt')
    by_id={r['id']:r for r in source}; lines=[by_id[i] for i in ids]
    local.semantic_performance_order=order
    # Source-only whole-song context; owner gloss/English is never a generator input.
    for attr in ('semantic_context_evidence','semantic_baseline','semantic_original_reader',
                 'semantic_seed_translation','semantic_previous_translations','semantic_confirmed_issues'):
        if hasattr(local,attr): delattr(local,attr)
    languages=snapshot['SONG_META']['languages']
    audited={'packet':{'verified_lines':lines,'metadata':{'languages':languages},'performance_order':order}}
    folder=Path(output_dir)/'cases'/case['id']; folder.mkdir(parents=True,exist_ok=True)
    write(folder/'source-input.json',audited)
    glosses=pipeline.gloss(folder,audited,local)
    write(folder/'gloss-result.json',glosses)
    translations=pipeline.translate(folder,audited,glosses,{'languages':languages},local)
    write(folder/'translation-result.json',translations)
    returned=index_rows(translations,'translations',ids)
    if set(returned)!=set(ids): raise ValueError('unexpected generation output IDs')
    result=comparison_record(case,snapshot,glosses,translations)
    result['generated_context_ids']=[i for i in ids if i not in case['target_ids']]
    result['reported_cost_usd']=pipeline.reported_cost(glosses,translations)
    write(folder/'comparison.json',result)
    text=['# Private comparison — editorial review pending','']
    for row in result['lines']:
        text.extend([f'## {row["id"]}',row['source'],row['roman'],'',f'Original: {row["original_english"]}',
                     f'Candidate: {row["proposed_english"]}','','Judgment: not reviewed',''])
    (folder/'comparison.md').write_text('\n'.join(text))
    return result

def run_diagnostic_case(case, reader, output_dir, options):
    lines,glosses,drafts=library.reader_evidence(reader)
    local=copy.copy(options);local.force=False;local.semantic_full_source=lines
    local.semantic_performance_order=copy.deepcopy(reader['SONG_SEQUENCE'])
    local.semantic_context_evidence=[{'source':s,'gloss':g,'draft':d} for s,g,d in zip(lines,glosses,drafts)]
    ids=set(case['target_ids']); selected=[[r for r in rows if r['id'] in ids] for rows in (lines,glosses,drafts)]
    folder=Path(output_dir)/'cases'/case['id'];folder.mkdir(parents=True,exist_ok=True)
    reviews,packets=pipeline.independently_review_translations(folder,*selected,'(none supplied)',local,
        languages=reader['SONG_META']['languages'])
    result={'case_id':case['id'],'semantic_status':'not-reviewed','reviews':reviews,'packets':packets,
            'reported_cost_usd':pipeline.reported_cost(*packets)}
    write(folder/'diagnostic.json',result)
    return result


@contextlib.contextmanager
def run_lock(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    with (output/'run.lock').open('a') as handle:
        try:fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:raise ValueError('benchmark run already active') from exc
        try:yield
        finally:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)

def dependency_identity():
    # Conservative provenance for this private experiment only. A code change
    # holds the benchmark; this never changes production/audio cache identities.
    names=('bhakti_pipeline','bhakti_library_pass','retranslate_bhakti',
        'prepare_library_review','editorial_baselines','process_song_gemini',
        'bhakti_translation_policy','bhakti_semantic_repair','bhakti_review_findings',
        'bhakti_lexical_retrieval','bhakti_embedding_client','bhakti_model_routes',
        'source_word_map','gloss_policy','display_word_map')
    return {name:hashlib.sha256(Path(importlib.import_module(name).__file__).read_bytes()).hexdigest()
            for name in names}

def artifact_receipt(case, folder):
    folder=Path(folder)
    required=(('source-input.json','gloss-result.json','translation-result.json','comparison.json','comparison.md')
              if case['mode']=='generation' else ('diagnostic.json',))
    if any(not (folder/name).is_file() for name in required):
        raise ValueError('required benchmark artifact missing')
    report=library.read_json(folder/('comparison.json' if case['mode']=='generation' else 'diagnostic.json'))
    if not isinstance(report,dict) or report.get('case_id')!=case['id'] or report.get('semantic_status')!='not-reviewed':
        raise ValueError('benchmark artifact has invalid review status or case identity')
    receipt={}
    for path in sorted(folder.rglob('*')):
        if path.is_symlink():raise ValueError('benchmark artifact must not be a symlink')
        if path.is_file():receipt[str(path.relative_to(folder))]=hashlib.sha256(path.read_bytes()).hexdigest()
    return receipt


def payment_checkpoint(output):
    output=Path(output);ledger=output/'api-ledger.json';responses=output/'api-ledger-responses'
    if ledger.is_symlink() or responses.is_symlink():raise ValueError('payment evidence must not be a symlink')
    result={'ledger_sha256':hashlib.sha256(ledger.read_bytes()).hexdigest() if ledger.is_file() else None,
            'response_sha256':{}}
    for path in sorted(responses.rglob('*')):
        if path.is_symlink():raise ValueError('payment evidence must not be a symlink')
        if path.is_file():result['response_sha256'][str(path.relative_to(responses))]=hashlib.sha256(path.read_bytes()).hexdigest()
    return result

def verify_payment_checkpoint(output,state):
    if state.get('payment_checkpoint')!=payment_checkpoint(output):
        raise ValueError('benchmark payment evidence missing or changed; do not recreate spending history')

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--cases',nargs='+',default=['koi-owner','arunachala-owner','rehna-bad','rehna-clean'])
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--model',default=gemini.MODEL)
    parser.add_argument('--budget-usd',type=float)
    parser.add_argument('--max-calls',type=int)
    parser.add_argument('--deadline-seconds',type=float)
    parser.add_argument('--timeout',type=float,default=180)
    options=parser.parse_args(argv); options.force=False;options.max_attempts=1
    output=options.output_dir.resolve();root=options.root.resolve()
    if output==root or root in output.parents: parser.error('use a private output directory outside the repository')
    selected=[case for case in CASES if case['id'] in options.cases]
    if len(selected)!=len(options.cases): parser.error('unknown or duplicate case')
    with run_lock(output):
        return execute_benchmark(root,output,selected,options,parser)

def execute_benchmark(root,output,selected,options,parser):
    manifest=prepare_benchmark(root,output,cases=selected)
    if not options.execute:
        print(json.dumps({'status':'prepared','manifest':str(output/'manifest.json'),'cases':len(selected)}));return 0
    if (options.budget_usd is None or not math.isfinite(options.budget_usd) or options.budget_usd<=0 or
        options.max_calls is None or options.max_calls<=0 or options.deadline_seconds is None or
        not math.isfinite(options.deadline_seconds) or options.deadline_seconds<=0):
        parser.error('--execute requires positive --budget-usd --max-calls --deadline-seconds')
    if gemini.provider_name()!='openrouter' or options.model not in {gemini.model_routes.FLASH_MODEL,gemini.model_routes.PRO_MODEL}:
        parser.error('bounded benchmark requires a supported OpenRouter model')
    # The shared bounded chat ledger does not encompass paid embedding calls.
    if os.environ.get('BHAKTI_EMBEDDING_LEDGER'):
        parser.error('embedding execution needs its separately reviewed budget; this benchmark does not activate it')
    configuration={'manifest':digest(manifest),'model':options.model,'budget_usd':options.budget_usd,
        'max_calls':options.max_calls,'deadline_seconds':options.deadline_seconds,'timeout':options.timeout,
        'policy':pipeline.translation_policy_payload(),
        'implementation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'dependencies':dependency_identity()}
    state=library.read_json(output/'run.json')
    if state:
        if state['configuration']!=configuration:raise ValueError('benchmark configuration changed; existing run retained')
    else:
        if (output/'api-ledger.json').exists() or (output/'api-ledger-responses').exists() or (output/'cases').exists():
            raise ValueError('benchmark run provenance missing; retain existing artifacts and ledger')
        state={'configuration':configuration,'deadline_at':time.time()+options.deadline_seconds,'outcomes':{},
            'payment_checkpoint':payment_checkpoint(output)}
        write(output/'run.json',state)
    for case in manifest['cases']:
        prior=state['outcomes'].get(case['id'])
        if prior is None:continue
        if prior.get('status')!='completed-awaiting-editorial-review':
            print(json.dumps({'status':'unresolved','case_id':case['id'],'prior_status':prior.get('status'),
                'recovery':'Review retained artifacts and ledger; this command will not redispatch an unresolved or interrupted case.'}))
            return 1
        if not prior.get('artifact_sha256') or artifact_receipt(case,output/'cases'/case['id'])!=prior['artifact_sha256']:
            raise ValueError('completed benchmark artifacts missing or changed')
    verify_payment_checkpoint(output,state)
    options.semantic_deadline_at=state['deadline_at']
    if time.time()>=state['deadline_at']: raise ValueError('original benchmark deadline exhausted')
    os.environ.update(BHAKTI_API_RUN_LEDGER=str(output/'api-ledger.json'),
        BHAKTI_API_RUN_BUDGET_USD=str(options.budget_usd),BHAKTI_API_RUN_MAX_CALLS=str(options.max_calls))
    for case in manifest['cases']:
        if case['id'] in state['outcomes']:continue
        reader=library.read_json(output/case['reader'])
        if digest(reader)!=case['reader_digest']:raise ValueError('frozen snapshot changed')
        verify_payment_checkpoint(output,state)
        started=time.monotonic()
        state['outcomes'][case['id']]={'status':'running','started_at':time.time()}
        write(output/'run.json',state)
        try:
            runner=run_generation_case if case['mode']=='generation' else run_diagnostic_case
            runner(case,reader,output,options)
            outcome={'status':'completed-awaiting-editorial-review',
                'artifact_sha256':artifact_receipt(case,output/'cases'/case['id'])}
        except Exception as exc:
            outcome={'status':'unresolved','error_type':type(exc).__name__,'error':str(exc)}
            state['outcomes'][case['id']]=outcome;write(output/'run.json',state)
            print(json.dumps({'status':'unresolved','case_id':case['id'],'error':str(exc)}))
            return 1
        outcome['elapsed_seconds']=time.monotonic()-started
        state['payment_checkpoint']=payment_checkpoint(output)
        state['outcomes'][case['id']]=outcome;write(output/'run.json',state)
    print(json.dumps({'status':'completed-awaiting-editorial-review','output':str(output)}));return 0

if __name__=='__main__':raise SystemExit(main())

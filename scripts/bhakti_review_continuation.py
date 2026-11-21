"""Explicit citation presentation derivatives; never provider output or judgment.

A caller must authenticate an independent review of the exact token_map and the
result before using this pure projection in semantic continuation.
"""
import copy
import re

from bhakti_word_accountability import _reference_errors, source_rows

CITATION_PROJECTION_VERSION = 1


def _mapped_runs(source, ref, mapping):
    if not isinstance(mapping, dict) or any(mapping.get(k) != source.get(k) for k in ('source_text', 'roman')):
        raise ValueError('reviewed native/Roman source mapping changed or absent')
    pairs = mapping.get('tokens', [])
    native_spans = list(re.finditer(r'\S+', source['source_text']))
    roman = source['roman'].split()
    if (not pairs or [list(p) for p in pairs] != [[n.group(), r] for n, r in zip(native_spans, roman)]
            or len(native_spans) != len(roman) or len(pairs) != len(roman)):
        raise ValueError('reviewed token mapping does not cover exact source')
    indices = ref.get('word_indices')
    if (not isinstance(indices, list) or not indices
            or any(type(i) is not int or not 0 <= i < len(pairs) for i in indices)
            or indices != sorted(set(indices))):
        raise ValueError('citation indices must be unique increasing source positions')
    runs = []
    for index in indices:
        if runs and index == runs[-1][-1] + 1:
            runs[-1].append(index)
        else:
            runs.append([index])
    expected = ' ... '.join(' '.join(roman[i] for i in run) for run in runs)
    if ref.get('source_quote') != expected:
        raise ValueError('Roman quotation does not exactly match the selected source runs')
    return [{**ref, 'word_indices': run,
             'source_quote': source['source_text'][native_spans[run[0]].start():native_spans[run[-1]].end()]}
            for run in runs]


def project_citations(lines, reviews, token_map):
    """Project only exact indexed Roman citations using a reviewed source map."""
    sources = source_rows(lines)
    result = copy.deepcopy(reviews)
    changes = []
    for row in result:
        for judgment in row.get('word_judgments', []):
            projected = []
            for index, ref in enumerate(judgment.get('references', [])):
                if not _reference_errors(ref, sources):
                    projected.append(ref)
                    continue
                if (not isinstance(ref, dict) or ref.get('domain') != 'word_glosses'
                        or ref.get('line_id') not in sources):
                    raise ValueError('only a known source word citation can be projected')
                replacements = _mapped_runs(sources[ref['line_id']], ref, token_map.get(ref['line_id']))
                if any(_reference_errors(item, sources) for item in replacements):
                    raise ValueError('projected native citation violates source contract')
                changes.append({'review_line_id':row['id'], 'english_unit':judgment['unit'],
                                'reference_index':index, 'before':copy.deepcopy(ref),
                                'after':copy.deepcopy(replacements)})
                projected.extend(replacements)
            judgment['references'] = projected
    return result, changes


def validate_projection(lines, original, derived, token_map):
    expected, _ = project_citations(lines, original, token_map)
    if derived != expected:
        raise ValueError('citation derivative changed judgments or source references')

# Continuation is a separate, authenticated operation; it never dispatches.
import hashlib
import json
from pathlib import Path


def _read(reference):
    if not isinstance(reference, dict) or set(reference) != {'path','sha256'}:
        raise ValueError('continuation requires an exact file reference')
    path = Path(reference['path'])
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != reference['sha256']:
        raise ValueError('continuation evidence hash mismatch: ' + str(path))
    return json.loads(path.read_text())


def _all_refs(value):
    if isinstance(value, dict):
        if set(value) == {'path','sha256'}:
            yield value
        else:
            for child in value.values(): yield from _all_refs(child)
    elif isinstance(value, list):
        for child in value: yield from _all_refs(child)


def verify_saved(state, translations):
    reference = state['review_continuation']
    declaration = _read(reference)
    for item in _all_refs(declaration): _read(item)
    if declaration.get('kind') == 'writer-citation':
        projection,_ = _writer_history(declaration)
        if (translations.get('writer_citation_projection',{}).get('declaration') != reference
                or [{k:v for k,v in row.items() if k != 'independent_review'} for row in translations['packet']['translations']] != projection['translations']):
            raise ValueError('accepted writer citation projection changed')
        return
    if translations.get('review_citation_projection', {}).get('declaration') != reference:
        raise ValueError('accepted citation continuation provenance changed')


def _route_identity(repair, stage, inputs, options):
    return repair.digest({'stage':stage,'inputs':inputs,'context':repair.stage_context(options),
                          'escalation':getattr(options,'semantic_stage_escalation',True)})


def complete(pipeline, song_dir, audited, job, options, reference, *, configuration_run_id,
             content_configuration_run_id, glossary_identity, evidence, baseline, order, automatic):
    """Close a settled citation-only review via the normal semantic acceptor."""
    import bhakti_model_routes as routes
    repair = pipeline.bhakti_semantic_repair
    declaration = _read(reference)
    if declaration.get('version') != 1:
        raise ValueError('unsupported review continuation version')
    if declaration.get('kind') == 'writer-citation':
        return complete_writer(pipeline,song_dir,audited,job,options,reference,
            configuration_run_id=configuration_run_id,content_configuration_run_id=content_configuration_run_id,
            glossary_identity=glossary_identity,evidence=evidence,baseline=baseline,order=order,automatic=automatic)
    # Check all frozen inputs before considering any state transition.
    for item in _all_refs(declaration): _read(item)
    parent = _read(declaration['parent_state'])
    if (parent.get('status') != 'blocked' or parent.get('rounds_used') != 0
            or parent.get('quality_hold') or parent.get('review_task_version') != pipeline.REVIEW_TASK_VERSION
            or parent.get('configuration_run_id',parent.get('run_id')) != configuration_run_id
            or parent.get('content_configuration_run_id') != content_configuration_run_id):
        raise ValueError('continuation parent/configuration is not the unchanged terminal first review')
    if (declaration.get('audited_source_sha256') != repair.digest(audited)
            or declaration.get('source_evidence_sha256') != repair.digest(evidence)):
        raise ValueError('continuation source identity changed')
    packet_dir = song_dir/'.transcription/pipeline'
    state_path = packet_dir/'semantic-repair-state.json'
    current = pipeline.read_packet(state_path)
    identity = repair.digest({'configuration_run_id':configuration_run_id,
        'parent_run_id':parent['run_id'],'citation_projection_version':CITATION_PROJECTION_VERSION,
        'declaration':reference})
    if current != parent and not (current.get('run_id') == identity and current.get('review_continuation') == reference):
        raise ValueError('continuation cannot replace an unrelated current parent')
    old_round = packet_dir/'semantic-repair'/parent['run_id']/'round-0'
    route_dir = old_round/'.transcription/pipeline/stage-routes'
    writer_path = Path(declaration['writer_route']['path'])
    if writer_path.parent.parent.resolve() != route_dir.resolve():
        raise ValueError('writer route is outside the bound parent')
    cached = routes.read_unit_cache(writer_path)
    if cached['state']['status'] != 'accepted' or cached['state']['unit_id'] != 'round-0:semantic-writer':
        raise ValueError('continuation requires the genuine accepted writer')
    writer = copy.deepcopy(cached['result']);writer['writer_route_state'] = str(writer_path)
    glosses = _read(declaration['gloss'])
    if Path(declaration['gloss']['path']).resolve() not in {
            (old_round/'gloss-ready.json').resolve(),(old_round/'source-gloss-ready.json').resolve()}:
        raise ValueError('continuation glossary is outside the bound parent round')
    local = copy.copy(options)
    local.semantic_deadline_at = parent['deadline_at_epoch']  # identity context only; no dispatch
    local.semantic_coordinator_acceptance = str(packet_dir/'semantic-acceptance.json')
    local.semantic_full_source = copy.deepcopy(getattr(options,'semantic_full_source',audited['packet']['verified_lines']))
    local.semantic_performance_order = order
    local.semantic_source_identity = getattr(options,'semantic_source_identity',repair.digest(evidence))
    local.semantic_baseline = baseline
    local.semantic_repair_feedback = [];local.semantic_prior_gloss = []
    local.semantic_translation_targets = None;local.semantic_previous_translations = None
    local.semantic_seed_translation = None;local.automatic_lexical_feedback = []
    local.semantic_review_generation = 0;local.semantic_previous_writer_context = None
    local = pipeline.bhakti_lexical_producer.prepare_source_from_gloss(audited,glosses,local)
    view, _ = pipeline.bhakti_lexical_producer.prepare_translation(old_round,audited,glosses,local)
    inputs = {'audited':audited,'glosses':glosses,'provided':pipeline.supplied_translation(job),
        'policy':pipeline.semantic_stage_policy(view,stage='writer'),
        'automatic_evidence_receipt':pipeline.automatic_evidence_receipt(view)}
    if cached['state']['input_fingerprint'] != _route_identity(repair,'writer',{**inputs,'draft_contract_version':1},local):
        raise ValueError('accepted writer input identity changed')
    repair.assert_baseline(baseline,writer['packet']['translations'])
    raw_reviews = []; raw_responses = []; final_options = local
    failures = declaration.get('failed_reviews',[])
    if not failures: raise ValueError('continuation has no authenticated review history')
    for failure in failures:
        path = Path(failure['route']['path'])
        if path.parent.parent.resolve() != route_dir.resolve():
            raise ValueError('review route is outside the bound parent')
        state = routes.read_unit_cache(path)['state']
        if state['status'] != 'unresolved' or state['unit_id'] != 'round-0:semantic-review':
            raise ValueError('review is not a settled failed review route')
        review_options = copy.copy(local)
        controls = failure.get('review_controls',{})
        if set(controls) - {'text_reasoning_effort'} or controls.get('text_reasoning_effort',{}) not in ({},{'review':'low'}):
            raise ValueError('continuation may only preserve the actual review-only reasoning control')
        for key,value in controls.items(): setattr(review_options,key,copy.deepcopy(value))
        review_view,_ = pipeline.bhakti_lexical_producer.prepare_translation(old_round,audited,glosses,review_options)
        expected = _route_identity(repair,'review',{**inputs,
            'policy':pipeline.semantic_stage_policy(review_view,stage='review'),
            'writer':writer,**pipeline.review_task_identity()},review_options)
        if state['input_fingerprint'] != expected:
            raise ValueError('review input identity differs from source/gloss/accepted writer')
        ledger = _read(failure['ledger']); requests = ledger.get('requests',[])
        if any(row.get('status') not in {'parsed','invalid-model-output'} for row in requests):
            raise ValueError('review ledger contains an unsettled or unsupported outcome')
        attempts = {item['attempt_id']:item for item in state['attempts']}
        for raw_ref in failure['responses']:
            matches = [row for row in requests if row.get('response_path') == raw_ref['path']]
            if len(matches) != 1: raise ValueError('raw response lacks unique settled ledger correlation')
            request = matches[0];context = request.get('unit_context',{})
            attempt = attempts.get(context.get('attempt_id'),{})
            if (context.get('state_path') != str(path) or context.get('unit_id') != state['unit_id']
                    or context.get('input_fingerprint') != expected
                    or context.get('dependency_fingerprint') != expected
                    or context.get('model') != attempt.get('model')
                    or attempt.get('status') not in {'transport-failed','quality-failed'}):
                raise ValueError('review request unit context does not match its actual terminal route')
            raw = _read(raw_ref);choice = raw['choices'][0]
            if request['status'] == 'invalid-model-output':
                if choice.get('finish_reason') != 'length' or attempt.get('status') != 'transport-failed':
                    raise ValueError('only explicit settled MAX_TOKENS history is supported')
                continue
            if choice.get('finish_reason') == 'length' or attempt.get('status') != 'quality-failed':
                raise ValueError('parsed review is not the genuine complete quote-failed result')
            parsed = json.loads(choice['message']['content'])
            raw_reviews.extend(parsed['reviews'])
            raw_responses.append({'raw_response':raw_ref,'ledger':failure['ledger'],'route':failure['route']})
            final_options = review_options
    lines = audited['packet']['verified_lines']
    if [row.get('id') for row in raw_reviews] != [line['id'] for line in lines]:
        raise ValueError('complete review source population or order changed')
    projection = _read(declaration['projection']); independent = _read(declaration['independent_review'])
    if (projection.get('version') != CITATION_PROJECTION_VERSION
            or projection.get('kind') != 'assistant-derived-citation-projection'
            or projection.get('source_sha256') != repair.digest(audited)
            or independent.get('status') != 'accepted' or independent.get('projection') != declaration['projection']):
        raise ValueError('citation derivative lacks exact source-bound independent review')
    validate_projection(lines,raw_reviews,projection['reviews'],projection['token_map'])
    errors = repair.scoped_gloss_contract_errors(pipeline,lines,glosses['packet']['glosses'],
        audited['packet'].get('metadata',{}).get('languages'),local)
    if errors: raise ValueError('continuation glossary contract: '+str(errors[:3]))
    if current.get('status') == 'accepted':
        accepted_gloss=pipeline.read_packet(packet_dir/'04-glosses.json')
        accepted_translation=pipeline.read_packet(packet_dir/'05-translation.json')
        repair.require_acceptance(pipeline,packet_dir,accepted_gloss,accepted_translation,audited=audited)
        return accepted_gloss,accepted_translation
    # Candidate assembly retains the original writer's proof/context and all
    # actual reviewer judgments. This writes only the new continuation folder.
    directory = packet_dir/'semantic-repair'/identity
    provenance = {'version':CITATION_PROJECTION_VERSION,'kind':projection['kind'],
        'declaration':reference,'projection':declaration['projection'],
        'independent_review':declaration['independent_review']}
    result = pipeline.review_translation(directory,audited,glosses,job,final_options,writer,
        citation_derivative={'reviews':projection['reviews'],'raw_responses':raw_responses,'provenance':provenance})
    result['automatic_lexical_feedback'] = []
    result['semantic_request_identity'] = repair.digest({'run':identity,'continuation':reference})
    errors,issues = repair.candidate_verdict(pipeline,directory,audited,glosses,result,final_options,baseline,order,automatic)
    if errors or issues:
        raise ValueError('continuation semantic acceptance hold: '+str((errors+issues)[:3]))
    if repair.writer_rows(result['packet']['translations']) != repair.writer_rows(writer['packet']['translations']):
        raise ValueError('continuation changed immutable writer evidence')
    state = {**copy.deepcopy(parent),'run_id':identity,'status':'in-progress',
        'configuration_run_id':configuration_run_id,'review_continuation':reference,
        'parent_run_id':parent['run_id']}
    state.pop('reason',None)
    # Original histories, deadlines and ledger bytes are not rewritten.
    pipeline.semantic_write_json(directory/'prior-parent-state.json',parent)
    pipeline.semantic_write_json(packet_dir/'semantic-repair-required.json',{'version':repair.VERSION,'run_id':identity})
    pipeline.semantic_write_json(state_path,state)
    accepted = repair.accept_candidate(pipeline,packet_dir,state_path,state,identity,
        copy.deepcopy(glosses),result,evidence,glossary_identity,content_configuration_run_id)
    repair.require_acceptance(pipeline,packet_dir,*accepted,audited=audited)
    return accepted


def project_writer_citations(lines, translations, token_map):
    """Exact quotation presentation; preserve every ordered cited index.

    A reviewed native/Roman map is an input, never inferred equivalence. Existing
    split runs retain their ordered index union; a containing quote changes only
    its script. No English, rationale, confidence or fidelity field can change.
    """
    sources = source_rows(lines)
    result = copy.deepcopy(translations)
    changes = []
    for row in result:
        for support in row.get('word_support', []):
            projected = []
            for ref in support.get('references', []):
                if not _reference_errors(ref, sources):
                    projected.append(ref)
                    continue
                source = sources.get(ref.get('line_id'))
                mapping = token_map.get(ref.get('line_id'))
                if (not source or not isinstance(mapping, dict)
                        or any(mapping.get(k) != source.get(k) for k in ('source_text', 'roman'))):
                    raise ValueError('writer citation source/token map changed')
                native = list(re.finditer(r'\S+', source['source_text']))
                roman = source['roman'].split()
                pairs = mapping.get('tokens')
                indices = ref.get('word_indices')
                if (len(native) != len(roman) or not isinstance(pairs,list)
                        or [list(p) for p in pairs] != [[n.group(), r] for n,r in zip(native,roman)]
                        or ref.get('domain') != 'word_glosses' or not isinstance(indices,list) or not indices
                        or any(type(i) is not int or not 0 <= i < len(roman) for i in indices)
                        or indices != sorted(set(indices))):
                    raise ValueError('writer citation token map or indices invalid')
                quote = ref.get('source_quote')
                if isinstance(quote,str) and ' ... ' in quote:
                    replacements = _mapped_runs(source,ref,mapping)
                else:
                    # Native validation permits a quote containing the selected
                    # indices. Require exactly one corresponding Roman span.
                    spans = [(a,b) for a in range(len(roman)) for b in range(a+1,len(roman)+1)
                             if ' '.join(roman[a:b]) == quote and a <= min(indices) and max(indices) < b]
                    if len(spans) != 1:
                        raise ValueError('writer quotation has no unique exact containing Roman span')
                    a,b = spans[0]
                    replacements = [{**ref,'source_quote':source['source_text'][native[a].start():native[b-1].end()]}]
                if ([i for replacement in replacements for i in replacement['word_indices']] != indices
                        or any(_reference_errors(item,sources) for item in replacements)):
                    raise ValueError('projected writer quotation changed indices or native contract')
                changes.append({'line_id':row['id'],'unit':support['unit'],
                                'before':copy.deepcopy(ref),'after':copy.deepcopy(replacements)})
                projected.extend(replacements)
            support['references'] = projected
    return result, changes


def _writer_projection(declaration):
    """Revalidate frozen source/map/derivative closure even on final consumption."""
    projection = _read(declaration['projection'])
    independent = _read(declaration['independent_review'])
    original = _read(declaration['writer_candidate'])
    source = _read(declaration['audited_source'])
    if (projection.get('version') != 1 or projection.get('kind') != 'assistant-derived-writer-citation-projection'
            or projection.get('source_sha256') != declaration['audited_source_sha256']
            or independent.get('status') != 'accepted' or independent.get('projection') != declaration['projection']):
        raise ValueError('writer quotation derivative lacks exact independent review')
    expected,_ = project_writer_citations(source['packet']['verified_lines'],original['packet']['translations'],projection['token_map'])
    if projection.get('translations') != expected:
        raise ValueError('writer citation derivative changed English, indices, fidelity or other nonquotation fields')
    return projection,original


def complete_writer(pipeline, song_dir, audited, job, options, reference, *, configuration_run_id,
                    content_configuration_run_id, glossary_identity, evidence, baseline, order, automatic):
    """Review a transparent quotation-only derivative of a settled failed writer.

    This does not promote the failed writer route. It spends only through the
    caller's new bounded intake and retains its exact identity across resume.
    """
    import os
    import math
    import bhakti_model_routes as routes
    repair = pipeline.bhakti_semantic_repair
    declaration = _read(reference)
    for item in _all_refs(declaration): _read(item)
    parent = _read(declaration['parent_state'])
    if (parent.get('status') != 'blocked' or parent.get('rounds_used') != 0 or parent.get('quality_hold')
            or parent.get('review_task_version') != pipeline.REVIEW_TASK_VERSION
            or parent.get('configuration_run_id',parent.get('run_id')) != configuration_run_id
            or parent.get('content_configuration_run_id') != content_configuration_run_id):
        raise ValueError('writer continuation requires unchanged blocked first parent')
    if (declaration.get('audited_source_sha256') != repair.digest(audited)
            or _read(declaration['audited_source']) != audited
            or declaration.get('source_evidence_sha256') != repair.digest(evidence)):
        raise ValueError('writer continuation source identity changed')
    packet_dir = song_dir/'.transcription/pipeline'
    state_path = packet_dir/'semantic-repair-state.json'
    current = pipeline.read_packet(state_path) or {}
    identity = repair.digest({'configuration_run_id':configuration_run_id,'parent_run_id':parent['run_id'],
                              'writer_citation_projection_version':1,'declaration':reference})
    own = current.get('run_id') == identity and current.get('review_continuation') == reference
    if current != parent and not own:
        raise ValueError('writer continuation cannot replace unrelated current parent')
    old_round = packet_dir/'semantic-repair'/parent['run_id']/'round-0'
    route_path = Path(declaration['writer_route']['path'])
    route = _read(declaration['writer_route'])
    if (route_path.parent.parent.resolve() != (old_round/'.transcription/pipeline/stage-routes').resolve()
            or route.get('status') != 'unresolved' or route.get('unit_id') != 'round-0:semantic-writer'):
        raise ValueError('writer continuation lacks exact failed writer route')
    projection,original = _writer_history(declaration)
    glosses = _read(declaration['gloss'])
    if Path(declaration['gloss']['path']).resolve() not in {(old_round/'gloss-ready.json').resolve(),(old_round/'source-gloss-ready.json').resolve()}:
        raise ValueError('writer continuation glossary is outside parent')
    local = copy.copy(options)
    local.semantic_deadline_at = parent['deadline_at_epoch']  # prior input identity only
    local.semantic_coordinator_acceptance = str(packet_dir/'semantic-acceptance.json')
    local.semantic_full_source = copy.deepcopy(getattr(options,'semantic_full_source',audited['packet']['verified_lines']))
    local.semantic_performance_order = order
    local.semantic_source_identity = getattr(options,'semantic_source_identity',repair.digest(evidence))
    local.semantic_baseline = baseline
    local.semantic_repair_feedback=[];local.semantic_prior_gloss=[]
    local.semantic_translation_targets=None;local.semantic_previous_translations=None
    local.semantic_seed_translation=None;local.automatic_lexical_feedback=[]
    local.semantic_review_generation=0;local.semantic_previous_writer_context=None
    local = pipeline.bhakti_lexical_producer.prepare_source_from_gloss(audited,glosses,local)
    view,_ = pipeline.bhakti_lexical_producer.prepare_translation(old_round,audited,glosses,local)
    inputs={'audited':audited,'glosses':glosses,'provided':pipeline.supplied_translation(job),
            'policy':pipeline.semantic_stage_policy(view,stage='writer'),
            'automatic_evidence_receipt':pipeline.automatic_evidence_receipt(view)}
    if route['input_fingerprint'] != _route_identity(repair,'writer',{**inputs,'draft_contract_version':1},local):
        raise ValueError('failed writer source/gloss/baseline context changed')
    lines=audited['packet']['verified_lines'];rows=projection['translations']
    repair.assert_baseline(baseline,rows)
    errors=pipeline.translation_draft_contract_errors(lines,glosses['packet']['glosses'],rows,
        accountability_sources=local.semantic_full_source+[x['source'] for x in getattr(local,'semantic_context_evidence',[])])
    errors+=repair.scoped_gloss_contract_errors(pipeline,lines,glosses['packet']['glosses'],audited['packet']['metadata'].get('languages'),local)
    if errors:raise ValueError('projected writer violates actual draft contract: '+str(errors[:3]))
    if own and current.get('status') == 'accepted':
        pair=(pipeline.read_packet(packet_dir/'04-glosses.json'),pipeline.read_packet(packet_dir/'05-translation.json'))
        repair.require_acceptance(pipeline,packet_dir,*pair,audited=audited)
        return pair
    # Only a real bounded caller may authorize the new review. Its immutable
    # ledger path and absolute deadline are saved before dispatch, never renewed.
    ledger_path=Path(os.environ.get('BHAKTI_API_RUN_LEDGER',''))
    live=pipeline.read_packet(ledger_path) if ledger_path.is_file() else None
    deadline=getattr(options,'unit_deadline_at',None)
    if (not isinstance(live,dict) or not repair._bounded_ready() or type(deadline) not in (int,float)
            or not math.isfinite(deadline) or live.get('deadline_at') != deadline):
        raise ValueError('writer continuation requires actual bounded intake ledger/deadline')
    phase={'ledger':str(ledger_path.resolve()),'deadline_at':deadline,'budget_usd':live.get('budget_usd'),'max_calls':live.get('max_calls')}
    if own and current.get('writer_continuation_phase') != phase:
        raise ValueError('writer continuation cannot renew its review phase')
    directory=packet_dir/'semantic-repair'/identity
    state={**copy.deepcopy(parent),'run_id':identity,'status':'in-progress','configuration_run_id':configuration_run_id,
           'review_continuation':reference,'parent_run_id':parent['run_id'],'writer_continuation_phase':phase}
    state.pop('reason',None)
    provenance={'version':1,'kind':projection['kind'],'declaration':reference,
                'projection':declaration['projection'],'independent_review':declaration['independent_review'],
                'original_writer':declaration['writer_candidate']}
    writer={key:copy.deepcopy(original[key]) for key in ('input_contract_version','fingerprint','automatic_evidence_receipt') if key in original}
    writer.update(packet={'translations':copy.deepcopy(rows)},origin=projection['kind'],
                  writer_citation_projection=provenance,writer_coordinator_acceptance=local.semantic_coordinator_acceptance)
    if getattr(view,'semantic_writer_gloss_binding',None) is not None:
        writer['writer_gloss_binding']=copy.deepcopy(view.semantic_writer_gloss_binding)
    local.semantic_deadline_at=deadline
    local.semantic_stage_escalation=False  # one genuine review route; no editorial repair loop
    pipeline.semantic_write_json(directory/'prior-parent-state.json',parent)
    pipeline.semantic_write_json(state_path,state)
    def validate_review(result):
        errors=pipeline.translation_review_contract_errors(lines,glosses['packet']['glosses'],result.get('packet',{}).get('translations',[]),
            **pipeline.translation_packet_contract_kwargs(lines,result,local,performance_order=order))
        if repair.writer_rows(result['packet']['translations']) != repair.writer_rows(rows):
            errors.append('review changed immutable citation-derived writer')
        return [{'kind':'review_contract','detail':e} for e in errors]
    result=repair.semantic_stage_route(pipeline,directory,'review',
        {**inputs,'policy':pipeline.semantic_stage_policy(view,stage='review'),'writer':writer,**pipeline.review_task_identity()},local,
        lambda target,opts:pipeline.review_translation(target,audited,glosses,job,opts,writer),validate_review)
    errors,issues=repair.candidate_verdict(pipeline,directory,audited,glosses,result,local,baseline,order,automatic)
    if errors or issues:raise ValueError('writer continuation semantic acceptance hold: '+str((errors+issues)[:3]))
    if pipeline.read_packet(state_path) != state:
        raise ValueError('writer continuation parent changed during review')
    result['semantic_request_identity']=repair.digest({'run':identity,'continuation':reference})
    pipeline.semantic_write_json(packet_dir/'semantic-repair-required.json',{'version':repair.VERSION,'run_id':identity})
    accepted=repair.accept_candidate(pipeline,packet_dir,state_path,state,identity,copy.deepcopy(glosses),result,evidence,glossary_identity,content_configuration_run_id)
    repair.require_acceptance(pipeline,packet_dir,*accepted,audited=audited)
    return accepted


def _writer_history(declaration):
    import bhakti_semantic_repair as repair
    route_path = Path(declaration['writer_route']['path'])
    route = _read(declaration['writer_route'])
    attempts = route.get('attempts',[])
    if not attempts or any(a.get('status') != 'quality-failed' for a in attempts):
        raise ValueError('writer continuation requires all attempts settled quality failures')
    selected = [a for a in attempts if a.get('attempt_id') == declaration.get('selected_attempt_id')]
    if len(selected) != 1 or selected[0] != attempts[0]:
        raise ValueError('writer continuation must name the original Flash attempt')
    candidate_path = route_path.parent/'flash/songs/round-0/.transcription/pipeline/translation-candidate.json'
    if Path(declaration['writer_candidate']['path']).resolve() != candidate_path.resolve():
        raise ValueError('wrong selected writer candidate path')
    attempt_packets = {}
    for index,attempt in enumerate(attempts):
        candidate = json.loads((route_path.parent/('flash' if index == 0 else 'pro')/'candidate.json').read_text())
        if candidate is None or repair.digest(candidate) != attempt.get('candidate_sha256'):
            raise ValueError('failed writer route candidate changed')
        attempt_packets[attempt['attempt_id']] = [d['packet'] for d in candidate['writer_diagnostics']]
    ledger = _read(declaration['prior_ledger'])
    if ledger.get('blocked') or any(r.get('status') != 'parsed' for r in ledger.get('requests',[])):
        raise ValueError('writer continuation ledger has unsettled or unsupported outcome')
    requests = [r for r in ledger.get('requests',[]) if Path(r.get('unit_context',{}).get('state_path','')).resolve() == route_path.resolve()]
    rawrefs = declaration.get('responses',[])
    if (not requests or len({r['response_path'] for r in requests}) != len(requests)
            or len(rawrefs) != len(requests) or {r['path'] for r in rawrefs} != {r['response_path'] for r in requests}):
        raise ValueError('writer continuation omitted or duplicated a batch response')
    raw_by_path = {r['path']:_read(r) for r in rawrefs}
    selected_rows = []
    actual_packets = {a['attempt_id']:[] for a in attempts}
    for request in requests:
        context = request.get('unit_context',{})
        attempt = next((a for a in attempts if a['attempt_id'] == context.get('attempt_id')),None)
        if (attempt is None or context.get('unit_id') != route['unit_id']
                or context.get('input_fingerprint') != route['input_fingerprint']
                or context.get('dependency_fingerprint') != route['dependency_fingerprint']
                or context.get('model') != attempt['model']):
            raise ValueError('writer response unit context differs from actual attempt')
        choice = raw_by_path[request['response_path']]['choices'][0]
        if choice.get('finish_reason') != 'stop':
            raise ValueError('writer response was not complete')
        packet = json.loads(choice['message']['content'])
        actual_packets[attempt['attempt_id']].append(packet)
        if request['unit_context']['attempt_id'] == selected[0]['attempt_id']:
            selected_rows.extend(packet['translations'])
    if any(repair.reservation_fields(row) is not None for packets in attempt_packets.values()
           for packet in packets for row in packet['translations']):
        raise ValueError('writer citation-only continuation cannot discard prior semantic concerns')
    if actual_packets != attempt_packets:
        raise ValueError('raw writer batches differ from authenticated failed attempt diagnostics')
    projection,original = _writer_projection(declaration)
    if selected_rows != original['packet']['translations']:
        raise ValueError('selected raw writer batches do not reproduce complete candidate')
    return projection, original

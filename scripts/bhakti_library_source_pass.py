"""Isolated source-stage candidates; preserve reviewed text and never publish."""
from __future__ import annotations
import copy,hashlib,json,math,time,unicodedata
from pathlib import Path
from typing import Any

VERSION=1

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp');temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temporary.replace(path)

def canonical_iast(value):
    # Unicode equivalence only. Reviewed lexical/roman aliases need an explicit map.
    return unicodedata.normalize('NFC',value).strip()

def plan_source(reader,rebuilt,*,reviewed_map=None):
    if rebuilt.get('uncertainties'):raise ValueError('rebuilt source has unresolved uncertainty')
    old=reader.get('SONG_LINES',{});raw=rebuilt.get('verified_lines',[]);order=rebuilt.get('performance_order',[])
    if not isinstance(old,dict) or not old or not isinstance(raw,list) or not raw or not isinstance(order,list) or not order:raise ValueError('incomplete source population')
    raw_by={}
    for line in raw:
        lid=line.get('id')
        if not isinstance(lid,str) or not lid or lid in raw_by:raise ValueError('duplicate/invalid audited line ID')
        if any(not isinstance(line.get(k),str) or not line[k].strip() for k in ('source_text','roman')):raise ValueError('audited line lacks source/roman')
        raw_by[lid]=line
    if any(not isinstance(r,dict) or r.get('line_id') not in raw_by for r in order):raise ValueError('unknown source occurrence reference')
    if {r['line_id'] for r in order}!=set(raw_by):raise ValueError('unperformed audited source rows')
    mapping={}
    if reviewed_map is not None:
        for item in reviewed_map.get('mapping',[]):
            rid=item.get('new_line_id')
            if rid not in raw_by or rid in mapping:raise ValueError('duplicate/unknown reviewed raw ID')
            if item.get('audited_source')!=raw_by[rid]['source_text'] or item.get('audited_roman')!=raw_by[rid]['roman']:raise ValueError('stale reviewed source/roman')
            previous=item.get('old_line_id')
            if previous is not None:
                if previous not in old or item.get('baseline_line')!=old[previous] or item.get('preserve_english')!=old[previous].get('english'):raise ValueError('stale reviewed public baseline')
            mapping[rid]=previous
        if set(mapping)!=set(raw_by):raise ValueError('reviewed map does not cover complete source')
        targets={x.get('new_line_id') for x in reviewed_map.get('new_gloss_targets',[])}
        if targets!={rid for rid,prior in mapping.items() if prior is None}:raise ValueError('reviewed fresh-target population mismatch')
    else:
        identities={}
        for lid,line in old.items():
            identity=(line.get('source'),canonical_iast(line.get('roman','')))
            identities.setdefault(identity,[]).append(lid)
        for line in raw:
            matches=identities.get((line['source_text'],canonical_iast(line['roman'])),[])
            if len(matches)>1:raise ValueError('ambiguous source identity needs reviewed mapping')
            mapping[line['id']]=matches[0] if matches else None
    used={lid for lid in mapping.values() if lid is not None}
    if used!=set(old):raise ValueError('old reviewed source would be dropped or changed without explicit mapping')
    lines=[];seen=set();raw_to_final={};new_targets=[];reuse={}
    for raw_line in raw:
        rid=raw_line['id'];prior=mapping[rid]
        if prior is not None:
            final=prior;line={**copy.deepcopy(raw_line),'id':final,'source_text':old[prior]['source'],'roman':old[prior]['roman']}
            for field in ('sourceWords','sourceLanguage'):
                if field in old[prior]:line[field]=copy.deepcopy(old[prior][field])
            reuse[final]=copy.deepcopy(old[prior])
        else:
            final='source-new-'+rid
            if final in old or final in seen:raise ValueError('new source ID collides with old reader')
            line={**copy.deepcopy(raw_line),'id':final};new_targets.append(final)
        raw_to_final[rid]=final
        if final not in seen:lines.append(line);seen.add(final)
    counts={};new_order=[]
    for event in order:
        lid=raw_to_final[event['line_id']];counts[lid]=counts.get(lid,0)+1
        new_order.append({**copy.deepcopy(event),'line_id':lid,'occurrence':counts[lid]})
    return {'lines':lines,'performance_order':new_order,'raw_to_final':raw_to_final,
            'new_target_ids':new_targets,'reuse_by_id':reuse,'rebuilt_source_digest':digest(rebuilt)}

def assert_source_candidate(before,after,plan,timing):
    if before.get('SONG_META')!=after.get('SONG_META'):raise ValueError('source stage changed metadata')
    old=before['SONG_LINES'];new=after.get('SONG_LINES',{});expected={r['id']:r for r in plan['lines']}
    if set(new)!=set(expected):raise ValueError('candidate source population mismatch')
    for lid,line in old.items():
        if new.get(lid)!=line:raise ValueError('changed existing reviewed row '+lid)
    for lid,line in expected.items():
        if new[lid].get('source')!=line['source_text'] or new[lid].get('roman')!=line['roman']:raise ValueError('candidate changed planned source/roman '+lid)
    expanded=[]
    for event in after.get('SONG_SEQUENCE',[]):
        repeats=event.get('repeats')
        if type(repeats) is not int or repeats<1 or event.get('ref') not in expected:raise ValueError('invalid candidate sequence')
        if event.get('section')!=expected[event['ref']].get('kind','verse'):raise ValueError('candidate section changed')
        expanded.extend([event['ref']]*repeats)
    if expanded!=[r['line_id'] for r in plan['performance_order']]:raise ValueError('candidate order/repeats differ from reviewed source')
    seq=timing.get('sequence',[])
    measured=[{'ref':e['ref'],'section':e.get('section','verse'),'repeats':e.get('repeats',1)} for e in seq]
    times=[{'start':round(e['start'],3),'end':round(e['end'],3)} for e in seq]
    if measured!=after['SONG_SEQUENCE'] or times!=after.get('SONG_TIMINGS'):raise ValueError('candidate differs from approved timing artifact')
    if len(times)!=len(measured) or any(not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in t.values()) for t in times):raise ValueError('invalid numeric timing')

def save_checkpoint(path,input_fingerprint,result):
    if result.get('status')!='accepted' or result.get('publicationEligible') is not True or result.get('issues'):raise ValueError('only accepted source stage may checkpoint')
    atomic_json(path,{'version':VERSION,'input_fingerprint':input_fingerprint,'result_digest':digest(result),'result':result})

def load_checkpoint(path,input_fingerprint):
    path=Path(path)
    if not path.exists():return None
    data=json.loads(path.read_text())
    if data.get('version')!=VERSION or data.get('input_fingerprint')!=input_fingerprint:return None
    result=data.get('result')
    if data.get('result_digest')!=digest(result):raise ValueError('accepted checkpoint result digest mismatch')
    if not isinstance(result,dict) or result.get('status')!='accepted' or result.get('publicationEligible') is not True or result.get('issues'):raise ValueError('checkpoint is not accepted source evidence')
    return result


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def process_new_targets(song_dir, plan, metadata, options, route_dir, deadline_at):
    """Fresh text is a routed, independently reviewed subset, never old English."""
    import bhakti_pipeline as pipeline
    import bhakti_library_pass as library
    import bhakti_model_routes as routes
    targets = [line for line in plan['lines'] if line['id'] in plan['new_target_ids']]
    languages = metadata.get('languages', [])
    evidence = {'targets': targets, 'source': plan['lines'], 'order': plan['performance_order'],
                'languages': languages, 'policy': pipeline.translation_policy_payload()}
    identity = digest(evidence)
    unit_id = song_dir.name + ':new-source-semantics'
    decisions = getattr(options, 'editorial_adjudications', None) or {}
    if not isinstance(decisions, dict):
        raise ValueError('editorial_adjudications must map exact unit IDs to decision paths')
    if unit_id in decisions:
        from bhakti_editorial_adjudication import recover_editorial_candidate
        decision_path = Path(decisions[unit_id])
        recovered = recover_editorial_candidate(decision_path,
            unit_id=unit_id, input_fingerprint=identity,
            dependency_fingerprint=digest(evidence['policy']),
            source_evidence=evidence, policy_payload=evidence['policy'],
            validate_candidate=lambda value: fresh_target_errors(plan, metadata, value),
            output_dir=Path(route_dir) / 'editorial-adjudications' / digest(unit_id)[:16] / file_hash(decision_path)[:16])
        return {**recovered['candidate'], 'editorial_receipt': recovered['receipt']}
    def execute(context):
        local = library.route_options(options, context)
        local.semantic_full_source = plan['lines']
        local.semantic_performance_order = plan['performance_order']
        local.semantic_source_identity = digest({'lines': plan['lines'], 'order': plan['performance_order']})
        attempt_song = context.attempt_dir / 'songs' / song_dir.name
        (attempt_song / '.transcription/pipeline').mkdir(parents=True, exist_ok=True)
        audited = {'packet': {'metadata': metadata, 'verified_lines': targets,
                             'performance_order': [event for event in plan['performance_order'] if event['line_id'] in plan['new_target_ids']],
                             'uncertainties': []}}
        glosses = pipeline.gloss(attempt_song, audited, local)
        errors = pipeline.fresh_gloss_contract_errors(targets, glosses['packet']['glosses'], languages)
        if errors: raise routes.QualityFailure([{'kind': 'source_gloss_contract', 'detail': error} for error in errors])
        translations = pipeline.translate(attempt_song, audited, glosses,
            {'slug': song_dir.name, 'languages': languages}, local, candidate_only=True)
        return {'glosses': glosses, 'translations': translations}
    def validate(value):
        return [{'kind': 'source_semantic_contract', 'detail': error} for error in fresh_target_errors(plan, metadata, value)]
    return routes.run_unit(route_dir, song_dir.name + ':new-source-semantics', identity,
        execute, validate, deadline_at=deadline_at, dependency_fingerprint=digest(evidence['policy']),
        base_model=options.model, pro_model=options.pro_model)


def fresh_target_errors(plan, metadata, value):
    import bhakti_pipeline as pipeline
    targets = [line for line in plan['lines'] if line['id'] in plan['new_target_ids']]
    try:
        glosses = value['glosses']['packet']['glosses']
        translations = value['translations']['packet']['translations']
        if not isinstance(glosses, list) or not isinstance(translations, list):
            return ['fresh target rows are not lists']
        if any(not isinstance(row, dict) for row in glosses + translations):
            return ['fresh target rows are not objects']
        return (pipeline.fresh_gloss_contract_errors(targets, glosses, metadata.get('languages', []))
                + pipeline.fresh_translation_contract_errors(targets, glosses, translations)
                + pipeline.validate_line_contract(targets, glosses, translations))
    except (KeyError, TypeError) as exc:
        return ['incomplete fresh target artifact: ' + str(exc)]


def run_source_candidate(*, root, slug, reader, workspace, route_dir, options, deadline_at):
    """Derive a private reader, preserving every existing editorial field exactly."""
    import re
    import shutil
    import bhakti_pipeline as pipeline
    import bhakti_library_pass as library
    import bhakti_model_routes as routes
    import audit_bhakti_contract as contract
    import apply_translation_style_review as writer
    import editorial_baselines
    root, workspace, route_dir = Path(root).resolve(), Path(workspace).resolve(), Path(route_dir).resolve()
    evidence = {}
    def hold(kind, detail):
        return {'status': 'unresolved', 'reader': reader, 'source_changed': False,
                'publicationEligible': False, 'evidence': evidence,
                'issues': [{'kind': kind, 'detail': str(detail)}]}
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
        return hold('source_input', 'invalid slug')
    if root == workspace or root in workspace.parents or workspace in root.parents:
        return hold('source_input', 'source and workspace must be isolated roots')
    song = root / 'songs' / slug
    target = workspace / 'songs' / slug
    original_audit = song / '.transcription/pipeline/02-transcript-audit.json'
    original_timing = song / '.transcription/pipeline/03-timing.json'
    try:
        if contract.load_data(song / 'data.js') != reader:
            raise ValueError('current reader differs from supplied original')
        if (root / 'data/editorial_baselines.json').read_bytes() != (workspace / 'data/editorial_baselines.json').read_bytes():
            raise ValueError('workspace owner registry differs from authoritative registry')
        baselines = editorial_baselines.load_baselines(root)
        editorial_baselines.assert_english_preserved(slug, reader['SONG_LINES'], root=root)
        old_lines, old_glosses, old_translations = library.reader_evidence(reader)
        original_audio = pipeline.preferred_listener_audio(song)
        audio = target / original_audio.name
        if file_hash(audio) != file_hash(original_audio):
            raise ValueError('workspace audio differs from original native listener audio')
        audit = json.loads(original_audit.read_text())
        timing_before = json.loads(original_timing.read_text())
        mapping_path = (getattr(options, 'source_reuse_maps', {}) or {}).get(slug)
        mapping = json.loads(Path(mapping_path).read_text()) if mapping_path else None
        source = pipeline.read_packet(song / '.transcription/source.json') or {}
        dependencies = {str(path.relative_to(root)): file_hash(path)
                        for path in [song / 'data.js', original_audit, original_timing, original_audio,
                                     *sorted((root / 'data').glob('*.json'))]}
        for path in [song / '.transcription/source.json', song / '.transcription/trim-applied.json',
                     song / '.transcription/pipeline/01-transcript.json', song / '.transcription/pipeline/song-packet.json']:
            if path.is_file(): dependencies[str(path.relative_to(root))] = file_hash(path)
        editorial_paths = getattr(options, 'editorial_adjudications', None) or {}
        if not isinstance(editorial_paths, dict):
            raise ValueError('editorial_adjudications must be an exact unit-to-path mapping')
        editorial_unit = slug + ':new-source-semantics'
        editorial_identity = ({editorial_unit: file_hash(editorial_paths[editorial_unit])}
                              if editorial_unit in editorial_paths else {})
        identity = digest({'version': VERSION, 'dependencies': dependencies, 'map': mapping,
                           'editorial_adjudications': editorial_identity,
                           'requested_stages': getattr(options, 'source_requested_stages', []),
                           'confirmed_issues': getattr(options, 'source_confirmed_issues', []),
                           'policy': pipeline.translation_policy_payload(),
                           'code': {name: file_hash(Path(pipeline.__file__).parent / name)
                                    for name in ['bhakti_pipeline.py', 'bhakti_model_routes.py']},
                           'adapter': file_hash(__file__)})
        evidence['input_fingerprint'] = identity
        checkpoint = route_dir / (slug + '-source-accepted.json')
        saved = load_checkpoint(checkpoint, identity)
        if saved:
            if contract.load_data(target / 'data.js') != saved['reader']:
                raise ValueError('accepted source checkpoint workspace reader drifted')
            expected_script = 'data.js?v=' + file_hash(target / 'data.js')[:12]
            if (file_hash(target / 'index.html') != saved['evidence'].get('candidate_html_sha256')
                    or expected_script not in (target / 'index.html').read_text()):
                raise ValueError('accepted source checkpoint workspace HTML drifted')
            if contract.audit_song(target)['status'] != 'ready':
                raise ValueError('accepted source checkpoint workspace contract no longer ready')
            assert_source_candidate(reader, saved['reader'], saved['evidence']['plan'], saved['evidence']['timing'])
            editorial_baselines.assert_english_preserved(slug, saved['reader']['SONG_LINES'], root=root)
            return saved
        # On a changed input do not reuse a previously mutated workspace.
        if contract.load_data(target / 'data.js') != reader:
            raise ValueError('workspace reader is stale for the changed input; prepare a new isolated workspace')
        segments = audit.get('segment_audits')
        rebuilt = pipeline.merge_audited_segments(segments) if segments else copy.deepcopy(audit['packet'])
        if mapping:
            if (mapping.get('original_public_sha256') != file_hash(song / 'data.js')
                    or mapping.get('original_audit_sha256') != file_hash(original_audit)
                    or mapping.get('rebuilt_audit_sha256') != hashlib.sha256((json.dumps(rebuilt, ensure_ascii=False, indent=2) + '\n').encode()).hexdigest()):
                raise ValueError('reviewed source map input hashes changed')
        plan = plan_source(reader, rebuilt, reviewed_map=mapping)
        if slug in baselines and plan['new_target_ids']:
            raise ValueError('locked_baseline_conflict: owner English population cannot be extended automatically')
        # Stored human declarations also cannot be silently extended or rewritten.
        summary = pipeline.read_packet(song / '.transcription/pipeline/song-packet.json') or {}
        declarations = [obj[field] for obj in [reader.get('SONG_META', {}), source, summary, summary.get('job', {})]
                        if isinstance(obj, dict) for field in ['humanTranslation','human_translation','providedTranslation','provided_translation']
                        if obj.get(field) not in (None, '', False, '(none supplied)')]
        if declarations and plan['new_target_ids']:
            raise ValueError('locked_baseline_conflict: supplied human translation requires a reviewed extended mapping')
        metadata = copy.deepcopy(rebuilt.get('metadata', {}))
        metadata['languages'] = reader['SONG_META'].get('languages') or metadata.get('languages', [])
        normalized = copy.deepcopy(audit)
        normalized['packet'] = {**copy.deepcopy(rebuilt), 'metadata': metadata,
                                'verified_lines': plan['lines'], 'performance_order': plan['performance_order']}
        old_order = [event['ref'] for event in reader['SONG_SEQUENCE'] for _ in range(event.get('repeats', 1))]
        source_changed = bool(plan['new_target_ids'] or old_order != [event['line_id'] for event in plan['performance_order']])
        requested = set(getattr(options, 'source_requested_stages', []) or [])
        unsupported = requested.intersection({'audio-review', 'focused-audio-review'})
        if unsupported:
            return hold('unsupported_audio_source_review', {'stages': sorted(unsupported),
                'issues': getattr(options, 'source_confirmed_issues', []),
                'reason': 'Cached merge/timing repair does not independently resolve broader audio/source flags.'})
        evidence.update({'plan': plan, 'original_dependencies': dependencies,
                         'new_target_ids': plan['new_target_ids'], 'audio_sha256': file_hash(original_audio)})
        local = copy.copy(options)
        for name, value in {'force': False, 'refresh_timing': False, 'source_witness_audit': False,
                            'timeout': 300, 'model': pipeline.MODEL, 'pro_model': 'google/gemini-3.1-pro-preview'}.items():
            if not hasattr(local, name): setattr(local, name, value)
        local.timing_deadline_at = min(deadline_at, getattr(options, 'timing_deadline_at', None) or deadline_at)
        if time.time() >= deadline_at: return hold('source_deadline', 'source-stage deadline exhausted before dispatch')
        archive = target / '.transcription/source-pass-original'
        archive.mkdir(parents=True, exist_ok=True)
        for name in ['data.js', 'index.html']:
            if not (archive / name).exists(): shutil.copy2(song / name, archive / name)
        for name in ['01-transcript.json', '02-transcript-audit.json', '03-timing.json']:
            original = song / '.transcription/pipeline' / name
            if original.exists() and not (archive / name).exists(): shutil.copy2(original, archive / name)
        new = process_new_targets(target, plan, metadata, local, route_dir, deadline_at) if plan['new_target_ids'] else {'glosses': {'packet': {'glosses': []}}, 'translations': {'packet': {'translations': []}}}
        if plan['new_target_ids']:
            errors = fresh_target_errors(plan, metadata, new)
            if errors: return hold('source_semantic_contract', '; '.join(errors))
        # Target only explicit saved uncertainty for a source-identical timing repair.
        if not source_changed and timing_before.get('uncertain_occurrence_ids'):
            local.timing_repair_occurrence_ids = copy.deepcopy(timing_before['uncertain_occurrence_ids'])
            local.timing_legacy_evidence_identity = {'audio_sha256': file_hash(original_audio),
                'timing_sha256': file_hash(original_timing),
                'trim': pipeline.read_packet(song / '.transcription/trim-applied.json') or {}}
            # Retain the exact original audited rows/order for the timing cache identity.
            timing_audit = audit
        else:
            timing_audit = normalized
        timing = pipeline.align(target, timing_audit, audio, local)
        gloss_by = {row['id']: row for row in old_glosses + new['glosses']['packet']['glosses']}
        english_by = {row['id']: row for row in old_translations + new['translations']['packet']['translations']}
        glosses = {'packet': {'glosses': [gloss_by[line['id']] for line in plan['lines']]}}
        translations = {'packet': {'translations': [english_by[line['id']] for line in plan['lines']]}}
        errors = pipeline.publication_errors(normalized, timing, glosses, translations)
        if errors: return hold('source_publication_contract', '; '.join(errors))
        job = {**copy.deepcopy(reader['SONG_META']), 'slug': slug,
               'displayTitle': reader['SONG_META']['title'], 'languages': metadata['languages']}
        pipeline.generate(target, job, source, normalized, timing, glosses, translations, write_catalogue_after=False)
        candidate = contract.load_data(target / 'data.js')
        candidate['SONG_META'] = copy.deepcopy(reader['SONG_META'])
        candidate['SONG_LINES'].update(copy.deepcopy(reader['SONG_LINES']))
        assert_source_candidate(reader, candidate, plan, timing)
        # Native/English links of every new row are checked after actual rendering.
        library.reader_evidence(candidate)
        editorial_baselines.assert_english_preserved(slug, candidate['SONG_LINES'], root=root)
        writer.write_reader(slug, candidate, root=workspace)
        # Regenerate HTML with the exact preserved metadata, avoiding metadata churn.
        html = pipeline.page_html(candidate['SONG_META'], slug)
        html, count = re.subn(r'(?<=src=")data\.js(?:\?v=[^"\s]+)?(?=")',
                              'data.js?v=' + file_hash(target / 'data.js')[:12], html)
        if count != 1: raise ValueError('candidate HTML lacks a unique data script')
        (target / 'index.html').write_text(html, encoding='utf-8')
        inspection = contract.audit_song(target)
        if inspection['status'] != 'ready': return hold('source_reader_contract', inspection)
        evidence.update({'timing': timing, 'contract': inspection,
                         'candidate_html_sha256': file_hash(target / 'index.html'),
                         'new_semantic_artifacts': new if plan['new_target_ids'] else None})
        atomic_json(target / '.transcription/source-pass-derived.json',
                    {'original_input_fingerprint': identity, 'audit': normalized,
                     'glosses': glosses, 'translations': translations, 'timing': timing,
                     'derivation': 'Original reviewed line objects retained; new units independently processed.'})
        result = {'status': 'accepted', 'reader': candidate, 'source_changed': source_changed,
                  'publicationEligible': True, 'evidence': evidence, 'issues': []}
        save_checkpoint(checkpoint, identity, result)
        return result
    except (routes.RunFatal, routes.UnitTransportFailure):
        raise
    except routes.UnitUnresolved as exc:
        return hold('source_unit_unresolved', exc)
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        # Deterministic input/contract failures are holds, never model escalation.
        return hold('source_stage_hold', exc)

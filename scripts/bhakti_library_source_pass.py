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
        # Hash guards and whole original-line validation above authorize this map.
        local.timing_reviewed_source_map = copy.deepcopy(mapping) if mapping else None
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


AUDIO_REVIEW_CONTRACT_VERSION = 1


def source_draft(reader, occurrence_indices=None):
    """Expand actual performances for audio review, excluding English/glosses."""
    lines = reader.get('SONG_LINES')
    sequence = reader.get('SONG_SEQUENCE')
    if not isinstance(lines, dict) or not lines or not isinstance(sequence, list) or not sequence:
        raise ValueError('source draft requires definitions and performed sequence')
    sections = {'invocation', 'refrain', 'verse', 'bridge', 'closing', 'spoken', 'instrumental'}
    kinds_by_id = {}
    for event in sequence:
        if not isinstance(event, dict) or event.get('ref') not in lines:
            raise ValueError('source draft contains an unknown performed reference')
        if type(event.get('repeats', 1)) is not int or event.get('repeats', 1) < 1:
            raise ValueError('source draft repeat count must be a positive integer')
        if event.get('section', 'verse') not in sections:
            raise ValueError('source draft contains an unknown section kind')
        kinds_by_id.setdefault(event['ref'], set()).add(event.get('section', 'verse'))
    indices = list(range(len(sequence))) if occurrence_indices is None else list(occurrence_indices)
    if (any(type(index) is not int or not 0 <= index < len(sequence) for index in indices)
            or indices != sorted(set(indices))):
        raise ValueError('source draft occurrence indices must be unique and ordered')
    definitions = {}; order = []; counts = {}
    for index in indices:
        event = sequence[index]; lid = event['ref']; line = lines[lid]
        instrumental_only = kinds_by_id[lid] == {'instrumental'}
        if (not isinstance(line, dict) or any(not isinstance(line.get(key), str) for key in ('source', 'roman'))
                or (not instrumental_only and any(not line[key].strip() for key in ('source', 'roman')))):
            raise ValueError('source draft requires exact native and Roman source for lyrics')
        definitions.setdefault(lid, {'id': lid, 'source_text': line['source'], 'roman': line['roman'],
                                     'kind': event.get('section', 'verse')})
        for repeat in range(event.get('repeats', 1)):
            counts[lid] = counts.get(lid, 0) + 1
            order.append({'line_id': lid, 'occurrence': counts[lid],
                          'display_occurrence_id': f'occ-{index:03d}', 'repeat_index': repeat,
                          'kind': event.get('section', 'verse')})
    return {'lines': list(definitions.values()), 'performance_order': order}


def reader_source_identity(reader):
    draft = source_draft(reader)
    lines = {lid: {key: line.get(key) for key in ('source', 'roman', 'sourceWords')}
             for lid, line in reader['SONG_LINES'].items()}
    order = [{'ref': event['line_id'], 'section': event['kind']} for event in draft['performance_order']]
    return digest({'lines': lines, 'order': order})


def plan_audio_review(reader, *, source_evidence, flags, duration_seconds):
    """Plan coverage/source/timing independently; no provider or file mutations.

    Receipt hashes identify evidence. This planner never decides a sung word or
    certifies first-syllable timing from a display interval.
    """
    import re
    if (not isinstance(duration_seconds, (int, float)) or isinstance(duration_seconds, bool)
            or not math.isfinite(duration_seconds) or duration_seconds <= 0):
        raise ValueError('audio planning requires a finite positive measured duration')
    if not isinstance(source_evidence, dict) or not isinstance(flags, dict):
        raise ValueError('audio evidence and flags must be objects')
    draft = source_draft(reader)
    identity = source_evidence.get('identity')
    if (not isinstance(identity, dict) or set(identity) != {'audio_sha256', 'trim_sha256', 'reader_source_sha256'}
            or any(not isinstance(identity.get(key), str) or not re.fullmatch(r'[0-9a-f]{64}', identity[key])
                   for key in ('audio_sha256', 'reader_source_sha256'))
            or (identity.get('trim_sha256') is not None and not re.fullmatch(r'[0-9a-f]{64}', str(identity['trim_sha256'])))
            or identity['reader_source_sha256'] != reader_source_identity(reader)):
        raise ValueError('audio planning identity does not match exact current source')
    sequence = reader['SONG_SEQUENCE']; lines = reader['SONG_LINES']
    disagreements = source_evidence.get('disagreements', [])
    receipts = source_evidence.get('focused_receipts', [])
    if (not isinstance(disagreements, list) or any(not isinstance(row, dict) for row in disagreements)
            or not isinstance(receipts, list) or any(not isinstance(row, dict) for row in receipts)):
        raise ValueError('audio disagreements/receipts must be object lists')
    ids = [row.get('id') for row in disagreements]
    if any(not isinstance(value, str) or not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError('audio disagreements need unique stable IDs')
    def receipt_bound(receipt):
        return (type(receipt.get('version')) is int and receipt['version'] == 1
                and receipt.get('status') == 'accepted'
                and type(receipt.get('source_contract_version')) is int
                and receipt['source_contract_version'] == AUDIO_REVIEW_CONTRACT_VERSION
                and receipt.get('identity') == identity)
    def focused_bound(receipt):
        # Changed-source lineage is accepted only by the later reviewed delta
        # producer. This first planner slice reuses source-preserving decisions.
        return (receipt_bound(receipt) and receipt.get('before_identity') == identity
                and receipt.get('source_lineage') == [])
    pending = [row for row in disagreements if not any(
        focused_bound(receipt) and receipt.get('resolved_disagreement_id') == row['id']
        and receipt.get('disagreement_sha256') == digest(row) for receipt in receipts)]
    receipt = source_evidence.get('coverage_receipt')
    covered = bool(isinstance(receipt, dict) and receipt_bound(receipt)
        and receipt.get('scope') == 'whole_recording'
        and isinstance(source_evidence.get('audit_sha256'), str)
        and re.fullmatch(r'[0-9a-f]{64}', source_evidence['audit_sha256'])
        and receipt.get('audit_sha256') == source_evidence['audit_sha256']
        and receipt.get('unresolved_disagreements') == []
        and receipt.get('observed_start') is True and receipt.get('observed_end') is True)
    if 'audio' in flags and type(flags['audio']) is not bool:
        raise ValueError('audio flag must be a boolean')
    targets = set(); hypotheses_by_target = {}
    def locate(value):
        line_ids = value.get('line_ids', []); occurrence_ids = value.get('occurrence_ids', [])
        if (not isinstance(line_ids, list) or not isinstance(occurrence_ids, list)
                or any(not isinstance(lid, str) or lid not in lines for lid in line_ids)):
            raise ValueError('audio flag/disagreement uses unknown source line IDs')
        selected = {index for index, event in enumerate(sequence) if event['ref'] in line_ids}
        for value in occurrence_ids:
            if not isinstance(value, str) or not re.fullmatch(r'occ-[0-9]{3,}', value):
                raise ValueError('invalid audio occurrence locator')
            index = int(value[4:])
            if index >= len(sequence): raise ValueError('unknown audio occurrence locator')
            selected.add(index)
        return selected
    # Validate even already-resolved locators: malformed input is not silently
    # swallowed just because a receipt names its digest.
    for disagreement in disagreements: locate(disagreement)
    for disagreement in pending:
        selected = locate(disagreement)
        if not selected: raise ValueError('focused audio disagreement lacks an occurrence scope')
        targets.update(selected)
        for index in selected: hypotheses_by_target.setdefault(index, []).append(disagreement)
    flag_targets = locate(flags)
    flag_pending = flags.get('audio') is True
    if flag_pending:
        desired = flag_targets or set(range(len(sequence)))
        covered_flags = set()
        for receipt in receipts:
            if focused_bound(receipt) and receipt.get('flag_sha256') == digest(flags):
                values = receipt.get('target_occurrence_ids', [])
                if isinstance(values, list):
                    covered_flags.update(index for index in desired if f'occ-{index:03d}' in values)
        flag_targets = desired - covered_flags
        flag_pending = bool(flag_targets)
        targets.update(flag_targets)
    pending_source = bool(pending or flag_pending)
    whole_flag = flag_pending and not flags.get('line_ids') and not flags.get('occurrence_ids')
    needs_coverage = not covered and source_evidence.get('coverage_requested') is True
    mode = 'focused' if targets and not whole_flag else 'whole_recording' if whole_flag or needs_coverage else 'reuse'
    units = []
    if mode == 'whole_recording':
        indices = list(range(len(sequence)))
        units.append({'id': 'whole-recording', 'kind': 'coverage',
                      'target_occurrence_ids': [f'occ-{index:03d}' for index in indices],
                      'core_occurrence_indices': indices, 'context_occurrence_indices': indices,
                      'clip_start': 0.0, 'clip_end': float(duration_seconds),
                      'hypotheses': copy.deepcopy(pending), 'prior_evidence': [], 'expanded_draft': draft})
    elif mode == 'focused':
        timings = reader.get('SONG_TIMINGS')
        if not isinstance(timings, list) or len(timings) != len(sequence):
            raise ValueError('focused audio routing lacks displayed intervals')
        groups = []
        for index in sorted(targets):
            context = set(range(max(0, index - 1), min(len(sequence), index + 2)))
            if groups and context.intersection(groups[-1]['context']):
                groups[-1]['targets'].add(index); groups[-1]['context'].update(context)
            else: groups.append({'targets': {index}, 'context': context})
        for group in groups:
            indices = sorted(group['context']); selected = sorted(group['targets'])
            for index in indices:
                interval = timings[index]
                if (not isinstance(interval, dict)
                        or any(not isinstance(interval.get(key), (int, float)) or isinstance(interval[key], bool)
                               or not math.isfinite(interval[key]) for key in ('start', 'end'))
                        or interval['start'] < 0 or interval['end'] <= interval['start']
                        or interval['end'] > duration_seconds + .0005):
                    raise ValueError('invalid existing interval cannot route a focused audio clip')
            if any(timings[left]['end'] > timings[right]['start'] + .0005
                   for left, right in zip(indices, indices[1:])):
                raise ValueError('focused audio context intervals are not ordered and nonoverlapping')
            start = 0.0 if indices[0] == 0 else float(timings[indices[0]]['start'])
            end = float(duration_seconds) if indices[-1] == len(sequence) - 1 else float(timings[indices[-1]]['end'])
            if start >= end: raise ValueError('focused audio context has reversed routing bounds')
            hypotheses = [row for row in pending if any(row in hypotheses_by_target.get(index, []) for index in selected)]
            units.append({'id': 'focused-' + '-'.join(str(index) for index in selected), 'kind': 'focused-source',
                          'target_occurrence_ids': [f'occ-{index:03d}' for index in selected],
                          'core_occurrence_indices': selected, 'context_occurrence_indices': indices,
                          'clip_start': start, 'clip_end': min(end, float(duration_seconds)),
                          'hypotheses': copy.deepcopy(hypotheses),
                          'prior_evidence': [copy.deepcopy(item) for row in hypotheses for item in row.get('evidence', [])],
                          'expanded_draft': source_draft(reader, indices)})
    timing_pending = source_evidence.get('timing_required') is True
    remaining = ([] if covered else ['coverage']) + (['source'] if pending_source else []) + (['timing'] if timing_pending else [])
    return {'version': 1, 'identity': copy.deepcopy(identity),
            'coverage': {'status': 'accepted' if covered else 'pending', 'reason': 'bound-complete-audio-receipt' if covered else 'coverage-unverified'},
            'source': {'status': 'pending' if pending_source else 'accepted', 'reason': 'audio-discrepancy-pending' if pending_source else 'no-unresolved-discrepancy'},
            'timing': {'status': 'pending' if timing_pending else 'accepted'},
            'mode': mode, 'units': units, 'expanded_draft': draft, 'remaining_obligations': remaining}

# Observations retain audio evidence; only the later source-delta consumer may
# accept a mutation or establish whole-recording coverage.
SOURCE_OBSERVATION_VERSION = 1


def collect_source_evidence(song_dir, reader, *, flags, coverage_requested):
    import bhakti_pipeline as pipeline
    song_dir = Path(song_dir)
    if not isinstance(flags, dict) or type(coverage_requested) is not bool:
        raise ValueError('invalid source review selection')
    audio = pipeline.preferred_listener_audio(song_dir)
    duration = pipeline.gemini.duration_seconds(audio)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('invalid recording duration')
    trim = song_dir / '.transcription/trim-applied.json'
    artifacts = {}
    for name in ('01-transcript.json', '02-transcript-audit.json', '03-timing.json'):
        path = song_dir / '.transcription/pipeline' / name
        artifacts[name] = ({'path': str(path), 'sha256': file_hash(path)} if path.is_file() else None)
    # A current byte hash cannot retroactively certify historical API inputs.
    return {'identity': {'audio_sha256': file_hash(audio),
                         'trim_sha256': file_hash(trim) if trim.is_file() else None,
                         'reader_source_sha256': reader_source_identity(reader)},
            'audio_path': str(audio), 'duration_seconds': duration,
            'artifacts': artifacts, 'historical_audio_binding': 'unbound',
            'coverage_requested': coverage_requested, 'timing_required': True,
            'routing_intervals': copy.deepcopy(reader.get('SONG_TIMINGS', [])),
            'disagreements': [], 'flags': copy.deepcopy(flags)}


def materialize_source_units(plan, evidence, *, duration_seconds):
    if (plan.get('identity') != evidence.get('identity')
            or evidence.get('duration_seconds') != duration_seconds
            or not isinstance(duration_seconds, (int, float)) or isinstance(duration_seconds, bool)
            or not math.isfinite(duration_seconds) or duration_seconds <= 0):
        raise ValueError('source plan identity or duration mismatch')
    units = copy.deepcopy(plan.get('units', []))
    for index, unit in enumerate(units):
        if unit['clip_end'] - unit['clip_start'] > 900:
            raise ValueError('long audio requires independently bounded segment partition')
        unit['segment_index'] = index
        if unit['kind'] == 'coverage':
            unit['core_start'], unit['core_end'] = unit['clip_start'], unit['clip_end']
        else:
            indices = unit['core_occurrence_indices']
            intervals = evidence.get('routing_intervals', [])
            if not indices or any(type(i) is not int or not 0 <= i < len(intervals) for i in indices):
                raise ValueError('focused unit lacks exact core routing intervals')
            unit['core_start'] = intervals[min(indices)]['start']
            unit['core_end'] = min(intervals[max(indices)]['end'], duration_seconds)
    return units


def _observation_draft(draft):
    """Validate and project source-only fields; never leak public English."""
    if not isinstance(draft, dict):
        raise ValueError('source observation draft must be an object')
    lines, order = draft.get('lines'), draft.get('performance_order')
    if not isinstance(lines, list) or not lines or not isinstance(order, list) or not order:
        raise ValueError('source observation draft lacks ordered source')
    by_id = {}
    allowed = {'invocation', 'refrain', 'verse', 'bridge', 'closing', 'spoken', 'instrumental'}
    for row in lines:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'] or row['id'] in by_id:
            raise ValueError('source observation duplicate/invalid source ID')
        if (row.get('kind') not in allowed or any(not isinstance(row.get(k), str) for k in ('source_text','roman'))
                or (row['kind'] != 'instrumental' and any(not row[k].strip() for k in ('source_text','roman')))):
            raise ValueError('source observation invalid source text')
        by_id[row['id']] = {k: copy.deepcopy(row[k]) for k in ('id','source_text','roman','kind')}
        by_id[row['id']].update(language=str(row.get('language','')), partial='none', notes='')
    clean_order = []
    for row in order:
        if (not isinstance(row, dict) or row.get('line_id') not in by_id
                or type(row.get('occurrence')) is not int or row['occurrence'] < 1):
            raise ValueError('source observation invalid performed reference')
        clean_order.append({k: copy.deepcopy(row[k]) for k in ('line_id','occurrence','display_occurrence_id','repeat_index','kind') if k in row})
    if {row['line_id'] for row in clean_order} != set(by_id):
        raise ValueError('source observation contains unperformed definitions')
    return {'lines': list(by_id.values()), 'performance_order': clean_order, 'uncertainties': []}


def _observation_errors(unit, result):
    def issue(message): return {'kind': 'source_observation', 'detail': message}
    try:
        segments = result['segment_audits']
        if len(segments) != 1:
            return [issue('observation must retain exactly one raw segment')]
        packet = segments[0]['audit']['packet']
        rows, order = packet['lines'], packet['performance_order']
        if not isinstance(rows,list) or not rows or not isinstance(order,list) or not order:
            return [issue('empty source observation')]
        by_id = {}
        for row in rows:
            if (not isinstance(row,dict) or not isinstance(row.get('id'),str) or not row['id']
                    or row['id'] in by_id or row.get('kind') not in {'invocation','refrain','verse','bridge','closing','spoken','instrumental'}
                    or row.get('partial') not in {'none','leading','trailing'}
                    or any(not isinstance(row.get(k),str) for k in ('source_text','roman'))
                    or (row['kind'] != 'instrumental' and any(not row[k].strip() for k in ('source_text','roman')))):
                return [issue('invalid or duplicate observed source')]
            by_id[row['id']] = row
        if (any(not isinstance(row,dict) or row.get('line_id') not in by_id
                or type(row.get('occurrence')) is not int or row['occurrence'] < 1 for row in order)
                or {r['line_id'] for r in order} != set(by_id)):
            return [issue('invalid observed performance order')]
        uncertainties=packet.get('uncertainties')
        if not isinstance(uncertainties,list) or uncertainties:
            return [issue('source observation has unresolved uncertainty')]
        original = unit['expanded_draft']; old_by = {row['id']:row for row in original['lines']}
        key=lambda row: (row['source_text'],row['roman'],row['kind'])
        target_ids=set(unit['target_occurrence_ids'])
        targets={key(old_by[e['line_id']]) for e in original['performance_order'] if e['display_occurrence_id'] in target_ids}
        contexts=[key(old_by[e['line_id']]) for e in original['performance_order'] if e['display_occurrence_id'] not in target_ids]
        for i,event in enumerate(order):
            row=by_id[event['line_id']];partial=row['partial']
            if partial=='none':continue
            outside=(partial=='leading' and i==0 and unit['clip_start'] < unit['core_start']) or (partial=='trailing' and i==len(order)-1 and unit['core_end'] < unit['clip_end'])
            if not outside or key(row) in targets or contexts.count(key(row)) != 1:
                return [issue('partial target or ambiguous clipped context remains unresolved')]
        return []
    except (KeyError,TypeError,ValueError):
        return [issue('malformed raw source observation')]


def _source_observation_context(unit):
    """Source-only projections; preserve original raw files separately by hash."""
    hypotheses = unit.get('hypotheses', [])
    if not isinstance(hypotheses, list):
        raise ValueError('invalid source hypotheses')
    projected = []
    source_fields = ('source_text','roman','language','kind','partial','notes')
    for item in hypotheses:
        if not isinstance(item,dict) or not isinstance(item.get('alternatives',[]),list):
            raise ValueError('invalid source hypothesis alternatives')
        alternatives=[]
        for value in item.get('alternatives',[]):
            if isinstance(value,str):alternatives.append(value)
            elif isinstance(value,dict):alternatives.append({k:copy.deepcopy(value[k]) for k in source_fields if k in value})
            else:raise ValueError('invalid source hypothesis')
        projected.append({**{k:copy.deepcopy(item[k]) for k in ('id','reason') if k in item},'alternatives':alternatives})
    prior=[]
    for item in unit.get('prior_evidence',[]):
        value=json.loads(Path(item['path']).read_text())
        packet=value.get('packet',value) if isinstance(value,dict) else None
        if not isinstance(packet,dict):raise ValueError('unsupported prior source packet')
        lines=packet.get('lines');order=packet.get('performance_order');uncertainties=packet.get('uncertainties')
        if not isinstance(lines,list) or not lines or not isinstance(order,list) or not order or not isinstance(uncertainties,list):
            raise ValueError('unsupported prior source packet shape')
        definitions=[];ids=set()
        for row in lines:
            if (not isinstance(row,dict) or not isinstance(row.get('id'),str) or not row['id'] or row['id'] in ids
                    or any(not isinstance(row.get(k),str) for k in ('source_text','roman'))):
                raise ValueError('invalid prior source definition')
            ids.add(row['id']);definitions.append({k:copy.deepcopy(row[k]) for k in ('id',*source_fields) if k in row})
        if any(not isinstance(row,dict) or row.get('line_id') not in ids for row in order):
            raise ValueError('invalid prior source order')
        prior.append({'sha256':item['sha256'],'lines':definitions,
                      'performance_order':[{k:copy.deepcopy(row[k]) for k in ('line_id','occurrence') if k in row} for row in order],
                      'uncertainties':copy.deepcopy(uncertainties)})
    return {'hypotheses':projected,'prior_source_observations':prior}


def review_audio_units(*, song_dir, units, audio, source_identity, options, route_dir, deadline_at):
    import re
    import bhakti_pipeline as pipeline
    import bhakti_library_pass as library
    import bhakti_model_routes as routes
    song_dir, audio = Path(song_dir), Path(audio)
    if not math.isfinite(deadline_at) or deadline_at <= time.time():
        raise ValueError('source observation deadline exhausted')
    if (not isinstance(source_identity,dict) or source_identity.get('audio_sha256') != file_hash(audio)
            or source_identity.get('trim_sha256') is not None and not re.fullmatch('[0-9a-f]{64}',str(source_identity['trim_sha256']))):
        raise ValueError('source observation native audio identity mismatch')
    trim = song_dir / '.transcription/trim-applied.json'
    if source_identity.get('trim_sha256') != (file_hash(trim) if trim.is_file() else None):
        raise ValueError('source observation trim identity mismatch')
    duration=pipeline.gemini.duration_seconds(audio)
    if not math.isfinite(duration) or duration <= 0 or not isinstance(units,list):
        raise ValueError('invalid observation recording/units')
    prepared=[]; seen=set()
    for unit in units:
        if not isinstance(unit,dict) or not isinstance(unit.get('id'),str) or not unit['id'] or unit['id'] in seen:
            raise ValueError('duplicate/invalid source observation unit')
        seen.add(unit['id'])
        if any(not isinstance(unit.get(k),(int,float)) or isinstance(unit[k],bool) or not math.isfinite(unit[k]) for k in ('clip_start','clip_end','core_start','core_end')):
            raise ValueError('invalid source observation bounds')
        if not 0 <= unit['clip_start'] <= unit['core_start'] < unit['core_end'] <= unit['clip_end'] <= duration:
            raise ValueError('source observation bounds outside recording/core')
        if unit['clip_end']-unit['clip_start'] > 900:
            raise ValueError('long audio requires segment partition')
        if type(unit.get('segment_index')) is not int or unit['segment_index'] < 0:
            raise ValueError('invalid source segment index')
        draft=_observation_draft(unit.get('expanded_draft'))
        targets=unit.get('target_occurrence_ids')
        if (not isinstance(targets,list) or not targets or any(not isinstance(v,str) for v in targets)
                or len(set(targets))!=len(targets)
                or not set(targets).issubset({e.get('display_occurrence_id') for e in draft['performance_order']})):
            raise ValueError('unknown or duplicate source target lineage')
        for event in draft['performance_order']:
            if (not isinstance(event.get('display_occurrence_id'),str) or not re.fullmatch(r'occ-[0-9]{3,}',event['display_occurrence_id'])
                    or type(event.get('repeat_index')) is not int or event['repeat_index'] < 0):
                raise ValueError('invalid source occurrence lineage')
        evidence=unit.get('prior_evidence',[])
        if not isinstance(evidence,list):raise ValueError('invalid prior source evidence')
        for item in evidence:
            if not isinstance(item,dict) or not isinstance(item.get('path'),str) or file_hash(item['path']) != item.get('sha256'):
                raise ValueError('prior source evidence identity mismatch')
        prepared.append((copy.deepcopy(unit),draft,_source_observation_context(unit)))
    # The actual witness used by the pipeline must participate in cache identity.
    witness_record=pipeline.source_witness.record_for_slug(song_dir.name)
    witness_path=pipeline.source_witness.cache_path(song_dir)
    if witness_record and not witness_path.is_file():
        raise ValueError('registered source witness must be acquired and bound before observation dispatch')
    witness_snapshot=None
    if witness_record:
        witness_snapshot=json.loads(witness_path.read_text())
        if (not isinstance(witness_snapshot,dict) or type(witness_snapshot.get('schema_version')) is not int
                or witness_snapshot['schema_version'] != 1 or witness_snapshot.get('work') != song_dir.name
                or witness_snapshot.get('witness') != witness_record or not isinstance(witness_snapshot.get('lines'),list)
                or not witness_snapshot['lines'] or any(not isinstance(row,dict)
                    or not isinstance(row.get('text'),str) or not row['text'].strip() or 'page' not in row
                    for row in witness_snapshot['lines'])):
            raise ValueError('registered source witness snapshot is empty, malformed, or mismatched')
    witness_identity={'record':witness_record,'snapshot':witness_snapshot}
    dependency=digest({'version':SOURCE_OBSERVATION_VERSION,'pipeline_sha256':file_hash(pipeline.__file__),
                       'adapter_sha256':file_hash(__file__),'witness':witness_identity})
    observed=[];issues=[]
    for unit,draft,source_context in prepared:
        fingerprint=digest({'unit':unit,'draft':draft,'source_identity':source_identity,'duration':duration,'dependency':dependency})
        def execute(context):
            local=library.route_options(options,context);local.source_witness_audit=False
            attempt_song=context.attempt_dir/'songs'/song_dir.name
            segment={'index':unit['segment_index'],**{k:unit[k] for k in ('clip_start','clip_end','core_start','core_end')}}
            raw={'packet':{'segmented':True,'source_first_witness':False,'segments':[{'segment':segment,'transcript':draft}]}}
            return pipeline.audit_long_transcript(attempt_song,raw,audio,local,
                observation_context={'witness':witness_snapshot,'source_context':source_context})
        try:
            result=routes.run_unit(route_dir,song_dir.name+':source-observation:'+unit['id'],fingerprint,execute,
                                  lambda result:_observation_errors(unit,result),deadline_at=deadline_at,
                                  dependency_fingerprint=dependency,base_model=options.model,pro_model=options.pro_model)
            errors=_observation_errors(unit,result)
            if errors:raise routes.RunFatal('cached source observation no longer validates')
            observed.append({'unit':unit,'result':result,'input_fingerprint':fingerprint})
        except routes.UnitUnresolved as exc:
            issues.append({'unit_id':unit['id'],'reason':exc.reason,'issues':exc.issues,'state_path':str(exc.state_path)})
    return {'status':'unresolved' if issues else 'observed','unit_results':observed,'issues':issues}

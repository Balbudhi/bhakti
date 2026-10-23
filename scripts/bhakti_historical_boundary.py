"""Private, resumable preparation of a complete historical boundary candidate.

Prepared files are not publication authorization. The original, source candidate
and final candidate have distinct lifetimes; none is installed by this module.
"""
from __future__ import annotations

import copy
import fcntl
import json
import math
import re
import shutil
import time
from pathlib import Path


def snapshot(directory):
    from bhakti_library_source_pass import file_hash
    directory = Path(directory)
    return {str(path.relative_to(directory)): file_hash(path)
        for path in sorted(directory.rglob('*')) if path.is_file()}


def bound(path):
    from bhakti_library_source_pass import file_hash
    return {'path': str(path), 'sha256': file_hash(path)}


def read_bound(declaration):
    from bhakti_library_source_pass import file_hash
    path = Path(declaration['path'])
    if file_hash(path) != declaration['sha256']:
        raise ValueError('historical preparation evidence hash changed: ' + str(path))
    return json.loads(path.read_text())


def root_data_snapshot(root):
    from bhakti_library_source_pass import file_hash
    return {str(path.relative_to(root)): file_hash(path) for path in sorted((root/'data').glob('*.json'))}


def copy_root_data(root, destination, expected):
    from bhakti_library_source_pass import file_hash
    for name, digest in expected.items():
        target = destination/name
        if target.exists():
            if file_hash(target) != digest:
                raise ValueError('private historical metadata copy changed: ' + name)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root/name, target)
        if file_hash(target) != digest:
            raise ValueError('historical metadata changed during copy: ' + name)


def validate_semantic_result(before, after, evidence, protected):
    import bhakti_candidate_guard as guard
    import bhakti_library_pass as library
    import bhakti_library_source_pass as source
    for path, expected in evidence['files'].items():
        if source.file_hash(path) != expected:
            raise ValueError('historical candidate semantic evidence changed')
    pre, repaired = evidence['pre_review'], evidence['repaired']
    lines, glosses, _ = library.reader_evidence(before)
    validate_semantic_routes(before, evidence, protected, lines, glosses)
    errors = library.current_review_errors(pre, lines, glosses, source.digest(before), evidence['dependency'])
    if errors:
        raise ValueError('historical candidate review is invalid: ' + str(errors))
    authorization = guard.authorize_semantic_candidate(before, after, source_lines=lines,
        gloss_rows=glosses, pre_review=pre, post_review=repaired['post_review'],
        dependency_fingerprint=evidence['dependency'], protected_english=protected,
        finding_snapshot=pre.get('finding_snapshot'), allow_partial=pre.get('finding_snapshot') is not None)
    if (after != repaired['reader'] or authorization != repaired['authorization']
            or authorization.get('publicationEligible') is False):
        raise ValueError('historical candidate semantic authorization is unresolved or changed')


def validate_semantic_routes(before, evidence, protected, lines, glosses):
    """Read the library-owned routes and journal; never recreate missing history."""
    import bhakti_library_pass as library
    import bhakti_library_source_pass as source
    import bhakti_model_routes as routes
    pre, repaired = evidence['pre_review'], evidence['repaired']
    context = evidence['route_context']
    dependency = evidence['dependency']

    def accepted(purpose, request):
        path = routes.unit_state_path(Path(context['route_dir']), context['slug']+':'+purpose,
            source.digest(request), dependency_fingerprint=dependency,
            base_model=context['model'], pro_model=context['pro_model'])
        cached = routes.read_unit_cache(path)
        if cached['state']['status'] != 'accepted':
            raise ValueError('historical semantic route is not accepted')
        return path, cached

    audit_path, audit = accepted('current-source-review', {'version': library.VERSION,
        'reader': before, 'policy': context['policy'], 'baseline': protected,
        'purpose': 'identify-current-defects'})
    raw_pre = {key: value for key, value in pre.items()
        if key not in {'finding_snapshot', 'finding_journal_path', 'finding_route_state_path'}}
    if str(audit_path) != pre['finding_route_state_path'] or audit['result'] != raw_pre:
        raise ValueError('historical pre-review differs from accepted route evidence')
    finding_context = dict(lines=lines, glosses=glosses, reader_digest=source.digest(before),
        dependency_fingerprint=dependency)
    journal = library.finding_store.load_snapshot(Path(pre['finding_journal_path']), **finding_context)
    if journal != pre['finding_snapshot']:
        raise ValueError('historical review journal differs from retained findings')
    # read_unit_cache checks each anchored candidate. Also establish that the
    # journal contains exactly those observations, including failed attempts.
    observations = []
    for index, attempt in enumerate(audit['state']['attempts']):
        candidate = audit_path.parent/('flash' if index == 0 else 'pro')/'candidate.json'
        if attempt.get('candidate_sha256') is not None:
            artifact = json.loads(candidate.read_text())
            if artifact.get('attempt_id') != attempt['attempt_id']:
                raise ValueError('historical review attempt identity changed')
            observations.append(artifact)
        elif candidate.exists():
            raise ValueError('historical review has unbound candidate evidence')
    if [entry['artifact'] for entry in journal['reviews']] != observations:
        raise ValueError('historical review journal differs from original route history')
    if repaired['post_review'] is not None:
        _, repair = accepted('targeted-semantics', {'version': library.VERSION,
            'reader': before, 'pre_review': pre, 'policy': context['policy'], 'baseline': protected})
        if repair['result'] != {key: value for key, value in repaired.items() if key != 'authorization'}:
            raise ValueError('historical repair differs from accepted route evidence')


def validate_historical_preparation(song_dir, prepared):
    """Revalidate a private completed result, without models or live writes."""
    import audit_bhakti_contract as contract
    import bhakti_library_source_pass as source
    import editorial_baselines
    song = Path(song_dir).resolve()
    if prepared.get('status') != 'prepared' or prepared.get('publicationEligible') is not False:
        raise ValueError('historical candidate lacks private prepared status')
    manifest = read_bound(prepared['manifest'])
    if (manifest.get('version') != 1 or manifest.get('original_song') != str(song)
            or manifest.get('candidate_song_dir') != prepared.get('candidate_song_dir')
            or manifest.get('original_archive') != prepared.get('original_archive')):
        raise ValueError('historical preparation manifest binding changed')
    root = song.parent.parent
    if snapshot(song) != manifest['original_files'] or root_data_snapshot(root) != manifest['root_data']:
        raise ValueError('original historical inputs changed during preparation')
    archive = Path(manifest['original_archive'])
    target = Path(manifest['candidate_song_dir'])
    if snapshot(archive) != manifest['original_files'] or snapshot(target) != manifest['candidate_files']:
        raise ValueError('historical archive or candidate file snapshot changed')
    if root_data_snapshot(target.parent.parent) != manifest['root_data']:
        raise ValueError('historical final metadata snapshot changed')
    original = contract.load_data(archive/'data.js')
    source_result = read_bound(manifest['source_result'])
    source.verify_source_result_evidence(source_result, original)
    stage = Path(manifest['source_candidate_song_dir'])
    if (contract.load_data(stage/'data.js') != source_result['reader']
            or source.file_hash(stage/'index.html') != source_result['evidence']['candidate_html_sha256']):
        raise ValueError('historical source candidate changed')
    final = contract.load_data(target/'data.js')
    baseline = editorial_baselines.load_baselines(root).get(song.name)
    protected = baseline['plainEnglishByLine'] if baseline else None
    if manifest['semantic_result'] is not None:
        validate_semantic_result(source_result['reader'], final,
            read_bound(manifest['semantic_result']), protected)
    elif source_result['source_changed'] or final != source_result['reader']:
        raise ValueError('changed historical source/context lacks final semantic review')
    editorial_baselines.assert_english_preserved(song.name, final['SONG_LINES'], root=root)
    if contract.audit_song(target)['status'] != 'ready':
        raise ValueError('historical candidate reader contract changed')
    return manifest


def _write_final_candidate(stage, final, reader, source_result, semantic, original_archive):
    import bhakti_pipeline as pipeline
    import bhakti_library_pass as library
    import bhakti_library_source_pass as source
    import apply_translation_style_review as writer
    final.mkdir(parents=True, exist_ok=True)
    names = [row['src'] for row in pipeline.listener_audio_sources(stage)]
    names += ['.transcription/source.json', '.transcription/trim-review.json',
        '.transcription/trim-applied.json', '.transcription/trim-originals.json',
        '.transcription/language-review.json', '.transcription/witnesses/textual-witness.json']
    names += ['.transcription/original-audio/' + row['src'] for row in pipeline.listener_audio_sources(stage)]
    for name in names:
        if (stage/name).is_file():
            (final/name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(stage/name, final/name)
    marker_path = final/'.transcription/trim-applied.json'
    marker = pipeline.read_packet(marker_path)
    if not marker or marker.get('status') != 'applied':
        raise ValueError('historical final candidate lacks its applied private crop')
    source.atomic_json(marker_path, {**marker, 'adoption': {'status': 'pending',
        'phase': 'private-prepared', 'remaining_obligations': [
            'playback-clock-qualification', 'installation-and-regeneration']}})
    writer.write_reader(final.name, reader, root=final.parent.parent)
    html = pipeline.page_html(reader['SONG_META'], final.name)
    html, count = re.subn(r'(?<=src=")data\.js(?:\?v=[^"\s]+)?(?=")',
        'data.js?v=' + source.file_hash(final/'data.js')[:12], html)
    if count != 1:
        raise ValueError('historical final page lacks one data reference')
    (final/'index.html').write_text(html)
    derived = pipeline.read_packet(stage/'.transcription/source-pass-derived.json')
    if not derived:
        raise ValueError('historical source candidate lacks derived artifacts')
    _, gloss_rows, translations = library.reader_evidence(reader)
    provenance = {'original_archive': str(original_archive),
        'source_adoption': source_result['evidence']['source_adoption_receipt'],
        'description': 'Derived from accepted source/timing and preserved or independently reviewed reader text; not a new provider response.'}
    audited = copy.deepcopy(derived['audit'])
    raw = {'packet': {'lines': copy.deepcopy(audited['packet']['verified_lines']),
        'performance_order': copy.deepcopy(audited['packet']['performance_order']), 'uncertainties': []},
        'derivation': provenance}
    glosses = {'packet': {'glosses': gloss_rows}, 'derivation': provenance}
    english = {'packet': {'translations': translations}, 'derivation': provenance}
    timing = derived['timing']
    summary = {'transcript': raw, 'audit': audited, 'timing': timing,
        'glosses': glosses, 'translation': english, 'derivation': provenance,
        'publication_status': 'private-prepared', 'semantic_result': semantic,
        'validation_errors': [], 'remaining_obligations': ['playback-clock-qualification', 'installation-and-regeneration']}
    for filename, value in [('01-transcript.json', raw), ('02-transcript-audit.json', audited),
            ('03-timing.json', timing), ('04-glosses.json', glosses),
            ('05-translation.json', english), ('song-packet.json', summary)]:
        source.atomic_json(final/'.transcription/pipeline'/filename, value)


def _prepare(song, boundary, workspace, options, state, inputs, deadline):
    import audit_bhakti_contract as contract
    import bhakti_pipeline as pipeline
    import bhakti_library_pass as library
    import bhakti_library_source_pass as source
    import bhakti_boundary_adoption as adoption
    import editorial_baselines
    root = song.parent.parent
    result_path = state/'prepared.json'
    if result_path.is_file():
        result = json.loads(result_path.read_text())
        validate_historical_preparation(song, result)
        return result
    if deadline <= time.time():
        raise ValueError('historical preparation requires the existing unexpired run deadline')
    archive = state/'original'/song.name
    if not archive.exists():
        temporary = state/'original-copy'/song.name
        if temporary.exists():
            shutil.rmtree(temporary)
        shutil.copytree(song, temporary)
        if snapshot(temporary) != inputs['original_files'] or snapshot(song) != inputs['original_files']:
            raise ValueError('original changed while preserving historical archive')
        archive.parent.mkdir(parents=True, exist_ok=True)
        temporary.rename(archive)
    if snapshot(archive) != inputs['original_files']:
        raise ValueError('preserved historical archive changed')
    copy_root_data(root, workspace, inputs['root_data'])
    stage = workspace/'songs'/song.name
    transform_path = state/'initial-transform.json'
    if not transform_path.is_file():
        if not stage.exists():
            shutil.copytree(archive, stage)
        current = snapshot(stage)
        if current != inputs['original_files']:
            native_names = {row['src'] for row in pipeline.listener_audio_sources(archive)}
            controls = {'.transcription/trim-applied.json', '.transcription/trim-originals.json'}
            allowed_new = controls | {'.transcription/original-audio/' + name for name in native_names}
            marker = pipeline.read_packet(stage/'.transcription/trim-applied.json') or {}
            if (set(current) - set(inputs['original_files']) - allowed_new
                    or any(current.get(name) != digest for name, digest in inputs['original_files'].items()
                        if name not in native_names | controls)
                    or marker.get('application_version') != 2
                    or marker.get('status') not in {'pending', 'applied'}
                    or any(marker.get(key) != boundary[key] for key in ('trim_start', 'trim_end', 'source_sha256'))):
                raise ValueError('historical preparation needs unchanged inputs or its exact interrupted crop')
            # The existing crop operation validates old/planned native hashes
            # and its original-audio manifest before completing the private cut.
        pipeline.apply_lossless_trim(stage, boundary)
        native = {}
        for row in pipeline.listener_audio_sources(archive):
            name = row['src']
            measurement = pipeline.measure_boundary_timebase(archive/name, stage/name,
                requested_start=boundary['trim_start'])
            if measurement.get('status') != 'verified':
                raise ValueError('historical native correspondence unresolved: ' + name)
            native[name] = {'before': bound(archive/name), 'after': bound(stage/name), 'measurement': measurement}
        def identity(directory):
            audio = pipeline.preferred_listener_audio(directory)
            marker = directory/'.transcription/trim-applied.json'
            return {'audio_sha256': source.file_hash(audio),
                'trim_sha256': source.file_hash(marker) if marker.is_file() else None,
                'trim': pipeline.read_packet(marker) or {}, 'duration_seconds': pipeline.gemini.duration_seconds(audio)}
        transform = {'version': 1, 'kind': 'boundary-timebase', 'status': 'verified',
            'before': {**identity(archive), 'reader_sha256': source.file_hash(archive/'data.js'),
                'archive_files': adoption.original_archive_snapshot(archive)},
            'after': identity(stage), 'boundary': boundary, 'native': native,
            'timing_basis': {'status': 'unresolved', 'reason': 'Decoded correspondence alone does not qualify browser/model clock origin.'}}
        source.atomic_json(transform_path, transform)
    reader = contract.load_data(archive/'data.js')
    local = copy.copy(options)
    local.unit_deadline_at = deadline
    local.source_audio_transform = bound(transform_path)
    flags = copy.deepcopy(getattr(options, 'source_review_flags', {}))
    edges = set(flags.get('occurrence_ids', []))
    if boundary['trim_start'] > 0:
        edges.add('occ-000')
    if boundary['trim_end'] < boundary['duration']:
        edges.add(f'occ-{len(reader["SONG_SEQUENCE"])-1:03d}')
    flags.update(audio=True, occurrence_ids=sorted(edges))
    local.source_review_flags = flags
    local.source_requested_stages = sorted(set(getattr(options, 'source_requested_stages', [])) | {'focused-audio-review'})
    local.source_coverage_requested = getattr(options, 'source_coverage_requested', False)
    routes = Path(getattr(options, 'boundary_route_dir', state/'routes'))
    source_result = source.run_source_candidate(root=root, slug=song.name, reader=reader,
        workspace=workspace, route_dir=routes, options=local, deadline_at=deadline)
    if source_result['status'] != 'accepted':
        return {'status': 'unresolved', 'publicationEligible': False,
            'source': source_result, 'issues': source_result.get('issues', [])}
    source_path = state/'source-result.json'
    source.atomic_json(source_path, source_result)
    final_reader = source_result['reader']
    semantic_declaration = None
    if source_result['source_changed']:
        dependency = source.digest({'inputs': inputs, 'source_result': source.digest(source_result)})
        baseline = editorial_baselines.load_baselines(root).get(song.name)
        protected = baseline['plainEnglishByLine'] if baseline else None
        pre = library.audit_current_reader(final_reader, slug=song.name, workspace=workspace,
            route_dir=routes, options=local, dependency_fingerprint=dependency,
            deadline_at=deadline, protected_english=protected)
        repaired = library.repair_current_reader(final_reader, slug=song.name, pre_review=pre,
            workspace=workspace, route_dir=routes, options=local,
            dependency_fingerprint=dependency, deadline_at=deadline, protected_english=protected)
        files = {}
        for key in ('finding_journal_path', 'finding_route_state_path'):
            if pre.get(key):
                files[pre[key]] = source.file_hash(pre[key])
        lines, _, _ = library.reader_evidence(final_reader)
        semantic_options = library.lexical_options(local, song.name, lines,
            final_reader.get('SONG_META', {}).get('languages', []))
        evidence = {'pre_review': pre, 'repaired': repaired, 'dependency': dependency, 'files': files,
            'route_context': {'slug': song.name, 'route_dir': str(routes),
                'model': local.model, 'pro_model': local.pro_model,
                'policy': pipeline.semantic_stage_policy(semantic_options)}}
        validate_semantic_result(final_reader, repaired['reader'], evidence, protected)
        semantic_path = state/'semantic-result.json'
        source.atomic_json(semantic_path, evidence)
        semantic_declaration = bound(semantic_path)
        final_reader = repaired['reader']
    final = state/'final'/'songs'/song.name
    copy_root_data(root, final.parent.parent, inputs['root_data'])
    _write_final_candidate(stage, final, final_reader, source_result, semantic_declaration, archive)
    manifest = {'version': 1, 'original_song': str(song), 'original_files': inputs['original_files'],
        'root_data': inputs['root_data'], 'original_archive': str(archive),
        'source_candidate_song_dir': str(stage), 'candidate_song_dir': str(final),
        'candidate_files': snapshot(final), 'source_result': bound(source_path),
        'semantic_result': semantic_declaration, 'inputs': inputs}
    manifest_path = state/'manifest.json'
    source.atomic_json(manifest_path, manifest)
    result = {'status': 'prepared', 'publicationEligible': False, 'manifest': bound(manifest_path),
        'original_archive': str(archive), 'candidate_song_dir': str(final),
        'remaining_obligations': ['playback-clock-qualification', 'installation-and-regeneration']}
    validate_historical_preparation(song, result)
    source.atomic_json(result_path, result)
    return result


def prepare_historical_boundary_candidate(song_dir, boundary, *, workspace, options):
    """Prepare one private candidate under the caller's existing budget/deadline."""
    import bhakti_pipeline as pipeline
    import bhakti_library_source_pass as source
    import bhakti_model_routes as routes
    song, workspace = Path(song_dir).resolve(), Path(workspace).resolve()
    try:
        if workspace == song.parent.parent or workspace.is_relative_to(song):
            raise ValueError('historical preparation requires a separate private workspace')
        pipeline.require_completed_boundary_transaction(song)
        normalized = pipeline.normalize_trim_artifact(boundary)
        if (normalized.get('status') != 'reviewed' or normalized.get('validation_errors')
                or any(boundary.get(k) != normalized.get(k) for k in ('trim_start', 'trim_end'))):
            raise ValueError('historical preparation requires accepted current boundary evidence')
        inputs = {'original_files': snapshot(song), 'root_data': root_data_snapshot(song.parent.parent),
            'boundary': boundary, 'model': options.model, 'pro_model': options.pro_model,
            'source_request': {'flags': copy.deepcopy(getattr(options, 'source_review_flags', {})),
                'stages': sorted(getattr(options, 'source_requested_stages', [])),
                'coverage_requested': getattr(options, 'source_coverage_requested', False)},
            'route_dir': str(Path(options.boundary_route_dir).resolve()) if getattr(options, 'boundary_route_dir', None) else None,
            'policy': pipeline.semantic_stage_policy(options),
            'implementation': {name: source.file_hash(path) for name, path in (
                ('preparation', Path(__file__)), ('source', Path(source.__file__)), ('pipeline', Path(pipeline.__file__)))}}
        identity = source.digest(inputs)
        home = workspace/'.transcription'/'historical-boundary'/song.name
        home.mkdir(parents=True, exist_ok=True)
        with (home/'preparation.lock').open('a+b') as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError('historical workspace already has an active preparer') from exc
            binding_path = home/'input.json'
            if binding_path.exists():
                binding = json.loads(binding_path.read_text())
                if binding.get('fingerprint') != identity or binding.get('inputs') != inputs:
                    raise ValueError('historical inputs changed; retain this attempt and use a fresh workspace')
            else:
                binding = {'fingerprint': identity, 'inputs': inputs,
                    'deadline_at': getattr(options, 'unit_deadline_at', None)}
            deadline = binding.get('deadline_at')
            if type(deadline) not in (int, float) or not math.isfinite(deadline):
                raise ValueError('historical preparation requires a bound finite absolute deadline')
            state = home/identity
            if (state/'prepared.json').is_file():
                return _prepare(song, boundary, workspace, options, state, inputs, deadline)
            requested_deadline = getattr(options, 'unit_deadline_at', None)
            if type(requested_deadline) not in (int, float) or not math.isfinite(requested_deadline):
                raise ValueError('historical preparation requires a bound finite absolute deadline')
            # A resumed caller may shorten its allowance, but cannot grant a
            # new stage more time than the original preparation was given.
            deadline = min(deadline, requested_deadline)
            if not binding_path.exists() or deadline != binding['deadline_at']:
                source.atomic_json(binding_path, {**binding, 'deadline_at': deadline})
            state.mkdir(parents=True, exist_ok=True)
            return _prepare(song, boundary, workspace, options, state, inputs, deadline)
    except (routes.RunFatal, routes.UnitTransportFailure):
        raise
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        return {'status': 'unresolved', 'publicationEligible': False,
            'issues': [{'kind': 'historical_preparation', 'detail': str(exc)}]}

"""Optional boundary transform admission for the existing source/timing engines."""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

_VERIFIED_MEASUREMENTS = set()


def original_evidence_song(transform):
    """Resolve the single preserved original directory bound by all formats."""
    native = transform.get('native', {})
    if not isinstance(native, dict) or not native:
        raise ValueError('boundary transform lacks original native files')
    directories = set()
    for name, row in native.items():
        path = Path(row['before']['path']).resolve()
        if path.name != name:
            raise ValueError('boundary transform original filename differs')
        directories.add(path.parent)
    if len(directories) != 1:
        raise ValueError('boundary transform original formats have different archives')
    return directories.pop()


def original_archive_snapshot(song):
    """Required original reader, native formats and source-support files."""
    import bhakti_pipeline as pipeline
    import bhakti_library_source_pass as source
    song = Path(song)
    names = {'data.js', '.transcription/trim-applied.json',
        '.transcription/pipeline/01-transcript.json',
        '.transcription/pipeline/02-transcript-audit.json',
        '.transcription/pipeline/03-timing.json',
        str(pipeline.source_witness.cache_path(song).relative_to(song)),
        *(row['src'] for row in pipeline.listener_audio_sources(song))}
    return {name: source.file_hash(song / name) if (song / name).is_file() else None for name in names}


def _check_original_archive(transform, live_song):
    """Bind durable original evidence, and check live input on fresh admission.

    Replay supplies the archived original itself. Fresh processing supplies the
    authoritative live directory and must match the complete bound snapshot.
    The install coordinator remains responsible for the final live recheck.
    """
    import bhakti_pipeline as pipeline
    import bhakti_library_source_pass as source
    archive = original_evidence_song(transform)
    live_song = Path(live_song).resolve()
    if archive.name != live_song.name:
        raise ValueError('boundary archive must preserve the original song slug')
    snapshot = transform['before'].get('archive_files')
    if snapshot is None:
        if archive != live_song:
            raise ValueError('boundary original archive requires a bound snapshot')
        return archive  # Legacy declarations only support pre-install replay.
    expected = original_archive_snapshot(archive)
    if not isinstance(snapshot, dict) or set(snapshot) != set(expected):
        raise ValueError('boundary original archive snapshot is incomplete')
    for directory in {archive, live_song}:
        if {row['src'] for row in pipeline.listener_audio_sources(directory)} != set(transform['native']):
            raise ValueError('boundary original archive/live native population changed')
        actual = expected if directory == archive else original_archive_snapshot(directory)
        if actual != snapshot:
            raise ValueError('boundary original archive/live snapshot changed')
    return archive


def checked_audio_transform(declaration, original_song, staged_song, reader):
    """Check the same immutable document at both existing native admission guards."""
    import bhakti_pipeline as pipeline
    import bhakti_library_source_pass as source
    import bhakti_boundary_timebase as timebase
    if not isinstance(declaration, dict) or set(declaration) != {'path','sha256'}:
        raise ValueError('boundary transform needs an exact path/hash declaration')
    path=Path(declaration['path'])
    if source.file_hash(path) != declaration['sha256']:
        raise ValueError('boundary transform declaration bytes changed')
    value=json.loads(path.read_text())
    if (value.get('version') != 1 or value.get('kind') != 'boundary-timebase'
            or value.get('status') != 'verified'):
        raise ValueError('boundary transform is not verified')
    original_song = _check_original_archive(value, original_song)
    staged_song = Path(staged_song)
    before,after=value['before'],value['after']
    actual_names={row['src'] for row in pipeline.listener_audio_sources(original_song)}
    if (not actual_names or actual_names != {row['src'] for row in pipeline.listener_audio_sources(staged_song)}
            or set(value.get('native',{})) != actual_names):
        raise ValueError('boundary transform does not bind the complete native format set')
    for key,song in [('before',original_song),('after',staged_song)]:
        binding=value[key];marker=song/'.transcription/trim-applied.json'
        if binding.get('trim_sha256') != (source.file_hash(marker) if marker.is_file() else None):
            raise ValueError('boundary transform trim marker changed')
        trim=pipeline.read_packet(marker) or {}
        if binding.get('trim') != trim:
            raise ValueError('boundary transform trim content differs from bound marker')
        if trim.get('status') == 'pending' or (trim.get('adoption') or {}).get('status') == 'pending':
            raise ValueError('pending boundary transform cannot authorize source consumption')
        audio=pipeline.preferred_listener_audio(song)
        if binding.get('audio_sha256') != source.file_hash(audio):
            raise ValueError('boundary transform preferred native identity changed')
        if abs(binding.get('duration_seconds',-1)-pipeline.gemini.duration_seconds(audio)) > .000001:
            raise ValueError('boundary transform recording duration changed')
    if before.get('reader_sha256') != source.file_hash(original_song/'data.js'):
        raise ValueError('boundary transform original reader changed')
    boundary=pipeline.normalize_trim_artifact(value['boundary'])
    if boundary.get('status') != 'reviewed' or boundary.get('validation_errors'):
        raise ValueError('boundary transform lacks accepted relationship evidence')
    if (boundary['source_sha256'] != before['audio_sha256']
            or value['boundary'].get('trim_start') != boundary['trim_start']
            or value['boundary'].get('trim_end') != boundary['trim_end']):
        raise ValueError('boundary transform source or accepted interval changed')
    applied=pipeline.read_packet(staged_song/'.transcription/trim-applied.json') or {}
    if (applied.get('status') != 'applied' or applied.get('application_version') != 2
            or applied.get('trim_start') != boundary['trim_start'] or applied.get('trim_end') != boundary['trim_end']):
        raise ValueError('boundary transform staged marker differs from reviewed crop')
    for name,row in value['native'].items():
        original,output=original_song/name,staged_song/name
        for key,actual in [('before',original),('after',output)]:
            if (Path(row[key]['path']).resolve() != actual.resolve()
                    or row[key]['sha256'] != source.file_hash(actual)):
                raise ValueError('boundary transform native file changed: '+name)
        witness=row['measurement']
        if (witness.get('status') != 'verified' or witness.get('source_sha256') != row['before']['sha256']
                or witness.get('output_sha256') != row['after']['sha256']
                or applied.get('outputs',{}).get(name,{}).get('sha256') != row['after']['sha256']):
            raise ValueError('boundary transform decoded witness changed: '+name)
        key=(row['before']['sha256'],row['after']['sha256'],boundary['trim_start'],source.digest(witness))
        if key not in _VERIFIED_MEASUREMENTS:
            measured=timebase.measure_boundary_timebase(original,output,requested_start=boundary['trim_start'])
            if measured != witness:
                raise ValueError('boundary transform decoded measurement does not reproduce: '+name)
            _VERIFIED_MEASUREMENTS.add(key)
    checked_original_memberships(value,reader,original_song)
    return value


def checked_original_memberships(transform, reader, original_song):
    """Validate exact original-edge hearing and independent source confirmation."""
    import bhakti_pipeline as pipeline
    import bhakti_library_source_pass as source
    import bhakti_model_routes as routes
    original_song = _check_original_archive(transform, original_song)
    full=source.source_draft(reader);order=full['performance_order']
    identity=source.collect_source_evidence(original_song,reader,flags={'audio':True},coverage_requested=False)['identity']
    result=set();edge_indices={'start':set(),'end':set()}
    for membership in transform.get('original_edge_membership',[]):
        edge=membership['edge'];boundary=transform['boundary'][edge]
        if (membership.get('source_identity') != identity or edge not in {'start','end'}
                or membership.get('boundary_digest') != source.digest(boundary)):
            raise ValueError('original-edge membership boundary or recording identity changed')
        interval=({'start':0.,'end':transform['boundary']['trim_start']} if edge=='start'
                  else {'start':transform['boundary']['trim_end'],'end':transform['boundary']['duration']})
        if membership.get('excluded_interval') != interval:
            raise ValueError('original-edge membership interval differs from excluded material')
        indices=membership.get('old_expanded_indices')
        if (not isinstance(indices,list) or not indices or len(indices)!=len(set(indices))
                or any(type(i) is not int or not 0<=i<len(order) for i in indices)):
            raise ValueError('original-edge membership occurrence lineage invalid')
        expected_indices=(list(range(len(indices))) if edge=='start'
            else list(range(len(order)-len(indices),len(order))))
        if indices!=expected_indices:
            raise ValueError('original-edge membership must be an ordered expanded prefix or suffix')
        edge_indices[edge].update(indices)
        if edge_indices['start'] & edge_indices['end']:
            raise ValueError('original-edge membership overlaps opposite excluded edges')
        selected=[order[i] for i in indices];ids={row['line_id'] for row in selected}
        draft={'lines':[row for row in full['lines'] if row['id'] in ids],'performance_order':selected}
        expected=source._observation_draft(draft)
        seen=[]
        for phase in ('observation','confirmation'):
            observation=membership.get(phase,{})
            if observation.get('status')!='observed' or observation.get('issues') or len(observation.get('unit_results',[]))!=1:
                raise ValueError('original-edge membership requires two complete source observations')
            item=observation['unit_results'][0];unit=item['unit']
            if (any(unit.get(key)!=interval['start' if key.endswith('start') else 'end']
                    for key in ('clip_start','clip_end','core_start','core_end'))
                    or source._observation_draft(unit['expanded_draft'])!=expected
                    or set(unit['target_occurrence_ids'])!={row['display_occurrence_id'] for row in selected}):
                raise ValueError('original-edge membership unit differs from exact occurrence lineage')
            state=Path(item['route_state_path']);accepted=state.parent/'accepted-result.json'
            files=membership.get('evidence_files',{})
            if any(files.get(str(path))!=source.file_hash(path) for path in (state,accepted)):
                raise ValueError('original-edge membership routed evidence changed')
            cached=routes.read_unit_cache(state)
            if cached['state']['status']!='accepted' or cached['result']!=item['result']:
                raise ValueError('original-edge membership route no longer accepted')
            contracts,duration,witness=source._prepare_audio_observations(song_dir=original_song,units=[unit],
                audio=pipeline.preferred_listener_audio(original_song),source_identity=identity,deadline_at=time.time()+60.)
            _,bound_draft,_,request=contracts[0]
            dependency_input={'version':source.SOURCE_OBSERVATION_VERSION,'request':request,'witness':witness}
            if phase=='confirmation':
                by={row['id']:row for row in expected['lines']}
                dependency_input['confirmation_expected_order']=[list(source._source_key(by[row['line_id']]))
                    for row in expected['performance_order']]
            dependency=source.digest(dependency_input)
            fingerprint=source.digest({'unit':unit,'draft':bound_draft,'source_identity':identity,
                'duration':duration,'dependency':dependency})
            if (item['input_fingerprint']!=fingerprint or cached['state']['input_fingerprint']!=fingerprint
                    or cached['state']['dependency_fingerprint']!=dependency
                    or cached['state']['unit_id']!=Path(original_song).name+':source-observation:'+unit['id']):
                raise ValueError('original-edge membership request no longer binds its audio/unit/confirmation')
            if source._observation_errors(unit,item['result']):
                raise ValueError('original-edge membership observation contract changed')
            packet=item['result']['segment_audits'][0]['audit']['packet']
            by_id={row['id']:row for row in packet['lines']}
            actual=[source._source_key(by_id[row['line_id']]) for row in packet['performance_order']]
            expected_by={row['id']:row for row in expected['lines']}
            wanted=[source._source_key(expected_by[row['line_id']]) for row in expected['performance_order']]
            if actual!=wanted:
                raise ValueError('original-edge membership source differs from mapped occurrence')
            seen.append((str(state),item['input_fingerprint']))
        if seen[0]==seen[1]:
            raise ValueError('original-edge membership lacks independent confirmation')
        result.update(indices)
    return result


def require_removed_membership(transform, reader, delta, original_song):
    removed={row['old_index'] for row in delta['occurrence_lineage']
             if row['old_index'] is not None and row['new_index'] is None}
    if removed!=checked_original_memberships(transform,reader,original_song):
        raise ValueError('original-edge membership and removed occurrence lineage differ')


def review_boundary_memberships(declaration, original_song, staged_song, reader, delta,
                                *, options, route_dir, deadline_at):
    """Produce cached original-edge proofs for a proposed cropped-source delta.

    The delta scopes questions; it does not authorize deletion. Both original
    hearings must agree with its exact old prefix/suffix. The caller retains the
    returned proofs in a new transform before the cropped-source consumer can
    accept removal. This function never changes the transform or public files.
    """
    import bhakti_pipeline as pipeline
    import bhakti_library_source_pass as source

    transform = checked_audio_transform(declaration, original_song, staged_song, reader)
    archive = original_evidence_song(transform)
    full = source.source_draft(reader)
    order = full['performance_order']
    lineage = delta.get('occurrence_lineage')
    if delta.get('status') != 'proposed' or not isinstance(lineage, list):
        raise ValueError('boundary membership needs proposed complete occurrence lineage')
    old_indices = []
    removed = set()
    for row in lineage:
        if not isinstance(row, dict) or set(row) != {'old_index', 'new_index'}:
            raise ValueError('boundary membership has malformed occurrence lineage')
        old, new = row['old_index'], row['new_index']
        if new is not None and (type(new) is not int or new < 0):
            raise ValueError('boundary membership has invalid retained occurrence')
        if old is None:
            if new is None:
                raise ValueError('boundary membership lineage contains no occurrence')
            continue
        if type(old) is not int or not 0 <= old < len(order):
            raise ValueError('boundary membership has invalid original occurrence')
        old_indices.append(old)
        if new is None:
            removed.add(old)
    if sorted(old_indices) != list(range(len(order))):
        raise ValueError('boundary membership lacks complete unique original lineage')
    if not removed:
        return {'status': 'observed', 'memberships': [], 'issues': []}
    if len(removed) == len(order):
        raise ValueError('boundary removal cannot discard the entire performance')
    start = 0
    while start in removed:
        start += 1
    end = len(order)
    while end - 1 in removed:
        end -= 1
    edges = {'start': list(range(start)), 'end': list(range(end, len(order)))}
    if set(edges['start'] + edges['end']) != removed:
        raise ValueError('boundary removal contains interior occurrences, not exact edges')

    identity = source.collect_source_evidence(archive, reader, flags={'audio': True},
        coverage_requested=False)['identity']
    audio = pipeline.preferred_listener_audio(archive)
    plans = []
    for edge, indices in edges.items():
        if not indices:
            continue
        interval = ({'start': 0., 'end': transform['boundary']['trim_start']} if edge == 'start'
            else {'start': transform['boundary']['trim_end'], 'end': transform['boundary']['duration']})
        if not 0 < interval['end'] - interval['start'] <= 900:
            raise ValueError('boundary edge requires a nonempty bounded audio interval')
        selected = [order[i] for i in indices]
        ids = {row['line_id'] for row in selected}
        draft = {'lines': [row for row in full['lines'] if row['id'] in ids],
            'performance_order': selected}
        targets = sorted({row['display_occurrence_id'] for row in selected})
        displays = [int(value.split('-')[1]) for value in targets]
        unit = {'id': 'boundary-original-' + edge, 'kind': 'focused', 'segment_index': 0,
            'clip_start': interval['start'], 'clip_end': interval['end'],
            'core_start': interval['start'], 'core_end': interval['end'],
            'core_occurrence_indices': displays, 'context_occurrence_indices': displays,
            'target_occurrence_ids': targets, 'expanded_draft': draft}
        by_id = {row['id']: row for row in draft['lines']}
        expected = [list(source._source_key(by_id[row['line_id']])) for row in selected]
        plans.append((edge, indices, interval, unit, expected))

    memberships = []
    def held(issues):
        return {'status': 'unresolved', 'memberships': memberships, 'issues': issues}
    for edge, indices, interval, unit, expected in plans:
        arguments = dict(song_dir=archive, units=[unit], audio=audio, source_identity=identity,
            options=options, route_dir=route_dir, deadline_at=deadline_at)
        observation = source.review_audio_units(**arguments)
        if observation['status'] != 'observed':
            return held(observation['issues'])
        packet = observation['unit_results'][0]['result']['segment_audits'][0]['audit']['packet']
        by_id = {row['id']: row for row in packet['lines']}
        actual = [list(source._source_key(by_id[row['line_id']])) for row in packet['performance_order']]
        if actual != expected:
            return held([{'kind': 'original_edge_source_conflict', 'edge': edge,
                'detail': 'Original edge hearing differs from the proposed removed occurrences; reconcile source first.',
                'expected_order': expected, 'observed_order': actual,
                'route_state_path': observation['unit_results'][0]['route_state_path']}])
        confirmation = source.review_audio_units(**arguments, expected_orders={unit['id']: expected})
        if confirmation['status'] != 'observed':
            return held(confirmation['issues'])
        files = {}
        for item in observation['unit_results'] + confirmation['unit_results']:
            state = Path(item['route_state_path'])
            for path in (state, state.parent / 'accepted-result.json'):
                files[str(path)] = source.file_hash(path)
        memberships.append({'edge': edge, 'source_identity': identity,
            'boundary_digest': source.digest(transform['boundary'][edge]),
            'excluded_interval': interval, 'old_expanded_indices': indices,
            'observation': observation, 'confirmation': confirmation, 'evidence_files': files})
    checked = {**transform, 'original_edge_membership': memberships}
    require_removed_membership(checked, reader, delta, original_song)
    return {'status': 'observed', 'memberships': memberships, 'issues': []}


def staged_source_evidence(transform, original_song, staged_song, reader, flags, coverage_requested):
    """Project routing hints only; the staged native identity owns every request."""
    import bhakti_library_source_pass as source
    original_song = _check_original_archive(transform, original_song)
    evidence=source.collect_source_evidence(staged_song,reader,flags=flags,coverage_requested=coverage_requested)
    old=source.collect_source_evidence(original_song,reader,flags=flags,coverage_requested=coverage_requested)
    evidence['artifacts']=old['artifacts']
    matches=[row for row in transform['native'].values() if row['after']['sha256']==evidence['identity']['audio_sha256']]
    if len(matches)!=1:raise ValueError('boundary transform has ambiguous selected native witness')
    # No claim about browser/model origins: this approximate native content
    # displacement conservatively routes source questions, never retains starts.
    offset=matches[0]['measurement']['decoded_source_offset_seconds'];duration=evidence['duration_seconds']
    evidence['routing_intervals']=[{'start':max(0.,min(duration,row['start']-offset)),
        'end':max(0.,min(duration,row['end']-offset))} for row in old['routing_intervals']]
    evidence['routing_intervals_kind'] = 'boundary-projected'
    return evidence


def timing_transform_context(transform, prior_identity, *, audio_sha256, trim, duration_seconds):
    """Use an explicit native-clock premise; never infer model/browser origins."""
    before,after=transform['before'],transform['after'];basis=transform.get('timing_basis',{})
    if (transform.get('status')!='verified' or transform.get('kind')!='boundary-timebase'
            or after.get('audio_sha256')!=audio_sha256 or after.get('trim')!=trim
            or after.get('duration_seconds')!=duration_seconds):
        raise ValueError('boundary timing transform current identity differs')
    if (basis.get('status')!='verified' or basis.get('axis')!='native-presentation'
            or prior_identity.get('time_axis')!='native-presentation'
            or any(basis.get(key,{}).get('time_axis')!='native-presentation'
                or basis.get(key,{}).get('audio_sha256')!=transform[key]['audio_sha256']
                for key in ('before','after'))):
        raise ValueError('boundary timing clock origin is unqualified or differs')
    if prior_identity.get('audio_sha256')!=before.get('audio_sha256'):
        raise ValueError('boundary timing transform prior native identity differs')
    matches=[row for row in transform.get('native',{}).values()
        if row.get('before',{}).get('sha256')==before['audio_sha256']
        and row.get('after',{}).get('sha256')==after['audio_sha256']]
    if len(matches)!=1:raise ValueError('boundary timing selected native witness is ambiguous')
    witness=matches[0]['measurement']
    if (witness.get('status')!='verified' or witness.get('source_sha256')!=before['audio_sha256']
            or witness.get('output_sha256')!=audio_sha256 or len(witness.get('sample_windows',[]))<3
            or 'decoded_source_offset_seconds' not in witness):
        raise ValueError('boundary timing lacks decoded correspondence')
    offset=witness.get('timeline_source_offset_seconds');interval=witness.get('verified_output_interval',{})
    numbers=[offset,interval.get('start'),interval.get('end'),before.get('duration_seconds')]
    if any(type(v) not in (float,int) or not math.isfinite(v) for v in numbers):
        raise ValueError('boundary timing contains invalid timebase values')
    if not 0<=interval['start']<interval['end'] or before['duration_seconds']<=0:
        raise ValueError('boundary timing verified interval invalid')
    return {'audio_sha256':before['audio_sha256'],'trim':before['trim'],
        'duration_seconds':before['duration_seconds'],'offset':offset,'interval':interval}

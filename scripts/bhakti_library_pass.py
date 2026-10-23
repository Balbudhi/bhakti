#!/usr/bin/env python3
"""Inventory and selectively review the committed library in a private workspace.

Dry inventory never spends money or mutates readers. A missing historical review
field is an evidence gap, not a linguistic defect or authorization to rewrite.
"""
from __future__ import annotations

import argparse
import copy
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import time
from typing import Any

import bhakti_pipeline as pipeline
import editorial_baselines
import prepare_library_review as prepare
import retranslate_bhakti
import apply_translation_style_review as reader_writer

VERSION = 1
ROOT = Path(__file__).resolve().parents[1]
PRIORITY = ('patta-bola-vrksha-se', 'rehna-nahi-isa-desa')


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text()) if path.is_file() else None


def fingerprints(reader: dict, audio: list[dict], source: dict, trim: Any,
                 policy: dict, baseline: Any) -> dict[str, str]:
    lines = reader.get('SONG_LINES', {})
    lines = lines if isinstance(lines, dict) else {}
    valid = {key: row for key, row in lines.items() if isinstance(row, dict)}
    text = {key: {field: row.get(field) for field in ('source', 'roman', 'sourceWords')}
            for key, row in valid.items()}
    source_id = prepare.json_digest({'audio': audio, 'source': source, 'trim': trim})
    text_id = prepare.json_digest({'lines': text, 'order': reader.get('SONG_SEQUENCE')})
    timing_id = prepare.json_digest({'source': text_id, 'timings': reader.get('SONG_TIMINGS')})
    gloss_id = prepare.json_digest({'source': text_id, 'words': {
        key: {field: row.get(field) for field in ('words', 'grammarNote')} for key, row in valid.items()}})
    english_id = prepare.json_digest({key: row.get('english') for key, row in valid.items()})
    result = {'audio': source_id, 'text': text_id, 'timing': timing_id, 'gloss': gloss_id,
              'english': english_id, 'policy': prepare.json_digest(policy),
              'baseline': prepare.json_digest(baseline)}
    return {**result, 'all': prepare.json_digest(result)}


def segment_coverage(stages: dict) -> dict:
    audit = stages.get('02-transcript-audit.json') or {}
    segments = audit.get('segment_audits')
    if not segments:
        return {'status': 'not-applicable'}
    checker = getattr(pipeline, 'audit_segment_merge_coverage', None)
    if checker is None:
        return {'status': 'unverified', 'reason': 'segment coverage checker unavailable in this code snapshot'}
    return checker(segments, audit.get('packet', {}))


def inspect(root: Path, revision: str, song: dict, locks: dict, state_dir: Path,
            policy: dict, flags: dict) -> dict:
    row = prepare.inspect_song(root, revision, song, locks)
    slug = row['slug']; directory = root / 'songs' / slug
    private = directory / '.transcription'; errors: list[str] = []
    reader = prepare.load_javascript((directory / 'data.js').read_bytes()) if (directory / 'data.js').is_file() else {}
    source = prepare.read_object(private / 'source.json', errors)
    stages = {name: prepare.read_object(private / 'pipeline' / name, errors) for name in prepare.STAGES}
    trim = prepare.read_object(private / 'trim-applied.json', errors)
    audio = [{**item, 'sha256': file_hash(root / item['path'])} for item in row['localAudio']]
    identity = fingerprints(reader, audio, source, trim, policy, locks.get(slug))
    trim_artifact = prepare.artifact(root, private / 'trim-applied.json')
    identity.update(reader=prepare.json_digest(reader), stages=prepare.json_digest(row['artifacts']['pipeline']),
                    page=prepare.json_digest(row['artifacts']['page']), flags=prepare.json_digest(flags))
    identity['all'] = prepare.json_digest({key: value for key, value in identity.items() if key != 'all'})
    defects = list(row['mechanicalDefects']) + errors
    gaps = []
    if not audio: gaps.append('local native/fallback recording unavailable')
    if not any(source.get(key) for key in ('audio_sha256', 'source_sha256', 'recording_sha256')):
        gaps.append('historical audio identity has no explicit hash; current bytes hashed, past correctness unverified')
    for name, stage in stages.items():
        if not stage: gaps.append(f'missing saved {name}')
    if any(not isinstance(item, dict) or not item.get('semantic_frame')
           for item in stages.get('04-glosses.json', {}).get('packet', {}).get('glosses', [])):
        gaps.append('legacy gloss evidence lacks modern frames; review source/current gloss before any repair')
    coverage = segment_coverage(stages)
    planned = ['semantic-review']
    if coverage['status'] == 'mismatch':
        defects.append('saved segment occurrences are missing or changed in merged transcript')
        planned.insert(0, 'source-merge')
    elif coverage['status'] in ('uncertain', 'unverified'):
        gaps.append('long-segment occurrence coverage ' + coverage['status'])
        if coverage['status'] == 'uncertain': planned.insert(0, 'focused-audio-review')
    audit = stages.get('02-transcript-audit.json', {}).get('packet', {})
    if audit.get('uncertainties'):
        gaps.append('saved transcript contains unresolved audio uncertainties')
        planned.insert(0, 'audio-review')
    if flags.get('audio'):
        planned.insert(0, 'audio-review')
    timing = stages.get('03-timing.json') or {}
    if timing.get('validation_errors') or timing.get('uncertain_occurrence_ids'):
        planned.append('timing-review')
    if not stages.get('02-transcript-audit.json'):
        gaps.append('source completeness not certified; audio review needed when this song is selected')
        # A missing historical packet alone is not evidence of missing lyrics.
        # Keep low-cost source-first review first; do not request full ASR here.
    baseline = locks.get(slug)
    summary = stages.get('song-packet.json') or {}
    declarations = [obj[field] for obj in (reader.get('SONG_META', {}), source, summary, summary.get('job', {}))
                    if isinstance(obj, dict) for field in prepare.TRANSLATION_FIELDS if field in obj]
    protected = bool(baseline) or any(value not in (None, '', False, '(none supplied)') for value in declarations)
    if baseline:
        try: editorial_baselines.assert_english_preserved(slug, reader.get('SONG_LINES', {}), root=root)
        except RuntimeError as exc: defects.append(str(exc))
    receipt = read_json(state_dir / 'songs' / slug / 'acceptance.json')
    receipt_valid = bool(isinstance(receipt, dict) and receipt.get('version') == VERSION
                         and receipt.get('fingerprints') == identity
                         and receipt.get('status') == 'accepted'
                         and receipt.get('reviewEvidence') and not receipt.get('issues'))
    status = 'repair-needed' if defects else 'review-needed'
    if receipt_valid and not defects and not flags and coverage['status'] not in ('uncertain', 'mismatch', 'unverified'):
        status = 'untouched-valid'; planned = []
    if row['readerChangedSinceCatalogueRevision']:
        status = 'unresolved'; gaps.append('working reader differs from fixed catalogue revision; never overwrite it')
    if protected:
        status = 'protected'; planned = [stage for stage in planned if stage != 'semantic-review' and flags.get('audio')]
    priority = PRIORITY.index(slug) if slug in PRIORITY else 2
    return {'slug': slug, 'title': row['title'], 'catalogueEntry': copy.deepcopy(song), 'state': status, 'priority': priority,
            'workingReaderChanged': row['readerChangedSinceCatalogueRevision'],
            'committedReaderSha256': row['committedReaderSha256'],
            'readerSha256': row['artifacts']['reader'].get('sha256'),
            'counts': row['counts'], 'audio': audio, 'sourceReference': row['sourceReference'],
            'fingerprints': identity, 'stageEvidence': row['artifacts']['pipeline'],
            'sourceArtifact': row['artifacts']['source'], 'trimArtifact': trim_artifact,
            'baselineFileSha256': file_hash(root / 'data/editorial_baselines.json'),
            'segmentCoverage': coverage, 'defects': sorted(set(defects)),
            'evidenceGaps': sorted(set(gaps)), 'flags': flags, 'protectedEnglish': protected,
            'baselineEvidence': row['translationLock']['evidence'],
            'plannedStages': list(dict.fromkeys(planned)),
            'dispatchEligible': not row['readerChangedSinceCatalogueRevision'] and (not protected or (bool(baseline) and bool(flags.get('audio')))),
            'publicationEligible': False, 'reusedAcceptance': receipt_valid}


def build_inventory(root: Path = ROOT, *, catalogue_ref: str = 'HEAD', state_dir: Path,
                    flags: dict | None = None) -> dict:
    root = root.resolve(); state_dir = state_dir.resolve()
    revision = prepare.git(root, 'rev-parse', '--verify', f'{catalogue_ref}^{{commit}}').decode().strip()
    raw = prepare.committed_bytes(root, revision, 'data/songs.js')
    if raw is None: raise ValueError('committed catalogue missing')
    catalogue = prepare.load_javascript(raw).get('BHAKTI_SONGS')
    if not isinstance(catalogue, list) or not catalogue: raise ValueError('empty or invalid catalogue')
    slugs = [row.get('slug') if isinstance(row, dict) else None for row in catalogue]
    if any(not isinstance(slug, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug) for slug in slugs):
        raise ValueError('invalid catalogue slug')
    if len(slugs) != len(set(slugs)): raise ValueError('duplicate catalogue slug')
    locks = editorial_baselines.load_baselines(root)
    flags = flags or {}
    if set(flags) - set(slugs): raise ValueError('flags refer to unpublished song')
    policy = pipeline.translation_policy_payload()
    rows = [inspect(root, revision, song, locks, state_dir, policy, flags.get(song['slug'], {})) for song in catalogue]
    rows.sort(key=lambda row: (row['priority'], row['slug']))
    return {'version': VERSION, 'catalogueRevision': revision, 'catalogueSha256': prepare.digest(raw),
            'counts': {'songs': len(rows), 'uniqueLines': sum(row['counts']['uniqueLines'] for row in rows),
                       'states': dict(sorted(Counter(row['state'] for row in rows).items()))}, 'songs': rows}


def assert_targeted_change(before: dict, after: dict, *, confirmed_changes: dict) -> None:
    """Mechanical mutation guard only; caller must separately prove confirmation."""
    if not confirmed_changes and before != after: raise ValueError('no independently confirmed changes')
    for key in set(before) | set(after):
        if key != 'SONG_LINES' and before.get(key) != after.get(key): raise ValueError(f'unapproved {key} change')
    old = before.get('SONG_LINES', {}); new = after.get('SONG_LINES', {})
    if set(old) != set(new): raise ValueError('unapproved line population change')
    for line_id in old:
        allowed = set(confirmed_changes.get(line_id, []))
        for field in set(old[line_id]) | set(new[line_id]):
            if old[line_id].get(field) != new[line_id].get(field) and field not in allowed:
                raise ValueError(f'unapproved {line_id}.{field} change')


def reader_evidence(reader: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Use current reviewed surfaces, not an old generated English draft."""
    lines = retranslate_bhakti.source_lines(reader)
    glosses = []; translations = []
    slot = re.compile(r'\{([\d,\s]+):([^{}]*)\}')
    for line in lines:
        current = reader['SONG_LINES'][line['id']]
        for key in ('sourceWords', 'sourceLanguage'):
            if key in current: line[key] = copy.deepcopy(current[key])
        glosses.append({'id': line['id'], 'word_glosses': copy.deepcopy(current['words']),
                       'grammar_note': current.get('grammarNote', '')})
        english = current['english']; segments = []; position = 0
        for match in slot.finditer(english):
            if match.start() > position:
                segments.append({'text': english[position:match.start()], 'word_indices': []})
            segments.append({'text': match.group(2), 'word_indices': [int(value.strip()) for value in match.group(1).split(',')]})
            position = match.end()
        if position < len(english): segments.append({'text': english[position:], 'word_indices': []})
        translations.append({'id': line['id'], 'literal_english': editorial_baselines.plain_english(english),
                             'segments': segments})
    return lines, glosses, translations


def route_options(options, context):
    local = copy.copy(options)
    local.model = context.model; local.timeout = min(float(options.timeout), context.call_timeout_seconds)
    local.force = False
    local.unit_context = context.transport_context
    local.unit_deadline_at = context.deadline_at
    local.semantic_deadline_at = context.deadline_at
    return local


def current_review_errors(artifact: dict, lines: list[dict], glosses: list[dict],
                          expected_reader_digest: str, dependency_fingerprint: str) -> list[dict]:
    errors = []
    if (artifact.get('reader_digest') != expected_reader_digest
            or artifact.get('dependency_fingerprint') != dependency_fingerprint
            or not artifact.get('attempt_id')):
        errors.append('current review input identity mismatch')
    reviews = artifact.get('reviews')
    if not isinstance(reviews, list): reviews = []; errors.append('review list missing')
    if [row.get('id') for row in reviews] != [line['id'] for line in lines]:
        errors.append('current review IDs incomplete or reordered')
    issues = []
    for row in reviews:
        if not isinstance(row.get('unsupported_additions'), list):
            errors.append('unsupported additions must be an explicit array')
        if not isinstance(row.get('material_choice'), str):
            errors.append('material choice must be an explicit string')
        elif row['material_choice']:
            errors.append('material poetic choice remains unresolved')
        recorded = row.get('issues')
        if not isinstance(recorded, list): errors.append('typed review issues missing'); continue
        issues.extend(recorded)
        failed = (any(row.get(key) is not True for key in
                      ('passes', 'agency_preserved', 'imagery_preserved', 'all_meaning_accounted_for'))
                  or row.get('human_review_recommended') is not False or bool(row.get('unsupported_additions')))
        if failed and not recorded: errors.append('failed source-first review has no typed evidenced issue')
        if not failed and recorded: errors.append('passing review contradicts its recorded defects')
    errors += pipeline.semantic_repair_issue_errors(lines, glosses, issues)
    if issues != artifact.get('issues'): errors.append('review issues differ from preserved issue list')
    return [{'kind': 'invalid_review', 'detail': error} for error in errors]


def audit_current_reader(reader: dict, *, slug: str, workspace: Path, route_dir: Path,
                         options, dependency_fingerprint: str, deadline_at: float,
                         protected_english: dict | None = None) -> dict:
    """Audit source/current gloss/current English; finding a defect is useful output.

    The router escalates an invalid audit, not a valid report of an existing
    defect. Repair attempts and their independent post-reviews use separate units.
    """
    import bhakti_model_routes as routes
    lines, glosses, translations = reader_evidence(reader)
    reader_digest = prepare.json_digest(reader)
    policy = pipeline.translation_policy_payload()
    request_identity = prepare.json_digest({'version': VERSION, 'reader': reader,
        'policy': policy, 'baseline': protected_english, 'purpose': 'identify-current-defects'})

    def execute(context):
        local = route_options(options, context)
        local.semantic_full_source = lines
        local.semantic_performance_order = copy.deepcopy(reader['SONG_SEQUENCE'])
        local.semantic_source_identity = dependency_fingerprint
        provided = json.dumps(protected_english, ensure_ascii=False) if protected_english else '(none supplied)'
        reviews, packets = pipeline.independently_review_translations(
            context.attempt_dir / slug, lines, glosses, translations, provided, local,
            languages=reader.get('SONG_META', {}).get('languages'))
        issues = [issue for row in reviews if isinstance(row.get('issues'), list) for issue in row['issues']]
        return {'reviewPurpose': 'identify-current-defects', 'reader_digest': reader_digest,
                'dependency_fingerprint': dependency_fingerprint, 'attempt_id': context.attempt_id,
                'reviews': reviews, 'issues': issues, 'reviewPackets': packets,
                'source_lines': lines, 'gloss_rows': glosses}

    return routes.run_unit(route_dir, slug + ':current-source-review', request_identity,
        execute, lambda value: current_review_errors(value, lines, glosses, reader_digest, dependency_fingerprint),
        deadline_at=deadline_at, dependency_fingerprint=dependency_fingerprint,
        base_model=options.model, pro_model=options.pro_model)


def repair_current_reader(reader: dict, *, slug: str, pre_review: dict, workspace: Path,
                          route_dir: Path, options, dependency_fingerprint: str,
                          deadline_at: float, protected_english: dict | None = None) -> dict:
    """Repair only independently identified targets, then apply the paired gate."""
    import bhakti_model_routes as routes
    import bhakti_candidate_guard as guard
    lines, original_glosses, original_translations = reader_evidence(reader)
    errors = current_review_errors(pre_review, lines, original_glosses,
                                   prepare.json_digest(reader), dependency_fingerprint)
    if errors: raise ValueError('unbound or invalid pre-review: ' + str(errors))
    issues = pre_review['issues']
    if any(issue['kind'] == 'unresolved_evidence' for issue in issues):
        raise ValueError('unresolved source evidence cannot authorize semantic repair')
    targets = {target for issue in issues for target in issue['target_line_ids']}
    if not targets:
        receipt = guard.authorize_semantic_candidate(reader, reader, source_lines=lines,
            gloss_rows=original_glosses, pre_review=pre_review, post_review=None,
            dependency_fingerprint=dependency_fingerprint, protected_english=protected_english)
        return {'reader': copy.deepcopy(reader), 'authorization': receipt, 'post_review': None}
    target_lines = [line for line in lines if line['id'] in targets]
    lexical_indices: dict[str, set[int]] = {}
    for issue in issues:
        if issue['kind'] not in ('gloss_sense', 'frame_relation'): continue
        for ref in issue['references']:
            if ref['line_id'] in issue['target_line_ids']:
                lexical_indices.setdefault(ref['line_id'], set()).update(ref['word_indices'])
    request_identity = prepare.json_digest({'version': VERSION, 'reader': reader, 'pre_review': pre_review,
        'policy': pipeline.translation_policy_payload(), 'baseline': protected_english})
    languages = reader.get('SONG_META', {}).get('languages', [])

    def execute(context):
        local = route_options(options, context)
        local.semantic_full_source = lines
        local.semantic_performance_order = copy.deepcopy(reader['SONG_SEQUENCE'])
        local.semantic_source_identity = dependency_fingerprint
        local.semantic_confirmed_issues = issues
        local.semantic_repair_feedback = issues
        local.semantic_original_reader = {key: copy.deepcopy(reader['SONG_LINES'][key]) for key in targets}
        local.semantic_baseline = ({key: protected_english[key] for key in targets}
                                   if protected_english is not None else None)
        audited = {'packet': {'verified_lines': target_lines, 'metadata': {'languages': languages},
                              'performance_order': copy.deepcopy(reader['SONG_SEQUENCE'])}}
        attempt_song = context.attempt_dir / slug
        glosses = pipeline.gloss(attempt_song, audited, local)
        # Reconstruction supplies missing modern frames only for confirmed
        # failed targets. It cannot authorize changing other displayed glosses.
        for row in glosses['packet']['glosses']:
            original_line = reader['SONG_LINES'][row['id']]
            old_words = original_line['words']
            for index, word in enumerate(row['word_glosses']):
                actual_word = copy.deepcopy(old_words[index])
                if index in lexical_indices.get(row['id'], set()): actual_word['gloss'] = word['gloss']
                row['word_glosses'][index] = actual_word
            row['grammar_note'] = original_line.get('grammarNote', '')
        job = {'slug': slug, 'languages': languages}
        if protected_english is not None:
            baseline_path = context.attempt_dir / 'locked-target-english.json'
            pipeline.semantic_write_json(baseline_path, local.semantic_baseline)
            job['providedTranslation'] = str(baseline_path)
        translations = pipeline.translate(attempt_song, audited, glosses, job, local, candidate_only=True)
        candidate = copy.deepcopy(reader)
        for row in glosses['packet']['glosses']:
            for index in lexical_indices.get(row['id'], set()):
                candidate['SONG_LINES'][row['id']]['words'][index]['gloss'] = row['word_glosses'][index]['gloss']
        for row in translations['packet']['translations']:
            candidate['SONG_LINES'][row['id']]['english'] = pipeline.segment_english(row['segments'], row['literal_english'])
        post = {'reader_digest': prepare.json_digest(candidate), 'dependency_fingerprint': dependency_fingerprint,
                'attempt_id': context.attempt_id,
                'reviews': [row['independent_review'] for row in translations['packet']['translations']]}
        return {'reader': candidate, 'post_review': post, 'glosses': glosses,
                'translations': translations, 'source_lines': target_lines}

    def validate(artifact):
        errors = pipeline.fresh_translation_contract_errors(target_lines,
            artifact['glosses']['packet']['glosses'], artifact['translations']['packet']['translations'])
        try:
            guard.authorize_semantic_candidate(reader, artifact['reader'],
                source_lines=lines, gloss_rows=original_glosses, pre_review=pre_review,
                post_review=artifact['post_review'], dependency_fingerprint=dependency_fingerprint,
                protected_english=protected_english)
        except ValueError as exc:
            # The pure gate reports exact rejected mutations; no blanket flag
            # clearing or selection of a less-bad candidate is permitted.
            kind = 'locked_baseline_conflict' if protected_english is not None else 'semantic_candidate_rejected'
            return [{'kind': kind, 'detail': str(exc)}]
        return [{'kind': 'semantic_contract', 'detail': error} for error in errors]

    accepted = routes.run_unit(route_dir, slug + ':targeted-semantics', request_identity, execute, validate,
        deadline_at=deadline_at, dependency_fingerprint=dependency_fingerprint,
        base_model=options.model, pro_model=options.pro_model)
    receipt = guard.authorize_semantic_candidate(reader, accepted['reader'], source_lines=lines,
        gloss_rows=original_glosses, pre_review=pre_review, post_review=accepted['post_review'],
        dependency_fingerprint=dependency_fingerprint, protected_english=protected_english)
    return {**accepted, 'authorization': receipt}


def guard_original_inputs(root: Path, row: dict) -> None:
    data = root / 'songs' / row['slug'] / 'data.js'
    if not data.is_file() or file_hash(data) != row['readerSha256']:
        raise ValueError(f"{row['slug']}: original reader changed during review")
    for audio in row['audio']:
        path = root / audio['path']
        if not path.is_file() or file_hash(path) != audio['sha256']:
            raise ValueError(f"{row['slug']}: original recording changed during review")
    artifacts = [row['sourceArtifact'], row['trimArtifact'], *row['stageEvidence'].values()]
    for artifact in artifacts:
        path = root / artifact['path']
        if path.is_file() != artifact['exists'] or (path.is_file() and file_hash(path) != artifact.get('sha256')):
            raise ValueError(f"{row['slug']}: source/stage evidence changed during review")
    if file_hash(root / 'data/editorial_baselines.json') != row['baselineFileSha256']:
        raise ValueError(f"{row['slug']}: owner baseline evidence changed during review")


def prepare_workspace(root: Path, row: dict, state_dir: Path) -> Path:
    folder = state_dir / 'songs' / row['slug']; workspace = folder / 'workspace'
    marker = folder / 'frozen-input.json'
    expected = {'fingerprints': row['fingerprints'], 'readerSha256': row['readerSha256'],
                'baselineFileSha256': file_hash(root / 'data/editorial_baselines.json')}
    if marker.exists():
        if read_json(marker) != expected: raise ValueError('workspace original input identity changed')
        return workspace
    original = root / 'songs' / row['slug']; target = workspace / 'songs' / row['slug']
    target.mkdir(parents=True, exist_ok=True); (workspace / 'data').mkdir(exist_ok=True)
    for name in ('data.js', 'index.html'):
        if (original / name).is_file(): shutil.copy2(original / name, target / name)
    private = original / '.transcription'
    if private.is_dir(): shutil.copytree(private, target / '.transcription', dirs_exist_ok=True)
    for audio in row['audio']:
        destination = target / Path(audio['path']).name
        if not destination.exists(): destination.symlink_to(root / audio['path'])
    shutil.copy2(root / 'data/editorial_baselines.json', workspace / 'data/editorial_baselines.json')
    shutil.copy2(original / 'data.js', folder / 'original-data.js')
    pipeline.semantic_write_json(marker, expected)
    return workspace


def ledger_summary(path: Path) -> dict:
    value = read_json(path) or {'requests': [], 'blocked': False}
    rows = value.get('requests', [])
    charged = sum(row.get('reported_cost_usd', row.get('reservation_usd', 0)) for row in rows)
    return {'calls': len(rows), 'accounted_usd': charged, 'blocked': bool(value.get('blocked'))}


def execute_song(root: Path, row: dict, state_dir: Path, options, deadline_at: float) -> dict:
    import bhakti_model_routes as routes
    slug = row['slug']; guard_original_inputs(root, row)
    before = prepare.load_javascript((root / 'songs' / slug / 'data.js').read_bytes())
    locks = editorial_baselines.load_baselines(root)
    protected = locks.get(slug, {}).get('plainEnglishByLine')
    if protected:
        editorial_baselines.assert_english_preserved(slug, before['SONG_LINES'], root=root)
    if not row['dispatchEligible']:
        return {'status': 'protected' if row['protectedEnglish'] else 'unresolved', 'publicationEligible': False,
                'issues': row['defects'] + row['evidenceGaps']}
    workspace = prepare_workspace(root, row, state_dir)
    route_dir = state_dir / 'routes'; source_result = None
    source_stages = {'source-merge', 'audio-review', 'focused-audio-review', 'timing-review'}
    if source_stages.intersection(row['plannedStages']):
        from bhakti_library_source_pass import run_source_candidate
        checkpoint_path = state_dir / 'songs' / slug / 'source-checkpoint.json'
        checkpoint = read_json(checkpoint_path)
        if checkpoint:
            if (checkpoint.get('input') != row['fingerprints']['all']
                    or checkpoint.get('sha256') != prepare.json_digest(checkpoint.get('result'))):
                raise routes.RunFatal('source checkpoint input or content identity changed')
            source_result = checkpoint['result']
        else:
            source_options = copy.copy(options); source_options.timing_deadline_at = deadline_at
            source_options.source_requested_stages = row['plannedStages']
            source_options.source_confirmed_issues = row['defects'] + row['evidenceGaps']
            source_result = run_source_candidate(root=root, slug=slug, reader=before, workspace=workspace,
                route_dir=route_dir, options=source_options, deadline_at=deadline_at)
            if source_result.get('status') == 'accepted':
                pipeline.semantic_write_json(checkpoint_path, {'input': row['fingerprints']['all'],
                    'sha256': prepare.json_digest(source_result), 'result': source_result})
        if source_result.get('status') != 'accepted':
            return {'status': 'unresolved', 'publicationEligible': False, 'source': source_result}
        before = source_result['reader']
    if protected:
        guard_original_inputs(root, row)
        return {'status': 'protected', 'publicationEligible': False, 'source': source_result,
                'issues': ['owner English remains protected; report source/mapping findings only']}
    dependency = prepare.json_digest({'inputs': row['fingerprints'],
        'source_candidate': prepare.json_digest(before) if source_result else None})
    pre = audit_current_reader(before, slug=slug, workspace=workspace, route_dir=route_dir,
        options=options, dependency_fingerprint=dependency, deadline_at=deadline_at)
    repaired = repair_current_reader(before, slug=slug, pre_review=pre, workspace=workspace,
        route_dir=route_dir, options=options, dependency_fingerprint=dependency, deadline_at=deadline_at)
    guard_original_inputs(root, row)
    candidate = repaired['reader']; changed = bool(repaired['authorization']['confirmed_changes'])
    if changed:
        reader_writer.write_reader(slug, candidate, root=workspace)
        page = workspace / 'songs' / slug / 'index.html'
        text = page.read_text()
        version = file_hash(workspace / 'songs' / slug / 'data.js')[:12]
        text, count = re.subn(r'(?<=src=")data\.js(?:\?v=[^"\s]+)?(?=")', 'data.js?v=' + version, text)
        if count != 1: raise ValueError('candidate page needs exactly one existing data script reference')
        page.write_text(text)
    problems = prepare.contract.audit_song(workspace / 'songs' / slug, row['catalogueEntry'])['problems']
    if problems:
        return {'status': 'unresolved', 'publicationEligible': False, 'issues': problems,
                'authorization': repaired['authorization'], 'source': source_result}
    guard_original_inputs(root, row)
    result = {'status': 'accepted', 'publicationEligible': changed or bool(source_result),
        'changed': changed or bool(source_result and source_result.get('source_changed')),
        'candidateRoot': str(workspace), 'candidateReaderSha256': file_hash(workspace / 'songs' / slug / 'data.js'),
        'candidatePageSha256': file_hash(workspace / 'songs' / slug / 'index.html'),
        'authorization': repaired['authorization'], 'source': source_result,
        'evidenceGaps': row['evidenceGaps'], 'audioClaim': 'No new audio clearance except recorded source-stage evidence.'}
    pipeline.semantic_write_json(state_dir / 'songs' / slug / 'result.json', result)
    return result


def reconcile_editorial_continuations(state_dir: Path, run: dict, rows: list[dict], options,
                                     run_path: Path) -> dict[str, dict]:
    """Record explicit source continuation without changing spent route history.

    This preflight binds files and the original run only. The source adapter
    must independently validate the editorial choice against its actual source
    and policy before consuming the retained candidate.
    """
    decisions = getattr(options, 'editorial_adjudications', {})
    if not isinstance(decisions, dict):
        raise ValueError('editorial adjudications must map exact source units to decision files')
    selected = {row['slug']: row for row in rows}
    pending = {}
    for unit, filename in decisions.items():
        if not isinstance(unit, str) or not unit.endswith(':new-source-semantics'):
            raise ValueError('editorial continuation only supports exact new-source-semantics units')
        slug = unit.removesuffix(':new-source-semantics')
        row = selected.get(slug)
        if (not row or not row['dispatchEligible']
                or not {'source-merge', 'audio-review', 'focused-audio-review', 'timing-review'}
                       .intersection(row['plannedStages'])):
            raise ValueError('editorial continuation requires a selected dispatch-eligible source stage')
        record_path = Path(filename).resolve()
        record = read_json(record_path)
        if (not isinstance(record, dict) or record.get('unit_id') != unit
                or record.get('decision_kind') != 'retain_existing_primary'):
            raise ValueError('editorial decision does not name this exact source unit')
        route_path = Path(record.get('route_state_path', '')).resolve()
        candidate_path = Path(record.get('candidate_path', '')).resolve()
        if (not route_path.is_relative_to((state_dir / 'routes').resolve())
                or route_path.name != 'route-state.json'
                or candidate_path not in [route_path.parent / attempt / 'candidate.json'
                                          for attempt in ('flash', 'pro')]):
            raise ValueError('editorial source decision escaped the original run route or attempt')
        for path, field in ((route_path, 'route_state_sha256'),
                            (candidate_path, 'candidate_file_sha256')):
            if not path.is_file() or file_hash(path) != record.get(field):
                raise ValueError('editorial decision original route or candidate changed')
        route = read_json(route_path)
        if (not isinstance(route, dict) or route.get('unit_id') != unit
                or route.get('status') != 'unresolved'):
            raise ValueError('editorial continuation requires the exact unresolved source route')
        binding = {'baseIdentityDigest': prepare.json_digest(run['identity']),
                   'deadline_at': run['deadline_at'],
                   'unit': unit, 'decisionPath': str(record_path), 'decisionSha256': file_hash(record_path),
                   'routeStateSha256': record['route_state_sha256'],
                   'candidateSha256': record['candidate_file_sha256'],
                   'reviewedLedgerSha256': record.get('run_ledger_sha256')}
        journal = run.get('reconciliations', [])
        if not isinstance(journal, list): raise ValueError('invalid reconciliation journal')
        existing = [event for event in journal if event.get('phase') == 'authorized'
                    and event.get('continuationIdentity', {}).get('unit') == unit]
        if len(existing) > 1: raise ValueError('duplicate editorial continuation authorization')
        ledger_path = state_dir / 'api-ledger.json'
        ledger = read_json(ledger_path)
        if (not isinstance(ledger, dict) or not isinstance(ledger.get('requests'), list)
                or not all(isinstance(item, dict) for item in ledger['requests'])
                or type(ledger.get('blocked')) is not bool
                or ledger.get('budget_usd') != run['identity']['budget_usd']
                or ledger.get('max_calls') != run['identity']['max_calls']):
            raise ValueError('editorial continuation requires the original bounded spending ledger')
        saved_spending = run.get('ledger')
        current_spending = ledger_summary(ledger_path)
        if (not isinstance(saved_spending, dict)
                or current_spending['calls'] < saved_spending.get('calls', 0)
                or current_spending['accounted_usd'] < saved_spending.get('accounted_usd', 0)
                or (saved_spending.get('blocked') and not current_spending['blocked'])):
            raise ValueError('editorial continuation ledger rolled back acknowledged spending')
        latest = run.get('ledgerCheckpoint')
        if latest is not None:
            acknowledged = latest.get('ledger') if isinstance(latest, dict) else None
            if (not isinstance(acknowledged, dict)
                    or prepare.json_digest(acknowledged) != latest.get('digest')
                    or not isinstance(acknowledged.get('requests'), list)
                    or ledger['requests'][:len(acknowledged['requests'])] != acknowledged['requests']
                    or {k: v for k, v in ledger.items() if k not in ('requests', 'blocked')}
                       != {k: v for k, v in acknowledged.items() if k not in ('requests', 'blocked')}
                    or (acknowledged.get('blocked') and not ledger['blocked'])):
                raise ValueError('editorial continuation latest acknowledged ledger changed')
        if existing:
            event = existing[0]
            ledger_archive = state_dir / 'reconciliations' / event['id'] / 'original-api-ledger.json'
            if (not ledger_archive.is_file()
                    or file_hash(ledger_archive) != record.get('run_ledger_sha256')):
                raise ValueError('editorial continuation original ledger archive changed')
            original_ledger = read_json(ledger_archive)
            if (not isinstance(original_ledger, dict)
                    or prepare.json_digest(original_ledger) != event.get('originalLedgerDigest')
                    or ledger['requests'][:len(original_ledger.get('requests', []))] != original_ledger.get('requests')
                    or {k: v for k, v in ledger.items() if k not in ('requests', 'blocked')}
                       != {k: v for k, v in original_ledger.items() if k not in ('requests', 'blocked')}
                    or (original_ledger.get('blocked') and not ledger['blocked'])):
                raise ValueError('editorial continuation spending ledger prefix changed')
            expected = {**binding, 'previousResultDigest': prepare.json_digest(event.get('previousResult'))}
            if event.get('continuationIdentity') != expected:
                raise ValueError('editorial continuation decision or frozen identity changed')
            archive = Path(event.get('originalRunPath', '')).resolve()
            expected_archive = state_dir.resolve() / 'reconciliations' / event['id'] / 'original-run.json'
            if (archive != expected_archive or not archive.is_file()
                    or file_hash(archive) != event.get('originalRunSha256')):
                raise ValueError('editorial continuation original run archive changed')
            completed = [item for item in journal if item.get('phase') == 'completed'
                         and item.get('id') == event['id']]
            if len(completed) > 1: raise ValueError('duplicate editorial continuation completion')
            if completed:
                if run['songs'].get(slug) != completed[0].get('result'):
                    raise ValueError('completed editorial continuation result changed')
                continue
            if run['songs'].get(slug) != event.get('previousResult'):
                raise ValueError('pending editorial continuation original result changed')
        else:
            if (file_hash(ledger_path) != record.get('run_ledger_sha256')
                    or ledger_summary(ledger_path) != run.get('ledger')):
                raise ValueError('editorial continuation spending ledger differs from reviewed decision or saved run')
            checkpoint = read_json(state_dir / 'songs' / slug / 'source-checkpoint.json')
            if checkpoint and checkpoint.get('result', {}).get('status') == 'accepted':
                raise ValueError('editorial continuation cannot reopen a completed source stage')
            previous = run['songs'].get(slug)
            if not isinstance(previous, dict) or previous.get('status') != 'unresolved':
                raise ValueError('editorial continuation can only reopen an unresolved song')
            source_failure = previous.get('source')
            if not ((isinstance(source_failure, dict) and source_failure.get('status') == 'unresolved')
                    or previous.get('errorType') == 'UnitUnresolved'):
                raise ValueError('unresolved result is not a recorded source-stage failure')
            identity = {**binding, 'previousResultDigest': prepare.json_digest(previous)}
            identifier = prepare.json_digest(identity)
            archive = state_dir / 'reconciliations' / identifier / 'original-run.json'
            original = run_path.read_bytes()
            if archive.exists():
                if archive.read_bytes() != original:
                    raise ValueError('existing original run archive disagrees with pending authorization')
            else:
                archive.parent.mkdir(parents=True, exist_ok=True)
                # Preserve exact bytes, not a reserialization of historical results.
                with archive.open('xb') as stream: stream.write(original)
            ledger_archive = archive.parent / 'original-api-ledger.json'
            if ledger_archive.exists():
                if file_hash(ledger_archive) != record['run_ledger_sha256']:
                    raise ValueError('existing original ledger archive changed')
            else:
                with ledger_archive.open('xb') as stream: stream.write(ledger_path.read_bytes())
            event = {'phase': 'authorized', 'id': identifier, 'slug': slug,
                     'continuationIdentity': identity, 'previousResult': copy.deepcopy(previous),
                     'originalRunPath': str(archive.resolve()), 'originalRunSha256': file_hash(archive),
                     'originalLedger': copy.deepcopy(ledger), 'originalLedgerDigest': prepare.json_digest(ledger)}
            run.setdefault('reconciliations', []).append(event)
            pipeline.semantic_write_json(run_path, run)
        pending[slug] = event
    return pending


def execute_inventory(root: Path, inventory: dict, state_dir: Path, options) -> dict:
    import bhakti_model_routes as routes
    if (not math.isfinite(options.budget_usd or 0) or options.budget_usd <= 0
            or type(options.max_calls) is not int or options.max_calls <= 0
            or not math.isfinite(options.deadline_seconds) or options.deadline_seconds <= 0):
        raise ValueError('execution requires positive bounded dollars, calls and deadline')
    selected = set(options.slugs) if options.slugs else {row['slug'] for row in inventory['songs']}
    if selected - {row['slug'] for row in inventory['songs']}: raise ValueError('selection contains unpublished song')
    rows = [row for row in inventory['songs'] if row['slug'] in selected]
    reuse_maps = getattr(options, 'source_reuse_maps', {})
    if not isinstance(reuse_maps, dict) or set(reuse_maps) - {row['slug'] for row in inventory['songs']}:
        raise ValueError('source reuse maps must name published songs')
    reuse_identity = {slug: {'path': str(Path(path).resolve()), 'sha256': file_hash(Path(path))}
                      for slug, path in reuse_maps.items()}
    identity = {'catalogueRevision': inventory['catalogueRevision'], 'budget_usd': options.budget_usd,
        'max_calls': options.max_calls, 'model': options.model, 'pro_model': options.pro_model,
        'source_reuse_maps': reuse_identity,
        'inputs': {row['slug']: row['fingerprints']['all'] for row in rows}}
    run_path = state_dir / 'run.json'; run = read_json(run_path)
    if run:
        if run.get('identity') != identity: raise ValueError('frozen run inputs or limits changed; existing evidence retained')
    else:
        if getattr(options, 'editorial_adjudications', {}):
            raise ValueError('editorial continuation requires an existing bounded run')
        run = {'version': VERSION, 'identity': identity, 'deadline_at': time.time() + options.deadline_seconds,
               'songs': {}, 'remaining': [row['slug'] for row in rows], 'status': 'running'}
        pipeline.semantic_write_json(state_dir / 'frozen-inventory.json', inventory)
        pipeline.semantic_write_json(run_path, run)
    continuations = reconcile_editorial_continuations(state_dir, run, rows, options, run_path)
    ledger = state_dir / 'api-ledger.json'
    env = {'BHAKTI_API_RUN_LEDGER': str(ledger), 'BHAKTI_API_RUN_BUDGET_USD': str(options.budget_usd),
           'BHAKTI_API_RUN_MAX_CALLS': str(options.max_calls), 'BHAKTI_GEMINI_PROVIDER': 'openrouter'}
    old_env = {key: os.environ.get(key) for key in env}
    # A CLI process owns its bounded run. Do not replace another active ledger.
    if old_env['BHAKTI_API_RUN_LEDGER'] and Path(old_env['BHAKTI_API_RUN_LEDGER']).resolve() != ledger.resolve():
        raise ValueError('another bounded API ledger is configured; do not overlap runs')
    os.environ.update(env)
    try:
        for row in rows:
            slug = row['slug']
            if slug in run['songs'] and slug not in continuations:
                accepted = run['songs'][slug]
                if accepted.get('status') == 'accepted':
                    candidate_root = Path(accepted['candidateRoot']).resolve()
                    if not candidate_root.is_relative_to(state_dir.resolve()):
                        raise ValueError('accepted candidate path escaped private run')
                    for name, field in [('data.js', 'candidateReaderSha256'), ('index.html', 'candidatePageSha256')]:
                        path = candidate_root / 'songs' / slug / name
                        if not path.is_file() or file_hash(path) != accepted.get(field):
                            raise ValueError('accepted candidate changed; do not reuse publication evidence')
                continue
            summary = ledger_summary(ledger)
            if (summary['blocked'] or summary['calls'] >= options.max_calls
                    or summary['accounted_usd'] >= options.budget_usd or time.time() >= run['deadline_at']):
                run['status'] = 'bounded-stop'; break
            try:
                for item in reuse_identity.values():
                    if file_hash(Path(item['path'])) != item['sha256']:
                        raise routes.RunFatal('reviewed source reuse map changed during run')
                run['songs'][slug] = execute_song(root, row, state_dir, options, run['deadline_at'])
            except routes.RunFatal as exc:
                run['status'] = 'bounded-stop'; run['stopReason'] = str(exc); break
            except (routes.UnitUnresolved, ValueError, RuntimeError, ImportError) as exc:
                run['songs'][slug] = {'status': 'unresolved', 'publicationEligible': False,
                                      'issues': [str(exc)], 'errorType': type(exc).__name__}
            if slug in continuations:
                run['reconciliations'].append({'phase': 'completed', 'id': continuations[slug]['id'],
                    'slug': slug, 'result': copy.deepcopy(run['songs'][slug])})
                del continuations[slug]
            run['remaining'] = [item['slug'] for item in rows
                                if item['slug'] not in run['songs'] or item['slug'] in continuations]
            pipeline.semantic_write_json(run_path, run)
        run['remaining'] = [row['slug'] for row in rows
                            if row['slug'] not in run['songs'] or row['slug'] in continuations]
        if not run['remaining']:
            run['status'] = 'unresolved' if any(row['status'] == 'unresolved' for row in run['songs'].values()) else 'complete'
        acknowledged_ledger = read_json(ledger)
        if run.get('reconciliations') and not isinstance(acknowledged_ledger, dict):
            raise ValueError('editorial continuation spending ledger disappeared during execution')
        run['ledger'] = ledger_summary(ledger)
        if isinstance(acknowledged_ledger, dict):
            run['ledgerCheckpoint'] = {'ledger': acknowledged_ledger,
                                       'digest': prepare.json_digest(acknowledged_ledger)}
        pipeline.semantic_write_json(run_path, run)
        return run
    finally:
        for key, value in old_env.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--catalogue-ref', default='HEAD')
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--flags', type=Path)
    parser.add_argument('--source-reuse-maps', type=Path, dest='source_reuse_maps_file')
    parser.add_argument('--editorial-adjudications', type=Path, dest='editorial_adjudications_file')
    parser.add_argument('--execute', action='store_true')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--all', action='store_true')
    selection.add_argument('--slugs', nargs='+')
    parser.add_argument('--budget-usd', type=float)
    parser.add_argument('--max-calls', type=int)
    parser.add_argument('--deadline-seconds', type=float, default=3600)
    parser.add_argument('--timeout', type=float, default=600)
    parser.add_argument('--model', default='google/gemini-3.7-flash')
    parser.add_argument('--pro-model', default='google/gemini-3.1-pro-preview')
    options = parser.parse_args(argv)
    options.source_reuse_maps = read_json(options.source_reuse_maps_file) if options.source_reuse_maps_file else {}
    options.editorial_adjudications = (read_json(options.editorial_adjudications_file)
                                      if options.editorial_adjudications_file else {})
    root = options.root.resolve(); output = options.state_dir.resolve()
    if output == root or (output.is_relative_to(root) and not output.is_relative_to(root / '.transcription')):
        raise ValueError('state directory must be private and outside public source paths')
    flags = read_json(options.flags) if options.flags else {}
    inventory = build_inventory(root, catalogue_ref=options.catalogue_ref, state_dir=output, flags=flags)
    output.mkdir(parents=True, exist_ok=True)
    pipeline.semantic_write_json(output / 'inventory.json', inventory)
    pipeline.semantic_write_json(output / 'queue.json', {'catalogueRevision': inventory['catalogueRevision'],
        'songs': [{'slug': row['slug'], 'state': row['state'], 'stages': row['plannedStages'],
                   'fingerprints': row['fingerprints']} for row in inventory['songs'] if row['plannedStages']]})
    print(json.dumps({'counts': inventory['counts'], 'output': str(output)}, ensure_ascii=False))
    if options.execute:
        run = execute_inventory(root, inventory, output, options)
        print(json.dumps({'status': run['status'], 'remaining': run['remaining'], 'ledger': run['ledger']}))
    return 0


if __name__ == '__main__': raise SystemExit(main())

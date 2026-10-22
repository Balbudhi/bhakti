"""Bounded, source-first semantic repair. No public writes or flag clearing."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any

VERSION = 1
KINDS = {'gloss_sense', 'frame_relation', 'english_realization', 'english_mapping', 'unresolved_evidence'}
HOLD_REASONS = {'audited_source_ambiguity', 'external_evidence_missing', 'locked_baseline_conflict'}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     prefix='.semantic-', delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def call_timeout(options) -> float:
    timeout = float(options.timeout)
    deadline = getattr(options, 'semantic_deadline_at', None)
    if deadline is not None:
        remaining = float(deadline) - time.time()
        if remaining <= 0:
            raise RuntimeError('semantic_deadline_exceeded')
        timeout = min(timeout, remaining)
    if not math.isfinite(timeout) or timeout <= 0:
        raise RuntimeError('invalid semantic timeout')
    return timeout


def issue_errors(lines, glosses, issues) -> list[str]:
    sources = {row['id']: row for row in lines}
    words = {row['id']: row.get('word_glosses', []) for row in glosses}
    errors = []
    if not isinstance(issues, list):
        return ['issues must be an array']
    for issue in issues:
        if not isinstance(issue, dict):
            errors.append('issue must be an object'); continue
        targets = issue.get('target_line_ids')
        if (issue.get('kind') not in KINDS or not isinstance(targets, list) or not targets
                or any(not isinstance(item, str) or item not in sources for item in targets)
                or len(set(targets)) != len(targets)):
            errors.append('invalid repair kind or target IDs')
        for field in ('explanation', 'evidence'):
            if not isinstance(issue.get(field), str) or not issue[field].strip():
                errors.append(f'issue lacks {field}')
        refs = issue.get('references')
        if not isinstance(refs, list) or not refs:
            errors.append('issue lacks source references'); continue
        for ref in refs:
            if not isinstance(ref, dict):
                errors.append('invalid reference'); continue
            line_id = ref.get('line_id'); indices = ref.get('word_indices'); quote = ref.get('source_quote')
            if (not isinstance(line_id, str) or line_id not in sources or ref.get('domain') != 'word_glosses'
                    or not isinstance(indices, list) or not indices
                    or any(type(index) is not int or index < 0 or index >= len(words.get(line_id, [])) for index in indices)
                    or len(set(indices)) != len(indices)
                    or not isinstance(quote, str) or not quote.strip()
                    or quote not in str(sources.get(line_id, {}).get('source_text', ''))):
                errors.append('invalid per-line word_glosses reference or source quotation')
        if issue.get('kind') == 'unresolved_evidence':
            if issue.get('hold_reason') not in HOLD_REASONS or not str(issue.get('needed_evidence', '')).strip():
                errors.append('unresolved evidence requires a typed reason and needed evidence')
        elif issue.get('hold_reason') or issue.get('needed_evidence'):
            errors.append('repairable issue cannot conceal an evidence hold')
    return errors


def issue_schema() -> dict:
    string = {'type': 'string'}
    reference = {'type': 'object', 'properties': {
        'line_id': string, 'domain': {'type': 'string', 'enum': ['word_glosses']},
        'word_indices': {'type': 'array', 'items': {'type': 'integer'}}, 'source_quote': string},
        'required': ['line_id', 'domain', 'word_indices', 'source_quote'], 'additionalProperties': False}
    fields = {'kind': {'type': 'string', 'enum': sorted(KINDS)},
              'target_line_ids': {'type': 'array', 'items': string},
              'references': {'type': 'array', 'items': reference},
              'explanation': string, 'evidence': string, 'needed_evidence': string, 'hold_reason': string}
    return {'type': 'array', 'items': {'type': 'object', 'properties': fields,
            'required': list(fields), 'additionalProperties': False}}


REVIEW_GUIDANCE = '''Return issues=[] only when no repair or evidence hold remains. For a concrete defect,
return a typed issue: gloss_sense, frame_relation, english_realization, english_mapping,
or unresolved_evidence. Name replacement target_line_ids and references as
{line_id,domain:"word_glosses",word_indices:[...],source_quote:"exact source substring"}.
Indices refer ONLY to that named line's word_glosses array, not source whitespace.
Explain the source grammar/context contradiction in explanation and evidence; do
not prescribe a preferred English rewrite. Dictionary candidates are possible
senses, not authority. Do not invent external evidence or entry IDs. Ordinary
polysemy resolvable from source grammar is repairable; a dictionary gap alone is
not missing evidence. Preserve simultaneous readings when supported. If the source
cannot resolve materially different agency/image, use unresolved_evidence with
hold_reason audited_source_ambiguity, external_evidence_missing, or
locked_baseline_conflict, and specify needed_evidence. For repairable issues,
needed_evidence and hold_reason must be empty. A passing, resolved review has no
issues. Source-first judgment takes precedence over the candidate frame and its
certainty claims. A locked baseline conflict still requires an evidence hold.
'''


def resolved_baseline(pipeline, song_dir, lines, job):
    """Same exact-map resolution used by text reconstruction, with explicit root.

    The registry is authoritative. Stored declarations are recovered from reader,
    intake and summary even when this job does not supply owner English.
    """
    registry = pipeline.editorial_baselines.load_baselines(pipeline.ROOT)
    expected_ids = [row['id'] for row in lines]
    registered = registry.get(song_dir.name)
    if registered:
        baseline = registered['plainEnglishByLine']
        if set(baseline) != set(expected_ids):
            raise RuntimeError('owner baseline line population changed')
        explicit = job.get('providedTranslation', job.get('provided_translation'))
        values = [explicit] if explicit not in (None, '', False, '(none supplied)') else []
    else:
        baseline = None; values = []
    summary = pipeline.read_packet(song_dir / '.transcription/pipeline/song-packet.json') or {}
    source = pipeline.read_packet(song_dir / '.transcription/source.json') or {}
    reader_meta = {}
    reader_path = song_dir / 'data.js'
    if reader_path.exists():
        # Existing public data loader has a bounded VM; never execute the source
        # as Python or infer a supplied baseline from current visible English.
        import audit_bhakti_contract
        reader = audit_bhakti_contract.load_data(reader_path)
        reader_meta = reader.get('SONG_META', {})
    if not registered:
        for obj in (job, reader_meta, source, summary, summary.get('job', {})):
            if not isinstance(obj, dict): continue
            for field in ('humanTranslation', 'human_translation', 'providedTranslation', 'provided_translation'):
                value = obj.get(field)
                if value not in (None, '', False, '(none supplied)'): values.append(value)
    maps = []
    for value in values:
        if not isinstance(value, (str, dict)) or isinstance(value, bool):
            raise RuntimeError('owner baseline declaration has no recoverable wording')
        if isinstance(value, str):
            try:
                path = Path(value).expanduser()
                if path.is_file(): value = path.read_text(encoding='utf-8')
            except OSError:
                pass
            try: parsed = json.loads(value)
            except ValueError: parsed = None
            if isinstance(parsed, dict): value = parsed
            else:
                texts = [part for part in value.splitlines() if part.strip()]
                if len(texts) != len(expected_ids):
                    raise RuntimeError('owner baseline needs an exact line-ID mapping')
                value = dict(zip(expected_ids, texts))
        if (set(value) != set(expected_ids)
                or any(not isinstance(text, str) or not text.strip() for text in value.values())):
            raise RuntimeError('owner baseline line population or wording invalid')
        maps.append(value)
    for value in maps:
        if baseline is not None and value != baseline:
            raise RuntimeError('conflicting owner baseline declarations')
        baseline = value
    return baseline


def assert_baseline(baseline, translations):
    if baseline is None: return
    proposed = {row.get('id'): row.get('literal_english') for row in translations}
    if proposed != baseline or len(translations) != len(baseline):
        raise RuntimeError('locked_baseline_conflict: owner English must remain exact')


def source_evidence(pipeline, song_dir, audited):
    source = pipeline.read_packet(song_dir / '.transcription/source.json') or {}
    stable_fields = ('source_url', 'id', 'youtube_id', 'audio_sha256', 'source_sha256',
                     'recording_sha256', 'applied_trim', 'trim_start', 'trim_end')
    audio_hashes = []
    for suffix in ('.m4a', '.webm', '.ogg', '.mp3', '.wav', '.flac'):
        path = song_dir / ('audio' + suffix)
        if not path.is_file(): continue
        h = hashlib.sha256()
        with path.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''): h.update(chunk)
        audio_hashes.append(h.hexdigest())
    trim = pipeline.read_packet(song_dir / '.transcription/trim-applied.json')
    return {'lines': audited.get('packet', {}).get('verified_lines', []),
            'performance_order': audited.get('packet', {}).get('performance_order', []),
            'recording': {key: source[key] for key in stable_fields if key in source},
            'audio_content_sha256': sorted(set(audio_hashes)), 'trim_applied': trim}


def prior_fingerprints(pipeline, stage, inputs, options):
    """Explicit compatibility for unchanged v8 lexical/English evidence only.

    Review schema changed in v9; old held review judgments are never reused.
    Fingerprint provenance must match every exact old input, not record shape.
    """
    return {hashlib.sha256(json.dumps({
        'stage': stage, 'gloss_version': pipeline.GLOSS_CONTRACT_VERSION,
        'translation_version': version, 'model': pipeline.gemini.batch_base_model(options.model),
        'provider': pipeline.gemini.provider_name(), 'policy': pipeline.translation_policy_payload(),
        'inputs': inputs}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        for version in (8, pipeline.TRANSLATION_INPUT_VERSION)}


def reusable_prior_stages(pipeline, packet_dir, lines, languages, job, options, source_context, snapshots=None):
    def read(name):
        return snapshots.get(name) if snapshots is not None else pipeline.read_packet(packet_dir / name)
    glosses = read('04-glosses.json')
    identities = prior_fingerprints(pipeline, 'gloss', {'lines': lines, 'languages': languages}, options)
    if (not glosses or glosses.get('fingerprint') not in identities
            or glosses.get('gloss_contract_version') != pipeline.GLOSS_CONTRACT_VERSION
            or pipeline.fresh_gloss_contract_errors(lines, glosses.get('packet', {}).get('glosses', []), languages)):
        return None, None
    rows = glosses['packet']['glosses']
    inputs = {'lines': lines, 'glosses': rows, 'provided_translation': pipeline.supplied_translation(job),
              'languages': job.get('languages', languages)}
    identities = prior_fingerprints(pipeline, 'translation', inputs, options)
    for filename in ('05-translation.json', 'translation-candidate.json'):
        candidate = read(filename)
        if (not candidate or candidate.get('fingerprint') not in identities
                or candidate.get('input_contract_version') not in (8, pipeline.TRANSLATION_INPUT_VERSION)):
            continue
        translations = candidate.get('packet', {}).get('translations', [])
        if not candidate_structure_valid(pipeline, lines, rows, translations): continue
        candidate = copy.deepcopy(candidate)
        # Version8 did not bind performance order/recording. Preserve its
        # draft, but refresh review when that extra source context is present
        # unless its provenance explicitly binds the same content.
        context_empty = not any(source_context.get(key) for key in
            ('performance_order', 'recording', 'audio_content_sha256', 'trim_applied'))
        context_certified = context_empty or candidate.get('source_context_sha256') == digest(source_context)
        candidate['semantic_adoption'] = {'path': filename, 'fingerprint': candidate['fingerprint'],
            'accepted': filename == '05-translation.json' and context_certified
                        and not pipeline.fresh_translation_contract_errors(lines, rows, translations)}
        return copy.deepcopy(glosses), candidate
    return copy.deepcopy(glosses), None


def candidate_structure_valid(pipeline, lines, glosses, translations):
    if not isinstance(translations, list) or [row.get('id') for row in translations if isinstance(row, dict)] != [row['id'] for row in lines]:
        return False
    by_id = {row['id']: row for row in glosses}
    for row in translations:
        english = row.get('literal_english'); segments = row.get('segments')
        if not isinstance(english, str) or not english.strip() or not isinstance(segments, list) or not segments: return False
        used = set(); count = len(by_id[row['id']]['word_glosses'])
        for segment in segments:
            if not isinstance(segment, dict) or not isinstance(segment.get('text'), str) or not isinstance(segment.get('word_indices'), list): return False
            for index in segment['word_indices']:
                if type(index) is not int or not 0 <= index < count: return False
                used.add(index)
        if used != set(range(count)): return False
        if pipeline.segment_english([{**part, 'word_indices': []} for part in segments], '') != english: return False
    return True


def require_acceptance(pipeline, packet_dir, glosses=None, translations=None, summary=None, audited=None, accepted_state=None):
    summary = summary or {}
    if glosses is None: glosses = pipeline.read_packet(packet_dir / '04-glosses.json')
    if translations is None: translations = pipeline.read_packet(packet_dir / '05-translation.json')
    marker = pipeline.read_packet(packet_dir / 'semantic-repair-required.json')
    required = (packet_dir / 'semantic-repair-required.json').exists() or any(isinstance(item, dict) and item.get('semantic_repair_version')
                                        for item in (summary, glosses, translations))
    if not required: return
    manifest = pipeline.read_packet(packet_dir / 'semantic-acceptance.json') or {}
    state = accepted_state if accepted_state is not None else (pipeline.read_packet(packet_dir / 'semantic-repair-state.json') or {})
    if audited is None:
        audited = pipeline.read_packet(packet_dir / '02-transcript-audit.json') or summary.get('audit') or {}
    if (state.get('status') != 'accepted' or state.get('run_id') != manifest.get('run_id')
            or manifest.get('source_sha256') != digest(source_evidence(pipeline, packet_dir.parent.parent, audited))
            or manifest.get('version') != VERSION or manifest.get('status') != 'accepted'
            or not isinstance(marker, dict) or manifest.get('run_id') != marker.get('run_id')
            or not isinstance(glosses, dict) or not isinstance(translations, dict)
            or manifest.get('gloss_sha256') != digest(glosses)
            or manifest.get('translation_sha256') != digest(translations)):
        raise RuntimeError('semantic repair acceptance manifest missing or pair hash mismatch')


def _bounded_ready():
    try: amount = float(os.environ.get('BHAKTI_API_RUN_BUDGET_USD', '0'))
    except ValueError: return False
    return bool(os.environ.get('BHAKTI_API_RUN_LEDGER')) and math.isfinite(amount) and amount > 0


def complete(pipeline, song_dir, audited, job, options):
    packet_dir = song_dir / '.transcription/pipeline'
    state_path = packet_dir / 'semantic-repair-state.json'
    prior_state = pipeline.read_packet(state_path) or {}
    state = dict(prior_state)
    state['status'] = 'in-progress'
    pipeline.semantic_write_json(state_path, state)
    lines = audited.get('packet', {}).get('verified_lines', [])
    languages = audited.get('packet', {}).get('metadata', {}).get('languages')
    try:
        baseline = resolved_baseline(pipeline, song_dir, lines, job)
        evidence = source_evidence(pipeline, song_dir, audited)
        identity = digest({'version': VERSION, 'source_evidence': evidence, 'languages': languages,
                           'baseline': baseline, 'policy': pipeline.translation_policy_payload(),
                           'model': options.model, 'provider': pipeline.gemini.provider_name()})
        if prior_state.get('run_id') == identity:
            state = dict(prior_state)
            if state.get('status') == 'blocked':
                raise RuntimeError(state.get('reason', 'semantic repair blocked'))
        else:
            seconds = float(getattr(options, 'semantic_repair_seconds', 600))
            if not math.isfinite(seconds) or seconds <= 0:
                raise RuntimeError('invalid semantic repair deadline')
            state = {'version': VERSION, 'run_id': identity, 'status': 'in-progress',
                     'rounds_used': 0, 'deadline_at_epoch': time.time() + seconds}
        local = copy.copy(options)
        local.force = False  # A force rerun cannot reset this run's paid history.
        local.semantic_deadline_at = state['deadline_at_epoch']
        local.semantic_full_source = lines
        local.semantic_performance_order = audited.get('packet', {}).get('performance_order', [])
        local.semantic_source_identity = digest(evidence)
        local.semantic_baseline = baseline
        marker = {'version': VERSION, 'run_id': identity}
        pipeline.semantic_write_json(packet_dir / 'semantic-repair-required.json', marker)
        if state.get('status') == 'accepted':
            glosses = pipeline.read_packet(packet_dir / '04-glosses.json')
            translations = pipeline.read_packet(packet_dir / '05-translation.json')
            require_acceptance(pipeline, packet_dir, glosses, translations, audited=audited, accepted_state=state)
            errors = pipeline.fresh_gloss_contract_errors(lines, glosses['packet']['glosses'], languages)
            errors += pipeline.fresh_translation_contract_errors(lines, glosses['packet']['glosses'], translations['packet']['translations'])
            if errors: raise RuntimeError('accepted semantic cache violates contract: ' + str(errors[:3]))
            pipeline.semantic_write_json(state_path, state)
            return glosses, translations
        state['status'] = 'in-progress'
        pipeline.semantic_write_json(state_path, state)
        run_dir = packet_dir / 'semantic-repair' / identity
        job = dict(job)
        if baseline is not None:
            baseline_path = run_dir / 'owner-english.json'
            pipeline.semantic_write_json(baseline_path, baseline)
            job['providedTranslation'] = str(baseline_path)
        # Persist adopted evidence before any stage-ready checkpoint. On
        # resume validate the immutable snapshot, not today's root artifacts.
        seed_path = run_dir / 'adopted-seeds.json'
        seed_bundle = pipeline.read_packet(seed_path)
        if seed_bundle is not None:
            payload = seed_bundle.get('payload')
            if (not isinstance(payload, dict) or payload.get('run_id') != identity
                    or seed_bundle.get('sha256') != digest(payload)):
                raise RuntimeError('adopted semantic seed identity mismatch')
            snapshots = payload.get('artifacts')
            if not isinstance(snapshots, dict): raise RuntimeError('invalid adopted semantic seed snapshot')
            seed_gloss, seed_translation = reusable_prior_stages(
                pipeline, packet_dir, lines, languages, job, options, evidence, snapshots=snapshots)
            if snapshots.get('04-glosses.json') is not None and seed_gloss is None:
                raise RuntimeError('adopted gloss no longer satisfies exact input contract')
            if any(snapshots.get(name) for name in ('05-translation.json', 'translation-candidate.json')) and seed_translation is None:
                raise RuntimeError('adopted translation no longer satisfies exact input contract')
        else:
            seed_gloss, seed_translation = reusable_prior_stages(
                pipeline, packet_dir, lines, languages, job, options, evidence)
            snapshots = {'04-glosses.json': seed_gloss}
            if seed_translation:
                snapshots[seed_translation['semantic_adoption']['path']] = seed_translation
            payload = {'run_id': identity, 'artifacts': snapshots}
            pipeline.semantic_write_json(seed_path, {'payload': payload, 'sha256': digest(payload)})
        maximum = min(2, max(0, int(getattr(options, 'semantic_repair_rounds', 2))))
        while True:
            call_timeout(local)
            number = state['rounds_used']; round_dir = run_dir / f'round-{number}'
            feedback = state.get('feedback', [])
            local.semantic_repair_feedback = feedback
            local.semantic_review_generation = number
            previous_gloss = None; previous_translation = None
            if number:
                previous = run_dir / f'round-{number-1}'
                previous_gloss = pipeline.read_packet(previous / 'gloss-ready.json')
                previous_translation = pipeline.read_packet(previous / 'translation-ready.json')
                if not previous_gloss or not previous_translation:
                    raise RuntimeError('repair predecessor evidence missing')
            referenced = {ref['line_id'] for issue in feedback for ref in issue.get('references', [])}
            referenced.update(item for issue in feedback for item in issue['target_line_ids'])
            local.semantic_prior_gloss = [row for row in previous_gloss['packet']['glosses'] if row['id'] in referenced] if previous_gloss else []
            ready_path = round_dir / 'gloss-ready.json'
            expected_gloss_identity = digest({'run': identity, 'round': number, 'feedback': feedback,
                                             'previous_gloss': previous_gloss})
            glosses = pipeline.read_packet(ready_path)
            if glosses and glosses.get('semantic_request_identity') != expected_gloss_identity:
                raise RuntimeError('repaired gloss cache identity mismatch')
            if glosses:
                errors = pipeline.fresh_gloss_contract_errors(lines, glosses['packet']['glosses'], languages)
                if errors: raise RuntimeError('repaired gloss cache violates contract: ' + str(errors[:3]))
            else:
                lexical_targets = set(item for issue in feedback if issue['kind'] in {'gloss_sense', 'frame_relation'}
                                      for item in issue['target_line_ids'])
                if number and not lexical_targets:
                    glosses = copy.deepcopy(previous_gloss)
                elif number:
                    subset = copy.deepcopy(audited)
                    subset['packet']['verified_lines'] = [row for row in lines if row['id'] in lexical_targets]
                    repaired = pipeline.gloss(round_dir, subset, local)
                    by_id = {row['id']: row for row in repaired['packet']['glosses']}
                    glosses = copy.deepcopy(previous_gloss)
                    glosses['packet']['glosses'] = [by_id.get(row['id'], row) for row in previous_gloss['packet']['glosses']]
                else:
                    glosses = seed_gloss or pipeline.gloss(round_dir, audited, local)
                glosses['semantic_request_identity'] = expected_gloss_identity
                errors = pipeline.fresh_gloss_contract_errors(lines, glosses['packet']['glosses'], languages)
                if errors: raise RuntimeError('gloss_contract_hold: ' + str(errors[:3]))
                pipeline.semantic_write_json(ready_path, glosses)
            translation_path = round_dir / 'translation-ready.json'
            translations = pipeline.read_packet(translation_path)
            expected_translation_identity = digest({'run': identity, 'round': number, 'gloss': glosses,
                                                   'feedback': feedback, 'previous_translation': previous_translation})
            if translations and translations.get('semantic_request_identity') != expected_translation_identity:
                raise RuntimeError('translation cache identity mismatch')
            if not translations and number == 0 and seed_translation and seed_translation.get('semantic_adoption', {}).get('accepted'):
                translations = seed_translation
                translations['semantic_request_identity'] = expected_translation_identity
                pipeline.semantic_write_json(translation_path, translations)
            if not translations:
                local.semantic_seed_translation = seed_translation if number == 0 else None
                local.semantic_translation_targets = sorted(set(item for issue in feedback for item in issue['target_line_ids'])) if number else None
                local.semantic_previous_translations = previous_translation['packet']['translations'] if number else None
                translations = pipeline.translate(round_dir, audited, glosses, job, local, candidate_only=True)
                translations['semantic_request_identity'] = expected_translation_identity
                pipeline.semantic_write_json(translation_path, translations)
            rows = translations['packet']['translations']
            assert_baseline(baseline, rows)
            errors = pipeline.fresh_translation_contract_errors(lines, glosses['packet']['glosses'], rows)
            issues = []
            for row in rows:
                review = row.get('independent_review', {})
                recorded = review.get('issues')
                if recorded is None and translations.get('semantic_adoption', {}).get('accepted') and not errors:
                    recorded = []  # Existing affirmative review remains unchanged.
                if not isinstance(recorded, list): raise RuntimeError('invalid_repair_feedback: missing typed issues')
                if review.get('passes') is True and review.get('human_review_recommended') is False and recorded:
                    raise RuntimeError('invalid_repair_feedback: passing review has issues')
                issues.extend(recorded)
            invalid = issue_errors(lines, glosses['packet']['glosses'], issues)
            if invalid: raise RuntimeError('invalid_repair_feedback: ' + str(invalid[:3]))
            if not errors and not issues:
                # New metadata is outside the candidate packet; linguistic
                # evidence and supplied English remain unchanged.
                glosses['semantic_repair_version'] = VERSION; glosses['semantic_run_id'] = identity
                glosses['fingerprint'] = digest({'unconditioned': glosses.get('fingerprint'), 'request': glosses['semantic_request_identity'], 'run': identity})
                translations['semantic_repair_version'] = VERSION; translations['semantic_run_id'] = identity
                translations['source_context_sha256'] = digest(evidence)
                pipeline.semantic_write_json(packet_dir / '04-glosses.json', glosses)
                pipeline.semantic_write_json(packet_dir / '05-translation.json', translations)
                pipeline.semantic_write_json(packet_dir / 'semantic-acceptance.json', {
                    'version': VERSION, 'status': 'accepted', 'run_id': identity,
                    'gloss_sha256': digest(glosses), 'translation_sha256': digest(translations),
                    'source_sha256': digest(evidence)})
                state['status'] = 'accepted'; state.pop('reason', None)
                pipeline.semantic_write_json(state_path, state)
                return glosses, translations
            for issue in issues:
                if issue['kind'] == 'unresolved_evidence':
                    raise RuntimeError(issue['hold_reason'] + ': ' + issue['needed_evidence'])
            if not issues: raise RuntimeError('semantic_contract_hold: ' + str(errors[:3]))
            if number >= maximum: raise RuntimeError('repair_limit_exhausted')
            if not _bounded_ready(): raise RuntimeError('repair_budget_required')
            candidate_hash = digest({'glosses': glosses['packet'], 'translations': [
                {key: value for key, value in row.items() if key != 'independent_review'} for row in rows]})
            if candidate_hash in state.get('candidate_hashes', []): raise RuntimeError('no_progress')
            state.setdefault('candidate_hashes', []).append(candidate_hash)
            state['feedback'] = issues
            state['rounds_used'] = number + 1
            pipeline.semantic_write_json(state_path, state)
    except Exception as exc:
        state['status'] = 'blocked'; state['reason'] = str(exc)
        pipeline.semantic_write_json(state_path, state)
        raise

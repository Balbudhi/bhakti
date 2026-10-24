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



# Private review evidence helpers; no model calls and no publication side effects.
def writer_rows(rows):
    return [{key: copy.deepcopy(value) for key, value in row.items()
             if key != 'independent_review'} for row in rows]


def review_context_basis(target_lines, *, full_source=None, performance_order=(), context_evidence=()):
    targets = {row['id'] for row in target_lines}
    return {'target_ids': [row['id'] for row in target_lines],
            'full_source': copy.deepcopy(target_lines if full_source is None else full_source),
            'performance_order': copy.deepcopy(list(performance_order)),
            'context_evidence': [{key: copy.deepcopy(row[key]) for key in ('source', 'gloss', 'draft')}
                                 for row in context_evidence if row['source']['id'] not in targets]}


def review_context_identity(lines, options=None, *, performance_order=()):
    return digest(review_context_basis(lines,
        full_source=getattr(options, 'semantic_full_source', lines),
        performance_order=getattr(options, 'semantic_performance_order', performance_order),
        context_evidence=getattr(options, 'semantic_context_evidence', [])))


def reservation_fields(row):
    uncertain = str(row.get('uncertainty') or '').strip().casefold() not in {'', 'none', 'no', 'null', 'n/a'}
    fidelity = row.get('fidelity', {})
    negative = (isinstance(fidelity, dict) and
                (fidelity.get('agency_and_image_preserved') is False
                 or fidelity.get('all_meaning_accounted_for') is False
                 or bool(fidelity.get('unsupported_additions'))))
    if row.get('human_review_recommended') is not True and not uncertain and not negative:
        return None
    if type(row.get('human_review_recommended')) is not bool or not isinstance(row.get('uncertainty'), str):
        raise ValueError('writer reservation has malformed confidence fields')
    return {key: copy.deepcopy(row.get(key)) for key in
            ('human_review_recommended', 'uncertainty', 'material_alternatives', 'choice_note', 'fidelity')}


def validated_writer_history(route_state_path):
    import bhakti_model_routes as routes
    state_path = Path(route_state_path)
    state = routes.read_unit_cache(state_path)['state']
    if state['status'] != 'accepted':
        raise ValueError('writer history has no accepted outcome')
    history = []
    for index, attempt in enumerate(state['attempts']):
        if attempt['status'] not in {'accepted', 'quality-failed'} or not attempt.get('candidate_sha256'):
            raise ValueError('writer history has unproven prior outcome')
        path = state_path.parent / ('flash' if index == 0 else 'pro') / 'candidate.json'
        candidate = json.loads(path.read_text())
        if digest(candidate) != attempt['candidate_sha256']:
            raise ValueError('writer history candidate changed')
        if 'writer_diagnostics' in candidate:
            observed = [row for response in candidate['writer_diagnostics'] if isinstance(response, dict)
                        for row in (response.get('packet', {}).get('translations') or []) if isinstance(row, dict)]
            rows = list({digest(row): row for row in observed}.values())
        else:
            rows = candidate.get('packet', {}).get('translations', [])
        history.append({'rows': writer_rows(rows), 'coordinator_acceptance': candidate.get('writer_coordinator_acceptance'),
                        'gloss_binding': candidate.get('writer_gloss_binding'),
                        'writer_fingerprint': candidate.get('fingerprint'), 'writer_model': attempt['model'],
                        'automatic_evidence_receipt': candidate.get('automatic_evidence_receipt', {}),
                        'proof': {'route_state_path': str(state_path), 'attempt_id': attempt['attempt_id'],
                                  'candidate_sha256': attempt['candidate_sha256']}})
    return history


def verify_writer_proof(proof, row):
    if 'route_state_path' in proof:
        history = validated_writer_history(proof['route_state_path'])
        records = [entry for entry in history if entry['proof'] == proof]
        if len(records) != 1 or row not in records[0]['rows']:
            raise ValueError('writer reservation lost its original route evidence')
    else:
        if row not in writer_proof_rows(proof):
            raise ValueError('writer reservation original draft changed')


def writer_review_context(lines, gloss_rows, translation_rows, *, context_identity, prior_candidates=(), previous_context=None, glossary_binding=None):
    current = writer_rows(translation_rows)
    by_id = {row['id']: row for row in current}
    targets = {row['id'] for row in lines}
    reservations = {}; origins = {}
    if previous_context:
        for ref in previous_context['reservations']:
            prior = next(item for item in previous_context['origins'] if item['reservation_id'] == ref['reservation_id'])
            verify_writer_proof(prior['proof'], prior['row'])
            reservations[ref['reservation_id']] = copy.deepcopy(ref)
            origins[ref['reservation_id']] = copy.deepcopy(prior)
    for candidate in prior_candidates:
        for row in candidate['rows']:
            if row.get('id') not in targets:
                continue
            fields = reservation_fields(row)
            if fields is None:
                continue
            rid = digest({'line_id': row['id'], 'row': row, 'context_identity': context_identity})
            reservations[rid] = {'reservation_id': rid, 'line_id': row['id'], 'candidate_sha256': digest(row)}
            origins[rid] = {'reservation_id': rid, 'row': copy.deepcopy(row), 'context_identity': context_identity, 'proof': copy.deepcopy(candidate['proof'])}
    # Every current concern needs durable source-bound writer evidence too.
    for row in current:
        if reservation_fields(row) is not None and not any(item['row'] == row for item in origins.values()):
            raise ValueError('writer reservation lacks immutable draft evidence')
    derived = glossary_binding is not None
    if derived and glossary_binding['review_sha256'] != digest(gloss_rows):
        raise ValueError('prepared glossary differs from writer binding')
    if not reservations and not derived:
        return None
    prior_concerns = [{'reservation_id': rid, 'fields': reservation_fields(item['row'])}
                      for rid, item in origins.items() if item['row'] != by_id.get(item['row']['id'])]
    result = {'version': 2 if derived else 1, 'source_sha256': digest(lines),
            'gloss_sha256': glossary_binding['authored_sha256'] if derived else digest(gloss_rows),
            'candidate_sha256': digest(current), 'context_identity': context_identity,
            'reservations': list(reservations.values()), 'prior_concerns': prior_concerns,
            'origins': list(origins.values())}
    if derived:
        result['review_gloss_sha256'] = glossary_binding['review_sha256']
    return result


def writer_review_context_errors(lines, gloss_rows, translation_rows, context, expected_context_identity, *, gloss_representation='authored'):
    try:
        if not isinstance(context, dict) or context.get('version') not in (1, 2):
            return ['writer reservation context missing or invalid']
        if gloss_representation not in ('authored', 'review'):
            return ['unknown glossary representation']
        gloss_key = 'review_gloss_sha256' if context['version'] == 2 and gloss_representation == 'review' else 'gloss_sha256'
        for field, expected in (('source_sha256', digest(lines)), (gloss_key, digest(gloss_rows)),
                                ('candidate_sha256', digest(writer_rows(translation_rows))),
                                ('context_identity', expected_context_identity)):
            if expected is None or context.get(field) != expected:
                return ['writer reservation ' + field + ' changed or unbound']
        references = context['reservations']; origins = context['origins']
        if (not references and context['version'] == 1) or len({r['reservation_id'] for r in references}) != len(references):
            return ['writer reservation population invalid']
        if {r['reservation_id'] for r in references} != {r['reservation_id'] for r in origins} or len(origins) != len(references):
            return ['writer reservation origin population invalid']
        target_ids = {line['id'] for line in lines}
        for reference in references:
            origin = next(item for item in origins if item['reservation_id'] == reference['reservation_id'])
            row = origin['row']
            if (reference['line_id'] not in target_ids or row['id'] != reference['line_id']
                    or digest(row) != reference['candidate_sha256'] or reservation_fields(row) is None):
                return ['writer reservation source/row binding changed']
            if digest({'line_id': row['id'], 'row': row, 'context_identity': origin['context_identity']}) != reference['reservation_id']:
                return ['writer reservation identity changed']
            verify_writer_proof(origin['proof'], row)
        # The immutable origin set must contain every current reservation.
        if any(reservation_fields(row) is not None and not any(item['row'] == row for item in origins)
               for row in writer_rows(translation_rows)):
            return ['current writer concern is missing from reservation context']
        expected_prior = [{'reservation_id': item['reservation_id'], 'fields': reservation_fields(item['row'])}
                          for item in origins if item['row'] not in writer_rows(translation_rows)]
        if context['prior_concerns'] != expected_prior:
            return ['writer prior concerns changed']
        return []
    except (KeyError, TypeError, ValueError, OSError) as exc:
        return ['invalid writer reservation evidence: ' + str(exc)]


def reservation_prompt_context(context, target_ids):
    if not context:
        return None
    refs = [row for row in context['reservations'] if row['line_id'] in target_ids]
    if not refs:
        return None
    ids = {row['reservation_id'] for row in refs}
    return {key: copy.deepcopy(context[key]) for key in
            ('version', 'source_sha256', 'gloss_sha256', 'review_gloss_sha256', 'candidate_sha256', 'context_identity') if key in context} | {
                'reservations': copy.deepcopy(refs),
                'prior_concerns': [copy.deepcopy(row) for row in context['prior_concerns'] if row['reservation_id'] in ids]}

def writer_proof_history(proof):
    """Read existing writer evidence, including an explicit legacy binding adoption."""
    if 'route_state_path' in proof:
        records = validated_writer_history(proof['route_state_path'])
        if sum(record['proof'] == proof for record in records) != 1:
            raise ValueError('writer evidence attempt missing')
        return records
    candidate = json.loads(Path(proof['path']).read_text())
    if digest(candidate) != proof['candidate_sha256']:
        raise ValueError('immutable writer evidence changed')
    record = {'rows': writer_rows(candidate['packet']['translations']), 'proof': proof,
              'coordinator_acceptance': candidate.get('writer_coordinator_acceptance'),
              'gloss_binding': candidate.get('writer_gloss_binding'),
              'writer_fingerprint': candidate.get('fingerprint'), 'writer_model': candidate.get('resolved_model'),
              'automatic_evidence_receipt': candidate.get('automatic_evidence_receipt', {})}
    previous = candidate.get('writer_binding_predecessor')
    history = []
    if previous is not None:
        history = writer_proof_history(previous)
        origin = next(item for item in history if item['proof'] == previous)
        if (origin['rows'] != record['rows'] or origin.get('gloss_binding') is not None
                or origin['automatic_evidence_receipt'] != record['automatic_evidence_receipt']):
            raise ValueError('legacy writer binding adoption changed original evidence')
    return history + [record]


def writer_proof_rows(proof):
    return next(record['rows'] for record in writer_proof_history(proof) if record['proof'] == proof)


def writer_evidence_receipt(history, context_identity, previous_context=None):
    items = [{'proof': copy.deepcopy(item['proof']), 'context_identity': context_identity} for item in history]
    if previous_context:
        items.extend({'proof': copy.deepcopy(origin['proof']), 'context_identity': origin['context_identity']}
                     for origin in previous_context['origins'])
    return {'version': 1, 'current': copy.deepcopy(history[-1]['proof']),
            'history': list({digest(item): item for item in items}.values())}


def check_writer_evidence(translations, lines, *, final_consumer=False):
    receipt = translations.get('writer_evidence')
    if not isinstance(receipt, dict) or receipt.get('version') != 1 or not isinstance(receipt.get('history'), list):
        raise ValueError('current translation lacks mandatory writer evidence')
    current = writer_rows(translations['packet']['translations'])
    if writer_proof_rows(receipt['current']) != current:
        raise ValueError('current translation differs from immutable writer evidence')
    proof = receipt['current']
    current_history = writer_proof_history(proof)
    record = next(item for item in current_history if item['proof'] == proof)
    binding = record.get('gloss_binding')
    automatic = record.get('automatic_evidence_receipt', {})
    if translations.get('writer_gloss_binding') != binding:
        raise ValueError('writer glossary binding differs from immutable writer evidence')
    context = translations.get('writer_review_context')
    if binding is not None:
        if (binding.get('version') != 1 or set(binding) != {'version', 'authored_sha256', 'review_sha256'}
                or any(not isinstance(binding[key], str) or len(binding[key]) != 64
                       for key in ('authored_sha256', 'review_sha256'))
                or translations.get('automatic_evidence_receipt', {}) != automatic):
            raise ValueError('invalid immutable writer glossary binding')
        if (not context or context.get('version') != 2
                or context.get('gloss_sha256') != binding['authored_sha256']
                or context.get('review_gloss_sha256') != binding['review_sha256']):
            raise ValueError('authored or prepared glossary binding changed')
    elif context and context.get('version') == 2:
        raise ValueError('derived glossary context lacks immutable writer binding')
    targets = {row['id'] for row in lines}
    required = set()
    history = list(receipt['history'])
    current_items = [item for item in history if item['proof'] == receipt['current']]
    if len(current_items) != 1:
        raise ValueError('current writer context missing')
    origin_context = current_items[0]['context_identity']
    history.extend({'proof': record['proof'], 'context_identity': origin_context}
                   for record in current_history)
    for item in history:
        for row in writer_proof_rows(item['proof']):
            if row.get('id') in targets and reservation_fields(row) is not None:
                required.add(digest({'line_id': row['id'], 'row': row, 'context_identity': item['context_identity']}))
    if receipt['current'] not in [item['proof'] for item in receipt['history']]:
        raise ValueError('writer evidence current attempt absent from history')
    context = translations.get('writer_review_context')
    actual = {row['reservation_id'] for row in context['reservations']} if context else set()
    if required != actual:
        raise ValueError('required original writer reservations removed or changed')
    proof = receipt['current']
    if 'route_state_path' in proof:
        authoritative = next(record for record in validated_writer_history(proof['route_state_path'])
                             if record['proof'] == proof)
        path = authoritative.get('coordinator_acceptance')
    else:
        # writer_proof_rows above already verified these immutable bytes.
        path = json.loads(Path(proof['path']).read_text()).get('writer_coordinator_acceptance')
    if path:
        directory = Path(path).parent
        state = json.loads((directory / 'semantic-repair-state.json').read_text())
        if state.get('status') != 'accepted':
            if final_consumer:
                raise ValueError('coordinator writer evidence is not finally accepted')
            return
        manifest = json.loads(Path(path).read_text())
        if (manifest.get('status') != 'accepted'
                or manifest.get('run_id') != state['run_id']
                or state.get('review_task_version') != translations.get('review_task_version')
                or state.get('writer_closure_sha256') != writer_closure(translations)):
            raise ValueError('coordinator writer obligation closure changed')
    elif translations.get('semantic_repair_version'):
        raise ValueError('current translation lost immutable coordinator evidence')


def writer_closure(translations):
    return digest({'writer_evidence': translations.get('writer_evidence'),
                   'writer_review_context': translations.get('writer_review_context'),
                   'review_task_version': translations.get('review_task_version')})


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
    support = pipeline.bhakti_lexical_support.prepare_options(options, lines, languages)
    policy = pipeline.semantic_stage_policy(options, stage='gloss')
    glosses = read('04-glosses.json')
    gloss_model = options.model
    if glosses and glosses.get('historical_gloss_route'):
        import bhakti_model_routes as routes
        prior = routes.read_unit_cache(Path(glosses['historical_gloss_route']))
        original = {key: value for key, value in glosses.items() if key != 'historical_gloss_route'}
        if (prior['state'].get('status') != 'accepted' or prior['state'].get('base_model') != options.model
                or prior['result'].get('glosses') != original):
            raise RuntimeError('historical source glossary receipt mismatch')
        gloss_model = original.get('resolved_model', prior['state'].get('accepted_model'))
    gloss_inputs = {'lines': lines, 'languages': languages}
    identities = {pipeline.text_stage_fingerprint('gloss', gloss_model, gloss_inputs, policy)}
    # Historical signatures never bound lexical support. They can only seed a
    # run without that new evidence; they are not current-policy equivalence.
    no_support = getattr(options, 'semantic_lexical_support', None) is None
    if no_support:
        identities.update(prior_fingerprints(pipeline, 'gloss', gloss_inputs, options))
    if (not glosses or glosses.get('fingerprint') not in identities
            or glosses.get('gloss_contract_version') != pipeline.GLOSS_CONTRACT_VERSION
            or scoped_gloss_contract_errors(pipeline, lines, glosses.get('packet', {}).get('glosses', []), languages, options)
            or pipeline.bhakti_lexical_support.support_decision_errors(support, glosses.get('packet', {}).get('glosses', []))):
        return None, None
    view_options, view_glosses = pipeline.bhakti_lexical_producer.prepare_translation(
        packet_dir.parent.parent, {'packet': {'verified_lines': lines, 'metadata': {'languages': languages},
            'performance_order': source_context.get('performance_order', [])}}, glosses, options)
    rows = view_glosses['packet']['glosses']
    support = pipeline.bhakti_lexical_support.prepare_options(view_options, lines, languages)
    policy = pipeline.semantic_stage_policy(view_options)
    provided = pipeline.supplied_translation(job)
    translation_languages = job.get('languages', languages)
    current_inputs = pipeline.translation_stage_inputs(lines, rows, provided, translation_languages, view_options,
        performance_order=source_context.get('performance_order', []))
    identities = {pipeline.text_stage_fingerprint('translation', options.model, current_inputs, policy)}
    if no_support and pipeline.bhakti_lexical_producer.settings(options) is None and not current_inputs['reading_context_evidence']:
        historical_inputs = {'lines': lines, 'glosses': rows, 'provided_translation': provided,
                             'languages': translation_languages}
        identities.update(prior_fingerprints(pipeline, 'translation', historical_inputs, options))
    for filename in ('05-translation.json', 'translation-candidate.json'):
        candidate = read(filename)
        candidate_identities = identities
        if candidate and candidate.get('historical_translation_route'):
            import bhakti_model_routes as routes
            prior = routes.read_unit_cache(Path(candidate['historical_translation_route']))
            original = {key: value for key, value in candidate.items() if key != 'historical_translation_route'}
            if (prior['state'].get('status') != 'accepted' or prior['state'].get('base_model') != options.model
                    or prior['state'].get('unit_id') != packet_dir.parent.parent.name + ':new-source-semantics'
                    or prior['result'].get('translations') != original):
                raise RuntimeError('historical writer receipt mismatch')
            producing_model = original.get('resolved_model', prior['state'].get('accepted_model'))
            candidate_identities = {pipeline.text_stage_fingerprint('translation', producing_model, current_inputs, policy)}
        if (not candidate or candidate.get('fingerprint') not in candidate_identities
                or candidate.get('input_contract_version') not in (8, pipeline.TRANSLATION_INPUT_VERSION)):
            continue
        translations = candidate.get('packet', {}).get('translations', [])
        if not candidate_structure_valid(pipeline, lines, rows, translations): continue
        if pipeline.bhakti_lexical_support.support_decision_errors(support, rows, translations): continue
        candidate = copy.deepcopy(candidate)
        # Version8 did not bind performance order/recording. Preserve its
        # draft, but refresh review when that extra source context is present
        # unless its provenance explicitly binds the same content.
        context_empty = not any(source_context.get(key) for key in
            ('performance_order', 'recording', 'audio_content_sha256', 'trim_applied'))
        context_certified = context_empty or candidate.get('source_context_sha256') == digest(source_context)
        candidate['semantic_adoption'] = {'path': filename, 'fingerprint': candidate['fingerprint'],
            'accepted': filename == '05-translation.json' and context_certified
                        and candidate.get('review_task_version', 0) == pipeline.REVIEW_TASK_VERSION
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
    if state.get('review_task_version', 0) >= 3:
        if translations.get('review_task_version') != state['review_task_version']:
            raise RuntimeError('current accepted review task missing or downgraded')
        if state.get('writer_closure_sha256') != writer_closure(translations):
            raise RuntimeError('accepted original writer obligation closure changed')
        check_writer_evidence(translations, audited['packet']['verified_lines'])


def _bounded_ready():
    try: amount = float(os.environ.get('BHAKTI_API_RUN_BUDGET_USD', '0'))
    except ValueError: return False
    return bool(os.environ.get('BHAKTI_API_RUN_LEDGER')) and math.isfinite(amount) and amount > 0



def derived_support_view(pipeline, song_dir, audited, glosses, translations, options):
    lines = audited['packet']['verified_lines']
    languages = audited['packet'].get('metadata', {}).get('languages')
    if 'automatic_lexical_feedback' in translations:
        options = copy.copy(options)
        feedback = translations['automatic_lexical_feedback']
        errors = issue_errors(lines, glosses['packet']['glosses'], feedback)
        if errors:
            raise RuntimeError('accepted lexical lookup feedback invalid: ' + str(errors[:3]))
        options.semantic_repair_feedback = copy.deepcopy(feedback)
    return pipeline.bhakti_lexical_producer.prepare_translation(song_dir, audited, glosses, options)


def derived_support_errors(pipeline, song_dir, audited, glosses, translations, options):
    lines = audited['packet']['verified_lines']
    languages = audited['packet'].get('metadata', {}).get('languages')
    view_options, view = derived_support_view(pipeline, song_dir, audited, glosses, translations, options)
    support = pipeline.bhakti_lexical_support.prepare_options(view_options, lines, languages)
    errors = pipeline.automatic_evidence_errors(view_options, translations)
    errors += pipeline.bhakti_lexical_support.support_decision_errors(
        support, view['packet']['glosses'], translations['packet']['translations'])
    discovery = getattr(view_options, 'automatic_source_discovery', None)
    if discovery is not None:
        import bhakti_source_discovery
        errors += bhakti_source_discovery.translation_decision_errors(discovery, translations['packet']['translations'])
    return errors


def validated_gloss_seed(pipeline, glossary, receipt, source_identity, glossary_identity, lines, languages, options=None):
    """Revalidate the immutable glossary snapshot authorized by prior acceptance."""
    manifest = receipt.get('manifest', {})
    if (receipt.get('source_gloss_identity') != glossary_identity
            or manifest.get('status') != 'accepted' or manifest.get('version') != VERSION
            or manifest.get('source_sha256') != source_identity
            or manifest.get('gloss_sha256') != digest(glossary)
            or receipt.get('prior_run_id') != manifest.get('run_id')):
        raise RuntimeError('accepted glossary seed receipt mismatch')
    errors = scoped_gloss_contract_errors(pipeline, lines, glossary['packet']['glosses'], languages, options)
    errors += issue_errors(lines, glossary['packet']['glosses'], receipt.get('automatic_lexical_feedback', []))
    if errors:
        raise RuntimeError('accepted glossary seed violates contract: ' + str(errors[:3]))
    return copy.deepcopy(glossary)


def validated_review_seed(pipeline, song_dir, audited, glossary, candidate, receipt,
                          content_identity, options, baseline):
    """Reuse exact prior paid writing only when the review task alone changed."""
    proof = receipt.get('review_only', {})
    if (proof.get('content_configuration_run_id') != content_identity
            or receipt.get('manifest', {}).get('translation_sha256') != digest(candidate)):
        raise RuntimeError('review-only writer seed receipt mismatch')
    lines = audited['packet']['verified_lines']
    rows = candidate.get('packet', {}).get('translations', [])
    errors = pipeline.fresh_translation_contract_errors(lines, glossary['packet']['glosses'], rows, require_review=False, **pipeline.translation_packet_contract_kwargs(lines, candidate, options, performance_order=audited['packet'].get('performance_order', []), expected_review_task_version=receipt.get('manifest', {}).get('review_task_version', 0)))
    errors += derived_support_errors(pipeline, song_dir, audited, glossary, candidate, options)
    view_options, _ = derived_support_view(pipeline, song_dir, audited, glossary, candidate, options)
    if pipeline.automatic_evidence_receipt(view_options) != proof.get('automatic_evidence_receipt'):
        errors.append('review-only writer evidence changed')
    if errors:
        raise RuntimeError('review-only writer seed violates current evidence: ' + str(errors[:3]))
    assert_baseline(baseline, rows)
    value = copy.deepcopy(candidate)
    value.pop('review_responses', None)
    value.pop('review_task_version', None)
    for row in value['packet']['translations']:
        row.pop('independent_review', None)
    value['semantic_adoption'] = {'accepted': False, 'path': '05-translation.json',
                                  'fingerprint': candidate.get('fingerprint')}
    return value


def stage_routes_enabled(options):
    import bhakti_model_routes as routes
    return options.model in {routes.FLASH_MODEL, routes.PRO_MODEL}


def stage_context(options):
    keys = ('semantic_context_evidence', 'semantic_full_source', 'semantic_performance_order',
            'semantic_source_identity', 'semantic_baseline', 'semantic_repair_feedback',
            'semantic_prior_gloss', 'semantic_translation_targets', 'semantic_previous_translations',
            'semantic_seed_translation', 'automatic_lexical_feedback', 'semantic_initial_repair')
    context = {key: copy.deepcopy(getattr(options, key)) for key in keys if hasattr(options, key)}
    import bhakti_lexical_producer as producer
    requests = producer.requested_identity(options)
    if requests:
        context['lexical_requested_spans'] = requests
    return context


def semantic_stage_route(pipeline, song_dir, stage, inputs, options, execute, validate, *, base_model=None):
    """Own exactly one stage's attempt history; later stages cannot relabel it."""
    import bhakti_model_routes as routes
    base_model = base_model or options.model
    pro_model = getattr(options, 'pro_model', routes.PRO_MODEL)
    escalation = getattr(options, 'semantic_stage_escalation', True)
    if type(escalation) is not bool:
        raise RuntimeError('semantic_stage_escalation must be boolean')
    if not escalation:
        pro_model = base_model
    deadlines = [float(getattr(options, key)) for key in
                 ('semantic_deadline_at', 'unit_deadline_at') if getattr(options, key, None) is not None]
    if not deadlines:
        raise RuntimeError('semantic stage requires bounded deadline')
    identity = digest({'stage': stage, 'inputs': inputs, 'context': stage_context(options),
                       'escalation': escalation})
    original_failure = []
    def run(context):
        local = copy.copy(options)
        if stage == 'writer':
            local.semantic_writer_diagnostics = []
        local.model = context.model
        local.force = False
        local.unit_context = context.transport_context
        local.unit_deadline_at = context.deadline_at
        local.semantic_deadline_at = min(deadlines + [context.deadline_at])
        local.timeout = min(float(options.timeout), context.call_timeout_seconds)
        target = context.attempt_dir / 'songs' / song_dir.name
        try:
            result = execute(target, local)
        except routes.QualityFailure as exc:
            if stage == 'writer' and local.semantic_writer_diagnostics:
                return {'writer_diagnostics': copy.deepcopy(local.semantic_writer_diagnostics),
                        'quality_issues': copy.deepcopy(exc.issues), 'resolved_model': context.model}
            raise
        except (routes.UnitTransportFailure, routes.RunFatal):
            raise
        except Exception as exc:
            original_failure.append(exc)
            raise
        result.setdefault('resolved_model', context.model)
        if getattr(options, 'semantic_initial_repair', None) is not None:
            result['semantic_stage_receipt'] = {'stage': stage, 'state_path': str(context.attempt_dir.parent / 'route-state.json'),
                'attempt_id': context.attempt_id, 'model': context.model}
        return result
    try:
        result = routes.run_unit(song_dir / '.transcription/pipeline/stage-routes',
            song_dir.name + ':semantic-' + stage, identity, run, validate,
            deadline_at=min(deadlines), base_model=base_model, pro_model=pro_model)
    except routes.UnitUnresolved:
        # The route durably records the failed attempt; preserve the precise
        # originating integration/baseline error instead of hiding its cause.
        if original_failure:
            raise original_failure[-1]
        raise
    errors = validate(copy.deepcopy(result))
    if errors:
        raise RuntimeError('accepted semantic stage violates current contract: ' + str(errors[:3]))
    if stage == 'writer':
        result = copy.deepcopy(result)
        result['writer_route_state'] = str(routes.unit_state_path(song_dir / '.transcription/pipeline/stage-routes',
            song_dir.name + ':semantic-' + stage, identity, base_model=base_model, pro_model=pro_model))
    return result


def routed_gloss(pipeline, song_dir, audited, options):
    if not stage_routes_enabled(options):
        return pipeline.gloss(song_dir, audited, options)
    import bhakti_model_routes as routes
    lines = audited['packet']['verified_lines']
    languages = audited['packet'].get('metadata', {}).get('languages')
    # Validation of corpus bytes remains before the first paid stage.
    pipeline.bhakti_lexical_producer.configuration_identity(options)
    policy = pipeline.semantic_stage_policy(options, stage='gloss')
    feedback = getattr(options, 'semantic_repair_feedback', [])
    repairing = any(issue['kind'] in {'gloss_sense', 'frame_relation'} for issue in feedback)
    base_model = (getattr(options, 'pro_model', routes.PRO_MODEL)
                  if repairing and getattr(options, 'semantic_stage_escalation', True)
                  and not (getattr(options, 'semantic_initial_repair', None) is not None
                           and getattr(options, 'semantic_review_generation', 0) == 0) else options.model)
    def validate(result):
        errors = pipeline.fresh_gloss_contract_errors(lines, result.get('packet', {}).get('glosses', []), languages)
        return [{'kind': 'source_gloss_contract', 'detail': error} for error in errors]
    return semantic_stage_route(pipeline, song_dir, 'gloss',
        {'lines': lines, 'languages': languages, 'policy': policy}, options,
        lambda directory, local: pipeline.gloss(directory, audited, local), validate, base_model=base_model)


def routed_translation(pipeline, song_dir, audited, glosses, job, options):
    if not stage_routes_enabled(options):
        return pipeline.translate(song_dir, audited, glosses, job, options, candidate_only=True)
    import bhakti_model_routes as routes
    lines = audited['packet']['verified_lines']
    view_options, view_glosses = pipeline.bhakti_lexical_producer.prepare_translation(song_dir, audited, glosses, options)
    inputs = {'audited': audited, 'glosses': glosses, 'provided': pipeline.supplied_translation(job),
              'policy': pipeline.semantic_stage_policy(view_options),
              'automatic_evidence_receipt': pipeline.automatic_evidence_receipt(view_options)}
    feedback = getattr(options, 'semantic_repair_feedback', [])
    english_repair = any(issue['kind'] in {'english_realization', 'english_mapping'} for issue in feedback)
    source_repair = any(issue['kind'] in {'gloss_sense', 'frame_relation'} for issue in feedback)
    base_model = (getattr(options, 'pro_model', routes.PRO_MODEL) if english_repair and not source_repair
                  and getattr(options, 'semantic_stage_escalation', True)
                  and not (getattr(options, 'semantic_initial_repair', None) is not None
                           and getattr(options, 'semantic_review_generation', 0) == 0) else options.model)
    def validate_writer(result):
        if 'writer_diagnostics' in result:
            return result['quality_issues']
        errors = pipeline.translation_draft_contract_errors(lines, glosses['packet']['glosses'],
            result.get('packet', {}).get('translations', []))
        errors += derived_support_errors(pipeline, song_dir, audited, glosses, result, options)
        return [{'kind': 'english_contract', 'detail': error} for error in errors]
    writer = semantic_stage_route(pipeline, song_dir, 'writer', {**inputs, 'draft_contract_version': 1}, options,
        lambda directory, local: pipeline.translate(directory, audited, glosses, job, local,
                                                     candidate_only=True, defer_review=True),
        validate_writer, base_model=base_model)
    def validate_review(result):
        errors = pipeline.translation_review_contract_errors(lines, glosses['packet']['glosses'],
            result.get('packet', {}).get('translations', []), **pipeline.translation_packet_contract_kwargs(
                lines, result, options, performance_order=audited['packet'].get('performance_order', [])))
        if writer_rows(result['packet']['translations']) != writer_rows(writer['packet']['translations']):
            errors.append('review changed writer evidence')
        return [{'kind': 'review_contract', 'detail': error} for error in errors]
    return semantic_stage_route(pipeline, song_dir, 'review', {**inputs, 'writer': writer, **pipeline.review_task_identity()}, options,
        lambda directory, local: pipeline.review_translation(directory, audited, glosses, job, local, writer),
        validate_review)


class SemanticQualityHold(RuntimeError):
    """A retained, valid semantic judgment; says nothing about spend settlement."""
    def __init__(self, reason, issues, evidence):
        self.reason = reason
        self.issues = copy.deepcopy(issues)
        self.evidence = copy.deepcopy(evidence)
        self.candidate_path = evidence['candidate']['path']
        super().__init__(reason)


def quality_hold(pipeline, reason, issues, audited, glosses, candidate, directory):
    evidence = {}
    for name, value in (('audited_source', audited), ('gloss', glosses), ('candidate', candidate)):
        path = directory / ('held-' + name + '.json')
        pipeline.semantic_write_json(path, value)
        evidence[name] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    return SemanticQualityHold(reason, issues, evidence)


def restore_quality_hold(pipeline, value):
    evidence = value.get('evidence', {})
    loaded = {}
    for name in ('audited_source', 'gloss', 'candidate'):
        record = evidence.get(name, {})
        path = Path(record.get('path', ''))
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != record.get('sha256'):
            raise RuntimeError('held semantic evidence hash mismatch')
        artifact = pipeline.read_packet(path)
        if not artifact:
            raise RuntimeError('held semantic evidence is not a valid packet')
        loaded[name] = artifact
    errors = issue_errors(loaded['audited_source']['packet']['verified_lines'],
                          loaded['gloss']['packet']['glosses'], value.get('issues'))
    if errors:
        raise RuntimeError('held semantic issues invalid: ' + str(errors[:3]))
    return SemanticQualityHold(value['reason'], value['issues'], evidence)


def initial_repair_context(pipeline, options, lines, languages):
    """Authenticate a current-reader repair scope, never a generated-stage seed."""
    value = getattr(options, 'semantic_initial_repair', None)
    if value is None:
        return None
    import bhakti_library_pass as library
    import bhakti_candidate_guard as guard
    if (not isinstance(value, dict) or value.get('version') != 1
            or set(value) != {'version', 'reader_digest', 'dependency_fingerprint',
                              'original_reader', 'pre_review', 'target_line_ids', 'gloss_word_indices'}):
        raise RuntimeError('invalid initial reader repair context')
    reader, pre = value['original_reader'], value['pre_review']
    original_lines, original_glosses, _ = library.reader_evidence(reader)
    if digest(reader) != value['reader_digest']:
        raise RuntimeError('initial reader repair digest changed')
    errors = library.current_review_errors(pre, original_lines, original_glosses,
        value['reader_digest'], value['dependency_fingerprint'])
    if errors:
        raise RuntimeError('initial reader review is invalid: ' + str(errors[:3]))
    snapshot = pre.get('finding_snapshot')
    if snapshot is not None:
        context = dict(lines=original_lines, glosses=original_glosses,
            reader_digest=value['reader_digest'], dependency_fingerprint=value['dependency_fingerprint'])
        snapshot = library.finding_store.validate_snapshot(snapshot, **context)
        if pre.get('finding_journal_path'):
            current = library.finding_store.load_snapshot(Path(pre['finding_journal_path']), **context)
            if current != snapshot:
                raise RuntimeError('initial reader finding journal changed')
        guard.authorize_semantic_candidate(reader, reader, source_lines=original_lines,
            gloss_rows=original_glosses, pre_review=pre, post_review=None,
            dependency_fingerprint=value['dependency_fingerprint'], finding_snapshot=snapshot,
            protected_english=getattr(options, 'semantic_baseline', None), allow_partial=True)
        findings = [f for f in snapshot['findings'] if f['kind'] == 'defect'
                    and f['issue']['kind'] != 'unresolved_evidence']
        issues = [f['issue'] for f in findings]
    else:
        findings = []
        issues = pre['issues']
    if not issues or any(issue['kind'] == 'unresolved_evidence' for issue in issues):
        raise RuntimeError('initial reader repair requires confirmed repairable issues')
    targets = {target for issue in issues for target in issue['target_line_ids']}
    expected_lines = [line for line in original_lines if line['id'] in targets]
    expected_indices = {}
    for issue in issues:
        if issue['kind'] in {'gloss_sense', 'frame_relation'}:
            for ref in issue['references']:
                if ref['line_id'] in issue['target_line_ids']:
                    expected_indices.setdefault(ref['line_id'], set()).update(ref['word_indices'])
    expected_indices = {key: sorted(indices) for key, indices in expected_indices.items()}
    if (lines != expected_lines or value['target_line_ids'] != [line['id'] for line in expected_lines]
            or value['gloss_word_indices'] != expected_indices
            or getattr(options, 'semantic_full_source', original_lines) != original_lines):
        raise RuntimeError('initial reader repair source or authorized scope changed')
    if getattr(options, 'semantic_confirmed_issues', issues) != issues:
        raise RuntimeError('initial reader repair feedback differs from authenticated review')
    if getattr(options, 'semantic_repair_findings', findings) != findings:
        raise RuntimeError('initial reader repair obligations changed')
    return {'context': copy.deepcopy(value), 'issues': copy.deepcopy(issues), 'findings': copy.deepcopy(findings)}


def project_initial_gloss(glosses, options):
    """Limit visible gloss edits before any writer/reviewer sees the result."""
    initial = getattr(options, 'semantic_initial_repair', None)
    if initial is None:
        return glosses
    result = copy.deepcopy(glosses)
    old = initial['original_reader']['SONG_LINES']
    for row in result['packet']['glosses']:
        words = old[row['id']]['words']
        if len(words) != len(row['word_glosses']):
            raise RuntimeError('initial reader repair changed word population')
        allowed = initial['gloss_word_indices'].get(row['id'], [])
        projected = []
        for index, word in enumerate(row['word_glosses']):
            if word['roman'] != words[index]['roman']:
                raise RuntimeError('initial reader repair changed source token')
            item = copy.deepcopy(words[index])
            if index in allowed:
                item['gloss'] = word['gloss']
            projected.append(item)
        row['word_glosses'] = projected
        row['grammar_note'] = old[row['id']].get('grammarNote', '')
    return result


def scoped_gloss_contract_errors(pipeline, lines, rows, languages, options):
    initial = getattr(options, 'semantic_initial_repair', None)
    if initial is None:
        return pipeline.fresh_gloss_contract_errors(lines, rows, languages)
    try:
        expected = project_initial_gloss({'packet': {'glosses': rows}}, options)['packet']['glosses']
    except (KeyError, TypeError, RuntimeError) as exc:
        return ['invalid original-reader gloss projection: ' + str(exc)]
    if expected != rows:
        return ['original-reader gloss exceeds authorized word/grammar scope']
    validated = copy.deepcopy(rows)
    original = initial['original_reader']['SONG_LINES']
    for row in validated:
        for index, word in enumerate(row['word_glosses']):
            old = original[row['id']]['words'][index]
            for key, default in (('concept_key', ''), ('preserve_in_english', False)):
                if key not in old and key not in word:
                    word[key] = default
    return pipeline.fresh_gloss_contract_errors(lines, validated, languages)


def outside_initial_scope(issues, options):
    initial = getattr(options, 'semantic_initial_repair', None)
    if initial is None:
        return []
    outside = []
    for issue in issues:
        if set(issue['target_line_ids']) - set(initial['target_line_ids']):
            outside.append(issue)
        elif issue['kind'] in {'gloss_sense', 'frame_relation'}:
            for ref in issue['references']:
                if (ref['line_id'] in issue['target_line_ids']
                        and set(ref['word_indices']) - set(initial['gloss_word_indices'].get(ref['line_id'], []))):
                    outside.append(issue)
                    break
    return outside


def complete(pipeline, song_dir, audited, job, options):
    packet_dir = song_dir / '.transcription/pipeline'
    state_path = packet_dir / 'semantic-repair-state.json'
    prior_state = pipeline.read_packet(state_path) or {}
    state = dict(prior_state)
    state['status'] = 'in-progress'
    new_run_claimed = False
    lines = audited.get('packet', {}).get('verified_lines', [])
    languages = audited.get('packet', {}).get('metadata', {}).get('languages')
    try:
        initial = initial_repair_context(pipeline, options, lines, languages)
        pipeline.bhakti_lexical_producer.requested_spans(options, lines)
        baseline = resolved_baseline(pipeline, song_dir, lines, job)
        options = pipeline.bhakti_translation_policy.prepare_naming_options(
            options, lines, languages, source_slug=job.get('slug'))
        support = pipeline.bhakti_lexical_support.prepare_options(options, lines, languages)
        evidence = source_evidence(pipeline, song_dir, audited)
        policy = pipeline.translation_policy_payload()
        naming_conventions = getattr(options, 'semantic_naming_conventions', None)
        if naming_conventions and naming_conventions.get('matches'):
            policy = {**policy, 'naming_conventions': naming_conventions}
        full_support = getattr(options, 'semantic_lexical_support', None)
        if full_support is not None:
            policy = {**policy, 'lexical_support': pipeline.bhakti_lexical_support.content_digest(full_support)}
        identity_inputs = {'version': VERSION, 'source_evidence': evidence, 'languages': languages,
                           'baseline': baseline, 'policy': policy,
                           'model': options.model, 'provider': pipeline.gemini.provider_name()}
        # Keep exact no-additional-evidence historical run identities. Explicit
        # reading evidence/overrides must bind acceptance before its early return.
        context = getattr(options, 'semantic_context_evidence', [])
        if context:
            identity_inputs['reading_context_evidence'] = context
        order = getattr(options, 'semantic_performance_order', evidence['performance_order'])
        if order != evidence['performance_order']:
            identity_inputs['reading_performance_order'] = order
        if initial is not None:
            identity_inputs['initial_reader_repair'] = initial['context']
        preautomatic_identity = digest(identity_inputs)
        automatic = pipeline.bhakti_lexical_producer.configuration_identity(options)
        glossary_inputs = copy.deepcopy(identity_inputs)
        if automatic is not None:
            identity_inputs['policy'] = {**policy, 'automatic_lexical': automatic}
            glossary_inputs['policy'] = {**policy, 'automatic_lexical':
                {key: automatic[key] for key in ('version', 'max_queries', 'source_discovery', 'requested_spans') if key in automatic}}
        if full_support is not None:
            glossary_inputs['policy']['lexical_support'] = pipeline.bhakti_lexical_support.content_digest(
                full_support, english_grammar=False)
        glossary_identity = digest(glossary_inputs)
        identity_inputs['policy'] = {**identity_inputs['policy'],
            **pipeline.bhakti_lexical_support.projection_policy(options)}
        if stage_routes_enabled(options):
            import bhakti_model_routes as routes
            escalation = getattr(options, 'semantic_stage_escalation', True)
            if type(escalation) is not bool:
                raise RuntimeError('semantic_stage_escalation must be boolean')
            identity_inputs['stage_routing'] = {'version': 1, 'escalation': escalation,
                'pro_model': getattr(options, 'pro_model', routes.PRO_MODEL)}
        content_configuration_run_id = digest(identity_inputs)
        if pipeline.REVIEW_TASK_VERSION >= 3:
            identity_inputs['review_context_identity'] = review_context_identity(lines, options, performance_order=evidence['performance_order'])
        identity_inputs.update(pipeline.review_task_identity())
        identity = digest(identity_inputs)
        configuration_run_id = identity
        revision_receipt = None
        prior_configuration = prior_state.get('configuration_run_id', prior_state.get('run_id'))
        if prior_configuration == configuration_run_id:
            if prior_state.get('status') == 'accepted':
                prior_gloss = pipeline.read_packet(packet_dir / '04-glosses.json')
                prior_translation = pipeline.read_packet(packet_dir / '05-translation.json')
                require_acceptance(pipeline, packet_dir, prior_gloss, prior_translation,
                                   audited=audited, accepted_state=prior_state)
                errors = scoped_gloss_contract_errors(pipeline, lines, prior_gloss['packet']['glosses'], languages, options)
                if errors:
                    raise RuntimeError('accepted source glossary violates contract: ' + str(errors[:3]))
                saved_receipt = pipeline.validate_automatic_evidence_receipt(
                    prior_translation.get('automatic_evidence_receipt', {}))
                view_options, _ = derived_support_view(pipeline, song_dir, audited, prior_gloss, prior_translation, options)
                current_receipt = pipeline.automatic_evidence_receipt(view_options)
                if current_receipt and not saved_receipt:
                    raise RuntimeError('accepted automatic evidence receipt missing')
                if current_receipt != saved_receipt:
                    revision_receipt = current_receipt
                    identity = digest({'configuration_run_id': configuration_run_id,
                                       'automatic_evidence_receipt': revision_receipt})
                else:
                    identity = prior_state['run_id']
                    revision_receipt = prior_state.get('automatic_evidence_receipt')
            elif 'automatic_evidence_receipt' in prior_state:
                revision_receipt = pipeline.validate_automatic_evidence_receipt(prior_state['automatic_evidence_receipt'])
                identity = digest({'configuration_run_id': configuration_run_id,
                                   'automatic_evidence_receipt': revision_receipt})
                if identity != prior_state.get('run_id'):
                    raise RuntimeError('automatic evidence revision identity mismatch')
        accepted_gloss = None
        accepted_gloss_receipt = None
        accepted_writer = None
        durable_seed = packet_dir / 'semantic-repair' / identity / 'adopted-seeds.json'
        if (prior_state.get('status') == 'accepted' and prior_state.get('run_id') != identity
                and not durable_seed.exists()):
            previous_manifest = pipeline.read_packet(packet_dir / 'semantic-acceptance.json') or {}
            if (previous_manifest.get('source_gloss_identity') == glossary_identity
                    or (automatic is not None and prior_state.get('content_configuration_run_id',
                        prior_state.get('run_id')) == preautomatic_identity)):
                previous_gloss = pipeline.read_packet(packet_dir / '04-glosses.json')
                previous_translation = pipeline.read_packet(packet_dir / '05-translation.json')
                # Verify the old pair before moving the required marker to the new run.
                require_acceptance(pipeline, packet_dir, previous_gloss, previous_translation,
                                   audited=audited, accepted_state=prior_state)
                accepted_gloss_receipt = {'source_gloss_identity': glossary_identity,
                    'prior_run_id': prior_state['run_id'], 'manifest': previous_manifest,
                    'automatic_lexical_feedback': copy.deepcopy(previous_translation.get('automatic_lexical_feedback', []))}
                accepted_gloss = validated_gloss_seed(pipeline, previous_gloss, accepted_gloss_receipt,
                    digest(evidence), glossary_identity, lines, languages, options)
                prior_content = prior_state.get('content_configuration_run_id', prior_configuration)
                if prior_content == content_configuration_run_id:
                    view_options, _ = derived_support_view(pipeline, song_dir, audited, previous_gloss,
                                                           previous_translation, options)
                    current_receipt = pipeline.automatic_evidence_receipt(view_options)
                    saved_receipt = pipeline.validate_automatic_evidence_receipt(
                        previous_translation.get('automatic_evidence_receipt', {}))
                    if current_receipt == saved_receipt:
                        accepted_gloss_receipt['review_only'] = {
                            'content_configuration_run_id': content_configuration_run_id,
                            'automatic_evidence_receipt': current_receipt}
                        validated_review_seed(pipeline, song_dir, audited, previous_gloss, previous_translation,
                            accepted_gloss_receipt, content_configuration_run_id, options, baseline)
                        accepted_writer = copy.deepcopy(previous_translation)
        if prior_state.get('run_id') == identity:
            state = dict(prior_state)
            if state.get('status') == 'blocked':
                if state.get('quality_hold'):
                    raise restore_quality_hold(pipeline, state['quality_hold'])
                raise RuntimeError(state.get('reason', 'semantic repair blocked'))
        else:
            if (prior_state.get('status') in {'blocked', 'in-progress'}
                    and prior_state.get('content_configuration_run_id', prior_configuration) == content_configuration_run_id
                    and prior_state.get('review_task_version', 0) != pipeline.REVIEW_TASK_VERSION):
                raise RuntimeError('prior unfinished semantic task requires explicit reconciliation')
            seconds = float(getattr(options, 'semantic_repair_seconds', 600))
            if not math.isfinite(seconds) or seconds <= 0:
                raise RuntimeError('invalid semantic repair deadline')
            state = {'version': VERSION, 'run_id': identity, 'status': 'in-progress',
                     'configuration_run_id': configuration_run_id,
                     'content_configuration_run_id': content_configuration_run_id, **pipeline.review_task_identity(),
                     'rounds_used': 0, 'deadline_at_epoch': min([time.time() + seconds] +
                         [float(getattr(options, key)) for key in ('unit_deadline_at', 'semantic_deadline_at')
                          if getattr(options, key, None) is not None])}
            if initial is not None:
                state['feedback'] = copy.deepcopy(initial['issues'])
            if revision_receipt is not None:
                state['automatic_evidence_receipt'] = copy.deepcopy(revision_receipt)
        local = copy.copy(options)
        local.semantic_coordinator_acceptance = str(packet_dir / 'semantic-acceptance.json')
        local.force = False  # A force rerun cannot reset this run's paid history.
        local.semantic_deadline_at = state['deadline_at_epoch']
        local.semantic_full_source = copy.deepcopy(getattr(options, 'semantic_full_source', lines))
        local.semantic_performance_order = order
        local.semantic_source_identity = getattr(options, 'semantic_source_identity', digest(evidence))
        local.semantic_baseline = baseline
        if accepted_gloss is not None:
            # Persist the validated prior glossary before either mutable marker
            # can stop identifying the old accepted pair. Resume rechecks receipt.
            payload = {'run_id': identity, 'artifacts': {'04-glosses.json': accepted_gloss},
                       'accepted_gloss_receipt': accepted_gloss_receipt}
            if accepted_writer is not None:
                payload['artifacts']['05-translation.json'] = accepted_writer
            pipeline.semantic_write_json(durable_seed, {'payload': payload, 'sha256': digest(payload)})
        marker = {'version': VERSION, 'run_id': identity}
        pipeline.semantic_write_json(packet_dir / 'semantic-repair-required.json', marker)
        if state.get('status') == 'accepted':
            glosses = pipeline.read_packet(packet_dir / '04-glosses.json')
            translations = pipeline.read_packet(packet_dir / '05-translation.json')
            require_acceptance(pipeline, packet_dir, glosses, translations, audited=audited, accepted_state=state)
            errors = scoped_gloss_contract_errors(pipeline, lines, glosses['packet']['glosses'], languages, options)
            errors += pipeline.fresh_translation_contract_errors(lines, glosses['packet']['glosses'], translations['packet']['translations'], **pipeline.translation_packet_contract_kwargs(lines, translations, local, performance_order=order))
            errors += derived_support_errors(pipeline, song_dir, audited, glosses, translations, options)
            if errors: raise RuntimeError('accepted semantic cache violates contract: ' + str(errors[:3]))
            pipeline.semantic_write_json(state_path, state)
            return glosses, translations
        state['status'] = 'in-progress'
        pipeline.semantic_write_json(state_path, state)
        new_run_claimed = True
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
            receipt = payload.get('accepted_gloss_receipt')
            if receipt is not None:
                seed_gloss = validated_gloss_seed(pipeline, snapshots.get('04-glosses.json'), receipt,
                    digest(evidence), glossary_identity, lines, languages, options)
                seed_translation = (validated_review_seed(pipeline, song_dir, audited, seed_gloss,
                    snapshots.get('05-translation.json'), receipt, content_configuration_run_id, options, baseline)
                    if receipt.get('review_only') else None)
            else:
                seed_gloss, seed_translation = reusable_prior_stages(
                    pipeline, packet_dir, lines, languages, job, options, evidence, snapshots=snapshots)
            if snapshots.get('04-glosses.json') is not None and seed_gloss is None:
                raise RuntimeError('adopted gloss no longer satisfies exact input contract')
            if any(snapshots.get(name) for name in ('05-translation.json', 'translation-candidate.json')) and seed_translation is None:
                raise RuntimeError('adopted translation no longer satisfies exact input contract')
        else:
            if accepted_gloss is not None:
                seed_gloss, seed_translation = accepted_gloss, None
            else:
                seed_gloss, seed_translation = reusable_prior_stages(
                    pipeline, packet_dir, lines, languages, job, options, evidence)
            snapshots = {'04-glosses.json': seed_gloss}
            if seed_translation:
                snapshots[seed_translation['semantic_adoption']['path']] = seed_translation
            payload = {'run_id': identity, 'artifacts': snapshots}
            if accepted_gloss_receipt is not None:
                payload['accepted_gloss_receipt'] = accepted_gloss_receipt
            pipeline.semantic_write_json(seed_path, {'payload': payload, 'sha256': digest(payload)})
        # Retained lookup obligations are not renewed translation objections.
        local.automatic_lexical_feedback = copy.deepcopy(payload.get('accepted_gloss_receipt', {}).get('automatic_lexical_feedback', []))
        if revision_receipt is not None:
            if seed_gloss is None:
                raise RuntimeError('automatic evidence revision lacks validated glossary seed')
            view_options, _ = derived_support_view(pipeline, song_dir, audited, seed_gloss,
                {'automatic_lexical_feedback': local.automatic_lexical_feedback}, local)
            if pipeline.automatic_evidence_receipt(view_options) != revision_receipt:
                raise RuntimeError('automatic evidence changed during interrupted revision')
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
                if automatic is not None:
                    inherited = previous_translation.get('automatic_lexical_feedback')
                    invalid = issue_errors(lines, previous_gloss['packet']['glosses'], inherited)
                    if invalid:
                        raise RuntimeError('repair predecessor lookup requirements invalid: ' + str(invalid[:3]))
                    local.automatic_lexical_feedback = copy.deepcopy(inherited)
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
                errors = scoped_gloss_contract_errors(pipeline, lines, glosses['packet']['glosses'], languages, options)
                if errors: raise RuntimeError('repaired gloss cache violates contract: ' + str(errors[:3]))
            else:
                lexical_targets = set(item for issue in feedback if issue['kind'] in {'gloss_sense', 'frame_relation'}
                                      for item in issue['target_line_ids'])
                if number and not lexical_targets:
                    glosses = copy.deepcopy(previous_gloss)
                elif number:
                    subset = copy.deepcopy(audited)
                    subset['packet']['verified_lines'] = [row for row in lines if row['id'] in lexical_targets]
                    repaired = routed_gloss(pipeline, round_dir, subset, local)
                    by_id = {row['id']: row for row in repaired['packet']['glosses']}
                    glosses = copy.deepcopy(previous_gloss)
                    glosses['packet']['glosses'] = [by_id.get(row['id'], row) for row in previous_gloss['packet']['glosses']]
                    producing = dict(glosses.get('producing_models_by_line',
                        {row['id']: glosses.get('resolved_model', local.model) for row in previous_gloss['packet']['glosses']}))
                    producing.update({line_id: repaired.get('resolved_model', local.model) for line_id in by_id})
                    glosses['producing_models_by_line'] = producing
                    glosses['resolved_model'] = next(iter(set(producing.values()))) if len(set(producing.values())) == 1 else 'mixed'
                    glosses.setdefault('repair_responses', []).append(copy.deepcopy(repaired))
                    glosses['producer_fingerprint'] = digest({'glosses': glosses['packet'], 'producing_models': producing,
                        'prior': previous_gloss.get('producer_fingerprint', previous_gloss.get('fingerprint')),
                        'repair': repaired.get('fingerprint')})
                else:
                    glosses = seed_gloss or routed_gloss(pipeline, round_dir, audited, local)
                unprojected = copy.deepcopy(glosses)
                glosses = project_initial_gloss(glosses, local)
                if glosses != unprojected:
                    glosses['producer_fingerprint'] = digest({'source_producer': unprojected.get('producer_fingerprint', unprojected.get('fingerprint')),
                        'projected_packet': glosses['packet'], 'scope': local.semantic_initial_repair})
                glosses.setdefault('producer_fingerprint', glosses.get('fingerprint'))
                glosses['semantic_request_identity'] = expected_gloss_identity
                errors = scoped_gloss_contract_errors(pipeline, lines, glosses['packet']['glosses'], languages, options)
                if errors: raise RuntimeError('gloss_contract_hold: ' + str(errors[:3]))
                pipeline.semantic_write_json(ready_path, glosses)
            lookup_feedback = []
            translation_inputs = {'run': identity, 'round': number, 'gloss': glosses,
                                  'feedback': feedback, 'previous_translation': previous_translation}
            if automatic is not None:
                # Requirements survive resolved objections and are checkpointed
                # with the candidate, before the next round can be claimed.
                lookup_feedback = copy.deepcopy(list({digest(item): item for item in
                    local.automatic_lexical_feedback + feedback}.values()))
                invalid = issue_errors(lines, glosses['packet']['glosses'], lookup_feedback)
                if invalid:
                    raise RuntimeError('lexical lookup requirements invalid: ' + str(invalid[:3]))
                translation_inputs['automatic_lexical_feedback'] = lookup_feedback
            translation_path = round_dir / 'translation-ready.json'
            translations = pipeline.read_packet(translation_path)
            expected_translation_identity = digest(translation_inputs)
            if translations and translations.get('semantic_request_identity') != expected_translation_identity:
                raise RuntimeError('translation cache identity mismatch')
            if translations and automatic is not None and translations.get('automatic_lexical_feedback') != lookup_feedback:
                raise RuntimeError('translation cache lookup requirements mismatch')
            if not translations and number == 0 and seed_translation and seed_translation.get('semantic_adoption', {}).get('accepted'):
                translations = seed_translation
                translations['semantic_request_identity'] = expected_translation_identity
                if automatic is not None:
                    translations['automatic_lexical_feedback'] = copy.deepcopy(lookup_feedback)
                pipeline.semantic_write_json(translation_path, translations)
            if not translations:
                local.semantic_seed_translation = seed_translation if number == 0 else None
                local.semantic_translation_targets = sorted(set(item for issue in feedback for item in issue['target_line_ids'])) if number else None
                local.semantic_previous_translations = previous_translation['packet']['translations'] if number else None
                local.semantic_previous_writer_context = previous_translation.get('writer_review_context') if number else None
                translations = routed_translation(pipeline, round_dir, audited, glosses, job, local)
                translations['semantic_request_identity'] = expected_translation_identity
                if automatic is not None:
                    translations['automatic_lexical_feedback'] = copy.deepcopy(lookup_feedback)
                pipeline.semantic_write_json(translation_path, translations)
            rows = translations['packet']['translations']
            assert_baseline(baseline, rows)
            errors = pipeline.fresh_translation_contract_errors(lines, glosses['packet']['glosses'], rows, **pipeline.translation_packet_contract_kwargs(lines, translations, local, performance_order=order))
            errors += derived_support_errors(pipeline, round_dir, audited, glosses, translations, local)
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
            if automatic is not None:
                discovery_options, _ = pipeline.bhakti_lexical_producer.prepare_translation(
                    round_dir, audited, glosses, local)
                issues.extend(pipeline.bhakti_source_discovery.repair_issues(
                    getattr(discovery_options, 'automatic_source_discovery', None), lines, rows))
            invalid = issue_errors(lines, glosses['packet']['glosses'], issues)
            if invalid: raise RuntimeError('invalid_repair_feedback: ' + str(invalid[:3]))
            outside = outside_initial_scope(issues, local)
            if outside:
                pipeline.semantic_write_json(packet_dir / 'additional-repair-findings.json', {
                    'version': 1, 'status': 'needs-expanded-confirmed-scope', 'run_id': identity,
                    'source_identity': digest(evidence), 'issues': outside,
                    'initial_repair_identity': digest(local.semantic_initial_repair),
                    'deadline_at_epoch': state['deadline_at_epoch']})
                raise quality_hold(pipeline, 'additional_confirmed_scope_required', issues, audited, glosses, translations, round_dir)
            if not errors and not issues:
                # New metadata is outside the candidate packet; linguistic
                # evidence and supplied English remain unchanged.
                glosses['semantic_repair_version'] = VERSION; glosses['semantic_run_id'] = identity
                glosses['fingerprint'] = digest({'unconditioned': glosses.get('fingerprint'), 'request': glosses['semantic_request_identity'], 'run': identity})
                translations['semantic_repair_version'] = VERSION; translations['semantic_run_id'] = identity
                translations['source_context_sha256'] = digest(evidence)
                if pipeline.REVIEW_TASK_VERSION >= 3:
                    translations['coordinator_acceptance'] = str(packet_dir / 'semantic-acceptance.json')
                pipeline.semantic_write_json(packet_dir / '04-glosses.json', glosses)
                pipeline.semantic_write_json(packet_dir / '05-translation.json', translations)
                pipeline.semantic_write_json(packet_dir / 'semantic-acceptance.json', {
                    'version': VERSION, 'status': 'accepted', 'run_id': identity,
                    'gloss_sha256': digest(glosses), 'translation_sha256': digest(translations),
                    'source_sha256': digest(evidence), 'source_gloss_identity': glossary_identity,
                    'content_configuration_run_id': content_configuration_run_id, **pipeline.review_task_identity()})
                state['status'] = 'accepted'; state.pop('reason', None)
                if pipeline.REVIEW_TASK_VERSION >= 3:
                    state['writer_closure_sha256'] = writer_closure(translations)
                pipeline.semantic_write_json(state_path, state)
                return glosses, translations
            for issue in issues:
                if issue['kind'] == 'unresolved_evidence':
                    raise quality_hold(pipeline, issue['hold_reason'], issues, audited, glosses, translations, round_dir)
            if not issues: raise RuntimeError('semantic_contract_hold: ' + str(errors[:3]))
            if number >= maximum:
                raise quality_hold(pipeline, 'repair_limit_exhausted', issues, audited, glosses, translations, round_dir)
            if not _bounded_ready(): raise RuntimeError('repair_budget_required')
            candidate_hash = digest({'glosses': glosses['packet'], 'translations': [
                {key: value for key, value in row.items() if key != 'independent_review'} for row in rows]})
            if candidate_hash in state.get('candidate_hashes', []): raise RuntimeError('no_progress')
            state.setdefault('candidate_hashes', []).append(candidate_hash)
            state['feedback'] = issues
            state['rounds_used'] = number + 1
            pipeline.semantic_write_json(state_path, state)
    except Exception as exc:
        # A failed read-only preflight must not destroy valid prior acceptance.
        # Its files are revalidated on every retry; restored evidence can resume.
        if prior_state.get('status') == 'accepted' and not new_run_claimed:
            raise
        state['status'] = 'blocked'; state['reason'] = str(exc)
        if isinstance(exc, SemanticQualityHold):
            state['quality_hold'] = {'reason': exc.reason, 'issues': exc.issues, 'evidence': exc.evidence}
        pipeline.semantic_write_json(state_path, state)
        raise

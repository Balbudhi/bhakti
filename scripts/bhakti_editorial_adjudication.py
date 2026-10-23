"""Apply an explicit source-bound editorial decision to an immutable saved primary.

Hashes bind evidence, not linguistic truth. The supplied decision is an editorial
act; this helper neither picks a translation nor retries a failed model attempt.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile

VERSION = 1


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_digest(value):
    return hashlib.sha256(value).hexdigest()


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('duplicate editorial evidence key')
        result[key] = value
    return result


def _read(path):
    try:
        raw = Path(path).read_bytes()
        value = json.loads(raw, object_pairs_hook=_object)
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError('cannot read complete editorial evidence') from exc
    if not isinstance(value, dict): raise ValueError('editorial evidence must be an object')
    return raw, value


def _atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                prefix='.editorial-', delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary: temporary.unlink(missing_ok=True)


def _clear(value):
    return isinstance(value, str) and value.strip().casefold() in {'', 'none', 'no', 'null', 'n/a'}


def recover_editorial_candidate(record_path, *, unit_id, input_fingerprint,
        dependency_fingerprint, source_evidence, policy_payload, validate_candidate, output_dir):
    """Return candidate/receipt after exact binding and the caller's fresh contract.

    Only two review-choice flags may differ. Failed route state, raw candidate,
    reviewer responses, wording, source, glosses and alternatives remain intact.
    The output receipt records an editorial resolution, not a new model review.
    """
    record_path = Path(record_path)
    record_bytes, record = _read(record_path)
    required = {'version': VERSION, 'decision_kind': 'retain_existing_primary',
        'unit_id': unit_id, 'input_fingerprint': input_fingerprint,
        'dependency_fingerprint': dependency_fingerprint,
        'source_digest': digest(source_evidence), 'policy_digest': digest(policy_payload)}
    if any(record.get(key) != value for key, value in required.items()):
        raise ValueError('editorial decision differs from current unit/source/policy')
    if type(record.get('version')) is not int or not callable(validate_candidate):
        raise ValueError('invalid editorial decision version or validator')
    if any(not isinstance(record.get(key), str) or not record[key].strip()
           for key in ('reviewer', 'rationale', 'line_id', 'attempt_id', 'candidate_path', 'route_state_path')):
        raise ValueError('editorial decision lacks explicit reviewer, rationale or evidence identity')
    candidate_path, state_path = Path(record['candidate_path']), Path(record['route_state_path'])
    candidate_bytes, candidate = _read(candidate_path)
    state_bytes, state = _read(state_path)
    if (record.get('candidate_file_sha256') != file_digest(candidate_bytes)
            or record.get('candidate_digest') != digest(candidate)
            or record.get('route_state_sha256') != file_digest(state_bytes)):
        raise ValueError('saved editorial evidence changed')
    if state.get('status') != 'unresolved' or any(state.get(key) != required[key]
            for key in ('unit_id', 'input_fingerprint', 'dependency_fingerprint')):
        raise ValueError('editorial decision requires the exact unresolved unit')
    attempts = state.get('attempts')
    if not isinstance(attempts, list) or any(not isinstance(row, dict) for row in attempts):
        raise ValueError('invalid failed attempt evidence')
    matching = [(index, row) for index, row in enumerate(attempts) if row.get('attempt_id') == record['attempt_id']]
    if len(matching) != 1 or matching[0][0] not in (0, 1) or matching[0][1].get('status') != 'quality-failed':
        raise ValueError('decision does not name one completed quality-failed attempt')
    index, attempt = matching[0]
    expected_path = state_path.resolve().parent / ('flash' if index == 0 else 'pro') / 'candidate.json'
    if candidate_path.resolve() != expected_path:
        raise ValueError('candidate is not from the named route attempt')
    output_dir = Path(output_dir)
    originals = (record_path.resolve(), candidate_path.resolve(), state_path.resolve())
    output_paths = (output_dir / 'accepted-candidate.json', output_dir / 'receipt.json')
    if any(path.resolve() in originals for path in output_paths):
        raise ValueError('editorial output would overwrite original evidence')
    try:
        rows = candidate['translations']['packet']['translations']
        glosses = candidate['glosses']['packet']['glosses']
        matched = [row for row in rows if row.get('id') == record['line_id']]
        matched_glosses = [row for row in glosses if row.get('id') == record['line_id']]
        targets = source_evidence['targets']; sources = source_evidence['source']
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('incomplete original candidate/source evidence') from exc
    if len(matched) != 1 or len(matched_glosses) != 1 or sum(row.get('id') == record['line_id'] for row in targets) != 1:
        raise ValueError('decision target is not one exact fresh source row')
    row, gloss = matched[0], matched_glosses[0]
    if (record.get('original_row_digest') != digest(row)
            or record.get('selected_literal_english') != row.get('literal_english')):
        raise ValueError('decision must retain the exact existing primary row')
    expected_flags = record.get('expected_flags')
    flag_keys = {'translation_human_review_recommended', 'independent_human_review_recommended'}
    if not isinstance(expected_flags, dict) or set(expected_flags) != flag_keys or any(value is not True for value in expected_flags.values()):
        raise ValueError('decision must name the two literal true choice flags')
    review, fidelity = row.get('independent_review'), row.get('fidelity')
    if not isinstance(review, dict) or not isinstance(fidelity, dict):
        raise ValueError('missing independent review or fidelity evidence')
    if row.get('human_review_recommended') is not True or review.get('human_review_recommended') is not True:
        raise ValueError('original choice flags are not literal true')
    if (any(fidelity.get(key) is not True for key in ('agency_and_image_preserved', 'all_meaning_accounted_for'))
            or any(review.get(key) is not True for key in ('passes', 'agency_preserved', 'imagery_preserved', 'all_meaning_accounted_for'))
            or fidelity.get('unsupported_additions') != [] or review.get('unsupported_additions') != []
            or review.get('issues') != [] or not _clear(row.get('uncertainty')) or not _clear(gloss.get('uncertainty'))):
        raise ValueError('editorial choice cannot override failed fidelity or unresolved evidence')
    alternatives = row.get('material_alternatives')
    if (not isinstance(review.get('material_choice'), str) or not review['material_choice'].strip()
            or not isinstance(alternatives, list) or not alternatives
            or any(not isinstance(value, str) or not value.strip() for value in alternatives)):
        raise ValueError('original candidate lacks a documented material choice')
    references = record.get('source_references'); by_id = {line['id']: line for line in sources}
    if not isinstance(references, list) or not references:
        raise ValueError('editorial decision lacks source references')
    for ref in references:
        if (not isinstance(ref, dict) or ref.get('line_id') not in by_id
                or not isinstance(ref.get('source_quote'), str) or not ref['source_quote'].strip()
                or ref['source_quote'] not in by_id[ref['line_id']].get('source_text', '')):
            raise ValueError('editorial decision source quotation is not exact')
    if record['line_id'] not in [ref['line_id'] for ref in references]:
        raise ValueError('editorial decision must reference its target source')
    effective = copy.deepcopy(candidate)
    target = next(value for value in effective['translations']['packet']['translations'] if value['id'] == record['line_id'])
    target['human_review_recommended'] = False
    target['independent_review']['human_review_recommended'] = False
    result_digest = digest(effective)
    if record.get('expected_result_digest') != result_digest:
        raise ValueError('effective editorial result differs from approved exact changes')
    errors = validate_candidate(effective)
    if digest(effective) != result_digest:
        raise ValueError('candidate validator changed the approved artifact')
    if not isinstance(errors, list) or errors:
        raise ValueError('editorial candidate still violates fresh contract: ' + str(errors))
    receipt = {**required, 'decision_digest': digest(record), 'attempt_id': record['attempt_id'],
        'reviewer': record['reviewer'], 'rationale': record['rationale'], 'source_references': references,
        'candidate_file_sha256': file_digest(candidate_bytes), 'candidate_digest': digest(candidate),
        'route_state_sha256': file_digest(state_bytes), 'original_row_digest': digest(row),
        'result_digest': result_digest, 'effective_changes': [
            {'line_id': record['line_id'], 'field': 'human_review_recommended', 'before': True, 'after': False},
            {'line_id': record['line_id'], 'field': 'independent_review.human_review_recommended', 'before': True, 'after': False}]}
    # No original evidence or decision may change during validation.
    if (record_path.read_bytes() != record_bytes or candidate_path.read_bytes() != candidate_bytes
            or state_path.read_bytes() != state_bytes or digest(source_evidence) != required['source_digest']
            or digest(policy_payload) != required['policy_digest']):
        raise ValueError('editorial inputs changed during validation')
    if any(path.exists() for path in output_paths):
        if not all(path.is_file() for path in output_paths): raise ValueError('incomplete prior editorial receipt')
        if _read(output_paths[0])[1] != effective or _read(output_paths[1])[1] != receipt:
            raise ValueError('saved editorial result or receipt changed')
    else:
        _atomic(output_paths[0], effective)
        _atomic(output_paths[1], receipt)
    return {'candidate': effective, 'receipt': receipt}

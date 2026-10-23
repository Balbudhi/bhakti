"""Retain source-linked audit observations; a finding is not edit permission.

One active song runner owns a journal. Its immutable reviews bind one exact
reader/dependency/source/gloss context. Appends are atomic; prior findings are
never dismissed by a later review. Classification checks structure, not linguistic
truth or quote-to-token correspondence (the mutation gate must check the latter).
"""
from __future__ import annotations

import copy
from collections import Counter
import json
from pathlib import Path

from bhakti_semantic_repair import atomic_write, digest, issue_errors

VERSION = 1
_FIDELITY = ('passes', 'agency_preserved', 'imagery_preserved', 'all_meaning_accounted_for')
_FLAGS = (*_FIDELITY, 'human_review_recommended')


def _context_identity(lines, glosses, reader_digest, dependency_fingerprint):
    if any(not isinstance(value, str) or not value.strip()
           for value in (reader_digest, dependency_fingerprint)):
        raise ValueError('review requires reader and dependency identities')
    ids = []
    for rows, label in ((lines, 'source'), (glosses, 'gloss')):
        if (not isinstance(rows, list) or not rows
                or any(not isinstance(row, dict) or not isinstance(row.get('id'), str)
                       or not row['id'] for row in rows)):
            raise ValueError(f'invalid {label} context')
        row_ids = [row['id'] for row in rows]
        if len(row_ids) != len(set(row_ids)):
            raise ValueError(f'duplicate {label} context IDs')
        if not ids:
            ids = row_ids
        elif row_ids != ids:
            raise ValueError('source/gloss context population or order differs')
    if any(not isinstance(row.get('source_text'), str) for row in lines):
        raise ValueError('source text missing from context')
    if any(not isinstance(row.get('word_glosses'), list)
           or any(not isinstance(word, dict) for word in row['word_glosses']) for row in glosses):
        raise ValueError('gloss words missing from context')
    return {'version': VERSION, 'reader_digest': reader_digest,
            'dependency_fingerprint': dependency_fingerprint,
            'context_digest': digest({'lines': lines, 'glosses': glosses})}


def _classify_rows(artifact, *, lines, glosses, reader_digest, dependency_fingerprint,
                   expected_review_ids=None):
    """Classify each unambiguous row; malformed siblings do not erase findings.

    A mismatched envelope cannot be adopted at all and raises ValueError. Row and
    population defects are returned as contract_errors alongside valid unrelated
    observations. No inputs or review flags are rewritten.
    """
    _context_identity(lines, glosses, reader_digest, dependency_fingerprint)
    if (not isinstance(artifact, dict) or artifact.get('reader_digest') != reader_digest
            or artifact.get('dependency_fingerprint') != dependency_fingerprint
            or not isinstance(artifact.get('attempt_id'), str) or not artifact['attempt_id'].strip()):
        raise ValueError('current review input identity mismatch')
    errors = []; findings = []; observations = []
    response_errors = artifact.get('response_contract_errors', [])
    if not isinstance(response_errors, list) or any(not isinstance(error, str) for error in response_errors):
        errors.append('invalid response contract errors')
    else:
        errors.extend(response_errors)
    reviews = artifact.get('reviews')
    if not isinstance(reviews, list):
        return {'contract_errors': ['review list missing'], 'findings': [], 'observations': []}
    known = {line['id'] for line in lines}
    expected = [line['id'] for line in lines] if expected_review_ids is None else expected_review_ids
    ids = [row.get('id') if isinstance(row, dict) else None for row in reviews]
    if ids != expected:
        errors.append('current review IDs incomplete, duplicated, unknown or reordered')
    counts = Counter(value for value in ids if isinstance(value, str))
    review_digest = digest(artifact)
    recorded_issues = []
    for row in reviews:
        if isinstance(row, dict) and isinstance(row.get('issues'), list):
            recorded_issues.extend(row['issues'])
        line_id = row.get('id') if isinstance(row, dict) else None
        if not isinstance(line_id, str) or line_id not in known or counts[line_id] != 1:
            errors.append('review row has invalid, unknown or duplicate ID')
            continue
        row_errors = []
        if any(type(row.get(key)) is not bool for key in _FLAGS):
            row_errors.append('review flags must be explicit booleans')
        for key in ('material_choice', 'reason'):
            if not isinstance(row.get(key), str):
                row_errors.append(f'{key} must be an explicit string')
        additions = row.get('unsupported_additions')
        if not isinstance(additions, list) or any(not isinstance(value, str) for value in additions):
            row_errors.append('unsupported additions must be an explicit string array')
        issues = row.get('issues')
        if not isinstance(issues, list):
            row_errors.append('typed review issues must be an explicit array')
        if row_errors:
            errors.extend(f'{line_id}: {message}' for message in row_errors)
            continue
        try:
            row_errors.extend(issue_errors(lines, glosses, issues))
        except (TypeError, KeyError):
            # The shared validator assumes provider-schema scalar/container types.
            # A damaged sibling row is a contract error, not loss of other evidence.
            row_errors.append('typed issue has malformed scalar/container types')
        if any(isinstance(issue, dict) and line_id not in issue.get('target_line_ids', [])
               for issue in issues if isinstance(issue, dict)
               and isinstance(issue.get('target_line_ids'), list)):
            row_errors.append('typed issue does not explain its reporting row')
        failed = any(row[key] is False for key in _FIDELITY) or bool(additions)
        if failed and not issues:
            row_errors.append('failed fidelity requires a typed evidenced issue')
        if issues and row['passes']:
            row_errors.append('passing review contradicts its recorded defects')
        if row['human_review_recommended'] and not issues and not row['material_choice'].strip():
            row_errors.append('human review flag has no issue or explicit open choice')
        if row_errors:
            errors.extend(f'{line_id}: {message}' for message in row_errors)
            continue
        common = {'line_id': line_id, 'row': copy.deepcopy(row),
                  'reader_digest': reader_digest, 'dependency_fingerprint': dependency_fingerprint,
                  'attempt_id': artifact['attempt_id'], 'review_digest': review_digest}
        if issues:
            for issue in issues:
                finding = {**common, 'kind': 'defect', 'issue': copy.deepcopy(issue)}
                findings.append({**finding, 'finding_id': digest(finding)})
        elif row['human_review_recommended']:
            finding = {**common, 'kind': 'open_choice'}
            findings.append({**finding, 'finding_id': digest(finding)})
        else:
            observations.append(copy.deepcopy(row))
    if not isinstance(artifact.get('issues'), list) or artifact['issues'] != recorded_issues:
        errors.append('review issues differ from preserved issue list')
    unique_findings = {finding['finding_id']: finding for finding in findings}
    return {'contract_errors': errors, 'findings': list(unique_findings.values()),
            'observations': observations}



def classify_review(artifact, *, lines, glosses, reader_digest, dependency_fingerprint):
    """Retain target findings and separately scoped context dependencies.

    A context observation never authorizes a target rewrite. Its original packet
    is part of the hash-bound artifact and is reclassified on every journal read.
    """
    context = dict(lines=lines, glosses=glosses, reader_digest=reader_digest,
                   dependency_fingerprint=dependency_fingerprint)
    result = _classify_rows(artifact, **context)
    packets = artifact.get('context_review_packets', [])
    if not isinstance(packets, list):
        result['contract_errors'].append('context review packets must be an array')
        return result
    known = {line['id'] for line in lines}
    labels = set()
    for packet in packets:
        if not isinstance(packet, dict):
            result['contract_errors'].append('context review packet must be an object')
            continue
        label = packet.get('label')
        targets = packet.get('target_ids'); context_ids = packet.get('context_ids')
        if (not isinstance(label, str) or not label or label in labels
                or any(not isinstance(ids, list)
                       or any(not isinstance(value, str) or value not in known for value in ids)
                       or len(ids) != len(set(ids)) for ids in (targets, context_ids))
                or not targets):
            result['contract_errors'].append('context review scope is invalid or duplicated')
            continue
        labels.add(label)
        response = packet.get('response')
        body = response.get('packet') if isinstance(response, dict) else None
        rows = body.get('reviews') if isinstance(body, dict) else None
        if not isinstance(rows, list):
            result['contract_errors'].append('context review response has no review array')
            continue
        # The original request scope, not mere membership in the reader, decides
        # whether a row was context. Unknown rows remain contract failures.
        scope_ids = set(targets) | set(context_ids)
        if any(not isinstance(row, dict) or not isinstance(row.get('id'), str)
               or row['id'] not in scope_ids for row in rows):
            result['contract_errors'].append('context response contains an unknown or malformed row')
        extra = [row for row in rows if isinstance(row, dict)
                 and isinstance(row.get('id'), str)
                 and row['id'] in context_ids and row['id'] not in targets]
        if not extra:
            continue
        subset = {key: artifact[key] for key in
                  ('reader_digest', 'dependency_fingerprint', 'attempt_id')}
        subset.update(reviews=extra, issues=[issue for row in extra
            if isinstance(row.get('issues'), list) for issue in row['issues']])
        classified = _classify_rows(subset, **context,
                                    expected_review_ids=[row['id'] for row in extra])
        result['contract_errors'].extend(classified['contract_errors'])
        for finding in classified['findings']:
            retained = {key: value for key, value in finding.items() if key != 'finding_id'}
            retained.update(kind='context_dependency', observed_kind=finding['kind'],
                review_digest=digest(artifact), context_scope={
                    'label': label, 'target_ids': copy.deepcopy(targets),
                    'context_ids': copy.deepcopy(context_ids), 'response_digest': digest(response)})
            result['findings'].append({**retained, 'finding_id': digest(retained)})
    return result


def _entry(artifact, context):
    classified = classify_review(artifact, **context)
    return ({'artifact': copy.deepcopy(artifact), 'review_digest': digest(artifact),
             'contract_errors': classified['contract_errors']}, classified['findings'])


def _rebuild(saved, identity, context):
    """Validate persisted original artifacts and their exact derived population."""
    if not isinstance(saved, dict) or any(saved.get(key) != value for key, value in identity.items()):
        raise ValueError('finding journal context or version changed')
    entries = saved.get('reviews')
    if not isinstance(entries, list):
        raise ValueError('finding journal reviews missing')
    rebuilt = {**identity, 'reviews': [], 'findings': []}
    attempts = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('finding journal entry malformed')
        expected, findings = _entry(entry.get('artifact'), context)
        attempt = expected['artifact']['attempt_id']
        if attempt in attempts or entry != expected:
            raise ValueError('finding journal review changed or duplicated')
        attempts.add(attempt)
        rebuilt['reviews'].append(expected)
        rebuilt['findings'].extend(findings)
    if saved != rebuilt:
        raise ValueError('finding journal derived findings or content changed')
    return rebuilt


def record_review(path, artifact, *, lines, glosses, reader_digest, dependency_fingerprint):
    """Atomically append an observation, retaining every earlier valid finding.

    Replaying identical evidence is byte-idempotent. Conflicting same-attempt
    evidence, changed context and corrupted journals fail before writing.
    """
    context = {'lines': lines, 'glosses': glosses, 'reader_digest': reader_digest,
               'dependency_fingerprint': dependency_fingerprint}
    identity = _context_identity(**context)
    entry, found = _entry(artifact, context)
    path = Path(path)
    if path.exists():
        snapshot = _rebuild(json.loads(path.read_text(encoding='utf-8')), identity, context)
    else:
        snapshot = {**identity, 'reviews': [], 'findings': []}
    for existing in snapshot['reviews']:
        if existing['artifact']['attempt_id'] == artifact['attempt_id']:
            if existing != entry:
                raise ValueError('conflicting evidence for an existing review attempt')
            return copy.deepcopy(snapshot)
    snapshot['reviews'].append(entry)
    snapshot['findings'].extend(found)
    atomic_write(path, snapshot)
    return copy.deepcopy(snapshot)


def pending_findings(snapshot):
    """Return retained findings from a snapshot validated by record_review.

    This does not load or authorize an arbitrary on-disk journal. The caller must
    record/revalidate against its current evidence before using a cached result.
    """
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('findings'), list):
        raise ValueError('validated finding snapshot required')
    return copy.deepcopy(snapshot['findings'])


def validate_snapshot(snapshot, *, lines, glosses, reader_digest, dependency_fingerprint):
    """Revalidate a supplied snapshot; completeness still comes from route history."""
    context = dict(lines=lines, glosses=glosses, reader_digest=reader_digest,
                   dependency_fingerprint=dependency_fingerprint)
    return _rebuild(snapshot, _context_identity(**context), context)


def load_snapshot(path, *, lines, glosses, reader_digest, dependency_fingerprint):
    """Load/revalidate existing state, or return a bound empty observation set."""
    context = dict(lines=lines, glosses=glosses, reader_digest=reader_digest,
                   dependency_fingerprint=dependency_fingerprint)
    identity = _context_identity(**context)
    path = Path(path)
    if not path.exists():
        return {**identity, 'reviews': [], 'findings': []}
    return _rebuild(json.loads(path.read_text(encoding='utf-8')), identity, context)

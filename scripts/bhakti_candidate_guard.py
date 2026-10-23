"""Authorize narrowly evidenced semantic changes; never certify linguistic truth by hashes."""
from __future__ import annotations

from bhakti_semantic_repair import digest, issue_errors
from editorial_baselines import plain_english
import bhakti_review_findings as finding_store
import source_word_map

_FIELDS = {'english_realization': {'english'}, 'english_mapping': {'english'},
           'gloss_sense': {'english', 'words'}, 'frame_relation': {'english', 'words'}}
_FIDELITY = ('passes', 'agency_preserved', 'imagery_preserved', 'all_meaning_accounted_for')


def _rows(rows, expected, label, *, complete=True):
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ValueError(f'{label}: rows must be objects')
    ids = [r.get('id') for r in rows]
    if any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
        raise ValueError(f'{label}: invalid/duplicate IDs')
    if set(ids) - set(expected) or (complete and set(ids) != set(expected)):
        raise ValueError(f'{label}: unexpected line population')
    return dict(zip(ids, rows))


def _clean(row):
    return (all(row.get(k) is True for k in _FIDELITY)
            and row.get('human_review_recommended') is False
            and row.get('unsupported_additions') == [] and row.get('issues') == []
            and row.get('material_choice') == '')


def _envelope(envelope, reader, dependency, label):
    if (not isinstance(envelope, dict) or envelope.get('reader_digest') != digest(reader)
            or envelope.get('dependency_fingerprint') != dependency
            or not isinstance(envelope.get('attempt_id'), str) or not envelope['attempt_id'].strip()):
        raise ValueError(f'{label}: unbound review evidence')


def _validate_quoted_indices(lines, glosses, issue):
    sources = {row['id']: row for row in lines}
    words = {row['id']: row['word_glosses'] for row in glosses}
    for ref in issue['references']:
        line = sources[ref['line_id']]; mapping = line.get('sourceWords')
        if source_word_map.validate_source_words(line['source_text'], words[ref['line_id']], mapping):
            raise ValueError('sourceWords mapping required for finding reference')
        if any(any(type(i) is not int for i in item['wordIndices']) for item in mapping):
            raise ValueError('sourceWords indices must be integers')
        source = line['source_text']; cursor = 0; spans = []
        for item in mapping:
            start = source.find(item['text'], cursor)
            if start < 0: raise ValueError('sourceWords surface cannot be located')
            end = start + len(item['text']); cursor = end
            spans.append((start, end, set(item['wordIndices'])))
        quote = ref['source_quote']; start = source.find(quote); matches = False
        while start >= 0:
            end = start + len(quote)
            covered = set().union(*(indices for left, right, indices in spans if left < end and right > start))
            if set(ref['word_indices']).issubset(covered):
                matches = True; break
            start = source.find(quote, start + 1)
        if not matches:
            raise ValueError('source quote does not map to referenced gloss indices')


def _resolved_finding_review(row):
    # Describing a chosen sense is not itself an open choice. Explicit review
    # flags and exact obligation dispositions still control this new path.
    return (all(row.get(key) is True for key in _FIDELITY)
            and row.get('human_review_recommended') is False
            and row.get('unsupported_additions') == [] and row.get('issues') == []
            and isinstance(row.get('material_choice'), str))


def _finding_receipt(before_reader, after_reader, changes, snapshot, pre, post, dependency, allow_partial):
    findings = snapshot['findings']; by_id = {f['finding_id']: f for f in findings}
    post_rows = {}; dispositions = {}
    if post is not None:
        _envelope(post, after_reader, dependency, 'post-review')
        if post['attempt_id'] in {entry['artifact']['attempt_id'] for entry in snapshot['reviews']}:
            raise ValueError('review dispatches are not independent')
        post_rows = _rows(post.get('reviews'), before_reader['SONG_LINES'], 'post-review', complete=False)
        for line_id, row in post_rows.items():
            recorded = row.get('finding_dispositions', [])
            if not isinstance(recorded, list):
                raise ValueError('finding dispositions must be an array')
            for item in recorded:
                if (not isinstance(item, dict) or not isinstance(item.get('finding_id'), str)
                        or item['finding_id'] not in by_id
                        or item['finding_id'] in dispositions):
                    raise ValueError('invalid or duplicate finding disposition')
                finding = by_id[item['finding_id']]
                if finding['kind'] != 'defect' or line_id not in finding['issue']['target_line_ids']:
                    raise ValueError('disposition does not address this target defect')
                if (not isinstance(item.get('status'), str)
                        or item['status'] not in {'repaired', 'unresolved'}
                        or not isinstance(item.get('explanation'), str) or not item['explanation'].strip()
                        or not isinstance(item.get('source_quote'), str)
                        or item['source_quote'] not in {r['source_quote'] for r in finding['issue']['references']}):
                    raise ValueError('finding disposition lacks exact source obligation')
                dispositions[item['finding_id']] = item
    if changes:
        if set(changes) - set(post_rows) or any(not _resolved_finding_review(row) for row in post_rows.values()):
            raise ValueError('candidate has unresolved fidelity review')
    resolved = []; pending = []
    for finding in findings:
        issue = finding.get('issue', {}); disposition = dispositions.get(finding['finding_id'])
        targets = issue.get('target_line_ids', [])
        altered = bool(targets) and all(target in changes for target in targets)
        if issue.get('kind') == 'gloss_sense':
            altered = altered and any(
                before_reader['SONG_LINES'][ref['line_id']]['words'][index]['gloss'] !=
                after_reader['SONG_LINES'][ref['line_id']]['words'][index]['gloss']
                for ref in issue['references'] if ref['line_id'] in targets for index in ref['word_indices'])
        if (finding['kind'] == 'defect' and issue.get('kind') in _FIELDS and altered
                and disposition and disposition['status'] == 'repaired'
                and all(target in post_rows and _resolved_finding_review(post_rows[target]) for target in targets)):
            resolved.append({'finding_id': finding['finding_id'], 'finding': finding,
                             'disposition': disposition, 'post_review_digest': digest(post)})
        else:
            pending.append(finding)
    if pending and not allow_partial:
        raise ValueError('pending unresolved audit findings prevent publication')
    return {'confirmed_changes': changes, 'original_digest': digest(before_reader),
            'candidate_digest': digest(after_reader), 'dependency_fingerprint': dependency,
            'pre_review_digest': digest(pre), 'post_review_digest': digest(post),
            'confirmed_issues': [f['issue'] for f in findings if f['kind'] == 'defect'],
            'finding_snapshot_digest': digest(snapshot), 'resolved_findings': resolved,
            'pending_findings': pending, 'publicationEligible': not pending}


def authorize_semantic_candidate(before_reader, after_reader, *, source_lines, gloss_rows,
                                 pre_review, post_review, dependency_fingerprint,
                                 protected_english=None, finding_snapshot=None, allow_partial=False):
    """Return changed fields plus exact review identity; raise on ambiguity/collateral edits.

    Caller loads the authoritative owner registry and supplies complete original
    source/gloss evidence. Separate actual model dispatches create the review
    envelopes; passing this gate is necessary, not sufficient, for publication.
    """
    if not isinstance(dependency_fingerprint, str) or not dependency_fingerprint.strip():
        raise ValueError('missing source/policy dependency identity')
    before = before_reader.get('SONG_LINES'); after = after_reader.get('SONG_LINES')
    if not isinstance(before, dict) or not before or not isinstance(after, dict) or set(before) != set(after):
        raise ValueError('line population changed')
    for key in set(before_reader) | set(after_reader):
        if key != 'SONG_LINES' and (key not in before_reader or key not in after_reader
                                  or before_reader[key] != after_reader[key]):
            raise ValueError(f'unapproved {key} change')
    if protected_english is not None:
        if not isinstance(protected_english, dict) or set(protected_english) != set(before):
            raise ValueError('protected population changed')
        for reader in (before, after):
            for line_id, saved in protected_english.items():
                value = reader[line_id].get('english')
                if not isinstance(value, str) or plain_english(value) != saved:
                    raise ValueError(f'{line_id}: protected wording changed')
    sources = _rows(source_lines, before, 'source')
    glosses = _rows(gloss_rows, before, 'gloss')
    for line_id, line in before.items():
        if (sources[line_id].get('source_text') != line.get('source')
                or sources[line_id].get('roman') != line.get('roman')
                or any(sources[line_id].get(k) != line.get(k) for k in ('sourceWords', 'sourceLanguage'))):
            raise ValueError(f'{line_id}: source evidence differs from original')
        words = line.get('words'); evidence = glosses[line_id].get('word_glosses')
        if not isinstance(words, list) or not isinstance(evidence, list) or len(words) != len(evidence):
            raise ValueError(f'{line_id}: gloss population differs')
        if any(not isinstance(w, dict) or not isinstance(e, dict)
               or w.get('roman') != e.get('roman') or w.get('gloss') != e.get('gloss')
               for w, e in zip(words, evidence)):
            raise ValueError(f'{line_id}: gloss evidence differs from original')
    _envelope(pre_review, before_reader, dependency_fingerprint, 'pre-review')
    allowed = {}; allowed_gloss_indices = {}; failed = set(); issues = []
    snapshot = None
    if finding_snapshot is not None:
        snapshot = finding_store.validate_snapshot(finding_snapshot, lines=source_lines,
            glosses=gloss_rows, reader_digest=digest(before_reader),
            dependency_fingerprint=dependency_fingerprint)
        raw_pre = {key: value for key, value in pre_review.items()
                   if key not in {'finding_snapshot', 'finding_journal_path', 'finding_route_state_path'}}
        if not any(entry['artifact'] == raw_pre for entry in snapshot['reviews']):
            raise ValueError('pre-review absent from retained finding evidence')
        diagnostic = finding_store.classify_review(raw_pre, lines=source_lines, glosses=gloss_rows,
            reader_digest=digest(before_reader), dependency_fingerprint=dependency_fingerprint)
        if diagnostic['contract_errors']:
            raise ValueError('invalid current diagnostic review')
        for finding in snapshot['findings']:
            if finding['kind'] != 'defect': continue
            issue = finding['issue']
            if issue['kind'] not in _FIELDS: continue
            _validate_quoted_indices(source_lines, gloss_rows, issue)
            issues.append(issue)
            for target in issue['target_line_ids']:
                allowed.setdefault(target, set()).update(_FIELDS[issue['kind']])
                failed.add(target)
            if issue['kind'] in ('gloss_sense', 'frame_relation'):
                for ref in issue['references']:
                    if ref['line_id'] in issue['target_line_ids']:
                        allowed_gloss_indices.setdefault(ref['line_id'], set()).update(ref['word_indices'])
    else:
        pre = _rows(pre_review.get('reviews'), before, 'pre-review')
        allowed = {}; allowed_gloss_indices = {}; failed = set(); issues = []
        for line_id, row in pre.items():
            if _clean(row):
                continue
            if (any(type(row.get(k)) is not bool for k in _FIDELITY)
                    or row.get('human_review_recommended') is not False or row.get('material_choice') != ''):
                raise ValueError(f'{line_id}: ambiguous pre-review')
            reported = row.get('issues')
            if not isinstance(reported, list) or not reported:
                raise ValueError(f'{line_id}: unconfirmed pre-review failure')
            if issue_errors(source_lines, gloss_rows, reported):
                raise ValueError(f'{line_id}: invalid source-linked issues')
            for issue in reported:
                if issue['kind'] not in _FIELDS:
                    raise ValueError(f'{line_id}: unresolved evidence')
                if line_id not in issue['target_line_ids']:
                    raise ValueError(f'{line_id}: issue does not explain failed row')
                for target in issue['target_line_ids']:
                    allowed.setdefault(target, set()).update(_FIELDS[issue['kind']])
                    failed.add(target)
                if issue['kind'] in ('gloss_sense', 'frame_relation'):
                    for ref in issue['references']:
                        if ref['line_id'] in issue['target_line_ids']:
                            allowed_gloss_indices.setdefault(ref['line_id'], set()).update(ref['word_indices'])
                issues.append(issue)
            failed.add(line_id)
    changes = {}
    for line_id, old in before.items():
        new = after[line_id]
        changed = {k for k in set(old) | set(new)
                   if k not in old or k not in new or old[k] != new[k]}
        if changed - allowed.get(line_id, set()):
            raise ValueError(f'{line_id}: unapproved fields {sorted(changed)}')
        if 'words' in changed:
            old_words = old['words']; new_words = new.get('words')
            if not isinstance(new_words, list) or len(old_words) != len(new_words):
                raise ValueError(f'{line_id}: token population changed')
            for index, (old_word, new_word) in enumerate(zip(old_words, new_words)):
                if old_word != new_word and index not in allowed_gloss_indices.get(line_id, set()):
                    raise ValueError(f'{line_id}: unreferenced gloss change')
                if not isinstance(new_word, dict) or set(old_word) != set(new_word):
                    raise ValueError(f'{line_id}: word schema changed')
                if any(old_word[k] != new_word[k] for k in old_word if k != 'gloss'):
                    raise ValueError(f'{line_id}: token identity or metadata changed')
        if changed:
            changes[line_id] = sorted(changed)
    if snapshot is not None:
        return _finding_receipt(before_reader, after_reader, changes, snapshot,
            pre_review, post_review, dependency_fingerprint, allow_partial)
    if failed or changes:
        _envelope(post_review, after_reader, dependency_fingerprint, 'post-review')
        if pre_review['attempt_id'] == post_review['attempt_id']:
            raise ValueError('review dispatches are not independent')
        post = _rows(post_review.get('reviews'), before, 'post-review', complete=False)
        if (failed | set(changes)) - set(post) or any(not _clean(r) for r in post.values()):
            raise ValueError('candidate has unresolved fidelity review')
    return {'confirmed_changes': changes, 'original_digest': digest(before_reader),
            'candidate_digest': digest(after_reader), 'dependency_fingerprint': dependency_fingerprint,
            'pre_review_digest': digest(pre_review), 'post_review_digest': digest(post_review),
            'confirmed_issues': issues}

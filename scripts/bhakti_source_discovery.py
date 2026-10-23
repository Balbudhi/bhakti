"""Witnessed source dictionary discovery; lookup results never create aliases.

Model suggestions are bounded query hypotheses. Only a later independent
source-form and semantic review can establish that a returned entry applies.
"""
from __future__ import annotations
import copy
import math
import time
import json
import tempfile
from pathlib import Path

import bhakti_lexical_retrieval as lexical
import bhakti_lexical_support as support
import bhakti_lexical_producer as producer
from bhakti_embedding_client import file_lock
import dictionary_corpus as corpus
import source_word_map

VERSION = 1
MAX_SUGGESTIONS = 2


def _write_records(path, records):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        json.dump(records, stream, ensure_ascii=False, indent=2)
        temporary = Path(stream.name)
    temporary.chmod(0o600)
    temporary.replace(path)


def _queries(values):
    support.require(isinstance(values, list) and len(values) <= MAX_SUGGESTIONS,
                    'source query suggestion limit exceeded')
    support.require(all(isinstance(value, str) and value.strip() and len(value) <= 128
                        for value in values), 'invalid source lookup query')
    return list(dict.fromkeys(value.strip() for value in values))


def source_lookup_plan(lines, proposals, languages):
    sources = {line['id']: line for line in lines}
    targets, gaps, seen = [], [], set()
    for proposal in proposals:
        line_id = proposal['line_id']
        support.require(line_id in sources, 'source lookup line unknown')
        line = sources[line_id]
        tokens = lexical.word_tokens(line)
        indices = proposal['word_indices']
        support.require(isinstance(indices, list) and indices and
                        all(type(index) is int and 0 <= index < len(tokens) for index in indices)
                        and indices == sorted(set(indices)), 'source lookup indices invalid')
        support.require(proposal.get('surfaces') == [tokens[index] for index in indices],
                        'source lookup surfaces differ from exact Roman tokens')
        key = (line_id, tuple(indices))
        support.require(key not in seen, 'duplicate source lookup target')
        seen.add(key)
        suggestions = _queries(proposal.get('source_queries', []))
        code = lexical.line_language(line, languages)
        target_id = 'discovery:' + line_id + ':' + ','.join(map(str, indices))
        gap_base = {'target_id': target_id, 'line_id': line_id, 'word_indices': list(indices)}
        if code != 'hi':
            gaps.append({**gap_base, 'kind': 'source_adapter_unavailable', 'language': code})
            continue
        native = None
        if line.get('sourceWords') is not None:
            errors = source_word_map.validate_source_words(line.get('source_text', line.get('source', '')),
                [{'roman': token} for token in tokens], line['sourceWords'])
            support.require(not errors, 'invalid sourceWords: ' + '; '.join(errors))
            matched = [row for row in line['sourceWords'] if row['wordIndices'] == indices]
            if len(matched) == 1:
                native = lexical.token(matched[0]['text'])
        if not native:
            gaps.append({**gap_base, 'kind': 'native_mapping_missing'})
        queries = ([{'text': native, 'origin': 'native_surface'}] if native else [])
        queries += [{'text': text, 'origin': 'model_hypothesis'} for text in suggestions if text != native]
        if queries:
            targets.append({'id': target_id, 'line_id': line_id, 'word_indices': list(indices),
                'surfaces': list(proposal['surfaces']), 'source_language': code, 'queries': queries})
    return {'version': VERSION, 'targets': targets, 'gaps': gaps}


def _budget_state(run_budget, reserve=False):
    support.require(isinstance(run_budget, dict), 'source discovery requires an explicit shared run budget')
    maximum, deadline = run_budget.get('max_requests'), run_budget.get('deadline_at')
    support.require(type(maximum) is int and maximum >= 0 and
                    isinstance(deadline, (int, float)) and math.isfinite(deadline),
                    'invalid shared source discovery limits')
    path = Path(run_budget['path'])
    path.parent.mkdir(parents=True, exist_ok=True)
    identity = {'version': VERSION, 'max_requests': maximum, 'deadline_at': deadline}
    with file_lock(path.with_suffix(path.suffix + '.lock')):
        state = support.read_json(path) if path.exists() else {'identity': identity, 'requests_started': 0}
        support.require(state.get('identity') == identity, 'shared source discovery budget identity changed')
        used = state.get('requests_started')
        support.require(type(used) is int and 0 <= used <= maximum, 'invalid shared source discovery budget counter')
        if not reserve:
            if not path.exists():
                _write_records(path, state)
            return None
        remaining = deadline - time.time()
        if remaining <= 0:
            return {'status': 'deadline_gap'}
        if used >= maximum:
            return {'status': 'budget_gap'}
        # Count before dispatch: an interrupted/uncertain attempt is not free on resume.
        state['requests_started'] += 1
        _write_records(path, state)
        return {'remaining_seconds': remaining}


def acquire_source_candidates(plan, cache_dir, *, opener=None, max_new_requests=16,
                              timeout=15, retry_errors=False, run_budget=None):
    support.require(type(max_new_requests) is int and max_new_requests >= 0,
                    'source discovery request limit must be nonnegative')
    support.require(isinstance(timeout, (int, float)) and math.isfinite(timeout) and timeout > 0,
                    'source discovery timeout must be positive and bounded')
    support.require(plan.get('version') == VERSION, 'source discovery plan version differs')
    _budget_state(run_budget)
    root = Path(cache_dir)/'platts-hi'
    root.mkdir(parents=True, exist_ok=True)
    acquired, query_order, budgeted = {}, [], 0
    for target in plan['targets']:
        support.require(target['source_language'] == 'hi', 'unsupported source dictionary language')
        support.require(len(target['queries']) <= MAX_SUGGESTIONS+1, 'source lookup target query limit')
        for query in target['queries']:
            support.require(query['origin'] in {'native_surface', 'model_hypothesis'} and
                            isinstance(query['text'], str) and query['text'] and len(query['text']) <= 128,
                            'invalid source lookup query')
            if query['text'] not in query_order:
                query_order.append(query['text'])
    # Acquisition owns one shared cache; preserve read/fetch/write transaction
    # while independent songs remain free to do other pipeline work.
    with file_lock(root/'acquisition.lock'):
        manifest = root/'acquisition.json'
        existing_rows = support.read_json(manifest) if manifest.exists() else []
        existing = {row['query']: row for row in existing_rows}
        for query in query_order:
            prior = existing.get(query)
            new_request = prior is None or (retry_errors and 'error' in prior)
            if new_request and budgeted >= max_new_requests:
                acquired[query] = {'status': 'budget_gap'}
                continue
            request_timeout = timeout
            if new_request:
                reservation = _budget_state(run_budget, reserve=True)
                if 'status' in reservation:
                    acquired[query] = reservation
                    continue
                request_timeout = min(timeout, reservation['remaining_seconds'])
                budgeted += 1
                if prior is not None:
                    # Retry is explicit and bounded; a transport error was never
                    # a lexical miss. Other successful cache evidence stays intact.
                    existing_rows = [row for row in existing_rows if row['query'] != query]
                    _write_records(manifest, existing_rows)
            record = corpus.acquire_queries(root, [query], opener=opener, timeout=request_timeout)[0]
            existing[query] = record
            existing_rows = support.read_json(manifest)
            if 'error' in record:
                acquired[query] = {'status': 'transport_error', 'detail': record['error']}
                continue
            raw = corpus.load_cached_witness(root, record)
            try:
                entries = corpus.parse_platts_html(raw.decode('utf-8'), query=query,
                    url=record['url'], witness_sha256=record['sha256'])
            except (ValueError, UnicodeError) as exc:
                acquired[query] = {'status': 'parse_error', 'detail': str(exc),
                                   'witness_sha256': record['sha256']}
                continue
            acquired[query] = {'status': 'candidate_entries' if entries else 'witnessed_miss',
                               'entries': entries, 'witness_sha256': record['sha256']}
    targets, all_entries, gaps = [], [], copy.deepcopy(plan['gaps'])
    for original in plan['targets']:
        target = copy.deepcopy(original)
        target['selection_status'] = 'lookup_hypothesis'
        target['candidate_entry_ids'] = []
        target['observations'] = []
        for query in target['queries']:
            outcome = acquired[query['text']]
            observation = {**query, **{key: value for key, value in outcome.items() if key != 'entries'}}
            target['observations'].append(observation)
            if outcome['status'] in {'transport_error', 'parse_error', 'budget_gap', 'deadline_gap'}:
                kinds = {'transport_error': 'source_transport_error', 'parse_error': 'source_parse_error',
                         'budget_gap': 'source_discovery_budget', 'deadline_gap': 'source_discovery_deadline'}
                gaps.append({'kind': kinds[outcome['status']], 'target_id': target['id'], 'query': query['text']})
            for entry in outcome.get('entries', []):
                all_entries.append(entry)
                if entry['entry_id'] not in target['candidate_entry_ids']:
                    target['candidate_entry_ids'].append(entry['entry_id'])
        targets.append(target)
    entries = corpus.merge_entries(all_entries)
    witnessed = producer.resolve_source_witnesses(entries, [root])
    gaps.extend(witnessed['gaps'])
    return {'version': VERSION, 'targets': targets, 'entries': entries,
            'evidence': witnessed['evidence'], 'entry_evidence_ids': witnessed['entry_evidence_ids'], 'gaps': gaps}


def discovery_decision_errors(discovery, decisions):
    errors = []
    targets = {target['id']: target for target in discovery['targets']}
    entries = {entry['entry_id']: entry for entry in discovery['entries']}
    expected = {(target['id'], entry_id) for target in targets.values()
                for entry_id in target['candidate_entry_ids']}
    seen = set()
    if not isinstance(decisions, list):
        return ['source discovery decisions must be an array']
    for decision in decisions:
        try:
            key = (decision['target_id'], decision['entry_id'])
            support.require(key in expected and key not in seen, 'unknown or duplicate source discovery decision')
            seen.add(key)
            target, entry = targets[key[0]], entries[key[1]]
            support.require(target['source_language'] == entry['language'], 'source discovery language mismatch')
            support.require(decision.get('status') in {'matched', 'rejected', 'unresolved'} and
                            isinstance(decision.get('reason'), str) and decision['reason'].strip() and
                            type(decision.get('changes_gloss')) is bool, 'source discovery disposition missing')
            if decision['status'] != 'matched':
                continue
            quotation, form = decision.get('quotation'), decision.get('attested_form')
            support.require(isinstance(quotation, str) and quotation and
                            quotation in entry['dictionary']['whole_entry_text'], 'source quotation not witnessed')
            support.require(isinstance(form, str) and form and form in quotation, 'attested form absent from quotation')
            relation = decision.get('relation_kind')
            support.require(relation in {'exact_form', 'vernacular_variant', 'compound_subentry'},
                            'matched source relation kind missing')
            support.require(isinstance(decision.get('meaning_applied'), str) and decision['meaning_applied'].strip(),
                            'matched source meaning missing')
            if relation == 'exact_form':
                native = [query['text'] for query in target['queries'] if query['origin'] == 'native_surface']
                heads = entry['source_spellings'] + entry['roman_search_aliases']
                support.require(any(lexical.token(value) == lexical.token(head) for value in native + target['surfaces']
                                    for head in heads), 'exact source-form claim has no matching witnessed headword')
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(str(exc))
    if seen != expected:
        errors.append('source discovery decisions omit candidate alternatives')
    return errors

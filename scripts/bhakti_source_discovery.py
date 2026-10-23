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


def _budget_state(run_budget, reserve=False, *, initialize=False):
    support.require(isinstance(run_budget, dict), 'source discovery requires an explicit shared run budget')
    maximum, deadline = run_budget.get('max_requests'), run_budget.get('deadline_at')
    support.require(type(maximum) is int and maximum >= 0 and
                    isinstance(deadline, (int, float)) and math.isfinite(deadline),
                    'invalid shared source discovery limits')
    path = Path(run_budget['path'])
    path.parent.mkdir(parents=True, exist_ok=True)
    identity = {'version': VERSION, 'max_requests': maximum, 'deadline_at': deadline}
    with file_lock(path.with_suffix(path.suffix + '.lock')):
        if not path.exists() and not initialize:
            raise ValueError('source discovery budget missing; only a new run owner may initialize its quota')
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


def run_limit(options):
    maximum = getattr(options, 'source_discovery_max_requests', 16)
    support.require(type(maximum) is int and maximum >= 0,
                    'source discovery run request limit must be nonnegative')
    return maximum


def configure_run_budget(state_dir, deadline_at, options, *, resume=False):
    budget = {'path': str(Path(state_dir)/'source-discovery-budget.json'),
              'max_requests': run_limit(options), 'deadline_at': deadline_at}
    if resume and not Path(budget['path']).is_file():
        raise ValueError('source discovery budget missing; resumed run cannot reset its quota')
    _budget_state(budget, initialize=not resume)
    return budget


def prepare(lines, gloss_rows, languages, bindings, config, options):
    """Discover only proposed unbound meanings; never change source aliases/glosses."""
    proposals = []
    for row in gloss_rows:
        for proposal in row.get('lexical_queries', []):
            tokens = {token['word_index']: token for token in bindings[row['id']]}
            bound = any(tokens[index]['candidates'] for index in proposal['word_indices'])
            if proposal.get('source_queries') or not bound:
                proposals.append({**proposal, 'line_id': row['id']})
    if not proposals:
        return None
    plan = source_lookup_plan(lines, proposals, languages)
    budget = getattr(options, 'source_discovery_budget', None)
    if plan['targets'] and budget is not None:
        return acquire_source_candidates(plan, config['cache']/'source-discovery', run_budget=budget,
            opener=getattr(options, 'source_discovery_opener', None))
    targets = [{**target, 'candidate_entry_ids': [], 'observations': [],
                'selection_status': 'lookup_hypothesis'} for target in plan['targets']]
    gaps = copy.deepcopy(plan['gaps'])
    if targets:
        gaps.append({'kind': 'source_discovery_budget_missing',
                     'detail': 'No shared run acquisition budget configured; no request dispatched.'})
    return {'version': VERSION, 'targets': targets, 'entries': [], 'evidence': [],
            'entry_evidence_ids': {}, 'gaps': gaps}


def projected(discovery, line_ids):
    if not discovery:
        return None
    selected = copy.deepcopy(discovery)
    selected['targets'] = [target for target in selected['targets'] if target['line_id'] in line_ids]
    ids = {entry_id for target in selected['targets'] for entry_id in target['candidate_entry_ids']}
    selected['entries'] = [entry for entry in selected['entries'] if entry['entry_id'] in ids]
    selected['entry_evidence_ids'] = {entry_id: refs for entry_id, refs in selected['entry_evidence_ids'].items() if entry_id in ids}
    evidence_ids = {eid for refs in selected['entry_evidence_ids'].values() for eid in refs}
    selected['evidence'] = [row for row in selected['evidence'] if row['id'] in evidence_ids]
    for row in selected['evidence']:
        row.pop('witness_path', None)
    selected['gaps'] = [gap for gap in selected['gaps'] if gap.get('line_id') is None or gap['line_id'] in line_ids]
    return selected


def prompt(options, line_ids):
    discovery = projected(getattr(options, 'automatic_source_discovery', None), line_ids)
    if not discovery:
        return ''
    # The parser's entry-context sense repeats the entire definition. Deliver
    # that complete text once; raw HTML remains bound privately by its hashes.
    for entry in discovery['entries']:
        if all(sense.get('granularity') == 'entry_context' and
               sense.get('dictionary_anchor') == entry['dictionary']['whole_entry_text']
               for sense in entry.get('senses', [])):
            entry.pop('senses', None)
    for evidence in discovery['evidence']:
        evidence.pop('quotation', None)
    return ('\nSOURCE DISCOVERY EVIDENCE:\n' + json.dumps(discovery, ensure_ascii=False) +
        '\nThese complete historical dictionary entries are lookup hypotheses, not selected meanings. '
        'Source query suggestions and similar spellings are not proof of a word relationship. '
        'For every target/entry pair return source_discovery_decisions with matched/rejected/unresolved, '
        'attested_form, exact quotation, relation_kind, meaning_applied, changes_gloss, and reason. '
        'A matched compound must quote the whole compound subentry, not just its root. '
        'Check source language, whole-word meaning, current passage grammar, and source/gloss/frame agreement. '
        'If new evidence requires a changed gloss, set changes_gloss=true; do not silently replace the glossary. '
        'The independent reviewer must evaluate each relation and contextual meaning separately. '
        'An unavailable adapter/native map or transport error is not a dictionary miss. '
        'If the translation depends on evidence still missing, report the targeted unresolved dependency.\n')


def extend_schema(schema, options):
    discovery = getattr(options, 'automatic_source_discovery', None)
    if not discovery or not discovery['entries']:
        return schema
    schema = copy.deepcopy(schema)
    props = {field: {'type': 'string'} for field in
             ('target_id', 'entry_id', 'attested_form', 'quotation', 'meaning_applied', 'reason')}
    props.update(status={'type': 'string', 'enum': ['matched', 'rejected', 'unresolved']},
                 relation_kind={'type': 'string', 'enum': ['exact_form', 'vernacular_variant', 'compound_subentry', 'unresolved']},
                 changes_gloss={'type': 'boolean'})
    row = schema['properties']['translations']['items']
    row['properties']['source_discovery_decisions'] = {'type': 'array', 'items': {
        'type': 'object', 'properties': props, 'required': list(props), 'additionalProperties': False}}
    row['required'].append('source_discovery_decisions')
    return schema


def translation_decision_errors(discovery, translation_rows):
    if discovery is None:
        return []
    by_id = {row['id']: row for row in translation_rows}
    errors = []
    for line_id in {target['line_id'] for target in discovery['targets']} | set(by_id):
        row = by_id.get(line_id, {})
        errors.extend(discovery_decision_errors(projected(discovery, [line_id]),
                                                row.get('source_discovery_decisions', [])))
    return errors


def repair_issues(discovery, lines, translation_rows):
    """Validated new evidence cannot silently contradict the authoritative gloss."""
    if discovery is None:
        return []
    targets = {target['id']: target for target in discovery['targets']}
    entries = {entry['entry_id']: entry for entry in discovery['entries']}
    sources = {line['id']: line for line in lines}
    issues = []
    for row in translation_rows:
        for decision in row.get('source_discovery_decisions', []):
            if not decision.get('changes_gloss'):
                continue
            target = targets[decision['target_id']]
            entry = entries[decision['entry_id']]
            source = sources[target['line_id']]
            issues.append({'kind': 'gloss_sense', 'target_line_ids': [target['line_id']],
                'references': [{'line_id': target['line_id'], 'domain': 'word_glosses',
                    'word_indices': target['word_indices'], 'source_quote': source['source_text']}],
                'explanation': 'New source evidence requires glossary reconsideration: ' + decision['reason'],
                'evidence': json.dumps({'entry': entry, 'decision': decision}, ensure_ascii=False),
                'hold_reason': '', 'needed_evidence': ''})
    return issues

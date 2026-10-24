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
RELATION_POLICY_VERSION = 4
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
        dictionary_id = next((key for key, spec in corpus.DICTIONARIES.items() if spec['language'] == code), None)
        if dictionary_id is None:
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
                'surfaces': list(proposal['surfaces']), 'source_language': code, 'dictionary_id': dictionary_id, 'queries': queries})
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
                              timeout=15, retry_errors=False, run_budget=None, request_deadline_at=None):
    support.require(type(max_new_requests) is int and max_new_requests >= 0,
                    'source discovery request limit must be nonnegative')
    support.require(isinstance(timeout, (int, float)) and math.isfinite(timeout) and timeout > 0,
                    'source discovery timeout must be positive and bounded')
    support.require(plan.get('version') == VERSION, 'source discovery plan version differs')
    _budget_state(run_budget)
    if request_deadline_at is not None:
        support.require(isinstance(request_deadline_at, (int, float)) and math.isfinite(request_deadline_at),
                        'invalid source request deadline')
    acquired, query_order, budgeted = {}, [], 0
    roots = {}
    for target in plan['targets']:
        dictionary_id = target.get('dictionary_id', 'platts1884')
        spec = corpus.dictionary_spec(dictionary_id)
        support.require(target['source_language'] == spec['language'], 'source dictionary language differs')
        roots[dictionary_id] = Path(cache_dir)/spec['cache_name']
        support.require(len(target['queries']) <= MAX_SUGGESTIONS+1, 'source lookup target query limit')
        for query in target['queries']:
            support.require(query['origin'] in {'native_surface', 'model_hypothesis'} and
                            isinstance(query['text'], str) and query['text'] and len(query['text']) <= 128,
                            'invalid source lookup query')
            key = (dictionary_id, query['text'])
            if key not in query_order:
                query_order.append(key)
    # Each dictionary owns its cache transaction; every fresh request still uses
    # one run ledger and one per-invocation allowance across all dictionaries.
    for dictionary_id, query in query_order:
        root = roots[dictionary_id]
        root.mkdir(parents=True, exist_ok=True)
        key = (dictionary_id, query)
        with file_lock(root/'acquisition.lock'):
            manifest = root/'acquisition.json'
            existing_rows = support.read_json(manifest) if manifest.exists() else []
            existing = {row['query']: row for row in existing_rows}
            prior = existing.get(query)
            new_request = prior is None or (retry_errors and 'error' in prior)
            if new_request and budgeted >= max_new_requests:
                acquired[key] = {'status': 'budget_gap'}
                continue
            request_timeout = timeout
            if new_request:
                if request_deadline_at is not None and request_deadline_at <= time.time():
                    acquired[key] = {'status':'deadline_gap'}
                    continue
                reservation = _budget_state(run_budget, reserve=True)
                if 'status' in reservation:
                    acquired[key] = reservation
                    continue
                request_timeout = min(timeout, reservation['remaining_seconds'],
                    request_deadline_at-time.time() if request_deadline_at is not None else timeout)
                if request_timeout <= 0:
                    acquired[key] = {'status':'deadline_gap'}
                    continue
                budgeted += 1
                if prior is not None:
                    # Explicit bounded retry; a transport error was never a miss.
                    existing_rows = [row for row in existing_rows if row['query'] != query]
                    _write_records(manifest, existing_rows)
            record = corpus.acquire_queries(root, [query], dictionary_id=dictionary_id,
                opener=opener, timeout=request_timeout)[0]
            if 'error' in record:
                acquired[key] = {'status': 'transport_error', 'detail': record['error']}
                continue
            raw = corpus.load_cached_witness(root, record)
            try:
                entries = corpus.parse_dictionary_html(dictionary_id, raw.decode('utf-8'), query=query,
                    url=record['url'], witness_sha256=record['sha256'])
            except (ValueError, UnicodeError) as exc:
                acquired[key] = {'status': 'parse_error', 'detail': str(exc),
                                 'witness_sha256': record['sha256']}
                continue
            acquired[key] = {'status': 'candidate_entries' if entries else 'witnessed_miss',
                             'entries': entries, 'witness_sha256': record['sha256']}
    targets, all_entries, gaps = [], [], copy.deepcopy(plan['gaps'])
    for original in plan['targets']:
        target = copy.deepcopy(original)
        target['selection_status'] = 'lookup_hypothesis'
        target['candidate_entry_ids'] = []
        target['observations'] = []
        for query in target['queries']:
            outcome = acquired[(target.get('dictionary_id', 'platts1884'), query['text'])]
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
    witnessed = producer.resolve_source_witnesses(entries, list(roots.values()))
    gaps.extend(witnessed['gaps'])
    return {'version': VERSION, 'relation_policy_version': RELATION_POLICY_VERSION, 'targets': targets, 'entries': entries,
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
            support.require(isinstance(form, str) and form.strip(), 'attested form missing')
            relation = decision.get('relation_kind')
            support.require(relation in {'exact_form', 'vernacular_variant', 'compound_subentry', 'inflected_form'},
                            'matched source relation kind missing')
            support.require(isinstance(decision.get('meaning_applied'), str) and decision['meaning_applied'].strip(),
                            'matched source meaning missing')
            if relation == 'exact_form':
                native = [query['text'] for query in target['queries'] if query['origin'] == 'native_surface']
                heads = entry['source_spellings'] + entry['roman_search_aliases']
                normalized = lexical.token(form)
                support.require(any(normalized == lexical.token(head) for head in heads)
                                and any(normalized == lexical.token(value) for value in native + target['surfaces']),
                                'exact source-form claim must itself match the witnessed headword and performed form')
            if relation in {'vernacular_variant', 'compound_subentry'}:
                support.require(form in quotation, 'attested form absent from quotation')
            if relation == 'inflected_form':
                heads = entry['source_spellings'] + entry['roman_search_aliases']
                support.require(any(lexical.token(form) == lexical.token(head) for head in heads),
                                'inflected form needs an attested dictionary headword, not an arbitrary definition fragment')
                explanation = decision.get('form_explanation')
                support.require(isinstance(explanation, str) and explanation.strip() and len(explanation) <= 2000,
                                'inflected form needs a bounded explanation of its ending and grammatical contribution')
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



def request_deadline(options):
    values = [float(getattr(options, name)) for name in ('semantic_deadline_at', 'unit_deadline_at')
              if getattr(options, name, None) is not None]
    support.require(all(math.isfinite(value) for value in values), 'invalid source request deadline')
    return min(values) if values else None

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
            opener=getattr(options, 'source_discovery_opener', None), request_deadline_at=request_deadline(options))
    targets = [{**target, 'candidate_entry_ids': [], 'observations': [],
                'selection_status': 'lookup_hypothesis'} for target in plan['targets']]
    gaps = copy.deepcopy(plan['gaps'])
    if targets:
        gaps.append({'kind': 'source_discovery_budget_missing',
                     'detail': 'No shared run acquisition budget configured; no request dispatched.'})
    return {'version': VERSION, 'relation_policy_version': RELATION_POLICY_VERSION, 'targets': targets, 'entries': [], 'evidence': [],
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


def decision_pairs(discovery):
    """Only candidate entries actually supplied for each source target need judgments."""
    return [{'target_id': target['id'], 'entry_id': entry_id}
            for target in discovery['targets'] for entry_id in target['candidate_entry_ids']]


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
        '\nSOURCE DECISION PAIRS:\n' + json.dumps(decision_pairs(discovery), ensure_ascii=False) +
        '\nThese complete historical dictionary entries are lookup hypotheses, not selected meanings. '
        'Source query suggestions and similar spellings are not proof of a word relationship. '
        'Return exactly one source_discovery_decisions row for each listed SOURCE DECISION PAIRS pair, '
        'on that target’s own output line, and no other decision rows. '
        'Targets with no candidate entries require zero decisions; a line with no listed pairs must return []. '
        'Never use an empty entry_id or invent a decision for a lookup miss, gap, or unavailable source. '
        'Those lookup observations remain in SOURCE DISCOVERY EVIDENCE. '
        'Proposed alternative source forms belong separately in lexical_queries[].source_queries, not decisions. '
        'A missing dictionary entry alone is not an unresolved meaning; genuine source/meaning uncertainty '
        'must still be recorded in the response uncertainty/hold fields. '
        'For a supplied pair use matched/rejected/unresolved, '
        'attested_form, exact quotation, relation_kind, meaning_applied, changes_gloss, and reason. '
        'For exact_form, attested_form itself must be a witnessed headword or roman alias that exactly matches '
        'the performed native or roman form. A dictionary query hypothesis, substring, or cognate is not an exact match. '
        'For exact_form and inflected_form, the headword/alias establishes the form witness; quotation may separately '
        'cite the exact relevant definition from that same entry without repeating its headword. '
        'A valid form and quotation do not establish contextual meaning or authorize extra qualifiers. '
        'For vernacular_variant and compound_subentry the quoted passage must contain attested_form. '
        'A matched compound must quote the whole compound subentry, not just its root. '
        'Use inflected_form for a performed form linked to an attested dictionary lemma; '
        'provide form_explanation accounting for the ending or particle and its grammatical contribution in this whole line. '
        'The lemma quotation does not prove that explanation. Preserve the complete performed token and its indices; '
        'never silently stem it or discard suffix meaning. For other relations form_explanation may be empty. '
        'Check source language, whole-word meaning, current passage grammar, and source/gloss/frame agreement. '
        'If new evidence requires a changed gloss, set changes_gloss=true; do not silently replace the glossary. '
        'The independent reviewer must evaluate each relation and contextual meaning separately. '
        'An unavailable adapter/native map or transport error is not a dictionary miss. '
        'If the translation depends on evidence still missing, report the targeted unresolved dependency.\n')


def extend_schema(schema, options):
    discovery = getattr(options, 'automatic_source_discovery', None)
    if not discovery:
        return schema
    schema = copy.deepcopy(schema)
    props = {field: {'type': 'string'} for field in
             ('target_id', 'entry_id', 'attested_form', 'quotation', 'meaning_applied', 'reason', 'form_explanation')}
    props['attested_form']['description'] = ('Exact witnessed headword/roman alias for exact_form or inflected_form; '
        'the claimed variant/compound must appear in quotation for those other relations.')
    props['quotation']['description'] = ('Verbatim definition or relevant passage from the selected entry. '
        'For exact_form/inflected_form its witnessed headword may be cited separately in attested_form. '
        'Citation validity does not certify meaning_applied.')
    props.update(status={'type': 'string', 'enum': ['matched', 'rejected', 'unresolved']},
                 relation_kind={'type': 'string', 'enum': ['exact_form', 'vernacular_variant', 'compound_subentry', 'inflected_form', 'unresolved']},
                 changes_gloss={'type': 'boolean'})
    item = {'type': 'object', 'properties': props, 'required': list(props), 'additionalProperties': False}
    branches = []
    for target in discovery['targets']:
        if not target['candidate_entry_ids']:
            continue
        branch = copy.deepcopy(item)
        branch['properties']['target_id']['enum'] = [target['id']]
        branch['properties']['entry_id']['enum'] = list(target['candidate_entry_ids'])
        branches.append(branch)
    # One branch per nonempty target, rather than a target/entry cross product.
    # Callers project to the actual request lines. Many targets within one
    # request can still reach provider schema limits; retain the normal hold.
    row = schema['properties']['translations']['items']
    row['properties']['source_discovery_decisions'] = {
        'type': 'array', 'maxItems': len(decision_pairs(discovery)),
        'items': {'anyOf': branches} if branches else item}
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



class SourceGlossRequired(RuntimeError):
    """A valid older glossary needs current witnessed-source adjudication."""
    def __init__(self, line_ids, options):
        super().__init__('source glossary evidence changed or missing: '+str(line_ids))
        self.line_ids = line_ids
        self.options = options

    def revision_receipt(self):
        return {'source_discovery': self.options.automatic_source_discovery_identity}

def merge_evidence(previous, current):
    """Retain native bootstrap targets; refreshed witnessed entries own their IDs."""
    if not previous:
        return copy.deepcopy(current)
    if not current:
        return copy.deepcopy(previous)
    result = copy.deepcopy(previous)
    support.require(previous['version'] == current['version'] and
                    previous['relation_policy_version'] == current['relation_policy_version'],
                    'source evidence policies differ')
    targets = {row['id']: row for row in result['targets']}
    prior_entries = {row['entry_id']: row for row in result['entries']}
    for row in current['targets']:
        old = targets.get(row['id'])
        if old is None:
            targets[row['id']] = copy.deepcopy(row)
            continue
        for key in ('line_id', 'word_indices', 'surfaces', 'source_language', 'dictionary_id'):
            support.require(old.get(key) == row.get(key), 'source target binding changed')
        refreshed = {(value['text'], value['origin']) for value in row.get('observations', [])
                     if value['status'] in {'candidate_entries', 'witnessed_miss'}}
        replaced_witnesses = {value.get('witness_sha256') for value in old.get('observations', [])
                              if (value['text'], value['origin']) in refreshed}
        retained = [eid for eid in old['candidate_entry_ids'] if
                    prior_entries[eid]['dictionary'].get('witness_sha256') not in replaced_witnesses]
        for key in ('queries', 'observations'):
            # A refreshed result for a query replaces its earlier observation.
            values = {(value['text'], value['origin']): value for value in old.get(key, [])}
            values.update({(value['text'], value['origin']): copy.deepcopy(value) for value in row.get(key, [])})
            old[key] = list(values.values())
        old['candidate_entry_ids'] = list(dict.fromkeys(retained + row['candidate_entry_ids']))
    result['targets'] = list(targets.values())
    for key, identity in (('entries', 'entry_id'), ('evidence', 'id')):
        values = {row[identity]: row for row in result[key]}
        values.update({row[identity]: copy.deepcopy(row) for row in current[key]})
        result[key] = list(values.values())
    result['entry_evidence_ids'].update(copy.deepcopy(current['entry_evidence_ids']))
    covered = {row['id'] for row in current['targets']}
    retained_gaps = [row for row in result['gaps'] if row.get('target_id') not in covered
                     and row.get('kind') != 'source_discovery_budget_missing']
    result['gaps'] = list({support.digest(row): row for row in retained_gaps + copy.deepcopy(current['gaps'])}.values())
    used = {eid for row in result['targets'] for eid in row['candidate_entry_ids']}
    result['entries'] = [row for row in result['entries'] if row['entry_id'] in used]
    result['entry_evidence_ids'] = {eid: refs for eid, refs in result['entry_evidence_ids'].items() if eid in used}
    refs = {ref for values in result['entry_evidence_ids'].values() for ref in values}
    result['evidence'] = [row for row in result['evidence'] if row['id'] in refs]
    return result



def evidence_identity(packet):
    """Bind lexical evidence, not which outer resource limit prevented a query."""
    value = copy.deepcopy(packet)
    for target in value.get('targets', []):
        for observation in target.get('observations', []):
            if observation.get('status') in {'budget_gap', 'deadline_gap'}:
                observation['status'] = 'unavailable'
    for gap in value.get('gaps', []):
        if gap.get('kind') in {'source_discovery_budget', 'source_discovery_deadline'}:
            gap['kind'] = 'source_discovery_unavailable'
    return support.content_digest(value)

def source_gloss_receipt(discovery):
    """Only target-bound witnessed source content, never English ranks or paths."""
    if not discovery:
        return None
    entries = {row['entry_id']: row for row in discovery['entries']}
    evidence = {row['id']: row for row in discovery['evidence']}
    targets = {}
    for target in discovery['targets']:
        if not target['candidate_entry_ids']:
            continue
        rows = [entries[eid] for eid in sorted(target['candidate_entry_ids'])]
        refs = sorted({ref for eid in target['candidate_entry_ids'] for ref in discovery['entry_evidence_ids'][eid]})
        binding = {key: copy.deepcopy(target[key]) for key in
                   ('line_id', 'word_indices', 'surfaces', 'source_language', 'dictionary_id')}
        targets[target['id']] = {**binding, 'content_sha256': support.content_digest(
            {'entries': rows, 'evidence': [evidence[ref] for ref in refs]})}
    return {'version': 1, 'targets': targets} if targets else None


def validate_gloss_receipt(receipt):
    if receipt is None:
        return
    import re
    support.require(isinstance(receipt, dict) and set(receipt) == {'version', 'targets'} and
                    receipt.get('version') == 1 and isinstance(receipt.get('targets'), dict),
                    'malformed source glossary receipt')
    for target_id, row in receipt['targets'].items():
        support.require(isinstance(target_id, str) and isinstance(row, dict) and
            set(row) == {'line_id', 'word_indices', 'surfaces', 'source_language', 'dictionary_id', 'content_sha256'} and
            isinstance(row.get('line_id'), str) and isinstance(row.get('word_indices'), list) and
            row['word_indices'] and all(type(i) is int and i >= 0 for i in row['word_indices']) and
            isinstance(row.get('surfaces'), list) and len(row['surfaces']) == len(row['word_indices']) and
            all(isinstance(value, str) for value in row['surfaces']) and
            isinstance(row.get('content_sha256'), str) and re.fullmatch('[a-f0-9]{64}', row['content_sha256']),
            'malformed source glossary target receipt')


def gloss_decision_errors(discovery, rows):
    errors = translation_decision_errors(discovery, rows)
    for row in rows:
        for decision in row.get('source_discovery_decisions', []):
            if decision.get('status') == 'unresolved':
                errors.append('source glossary relation unresolved: ' + str(decision.get('target_id')))
    return errors


def pending_gloss_lines(discovery, glosses):
    """Missing old grounding renews; malformed or contradictory present proof holds."""
    receipt = glosses.get('source_gloss_receipt')
    validate_gloss_receipt(receipt)
    discovery = projected(discovery, [row['id'] for row in glosses['packet']['glosses']])
    expected = source_gloss_receipt(discovery)
    previous = receipt['targets'] if receipt else {}
    current = expected['targets'] if expected else {}
    pending = {row['line_id'] for key, row in previous.items() if key not in current}
    pending.update( row['line_id'] for key, row in current.items() if previous.get(key) != row)
    checked = [row for row in glosses['packet']['glosses'] if row['id'] not in pending]
    errors = gloss_decision_errors(projected(discovery, [row['id'] for row in checked]), checked)
    support.require(not errors, 'source glossary receipt decision invalid: ' + '; '.join(errors))
    return sorted(pending)


def gloss_prompt(options, line_ids):
    text = prompt(options, line_ids)
    if not text:
        return ''
    return (text.replace('SOURCE DISCOVERY EVIDENCE:', 'SOURCE GLOSS EVIDENCE:').replace(
        'If new evidence requires a changed gloss, set changes_gloss=true; do not silently replace the glossary. ',
        'This stage adjudicates source meanings; record the resulting word gloss and frame explicitly. ') +
        '\nSOURCE GLOSSARY ADJUDICATION: Decide source meanings before English realization. '
        'Return source_discovery_decisions on each glossary row for every supplied target/entry pair; '
        'matched/rejected/unresolved describes applicability, never dictionary prestige. '
        'Set changes_gloss=false because this response IS the new source gloss. '
        'The primary word gloss and semantic frame must express the justified contextual meaning. '
        'Do not import an additional qualifier from an unrelated dictionary sense. '
        'A real quotation and headword establish textual evidence, not contextual correctness. '
        'No fluent English translation or English dictionary decision belongs in this response.\n')


def extend_gloss_schema(schema, options):
    # Reuse exactly the same witnessed form/definition relation contract.
    wrapper = {'properties': {'translations': schema['properties']['glosses']}}
    extended = extend_schema(wrapper, options)
    result = copy.deepcopy(schema)
    result['properties']['glosses'] = extended['properties']['translations']
    return result

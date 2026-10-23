"""Automatic dictionary evidence with optional bounded English embedding discovery.

Existing gloss batches propose lookup queries. Dictionaries supply definitions,
never meaning selections. All stored evidence remains private.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile

import bhakti_lexical_retrieval as lexical
import bhakti_english_discovery as english_discovery
import bhakti_lexical_support as support
from bhakti_embedding_client import file_lock
import dictionary_corpus as corpus

VERSION = 1
MAX_QUERIES = 4


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)
        temporary = Path(stream.name)
    temporary.chmod(0o600)
    temporary.replace(path)


def settings(options=None):
    if os.environ.get('BHAKTI_AUTO_LEXICAL') != '1':
        return None
    directory = os.environ.get('BHAKTI_WORDNET_DIR')
    if not directory:
        raise ValueError('automatic lexical support requires configured WordNet corpus')
    roots = json.loads(os.environ.get('BHAKTI_SOURCE_WITNESS_ROOTS', '[]'))
    if not isinstance(roots, list) or any(not isinstance(root, str) for root in roots):
        raise ValueError('source witness roots must be a JSON list of directories')
    return {'directory': Path(directory), 'edition': os.environ.get('BHAKTI_WORDNET_EDITION', '3.1'),
            'roots': [Path(root) for root in roots],
            'cache': Path(os.environ.get('BHAKTI_LEXICAL_SUPPORT_CACHE',
                                         Path.home()/'.cache/bhakti/lexical-support'))}


def _source_records(roots):
    records = []
    for root in roots:
        path = Path(root)/'acquisition.json'
        if not path.exists():
            continue
        for record in support.read_json(path):
            if 'error' in record:
                continue
            corpus.load_cached_witness(root, record)
            records.append((Path(root), record))
    return records


def _dictionary_identity(directory, edition):
    # Validate actual installed/subset coverage before any accepted-cache lookup.
    directory = Path(directory)
    receipt = support.wordnet_receipt(directory, edition, [])
    if (directory/'manifest.json').exists():
        manifest = support.read_json(directory/'manifest.json')
        support.require(manifest.get('edition') == edition, 'WordNet edition mismatch')
        available = manifest.get('available_pos')
        support.require(isinstance(available, list) and available and set(available) <= set(support.POS),
                        'WordNet POS coverage undeclared')
        for name in available:
            for prefix in ('data', 'index'):
                support.require(receipt['files'].get(prefix+'.'+name) == manifest[prefix+'_sha256'][name],
                                'WordNet witness hash mismatch')
    else:
        support.require(all(prefix+name in receipt['files'] for name in support.POS for prefix in ('data.', 'index.')),
                        'installed WordNet needs all four POS files')
    receipt.pop('directory')
    return receipt


def configuration_identity(options=None):
    config = settings(options)
    if config is None:
        return None
    records = _source_records(config['roots'])
    witnesses = [{'query': row['query'], 'url': row['url'], 'sha256': row['sha256']}
                 for _, row in records]
    identity = {'version': VERSION, 'max_queries': MAX_QUERIES,
            'english': _dictionary_identity(config['directory'], config['edition']),
            'source_witnesses': sorted(witnesses, key=lambda row: (row['sha256'], row['query'])),
            'source_discovery': {'version': 1, 'max_suggestions': 2}}
    discovery = english_discovery.configuration()
    if discovery is not None:
        identity['english_discovery'] = discovery
    return identity


def proposal_errors(lines, gloss_rows, languages, required_spans=()):
    errors = []
    sources = {line['id']: line for line in lines}
    covered = set()
    for row in gloss_rows:
        try:
            source = sources[row['id']]
            tokens = lexical.word_tokens(source)
            proposals = row.get('lexical_queries', [])
            gaps = row.get('lexical_query_gaps', [])
            support.require(isinstance(proposals, list) and isinstance(gaps, list), 'lexical query arrays missing')
            seen = set()
            for proposal in proposals + gaps:
                indices = proposal.get('word_indices')
                support.require(isinstance(indices, list) and indices and
                                all(type(i) is int and 0 <= i < len(tokens) for i in indices) and
                                indices == sorted(set(indices)), 'invalid lexical query indices')
                key = (row['id'], tuple(indices))
                support.require(key not in seen, 'duplicate lexical query span')
                seen.add(key)
                support.require(isinstance(proposal.get('reason'), str) and proposal['reason'].strip(),
                                'lexical query reason missing')
                covered.add(key)
                if proposal in gaps:
                    continue
                support.require(proposal.get('surfaces') == [tokens[i] for i in indices],
                                'lexical query surface differs from source')
                candidates = proposal.get('english_candidates')
                support.require(isinstance(candidates, list) and 1 <= len(candidates) <= MAX_QUERIES,
                                'lexical query candidate limit')
                queries = set()
                for candidate in candidates:
                    support.require(candidate.get('kind') in {'word', 'compositional_phrase', 'transparent_compound'}
                                    and isinstance(candidate.get('expression'), str) and candidate['expression'].strip(),
                                    'invalid lexical query candidate')
                    words = support.english_queries(candidate.get('english_lemmas', []))
                    queries.update(words)
                    if candidate['kind'] == 'word':
                        support.require(words, 'word candidate needs dictionary lookup query')
                support.require(len(queries) <= MAX_QUERIES, 'lexical query limit exceeded')
                import bhakti_source_discovery as discovery
                discovery._queries(proposal.get('source_queries', []))
                ids = proposal.get('source_entry_ids')
                support.require(isinstance(ids, list) and all(isinstance(i, str) for i in ids),
                                'source entry IDs missing')
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(str(exc))
    for required in required_spans:
        if required['line_id'] in sources and (required['line_id'], tuple(required['word_indices'])) not in covered:
            errors.append('required lexical span omitted: ' + required['line_id'])
    return errors


def resolve_source_witnesses(entries, acquisition_roots):
    by_hash = {}
    for root, record in _source_records(acquisition_roots):
        by_hash.setdefault(record['sha256'], (root, record))
    evidence, bindings, gaps = [], {}, []
    for entry in entries:
        dictionary = entry['dictionary']
        digest = dictionary.get('witness_sha256')
        if not dictionary.get('entry_html_sha256'):
            gaps.append({'kind': 'source_adapter_unavailable', 'entry_id': entry['entry_id']})
            continue
        if digest not in by_hash:
            gaps.append({'kind': 'source_witness_missing', 'entry_id': entry['entry_id']})
            continue
        root, record = by_hash[digest]
        raw = corpus.load_cached_witness(root, record)
        parsed = corpus.parse_platts_html(raw.decode(), query=record['query'], url=record['url'], witness_sha256=digest)
        actual = next((item for item in parsed if item['entry_id'] == entry['entry_id']), None)
        support.require(actual is not None, 'source entry absent from original witness')
        for field in ('language', 'lemma', 'source_spellings', 'roman_search_aliases', 'senses'):
            support.require(actual[field] == entry[field], 'source entry differs from witnessed ' + field)
        for field in ('whole_entry_text', 'headword_text', 'entry_html_sha256'):
            support.require(actual['dictionary'][field] == dictionary[field], 'source definition differs from witness')
        # Citation attribution comes from the parser's known source and witnessed locus,
        # never from unchecked metadata attached to an otherwise genuine entry.
        dictionary = actual['dictionary']
        parser = corpus.PlattsParser(raw.decode())
        parser.feed(raw.decode()); parser.close()
        matching = [item['raw'] for item in parser.records if corpus.sha(item['raw'].encode()) == dictionary['entry_html_sha256']]
        support.require(len(matching) == 1, 'source entry quotation absent or ambiguous')
        quote = matching[0]
        eid = 'source:' + entry['entry_id']
        evidence.append({'id': eid, 'kind': 'current_language_usage', 'language': entry['language'],
            'lemma': entry['lemma'], 'work': dictionary['work'], 'locus': dictionary['entry_locator'],
            'source_url': dictionary['url'], 'quotation': quote,
            'quotation_sha256': corpus.sha(quote.encode()), 'witness_sha256': digest,
            'witness_path': str((root/record['path']).resolve()), 'witness_span': None,
            'limitations': ['Historical dictionary usage; full entry contains alternatives, not selected meanings.']})
        bindings[entry['entry_id']] = [eid]
    return {'evidence': evidence, 'entry_evidence_ids': bindings, 'gaps': gaps}


def lookup_english_cached(directory, lemmas, *, edition, cache_dir):
    directory = Path(directory).resolve()
    requested = support.english_queries(lemmas)
    identity = _dictionary_identity(directory, edition)
    root = Path(cache_dir)/'english'/support.digest(identity)
    root.mkdir(parents=True, exist_ok=True)
    rows = {}
    # A shared corpus lock covers the read-missing-write transaction; no provider calls.
    with file_lock(root/'lookup.lock'):
        missing = []
        for lemma in requested:
            path = root/(support.digest(lemma)+'.json')
            if not path.exists():
                missing.append(lemma)
                continue
            cached = support.read_json(path)
            support.require(cached.get('identity') == identity and cached.get('lemma') == lemma,
                            'English cache identity differs')
            support.require(cached.get('sha256') == support.digest(cached['evidence']), 'English cache content changed')
            rows[lemma] = cached['evidence']
        if missing:
            acquired = support.lookup_wordnet(directory, missing, edition=edition)
            for lemma in missing:
                values = [copy.deepcopy(row) for row in acquired if lemma in row['requested_lemmas']]
                for row in values:
                    row['requested_lemmas'] = [lemma]
                    row.pop('witness_path')
                rows[lemma] = values
                _write(root/(support.digest(lemma)+'.json'), {'identity': identity, 'lemma': lemma,
                    'evidence': values, 'sha256': support.digest(values)})
    combined = {}
    for lemma in requested:
        for original in rows[lemma]:
            row = copy.deepcopy(original)
            row['witness_path'] = str(directory/('data.'+next(name for name, pos in support.POS.items() if pos == row['pos'])))
            if row['id'] not in combined:
                combined[row['id']] = row
            elif lemma not in combined[row['id']]['requested_lemmas']:
                combined[row['id']]['requested_lemmas'].append(lemma)
    for row in combined.values():
        row['requested_lemmas'].sort()
        row['grammar'] = support.wordnet_grammar(row)
    return {'evidence': sorted(combined.values(), key=lambda row: row['id']),
            'receipt': support.wordnet_receipt(directory, edition, requested),
            'misses': [lemma for lemma in requested if not rows[lemma]]}


def _english_discovery_query(line, proposal, gloss, bound, languages, context_lines, performance_order):
    context = json.loads(lexical.query_context(line, ' '.join(proposal['surfaces']), languages,
        context_lines=context_lines, performance_order=performance_order))
    decisions = [item for item in gloss['sense_decisions'] if item['word_index'] in proposal['word_indices']]
    chosen = {(choice['entry_id'], choice['sense_id']) for item in decisions for choice in item.get('chosen', [])}
    definitions = [sense['short_english'] for entry in bound.values() for sense in entry['senses']
                   if (entry['entry_id'], sense['sense_id']) in chosen]
    if not definitions:
        definitions = [gloss['word_glosses'][index]['gloss'] for index in proposal['word_indices']]
    # Native source windows and actual source/gloss meanings only. Owner English,
    # previous draft English and catalog descriptions never enter this query.
    return {'source_language': context['language'],
        'source_span': {'roman': proposal['surfaces'], 'word_indices': proposal['word_indices']},
        'source_context': {'target': context['target']['source_text'], 'windows': [
            {side: [item['source_text'] for item in window[side]] for side in ('before', 'after')}
            for window in context['performed_context']]},
        'sense_evidence': definitions,
        'grammatical_role': [item['grammatical_role'] for item in decisions]}


def produce_support(lines, gloss_rows, languages, *, token_candidates, acquisition_roots,
                    wordnet_directory, edition, cache_dir, context_lines, performance_order):
    errors = proposal_errors(lines, gloss_rows, languages)
    support.require(not errors, '; '.join(errors))
    by_line = {line['id']: line for line in lines}
    all_entries = {}
    selected = []
    diagnostics = []
    for row in gloss_rows:
        for gap in row.get('lexical_query_gaps', []):
            diagnostics.append({'kind': 'proposal_unavailable', 'line_id': row['id'], **copy.deepcopy(gap)})
        for proposal in row.get('lexical_queries', []):
            bound = {entry['entry_id']: entry for token in token_candidates[row['id']]
                     if token['word_index'] in proposal['word_indices'] for entry in token['candidates']}
            support.require(set(proposal['source_entry_ids']) <= set(bound), 'source entry not bound to exact language/token')
            all_entries.update(bound)
            selected.append((row, proposal, bound))
    witnessed = resolve_source_witnesses(list(all_entries.values()), acquisition_roots)
    diagnostics.extend(witnessed['gaps'])
    queries = list(dict.fromkeys(word for _, proposal, _ in selected for candidate in proposal['english_candidates']
                                for word in support.english_queries(candidate['english_lemmas'])))
    english = lookup_english_cached(wordnet_directory, queries, edition=edition, cache_dir=cache_dir)
    diagnostics.extend({'kind': 'english_word_unattested', 'lemma': word} for word in english['misses'])
    targets = []
    discovery_config = english_discovery.configuration()
    encoder = lexical.configured_encoder() if discovery_config is not None else None
    discovery_queries = {}
    amended = copy.deepcopy(gloss_rows)
    amended_by = {row['id']: row for row in amended}
    for row, proposal, bound in selected:
        discovered = None
        proposed_candidates = copy.deepcopy(proposal['english_candidates'])
        seeds = list(dict.fromkeys(word for candidate in proposed_candidates
                    for word in support.english_queries(candidate['english_lemmas'])))
        if discovery_config is not None and seeds:
            query = _english_discovery_query(by_line[row['id']], proposal, row, bound, languages,
                                              context_lines, performance_order)
            discovered = english_discovery.discover_english(wordnet_directory, seeds,
                edition=edition, query=query, cache_dir=cache_dir, encoder=encoder,
                space=discovery_config['space'], max_neighbor_synsets=discovery_config['max_neighbor_synsets'],
                max_discovered_lemmas=discovery_config['max_discovered_lemmas'])
            tid = 'lexical:' + row['id'] + ':' + ','.join(map(str, proposal['word_indices']))
            discovery_queries[tid] = query
            diagnostics.extend({'line_id': row['id'], **item} for item in discovered['diagnostics'])
            existing = {support.normalize_english_lemma(item['expression']) for item in proposed_candidates if item['kind'] == 'word'}
            for candidate in discovered['candidates']:
                if candidate['evidence_ids'] and candidate['lemma'] not in existing:
                    proposed_candidates.append({'expression': candidate['lemma'], 'kind': 'word',
                                                'english_lemmas': [candidate['lemma']]})
                    existing.add(candidate['lemma'])
            queries = list(dict.fromkeys(queries + [candidate['lemma'] for candidate in discovered['candidates']]))
            english = lookup_english_cached(wordnet_directory, queries, edition=edition, cache_dir=cache_dir)
        candidates = []
        for proposed in proposed_candidates:
            item = copy.deepcopy(proposed)
            item['english_lemmas'] = support.english_queries(item['english_lemmas'])
            refs = [entry['id'] for entry in english['evidence'] if set(item['english_lemmas']) & set(entry['requested_lemmas'])]
            if item['kind'] == 'word' and not any(support.normalize_english_lemma(item['expression']) in
                [support.normalize_english_lemma(word) for word in entry['lemmas']]
                for entry in english['evidence'] if entry['id'] in refs):
                diagnostics.append({'kind': 'english_word_unattested', 'line_id': row['id'], 'expression': item['expression']})
                continue
            item['english_evidence_ids'] = refs
            item['id'] = 'candidate:' + support.digest(item)[:20]
            candidates.append(item)
        if not candidates:
            diagnostics.append({'kind': 'target_evidence_gap', 'line_id': row['id'], 'word_indices': proposal['word_indices']})
            continue
        indices = proposal['word_indices']
        source_ids = [eid for entry_id in bound for eid in witnessed['entry_evidence_ids'].get(entry_id, [])]
        tid = 'lexical:' + row['id'] + ':' + ','.join(map(str, indices))
        targets.append({'id': tid, 'line_id': row['id'], 'word_indices': indices,
            'surfaces': proposal['surfaces'], 'source_language': lexical.line_language(by_line[row['id']], languages),
            'source_evidence_ids': source_ids, 'background_evidence_ids': [], 'language_link_evidence_ids': [],
            'english_candidates': candidates})
        if discovered is not None:
            targets[-1]['english_discovery'] = {key: copy.deepcopy(value) for key, value in discovered.items() if key != 'evidence'}
        chosen = {choice['entry_id'] for decision in row['sense_decisions'] if decision['word_index'] in indices
                  for choice in decision.get('chosen', [])}
        used = [eid for entry_id in chosen for eid in witnessed['entry_evidence_ids'].get(entry_id, [])]
        reasons = [decision['contextual_reason'] for decision in row['sense_decisions'] if decision['word_index'] in indices]
        amended_by[row['id']].setdefault('support_decisions', []).append({'target_id': tid,
            'used_evidence_ids': used, 'role': 'operative_meaning', 'reason': 'Existing gloss sense decision: ' + '; '.join(reasons)})
    packet = {'version': support.VERSION, 'targets': targets,
              'evidence': witnessed['evidence'] + english['evidence'], 'english_lookup': english['receipt']}
    if targets:
        # Every target retains all alternatives associated with its lookup queries.
        support.validate_support(packet, lines, languages)
    else:
        packet = None
    identity = support.digest({'version': VERSION, 'lines': lines, 'languages': languages,
        'context': context_lines, 'order': performance_order, 'gloss_queries': gloss_rows,
        'support': support.content_digest(packet) if packet else None, 'diagnostics': diagnostics})
    result = {'packet': packet, 'gloss_rows': amended, 'diagnostics': diagnostics, 'identity': identity}
    if discovery_config is not None:
        result['discovery_queries'] = discovery_queries
    return result


def required_spans(options, lines):
    ids = {line['id'] for line in lines}
    found = {}
    feedback = list(getattr(options, 'automatic_lexical_feedback', []) or [])
    feedback.extend(getattr(options, 'semantic_repair_feedback', []) or [])
    for issue in feedback:
        if issue.get('kind') not in {'gloss_sense', 'english_realization', 'frame_relation'}:
            continue
        for ref in issue.get('references', []):
            if ref.get('line_id') in ids:
                indices = ref.get('word_indices', [])
                found[(ref['line_id'], tuple(indices))] = {'line_id': ref['line_id'], 'word_indices': indices}
    return list(found.values())


def gloss_prompt(options, lines):
    if settings(options) is None:
        return ''
    return '\nAUTOMATIC LEXICAL LOOKUP QUERIES:\n' + (
        'For difficult contextual sense or English wording choices, propose lexical_queries in this same response. '
        'Use exact word_indices and surfaces; briefly explain the difficulty in reason. '
        'Supply 1–4 english_candidates with expression, kind (word, compositional_phrase, transparent_compound), '
        'and english_lemmas (at most four distinct lookup words per source span). These are lookup queries, '
        'not accepted translations or invented dictionary definitions. source_entry_ids may name only the '
        'existing source entries bound to these exact tokens above; retain all alternatives. '
        'For missing or uncertain source entries, propose source_queries: up to two dictionary lookup spellings '
        '(prefer native forms/compound headwords when known). These are hypotheses, never invented citations '
        'or authoritative etymologies. Use [] when no extra source lookup is needed. '
        'Use [] for ordinary lines needing no extra lookup. Explicit requested spans must have a proposal '
        'or a lexical_query_gaps item {word_indices,reason}; do not silently omit them. '
        'Compare phrases and compounds intentionally without forcing a coinage. Context embedding scores '
        'only inspire investigation; they do not select a sense.\nRequested spans: ' +
        json.dumps(required_spans(options, lines), ensure_ascii=False) + '\n')


def gloss_schema(schema, options):
    if settings(options) is None:
        return schema
    schema = copy.deepcopy(schema)
    string = {'type': 'string'}
    strings = {'type': 'array', 'items': string}
    indices = {'type': 'array', 'items': {'type': 'integer'}}
    candidate = {'type': 'object', 'properties': {'expression': string,
        'kind': {'type': 'string', 'enum': ['word', 'compositional_phrase', 'transparent_compound']},
        'english_lemmas': strings}, 'required': ['expression', 'kind', 'english_lemmas'], 'additionalProperties': False}
    props = {'word_indices': indices, 'surfaces': strings, 'reason': string, 'source_entry_ids': strings,
             'source_queries': {'type': 'array', 'items': string, 'maxItems': 2},
             'english_candidates': {'type': 'array', 'items': candidate, 'minItems': 1, 'maxItems': MAX_QUERIES}}
    row = schema['properties']['glosses']['items']
    row['properties']['lexical_queries'] = {'type': 'array', 'items': {'type': 'object',
        'properties': props, 'required': list(props), 'additionalProperties': False}}
    row['properties']['lexical_query_gaps'] = {'type': 'array', 'items': {'type': 'object',
        'properties': {'word_indices': indices, 'reason': string},
        'required': ['word_indices', 'reason'], 'additionalProperties': False}}
    row['required'] += ['lexical_queries', 'lexical_query_gaps']
    return schema


def fresh_proposal_errors(lines, rows, languages, options):
    if settings(options) is None:
        return []
    errors = ['automatic lexical query fields missing' for row in rows
              if 'lexical_queries' not in row or 'lexical_query_gaps' not in row]
    return errors + proposal_errors(lines, rows, languages, required_spans(options, lines))


def _legacy_queries(lines, rows, bindings, requested):
    """Fill legacy or newly required spans without a new glossary model call."""
    import re
    wanted = {(ref['line_id'], tuple(ref['word_indices'])) for ref in requested}
    for row in rows:
        legacy = 'lexical_queries' not in row
        proposals = row.setdefault('lexical_queries', [])
        gaps = row.setdefault('lexical_query_gaps', [])
        support.require(isinstance(proposals, list) and isinstance(gaps, list),
                        'lexical query arrays missing')
        covered = {tuple(item['word_indices']) for item in proposals + gaps}
        tokens = {token['word_index']: token for token in bindings[row['id']]}
        spans = {indices for line_id, indices in wanted if line_id == row['id']}
        if legacy:
            spans.update((index,) for index, token in tokens.items() if token['candidates'])
        for indices in sorted(spans - covered):
            support.require(indices and all(type(index) is int and index in tokens for index in indices)
                            and list(indices) == sorted(set(indices)), 'invalid requested lexical indices')
            if len(indices) != 1:
                gaps.append({'word_indices': list(indices),
                    'reason': 'Existing phrase has no bounded lookup proposal; retain contextual review.'})
                continue
            index = indices[0]
            token = tokens[index]
            gloss = row['word_glosses'][index]['gloss'].strip()
            if not re.fullmatch(r"[A-Za-z][A-Za-z'-]*", gloss):
                gaps.append({'word_indices': [index],
                    'reason': 'Existing gloss has no bounded single-word lookup proposal; retain contextual review.'})
                continue
            proposals.append({'word_indices': [index], 'surfaces': [token['roman']],
                'reason': 'Check existing primary gloss against actual English definitions.',
                'source_entry_ids': [entry['entry_id'] for entry in token['candidates']],
                'english_candidates': [{'expression': gloss, 'kind': 'word', 'english_lemmas': [gloss]}]})


def prepare_translation(song_dir, audited, glosses, options):
    import bhakti_translation_policy as policy
    config = settings(options)
    if config is None:
        return options, glosses
    configuration_identity(options)  # Validate configured corpus before cache acceptance.
    if getattr(options, 'semantic_lexical_support', None) is not None or getattr(options, 'lexical_support', None):
        raise ValueError('automatic and explicit lexical support cannot both own a translation')
    local = copy.copy(options)
    augmented = copy.deepcopy(glosses)
    lines = audited['packet']['verified_lines']
    languages = audited['packet'].get('metadata', {}).get('languages', [])
    rows = augmented['packet']['glosses']
    bindings = policy.token_candidates(lines, languages)
    requested = required_spans(options, lines)
    _legacy_queries(lines, rows, bindings, requested)
    errors = proposal_errors(lines, rows, languages, requested)
    support.require(not errors, '; '.join(errors))
    produced = produce_support(lines, rows, languages, token_candidates=bindings,
        acquisition_roots=config['roots'], wordnet_directory=config['directory'], edition=config['edition'],
        cache_dir=config['cache'], context_lines=getattr(options, 'semantic_full_source', lines),
        performance_order=getattr(options, 'semantic_performance_order', audited['packet'].get('performance_order', [])))
    augmented['packet']['glosses'] = produced['gloss_rows']
    if produced['packet'] is not None:
        local.semantic_lexical_support = produced['packet']
    import bhakti_source_discovery as discovery
    source_evidence = discovery.prepare(lines, rows, languages, bindings, config, options)
    if source_evidence is not None:
        local.automatic_source_discovery = source_evidence
        local.automatic_source_discovery_identity = support.content_digest(source_evidence)
    local.automatic_lexical_identity = produced['identity']
    local.automatic_lexical_diagnostics = produced['diagnostics']
    _write(Path(song_dir)/'.transcription/pipeline/automatic-lexical-support.json', produced)
    return local, augmented


def diagnostics_prompt(options):
    diagnostics = getattr(options, 'automatic_lexical_diagnostics', [])
    if not diagnostics:
        return ''
    return ('\nLEXICAL EVIDENCE COVERAGE GAPS:\n' + json.dumps(diagnostics, ensure_ascii=False) +
            '\nA missing adapter or witness is not a dictionary miss. Do not invent a citation or claim '
            'that unavailable evidence was checked. Grammar/context may resolve ordinary meaning; if '
            'the decision actually depends on missing evidence, report the unresolved dependency.\n')

"""Bounded English dictionary exploration and cached, non-selecting sense ranking.

WordNet supplies candidates and all their attested senses. Embeddings only order
those alternatives; they never select a meaning or rewrite a source gloss.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

import bhakti_lexical_retrieval as lexical
import bhakti_lexical_support as support
from bhakti_embedding_client import MAX_INPUT_BYTES, file_lock, validate_vector

VERSION = 1
DEFAULT_SPACE = lexical.DEFAULT_SPACE
MAX_NEIGHBOR_SYNSETS = 8
MAX_DISCOVERED_LEMMAS = 4
POINTERS = {'&', '@', '~'}


PROJECTION_VERSION = 1
MAX_QUERY_PARTS = 32
MAX_EMBEDDING_INPUTS = 64


def _query_evidence(query):
    rows = []
    for index, value in enumerate(query.get('sense_evidence', [])):
        rows.append(('sense_evidence', index, value if isinstance(value, str) else lexical.canonical(value)))
    for index, value in enumerate(query.get('source_hypotheses', [])):
        support.require(value.get('status') == 'lookup_hypothesis' and isinstance(value.get('definition'), str),
                        'source discovery embedding input must remain an unselected hypothesis')
        rows.append(('source_hypothesis', index, value['definition']))
    return rows


def query_projection(query, *, max_parts=MAX_QUERY_PARTS):
    """Lossless evidence/window coverage under our conservative byte policy."""
    support.require(type(max_parts) is int and 1 <= max_parts <= MAX_QUERY_PARTS,
                    'query part allowance must be between one and32')
    evidence = _query_evidence(query)
    context = query['source_context']
    windows = context.get('windows', []) if isinstance(context, dict) else []
    groups = {}
    for index, window in enumerate(windows):
        groups.setdefault(lexical.canonical(window), {'window': window, 'indices': []})['indices'].append(index)
    if not groups:
        groups[''] = {'window': None, 'indices': []}
    def span(role, index, text, start, end):
        return {'role': role, 'index': index, 'start': start, 'end': end,
                'sha256': hashlib.sha256(text.encode()).hexdigest()}
    whole = lexical.canonical(query)
    if len(whole.encode()) <= MAX_INPUT_BYTES:
        return {'complete': True, 'parts': [{'text': whole, 'window_indices': list(range(len(windows))),
                'evidence_slices': [span(role, index, text, 0, len(text)) for role, index, text in evidence]}],
                'diagnostics': []}
    parts = []
    def gap(kind):
        return {'complete': False, 'parts': [], 'diagnostics': [{'kind': kind,
                'required_windows': len(groups), 'max_parts': max_parts}]}
    for group in groups.values():
        base = {key: copy.deepcopy(query[key]) for key in ('source_language', 'source_span', 'grammatical_role')}
        base['source_context'] = (dict(context, windows=[group['window']] if group['window'] is not None else [])
                                  if isinstance(context, dict) else context)
        for role, index, text in evidence or [('context', 0, '')]:
            def encode(start, end):
                value = copy.deepcopy(base)
                if role == 'source_hypothesis':
                    hypothesis = copy.deepcopy(query['source_hypotheses'][index])
                    hypothesis['definition'] = text[start:end]
                    value['source_hypotheses'] = [hypothesis]
                elif role == 'sense_evidence':
                    value['sense_evidence'] = [text[start:end]]
                return lexical.canonical(value)
            if len(encode(0, 0).encode()) > MAX_INPUT_BYTES:
                return gap('query_context_input_too_long')
            start = 0
            while start < len(text) or (start == 0 and not text):
                low, high = start, len(text)
                while low < high:
                    middle = (low + high + 1)//2
                    if len(encode(start, middle).encode()) <= MAX_INPUT_BYTES:
                        low = middle
                    else:
                        high = middle - 1
                if low == start and text:
                    return gap('query_context_input_too_long')
                end = low
                if end < len(text):
                    boundary = max(text.rfind(' ', start, end), text.rfind('\n', start, end))
                    if boundary > start:
                        end = boundary + 1
                parts.append({'text': encode(start, end), 'window_indices': group['indices'],
                    'evidence_slices': [] if role == 'context' else [span(role, index, text, start, end)]})
                if len(parts) > max_parts:
                    return gap('query_part_budget_exhausted')
                if not text:
                    break
                start = end
    return {'complete': True, 'parts': parts, 'diagnostics': []}


def _group_scores(parts, values):
    """Weight spans within whole items, then distinct contexts; never pick a sense."""
    groups = {}
    for part, value in zip(parts, values):
        window = tuple(part['window_indices'])
        for item in part['evidence_slices'] or [{'role': 'context', 'index': 0, 'start': 0, 'end': 1}]:
            group = groups.setdefault((item['role'], item['index']), {})
            totals = group.setdefault(window, [0., 0])
            length = max(1, item['end'] - item['start'])
            totals[0] += value * length
            totals[1] += length
    output = []
    for (role, index), windows in groups.items():
        rows = [{'window_indices': list(window), 'score': total/length}
                for window, (total, length) in windows.items()]
        output.append({'role': role, 'index': index, 'window_scores': rows,
                       'score': sum(row['score'] for row in rows)/len(rows)})
    return output

def configuration():
    if os.environ.get('BHAKTI_ENGLISH_DISCOVERY') != '1':
        return None
    return {'version': VERSION, 'projection_version': PROJECTION_VERSION, 'max_query_parts': MAX_QUERY_PARTS,
            'max_embedding_inputs': MAX_EMBEDDING_INPUTS, 'max_neighbor_synsets': MAX_NEIGHBOR_SYNSETS,
            'max_discovered_lemmas': MAX_DISCOVERED_LEMMAS, 'space': copy.deepcopy(DEFAULT_SPACE)}


def _content(row):
    value = copy.deepcopy(row)
    value.pop('witness_path', None)
    return value


def _pointers(row):
    fields = row['raw'].partition('|')[0].split()
    # Existing parser validates the complete row, including lexical indices.
    support.parse_wordnet_row(row['raw'], row['synset_offset'], row['pos'])
    cursor = 4 + 2 * int(fields[3], 16)
    count = int(fields[cursor]); cursor += 1
    for _ in range(count):
        pointer, offset, pos, indices = fields[cursor:cursor + 4]
        cursor += 4
        if pointer in POINTERS and indices == '0000':
            yield pointer, int(offset), 'a' if pos == 's' else pos


def _neighbor(directory, edition, manifest, pos, offset):
    name = next(name for name, code in support.POS.items() if code == pos)
    path = directory / ('data.' + name)
    if name not in manifest['available_pos'] or not path.exists():
        return None
    with path.open('rb') as stream:
        stream.seek(offset)
        raw = stream.readline()
    # Sparse test corpora have holes. A missing record is an exploration gap,
    # never a license to parse bytes from the next available synset.
    if not raw or not raw[:8].isdigit() or int(raw[:8]) != offset:
        return None
    text = raw.decode('ascii')
    words, gloss = support.parse_wordnet_row(text, offset, pos)
    return {'id': f'wordnet:{edition}:{pos}:{offset:08d}', 'kind': 'english_definition',
        'language': 'en', 'edition': edition, 'pos': pos, 'synset_offset': offset,
        'lemmas': words, 'requested_lemmas': [], 'gloss': gloss, 'raw': text,
        'work': 'Princeton WordNet ' + edition, 'locus': f'data.{name}:{offset:08d}',
        'source_url': manifest.get('source', 'https://wordnet.princeton.edu/'),
        'witness_path': str(path.resolve()), 'witness_sha256': manifest['data_sha256'][name],
        'limitations': ['Explored synset; complete candidate senses require all-POS lookup.']}


def _write(path, payload):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
        temp = Path(stream.name)
    temp.chmod(0o600)
    temp.replace(path)


def _vectors(cache_dir, jobs, space, encoder):
    root = Path(cache_dir) / 'english-discovery-vectors' / support.digest(space)
    root.mkdir(parents=True, exist_ok=True)
    values = {}
    with file_lock(root / 'vectors.lock'):
        missing = []
        for key, identity in jobs.items():
            path = root / (key + '.json')
            if path.exists():
                cached = support.read_json(path)
                support.require(cached.get('identity') == identity, 'English vector cache identity mismatch')
                support.require(cached.get('sha256') == support.digest(cached.get('vector')),
                                'English vector cache content changed')
                validate_vector(cached['vector'], space['dimensions'])
                values[key] = cached['vector']
            else:
                missing.append((key, identity))
        if encoder is not None:
            for start in range(0, len(missing), 16):
                batch = missing[start:start + 16]
                vectors = encoder.embed([item['text'] for _, item in batch])
                support.require(isinstance(vectors, list) and len(vectors) == len(batch),
                                'English encoder cardinality differs')
                # Validate the whole batch before accepting any of its vectors.
                for vector in vectors:
                    validate_vector(vector, space['dimensions'])
                for (key, identity), vector in zip(batch, vectors):
                    _write(root / (key + '.json'), {'identity': identity, 'vector': vector,
                                                  'sha256': support.digest(vector)})
                    values[key] = vector
    return values


def discover_english(directory, seeds, *, edition, query, cache_dir, encoder=None,
                     space=DEFAULT_SPACE, max_neighbor_synsets=MAX_NEIGHBOR_SYNSETS,
                     max_discovered_lemmas=MAX_DISCOVERED_LEMMAS,
                     max_embedding_inputs=MAX_EMBEDDING_INPUTS):
    directory = Path(directory).resolve()
    seeds = support.english_queries(seeds)
    support.require(1 <= len(seeds) <= 4, 'English discovery needs one to four seed lemmas')
    support.require(type(max_neighbor_synsets) is int and 0 <= max_neighbor_synsets <= 128,
                    'English neighbor allowance must be between zero and128')
    support.require(type(max_discovered_lemmas) is int and 0 <= max_discovered_lemmas <= 32,
                    'English new lemma allowance must be between zero and32')
    support.require(isinstance(query, dict) and all(key in query for key in
        ('source_language', 'source_span', 'source_context', 'sense_evidence', 'grammatical_role')),
        'English discovery needs source context, evidence and grammar')
    support.require(isinstance(space, dict) and type(space.get('dimensions')) is int and
                    space['dimensions'] > 0 and all(key in space for key in DEFAULT_SPACE),
                    'English discovery needs a complete embedding space')
    support.require(type(max_embedding_inputs) is int and 1 <= max_embedding_inputs <= MAX_EMBEDDING_INPUTS,
                    'embedding input allowance must be between one and64')
    seed_rows = support.lookup_wordnet(directory, seeds, edition=edition)
    receipt = support.wordnet_receipt(directory, edition, [])
    receipt.pop('directory')
    manifest_path = directory / 'manifest.json'
    manifest = support.read_json(manifest_path) if manifest_path.exists() else {
        'available_pos': list(support.POS), 'data_sha256': {
            name: receipt['files']['data.' + name] for name in support.POS}}
    coverage = manifest.get('complete_for_lemmas')
    if coverage is not None:
        coverage = set(support.english_queries(coverage))
    diagnostics = []
    if not lexical.language(query['source_language']):
        diagnostics.append({'kind': 'source_language_unknown', 'language': query['source_language']})
    routes = {seed: [{'kind': 'seed'}] for seed in seeds}
    targets = {}
    for row in seed_rows:
        for lemma in row['lemmas']:
            lemma = support.normalize_english_lemma(lemma)
            routes.setdefault(lemma, []).append({'kind': 'same_synset', 'from_evidence_id': row['id']})
        for pointer, offset, pos in _pointers(row):
            targets.setdefault((pos, offset), []).append({'pointer': pointer, 'from_evidence_id': row['id']})
    ordered = sorted(targets)
    explored = []
    for pos, offset in ordered[:max_neighbor_synsets]:
        row = _neighbor(directory, edition, manifest, pos, offset)
        if row is None:
            diagnostics.append({'kind': 'neighbor_witness_unavailable', 'pos': pos, 'offset': offset,
                                'routes': targets[(pos, offset)]})
            continue
        explored.append({**_content(row), 'routes': copy.deepcopy(targets[(pos, offset)])})
        for lemma in row['lemmas']:
            lemma = support.normalize_english_lemma(lemma)
            for route in targets[(pos, offset)]:
                routes.setdefault(lemma, []).append({**route, 'to_evidence_id': row['id']})
    pool_rows = {row['id']: _content(row) for row in seed_rows}
    for row in explored:
        pool_rows.setdefault(row['id'], row)
    projection = query_projection(query)
    if len(projection['parts']) > max_embedding_inputs:
        projection = {'complete': False, 'parts': [], 'diagnostics': [{'kind': 'query_embedding_budget_exhausted'}]}
    diagnostics.extend(projection['diagnostics'])
    query_large = not projection['complete']
    jobs = {}
    def add(text, kind, evidence_hash=''):
        identity = {'version': VERSION, 'space': space, 'text': text, 'kind': kind,
                    'evidence_hash': evidence_hash}
        key = support.digest(identity)
        jobs[key] = identity
        return key
    qkeys = [] if query_large else [add(part['text'], 'query') for part in projection['parts']]
    omitted_documents = set()
    documents = {}
    for row in pool_rows.values():
        document = lexical.canonical({**{key: row[key] for key in
            ('lemmas', 'gloss', 'pos', 'work', 'locus', 'source_url')},
            'grammar': support.wordnet_grammar(row)})
        if len(document.encode()) > MAX_INPUT_BYTES:
            documents[row['id']] = None
        elif not query_large and len(jobs) >= max_embedding_inputs:
            omitted_documents.add(row['id'])
        elif not query_large:
            # Lookup/query bookkeeping does not change the dictionary definition.
            evidence_hash = support.digest({key: row[key] for key in
                ('id', 'raw', 'witness_sha256', 'lemmas', 'gloss', 'pos', 'work', 'locus', 'source_url')})
            documents[row['id']] = add(document, 'definition', evidence_hash)
    vectors = _vectors(cache_dir, jobs, space, encoder) if jobs else {}
    def score(eid):
        dkey = documents.get(eid)
        value = None
        part_scores, group_scores = [], []
        if query_large:
            status = 'query_input_too_long' if any(item['kind'] == 'query_context_input_too_long'
                for item in projection['diagnostics']) else 'query_coverage_incomplete'
        elif any(key not in vectors for key in qkeys):
            status = 'partial_query_vectors' if any(key in vectors for key in qkeys) else 'query_not_cached'
        elif eid not in pool_rows:
            status = 'outside_ranked_pool'
        elif eid in omitted_documents:
            status = 'embedding_budget_exhausted'
        elif dkey is None:
            status = 'input_too_long'
        elif dkey not in vectors:
            status = 'document_not_cached'
        else:
            right = vectors[dkey]
            for index, key in enumerate(qkeys):
                left = vectors[key]
                similarity = sum(a*b for a,b in zip(left,right)) / (
                    math.sqrt(sum(a*a for a in left)) * math.sqrt(sum(b*b for b in right)))
                part_scores.append({'part_index': index, 'score': similarity})
            group_scores = _group_scores(projection['parts'], [row['score'] for row in part_scores])
            value = max(row['score'] for row in group_scores)
            status = 'ranked'
        return {'evidence_id': eid, 'score': value, 'status': status,
                'part_scores': part_scores, 'group_scores': group_scores}
    pool_scores = {eid: score(eid) for eid in pool_rows}
    def lemma_order(lemma):
        values = [pool_scores[eid]['score'] for eid, row in pool_rows.items()
                  if lemma in [support.normalize_english_lemma(word) for word in row['lemmas']]
                  and pool_scores[eid]['score'] is not None]
        return (not values, -max(values) if values else 0, lemma)
    nonseed = sorted(set(routes) - set(seeds), key=lemma_order)
    complete = list(seeds)
    for lemma in nonseed:
        if coverage is not None and lemma not in coverage:
            diagnostics.append({'kind': 'english_coverage_unavailable', 'lemma': lemma})
            continue
        if len(complete) - len(seeds) < max_discovered_lemmas:
            complete.append(lemma)
    evidence = support.lookup_wordnet(directory, complete, edition=edition)
    candidates = []
    for lemma in complete:
        ids = [row['id'] for row in evidence if lemma in row['requested_lemmas']]
        if not ids:
            diagnostics.append({'kind': 'english_word_unattested', 'lemma': lemma})
        scores = [score(eid) for eid in ids]
        scores.sort(key=lambda row: (row['score'] is None, -(row['score'] or 0), row['evidence_id']))
        candidates.append({'lemma': lemma, 'evidence_ids': ids, 'scores': scores,
                           'discovered_by': routes[lemma]})
    packet = {'seed_lemmas': seeds, 'candidates': candidates, 'evidence': evidence,
        'pool': {'seed_evidence_ids': [row['id'] for row in seed_rows],
                 'neighbor_synsets_visited': len(explored),
                 'neighbor_synsets_omitted': max(0, len(ordered) - max_neighbor_synsets),
                 'discovered_lemmas_omitted': len(nonseed) - (len(complete) - len(seeds)),
                 'max_neighbor_synsets': max_neighbor_synsets,
                 'max_discovered_lemmas': max_discovered_lemmas,
                 'records': list(pool_rows.values()), 'limitations': ['bounded_pool_not_exhaustive']},
        'diagnostics': diagnostics, 'query_coverage': projection}
    packet['identity'] = support.content_digest({'version': VERSION, 'projection_version': PROJECTION_VERSION,
        'max_embedding_inputs': max_embedding_inputs, 'space': space, 'query': query,
        'dictionary': receipt, 'max_neighbor_synsets': max_neighbor_synsets,
        'max_discovered_lemmas': max_discovered_lemmas, **packet})
    return packet

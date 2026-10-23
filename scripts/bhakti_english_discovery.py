"""Bounded English dictionary exploration and cached, non-selecting sense ranking.

WordNet supplies candidates and all their attested senses. Embeddings only order
those alternatives; they never select a meaning or rewrite a source gloss.
"""
from __future__ import annotations

import copy
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


def configuration():
    if os.environ.get('BHAKTI_ENGLISH_DISCOVERY') != '1':
        return None
    return {'version': VERSION, 'max_neighbor_synsets': MAX_NEIGHBOR_SYNSETS,
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
                     max_discovered_lemmas=MAX_DISCOVERED_LEMMAS):
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
    text = lexical.canonical(query)
    query_large = len(text.encode()) > MAX_INPUT_BYTES
    jobs = {}
    def add(text, kind, evidence_hash=''):
        identity = {'version': VERSION, 'space': space, 'text': text, 'kind': kind,
                    'evidence_hash': evidence_hash}
        key = support.digest(identity)
        jobs[key] = identity
        return key
    qkey = None if query_large else add(text, 'query')
    documents = {}
    for row in pool_rows.values():
        document = lexical.canonical({**{key: row[key] for key in
            ('lemmas', 'gloss', 'pos', 'work', 'locus', 'source_url')},
            'grammar': support.wordnet_grammar(row)})
        if len(document.encode()) > MAX_INPUT_BYTES:
            documents[row['id']] = None
        elif not query_large:
            # Lookup/query bookkeeping does not change the dictionary definition.
            evidence_hash = support.digest({key: row[key] for key in
                ('id', 'raw', 'witness_sha256', 'lemmas', 'gloss', 'pos', 'work', 'locus', 'source_url')})
            documents[row['id']] = add(document, 'definition', evidence_hash)
    vectors = _vectors(cache_dir, jobs, space, encoder) if jobs else {}
    def score(eid):
        dkey = documents.get(eid)
        value = None
        if query_large:
            status = 'query_input_too_long'
        elif qkey not in vectors:
            status = 'query_not_cached'
        elif eid not in pool_rows:
            status = 'outside_ranked_pool'
        elif dkey is None:
            status = 'input_too_long'
        elif dkey not in vectors:
            status = 'document_not_cached'
        else:
            left, right = vectors[qkey], vectors[dkey]
            value = sum(a*b for a,b in zip(left,right)) / (
                math.sqrt(sum(a*a for a in left)) * math.sqrt(sum(b*b for b in right)))
            status = 'ranked'
        return {'evidence_id': eid, 'score': value, 'status': status}
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
        'diagnostics': diagnostics}
    packet['identity'] = support.content_digest({'version': VERSION, 'space': space, 'query': query,
        'dictionary': receipt, 'max_neighbor_synsets': max_neighbor_synsets,
        'max_discovered_lemmas': max_discovered_lemmas, **packet})
    return packet

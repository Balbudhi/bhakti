"""Reviewed shuffle metadata, independent feature freshness and publication gates.

The public projection is optional ranking input, never song eligibility. Reviewed
summaries are repository editorial records, not cryptographic proof a model was
correct; raw extraction and independent review remain in private assessment caches.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile

SCHEMA_VERSION = 1
POLICY = 'data/shuffle-profile-policy.json'
REVIEWS = 'data/shuffle-profile-reviews.json'
TAXONOMY = 'data/shuffle-taxonomy.json'
PUBLIC = 'data/shuffle-profiles.js'
TEXT_REPAIRS = 'data/translation-repair-reviews.json'


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_hash(path: Path) -> str:
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def meaning(field, value):
    """Word-link markers are presentation; the assessment never receives them."""
    return re.sub(r'\{[^:{}]*:([^{}]*)\}', r'\1', value) if field == 'english' and isinstance(value, str) else value


def semantic_input_hash(reader: dict, taxonomy: dict) -> str:
    """Hash consumed meaning, not transport URLs, onset timings or presentation."""
    sequence = reader.get('SONG_SEQUENCE', [])
    ids = list(dict.fromkeys(row['ref'] for row in sequence))
    lines = reader.get('SONG_LINES', {})
    fields = ('source', 'roman', 'sourceLanguage', 'english', 'words', 'grammarNote')
    projection = {
        'version': 2,
        'lines': {key: {field: meaning(field, lines[key].get(field)) for field in fields} for key in ids},
        'sequence': [{key: row.get(key) for key in ('ref', 'section', 'repeats')} for row in sequence],
        'languages': reader['SONG_META'].get('languages', []),
        'subjectTags': reader['SONG_META'].get('subjectTags', []),
        'taxonomy': taxonomy,
    }
    return digest(projection)


def audio_input_hash(media_sha256: str) -> str:
    # Physical features consume retained bytes. Trim provenance is independently
    # checked by the existing boundary gate; changed retained bytes invalidate us.
    require_hash(media_sha256, 'audio media hash')
    return digest({'version': 1, 'retainedMediaSha256': media_sha256})


def require_hash(value, label):
    if not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{64}', value) is None:
        raise ValueError(f'{label} must be a SHA-256 digest')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate profile key: {key}')
        result[key] = value
    return result


def read_json(path: Path):
    return json.loads(path.read_text(), object_pairs_hook=_unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f'nonfinite JSON: {value}')))


def atomic_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(text); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def enabled(root: Path) -> bool:
    root = Path(root)
    if (root / POLICY).is_file():
        return True
    installed = any((root / name).exists() for name in (REVIEWS, PUBLIC, 'assets/shuffle.js'))
    if not installed:
        for path in [root / 'index.html', *root.glob('songs/*/index.html')]:
            if path.is_file() and re.search(r'(?:shuffle-profiles|assets/shuffle)\.js', path.read_text()):
                installed = True; break
    if installed:
        raise ValueError('shuffle profile policy missing from installed feature')
    return False


def _review(record, *, expected_lines=None):
    if not isinstance(record, dict):
        raise ValueError('assessment review missing')
    require_hash(record.get('recordHash'), 'review record hash')
    if record.get('kind') == 'independent-model':
        extraction, review = record.get('extractionRequestIds'), record.get('reviewRequestIds')
        if (not isinstance(extraction, list) or not extraction or not isinstance(review, list) or not review
                or any(not isinstance(x, str) or not x.strip() for x in extraction + review)
                or set(extraction).intersection(review)):
            raise ValueError('independent review request identities missing or reused')
        if expected_lines is not None and record.get('coveredLineCount') != expected_lines:
            raise ValueError('independent review coverage differs from performed lines')
    elif record.get('kind') == 'human':
        if not isinstance(record.get('reason'), str) or not record['reason'].strip():
            raise ValueError('reviewed fallback needs its substantive disposition')
    else:
        raise ValueError('unsupported assessment review kind')


def _number(value, label, minimum=None, maximum=None, nullable=False):
    if value is None and nullable:
        return None
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            or minimum is not None and value < minimum or maximum is not None and value > maximum):
        raise ValueError(f'invalid {label}')
    return value


def _subject_tag_revision(part, reader, taxonomy, *, root, slug):
    """Validate a public name-reference correction, not a new model assessment.

    The original model input and features stay authoritative for the semantic
    dimensions. Only subjectTags may differ, and the real reviewed registry must
    produce those tags from the original tags with still-performed evidence.
    """
    from tag_taxonomy import apply_reviewed_subject_tags
    revision = part.get('subjectTagRevision')
    fields = {'version', 'priorTags', 'originalInputHash', 'inputHash', 'evidenceHash'}
    if (root is None or not slug or not isinstance(revision, dict)
            or set(revision) != fields or type(revision.get('version')) is not int
            or revision['version'] != 1):
        raise ValueError('subject tag revision requires its repository and supported binding')
    prior_tags = revision['priorTags']
    if (not isinstance(prior_tags, list)
            or any(not isinstance(tag, str) or not tag.strip() for tag in prior_tags)
            or len(set(prior_tags)) != len(prior_tags)):
        raise ValueError('subject tag revision prior tags invalid')
    for key in ('originalInputHash', 'inputHash', 'evidenceHash'):
        require_hash(revision[key], f'subject tag revision {key}')
    current_hash = semantic_input_hash(reader, taxonomy)
    original_reader = copy.deepcopy(reader)
    original_reader['SONG_META']['subjectTags'] = list(prior_tags)
    if (revision['originalInputHash'] != part.get('inputHash')
            or semantic_input_hash(original_reader, taxonomy) != part.get('inputHash')
            or revision['inputHash'] != current_hash
            or prior_tags == reader['SONG_META'].get('subjectTags', [])):
        raise ValueError('subject tag revision is stale or changes assessed meaning')
    try:
        registry = read_json(Path(root) / 'data/song_tag_overrides.json')
        evidence = registry['songs'][slug]
    except (OSError, KeyError, TypeError) as exc:
        raise ValueError('subject tag revision reviewed registry record missing') from exc
    if digest(evidence) != revision['evidenceHash']:
        raise ValueError('subject tag revision evidence changed; review required')
    apply_reviewed_subject_tags(original_reader['SONG_META'], slug,
        reader['SONG_LINES'], reader['SONG_SEQUENCE'], root=Path(root))
    if original_reader['SONG_META']['subjectTags'] != reader['SONG_META'].get('subjectTags', []):
        raise ValueError('subject tag revision includes unreviewed tag changes')


def reviewed_subject_tag_revision(root, slug, reader, record, *, prior_tags):
    """Prepare an amendment from the stored assessment without changing it.

    Callers supply the original assessed tags, retain every existing assessment
    field, and store only this returned object as semantic.subjectTagRevision.
    A previous amendment may be replaced when the registry review changes; the
    original tags/hash still anchor all non-tag meaning to the model assessment.
    """
    root = Path(root)
    policy, reviews, taxonomy = _configuration(root)
    queue_id = hashlib.blake2s(slug.encode(), digest_size=4).hexdigest()
    if (not isinstance(record, dict) or record.get('slug') != slug
            or record != reviews['profiles'].get(queue_id)):
        raise ValueError('subject tag revision must retain the stored assessment record')
    if 'editorialTextRevision' in record.get('semantic', {}):
        # An already-current combined amendment is an idempotent retag. New tag
        # changes need the combined text receipt reviewed, not an implicit rebase.
        part = record['semantic']
        if part.get('subjectTagRevision', {}).get('priorTags') != prior_tags:
            raise ValueError('subject tag revision original tags differ from the text amendment')
        _qualified(part, 'semantic', reader, policy)
        _semantic(part, reader, taxonomy, root=root, slug=slug)
        return copy.deepcopy(part['subjectTagRevision'])
    original_reader = copy.deepcopy(reader)
    original_reader['SONG_META']['subjectTags'] = copy.deepcopy(prior_tags)
    part = copy.deepcopy(record.get('semantic'))
    if not isinstance(part, dict):
        raise ValueError('subject tag revision requires an existing semantic assessment')
    part.pop('subjectTagRevision', None)
    _qualified(part, 'semantic', original_reader, policy)
    _semantic(part, original_reader, taxonomy)
    try:
        evidence = read_json(root / 'data/song_tag_overrides.json')['songs'][slug]
    except (OSError, KeyError, TypeError) as exc:
        raise ValueError('subject tag revision reviewed registry record missing') from exc
    revision = {'version': 1, 'priorTags': copy.deepcopy(prior_tags),
                'originalInputHash': part['inputHash'],
                'inputHash': semantic_input_hash(reader, taxonomy), 'evidenceHash': digest(evidence)}
    part['subjectTagRevision'] = revision
    _subject_tag_revision(part, reader, taxonomy, root=root, slug=slug)
    return revision


def _text_repair_evidence(root, slug):
    try:
        registry = read_json(Path(root) / TEXT_REPAIRS)
        if type(registry.get('version')) is not int or registry['version'] != 1:
            raise ValueError('unsupported text repair registry version')
        evidence = registry['songs'][slug]
    except (OSError, KeyError, TypeError) as exc:
        raise ValueError('text revision reviewed repair receipt missing') from exc
    return evidence


def _editorial_text_revision(part, reader, taxonomy, *, root, slug):
    """Validate a source review, never claim the model assessed corrected text.

    Hashes bind the receipt to actual text; they do not prove its review is true.
    The reviewer must check every retained feature against the corrected meaning.
    Unsupported features may only be reduced, and unresolved changes stay blocked.
    """
    revision = part.get('editorialTextRevision')
    fields = {'version', 'priorLines', 'originalInputHash', 'inputHash',
              'evidenceHash', 'baseFeaturesHash'}
    if (root is None or not slug or not isinstance(revision, dict)
            or set(revision) != fields or type(revision.get('version')) is not int
            or revision['version'] != 1):
        raise ValueError('text revision requires its repository and supported binding')
    for key in ('originalInputHash', 'inputHash', 'evidenceHash', 'baseFeaturesHash'):
        require_hash(revision[key], f'text revision {key}')
    evidence = _text_repair_evidence(root, slug)
    if not isinstance(evidence, dict) or digest(evidence) != revision['evidenceHash']:
        raise ValueError('text revision evidence changed; review required')
    review = evidence.get('reviewer')
    if (not isinstance(review, dict) or review.get('kind') != 'assistant-source-review'
            or not isinstance(review.get('reason'), str) or not review['reason'].strip()):
        raise ValueError('text revision needs an explicit assistant source-review disposition')
    prior, after, line_evidence = (evidence.get(key) for key in ('beforeLines', 'afterLines', 'lineEvidence'))
    line_ids = {row['ref'] for row in reader['SONG_SEQUENCE']}
    if (not isinstance(prior, dict) or not prior or not isinstance(after, dict)
            or not isinstance(line_evidence, dict) or set(prior) != set(after)
            or set(prior) != set(line_evidence) or not set(prior).issubset(line_ids)
            or revision['priorLines'] != prior):
        raise ValueError('text revision needs exact reviewed performed before/after lines')
    restored = copy.deepcopy(reader)
    for key in prior:
        if (not isinstance(prior[key], dict) or not isinstance(after[key], dict)
                or prior[key] == after[key] or reader['SONG_LINES'].get(key) != after[key]
                or not isinstance(line_evidence[key], str) or not line_evidence[key].strip()):
            raise ValueError('text revision changed line differs from its reviewed source evidence')
        restored['SONG_LINES'][key] = copy.deepcopy(prior[key])
    if (revision['originalInputHash'] != part.get('inputHash')
            or revision['inputHash'] != semantic_input_hash(reader, taxonomy)
            or revision['baseFeaturesHash'] != digest(part.get('features'))):
        raise ValueError('text revision current input or original feature binding is stale')
    if 'subjectTagRevision' in part:
        # The tag amendment remains the original receipt for the intermediate
        # tag-only state; do not rewrite it as if it had assessed the new text.
        _subject_tag_revision(part, restored, taxonomy, root=root, slug=slug)
        from tag_taxonomy import apply_reviewed_subject_tags
        meta = copy.deepcopy(reader['SONG_META'])
        meta['subjectTags'] = copy.deepcopy(part['subjectTagRevision']['priorTags'])
        apply_reviewed_subject_tags(meta, slug, reader['SONG_LINES'], reader['SONG_SEQUENCE'], root=Path(root))
        if meta.get('subjectTags', []) != reader['SONG_META'].get('subjectTags', []):
            raise ValueError('text revision invalidates current tag evidence')
    elif semantic_input_hash(restored, taxonomy) != part.get('inputHash'):
        raise ValueError('text revision does not reconstruct the original assessed reader')
    expected = {(facet, row['id'], row.get('role')) for facet in ('themes', 'actions', 'subjects')
                for row in part.get('features', {}).get(facet, [])}
    dispositions = evidence.get('featureDispositions')
    if not isinstance(dispositions, list):
        raise ValueError('text revision feature dispositions missing')
    seen = set()
    for row in dispositions:
        if not isinstance(row, dict):
            raise ValueError('text revision feature disposition invalid')
        identity = (row.get('facet'), row.get('id'), row.get('role'))
        if (identity not in expected or identity in seen
                or set(row) - {'facet', 'id', 'role', 'factor', 'disposition', 'reason', 'sourceLineIds'}
                or row.get('facet') != 'subjects' and 'role' in row):
            raise ValueError('text revision must review every original feature exactly once')
        seen.add(identity)
        factor = _number(row.get('factor'), 'text revision reduction factor', 0, 1)
        ids = row.get('sourceLineIds')
        if (row.get('disposition') != ('retain' if factor == 1 else 'reduce')
                or not isinstance(row.get('reason'), str) or not row['reason'].strip()
                or not isinstance(ids, list) or not ids or len(set(ids)) != len(ids)
                or any(not isinstance(key, str) or key not in line_ids for key in ids)):
            raise ValueError('text revision feature needs its explicit source-bound disposition')
    if seen != expected:
        raise ValueError('text revision must review every original feature exactly once')
    if not expected and (not isinstance(evidence.get('emptyFeatureDisposition'), str)
                         or not evidence['emptyFeatureDisposition'].strip()):
        raise ValueError('text revision must explicitly review an empty semantic classification')
    return dispositions


def reviewed_editorial_text_revision(root, slug, reader, record):
    """Prepare only an amendment from a real stored assessment and repair receipt."""
    root = Path(root)
    policy, reviews, taxonomy = _configuration(root)
    queue_id = hashlib.blake2s(slug.encode(), digest_size=4).hexdigest()
    if (not isinstance(record, dict) or record.get('slug') != slug
            or record != reviews['profiles'].get(queue_id)):
        raise ValueError('text revision must retain the stored assessment record')
    part = copy.deepcopy(record.get('semantic'))
    if not isinstance(part, dict):
        raise ValueError('text revision requires the original semantic assessment')
    evidence = _text_repair_evidence(root, slug)
    revision = {'version': 1, 'priorLines': copy.deepcopy(evidence.get('beforeLines')),
                'originalInputHash': part.get('inputHash'),
                'inputHash': semantic_input_hash(reader, taxonomy),
                'baseFeaturesHash': digest(part.get('features')), 'evidenceHash': digest(evidence)}
    part['editorialTextRevision'] = revision
    _qualified(part, 'semantic', reader, policy)
    _semantic(part, reader, taxonomy, root=root, slug=slug)
    return revision


def _semantic(part, reader, taxonomy, *, root=None, slug=None):
    text_dispositions = []
    if 'editorialTextRevision' in part:
        text_dispositions = _editorial_text_revision(part, reader, taxonomy, root=root, slug=slug)
    elif 'subjectTagRevision' in part:
        _subject_tag_revision(part, reader, taxonomy, root=root, slug=slug)
    elif part.get('inputHash') != semantic_input_hash(reader, taxonomy):
        raise ValueError('semantic profile stale; reassess current reader')
    if part.get('assessment') != 'reviewed' or part.get('outcome') not in {'known', 'unknown'}:
        raise ValueError('semantic assessment is not completed and reviewed')
    method = part.get('method', {})
    if not method.get('id') or not method.get('version'):
        raise ValueError('semantic assessment method missing')
    line_ids = {row['ref'] for row in reader['SONG_SEQUENCE']}
    count = sum(bool(reader['SONG_LINES'][key].get('source', '').strip()) for key in line_ids)
    _review(part.get('review'), expected_lines=count)
    allowed = {row['id']: row.get('facet') for row in taxonomy.get('concepts', [])}
    entities = taxonomy.get('entities', [])
    allowed_entities = set(entities) if isinstance(entities, dict) else {row['id'] for row in entities}
    features = part.get('features', {})
    result = {'status': 'accepted'}
    for facet, key in [('theme', 'themes'), ('action', 'actions'), ('entity', 'subjects')]:
        rows = features.get(key)
        if not isinstance(rows, list):
            raise ValueError(f'semantic {key} must be an array')
        seen = set(); output = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('id'), str):
                raise ValueError(f'invalid semantic {key} entry')
            concept = row['id']
            if facet == 'entity':
                if concept not in allowed_entities or row.get('role') not in {'worship_focus', 'narrative_subject'}:
                    raise ValueError('semantic subject identity or role unknown')
                identity = (concept, row['role'])
            else:
                if allowed.get(concept) != facet:
                    raise ValueError('semantic concept outside its taxonomy facet')
                identity = concept
            if identity in seen:
                raise ValueError('duplicate semantic feature')
            seen.add(identity)
            weight = _number(row.get('weight'), 'semantic weight', 0, 1)
            output.append({'id': concept, **({'role': row['role']} if facet == 'entity' else {}), 'weight': weight})
        if sum(row['weight'] for row in output) > 1.000000001:
            raise ValueError('semantic facet mass exceeds one')
        result[key] = output
    present = any(result[key] for key in ('themes', 'actions', 'subjects'))
    if (part['outcome'] == 'known') != present:
        raise ValueError('semantic outcome contradicts accepted features')
    if not present and not str(part.get('reason', '')).strip():
        raise ValueError('semantic unknown needs an assessment reason')
    _apply_editorial_reductions(part, result, line_ids)
    for disposition in text_dispositions:
        rows = result[disposition['facet']]
        for row in list(rows):
            if (row['id'], row.get('role')) == (disposition['id'], disposition.get('role')):
                if disposition['factor'] == 0:
                    rows.remove(row)
                else:
                    row['weight'] *= disposition['factor']
    return result


def _apply_editorial_reductions(part, result, line_ids):
    """Apply separately reviewed reductions without changing model evidence."""
    if not any(key in part for key in ('editorialReview', 'editorialAdjustments')):
        return
    review, adjustments = part.get('editorialReview'), part.get('editorialAdjustments')
    if (not isinstance(review, dict) or review.get('kind') != 'independent-assistant'
            or review.get('inputHash') != part['inputHash']
            or review.get('baseFeaturesHash') != digest(part['features'])):
        raise ValueError('editorial review source or base feature binding invalid; review required')
    require_hash(review.get('evidenceHash'), 'editorial evidence hash')
    if not isinstance(adjustments, list):
        raise ValueError('editorial adjustments must be an array paired with review')
    seen = set()
    for adjustment in adjustments:
        if not isinstance(adjustment, dict):
            raise ValueError('editorial adjustment must be an object')
        facet, identity, role = adjustment.get('facet'), adjustment.get('id'), adjustment.get('role')
        if (facet not in {'themes', 'actions', 'subjects'} or not isinstance(identity, str)
                or set(adjustment) - {'facet', 'id', 'role', 'factor', 'reason', 'sourceLineIds'}
                or facet != 'subjects' and 'role' in adjustment):
            raise ValueError('editorial feature target invalid')
        target = (facet, identity, role)
        if target in seen:
            raise ValueError('duplicate editorial adjustment')
        seen.add(target)
        matching = [row for row in result[facet] if row['id'] == identity and row.get('role') == role]
        if len(matching) != 1:
            raise ValueError('editorial adjustment must target an existing feature and exact role')
        reason, evidence_lines = adjustment.get('reason'), adjustment.get('sourceLineIds')
        if (not isinstance(reason, str) or not reason.strip() or not isinstance(evidence_lines, list)
                or not evidence_lines or any(not isinstance(key, str) or key not in line_ids for key in evidence_lines)
                or len(set(evidence_lines)) != len(evidence_lines)):
            raise ValueError('editorial adjustment requires a reason and current performed source line IDs')
        factor = _number(adjustment.get('factor'), 'editorial reduction factor', 0, 1)
        row = matching[0]
        if factor == 0:
            result[facet].remove(row)
        else:
            row['weight'] *= factor


def _audio(part, media_hash):
    if part.get('mediaSha256') != media_hash or part.get('inputHash') != audio_input_hash(media_hash):
        raise ValueError('audio profile stale; reassess retained listener bytes')
    require_hash(part.get('methodFingerprint'), 'audio method fingerprint')
    assessment, outcome = part.get('assessment'), part.get('outcome')
    if assessment not in {'measured', 'reviewed'} or outcome not in {'known', 'unknown', 'unmetered'}:
        raise ValueError('audio assessment is incomplete')
    if assessment == 'reviewed':
        _review(part.get('review'))
    elif outcome != 'known':
        raise ValueError('unknown audio requires reviewed disposition')
    result = {'status': 'accepted'}
    if outcome == 'known':
        physical = part.get('physical')
        if not isinstance(physical, dict) or not isinstance(physical.get('whole'), dict):
            raise ValueError('audio known outcome lacks measured physical features')
        whole = {}
        for key in ('integratedLufs', 'truePeakDbfs', 'rmsDbfs', 'centroidHz'):
            whole[key] = _number(physical['whole'].get(key), f'audio {key}',
                                 minimum=0 if key == 'centroidHz' else -200,
                                 maximum=200000 if key == 'centroidHz' else 30, nullable=True)
        if not any(value is not None for value in whole.values()):
            raise ValueError('audio known outcome has no physical measurement')
        windows = {}
        for key, row in physical.get('profiles', {}).items():
            if key not in {'beginning', 'body', 'end'} or not isinstance(row, dict):
                raise ValueError('audio physical window invalid')
            clean = {name: _number(row.get(name), f'audio {name}', 0) for name in ('startSeconds', 'endSeconds')}
            if clean['endSeconds'] <= clean['startSeconds']:
                raise ValueError('audio window interval invalid')
            for name in ('rmsDbfs', 'centroidHz'):
                clean[name] = _number(row.get(name), f'audio {name}', 0 if name == 'centroidHz' else -200,
                                      200000 if name == 'centroidHz' else 30, nullable=True)
            windows[key] = clean
        result['physical'] = {'whole': whole, 'profiles': windows}
    elif part.get('physical'):
        raise ValueError('unknown audio outcome cannot carry claimed physical features')
    return result



def semantic_text_bytes(reader):
    ids = list(dict.fromkeys(row['ref'] for row in reader['SONG_SEQUENCE']))
    return len(json.dumps({key: {field: meaning(field, reader['SONG_LINES'][key].get(field))
        for field in ('source', 'roman', 'sourceLanguage', 'english', 'words', 'grammarNote')} for key in ids},
                          ensure_ascii=False, separators=(',', ':')).encode())


def _qualified(part, kind, reader, qualification):
    if not isinstance(qualification, dict):
        raise ValueError('qualification policy missing')
    if part.get('qualificationVersion') != qualification.get('qualificationVersion'):
        raise ValueError('qualification version differs')
    rule = qualification.get('methods', {}).get(kind)
    if not isinstance(rule, dict) or rule.get('qualified') is not True or not rule.get('evidenceRevision'):
        raise ValueError('qualification method has no accepted evidence revision')
    if part.get('evidenceRevision') != rule['evidenceRevision']:
        raise ValueError('qualification evidence revision differs')
    review = part.get('review', {})
    if (part.get('assessment') == 'reviewed' and part.get('outcome') in {'unknown', 'unmetered'}
            and review.get('kind') in qualification.get('fallbackKinds', [])):
        _review(review)
        return
    method = part.get('method', {})
    if any(method.get(key) != rule.get(key) for key in ('id', 'version')):
        raise ValueError('qualification method differs')
    if kind == 'semantic':
        if method.get('fingerprint') != rule.get('fingerprint'):
            raise ValueError('qualification semantic recipe differs')
        if method.get('model') != rule.get('model'):
            raise ValueError('qualification model differs')
        projection_fields = ('projectionVersion', 'projectionFingerprint')
        if any(key in side for side in (method, rule) for key in projection_fields):
            version = method.get('projectionVersion')
            if (type(version) is not int or version < 1 or type(rule.get('projectionVersion')) is not int or
                    any(not rule.get(key) or method.get(key) != rule[key] for key in projection_fields)):
                raise ValueError('qualification semantic projection contract differs')
            require_hash(method.get('projectionFingerprint'), 'qualification semantic projection fingerprint')
        languages = reader['SONG_META'].get('languages', [])
        if not languages or not set(languages).issubset(rule.get('languages', [])):
            raise ValueError('qualification language outside supported domain')
        if len({row['ref'] for row in reader['SONG_SEQUENCE']}) > rule.get('maxLines', 0):
            raise ValueError('qualification line count outside supported domain')
        if semantic_text_bytes(reader) > rule.get('maxTextBytes', 0):
            raise ValueError('qualification text size outside supported domain')
        for field in ('sourceStatus', 'translationStatus'):
            if field in rule and reader['SONG_META'].get(field) not in rule[field]:
                raise ValueError('qualification reviewed-text status outside supported domain')
    else:
        if rule.get('fingerprint'):
            if method.get('fingerprint') != rule['fingerprint']:
                raise ValueError('qualification audio method signature differs')
        elif part.get('methodFingerprint') not in rule.get('recipeFingerprints', []):
            raise ValueError('qualification audio recipe differs')
        domain = part.get('domain', {})
        if domain.get('codec') not in rule.get('codecs', []) or domain.get('sampleRate') not in rule.get('sampleRates', []):
            raise ValueError('qualification audio codec or sample rate outside supported domain')
        _number(domain.get('channels'), 'qualification channels', 1, rule.get('maxChannels', 0))
        if 'channels' in rule and domain.get('channels') not in rule['channels']:
            raise ValueError('qualification channels outside supported domain')
        _number(domain.get('durationSeconds'), 'qualification duration',
                rule.get('minDurationSeconds', 0.001), rule.get('maxDurationSeconds', 0))

def project_song_profile(queue_id, slug, reader, taxonomy, media_hash, record, *, required, qualification=None,
                         root=None):
    """Reject incomplete new intake; unavailable legacy dimensions remain neutral."""
    if record and record.get('slug') != slug:
        raise ValueError(f'{slug}: profile belongs to another song')
    output = {}
    for key, validator in [('semantic', lambda part: _semantic(part, reader, taxonomy, root=root, slug=slug)),
                           ('audio', lambda part: _audio(part, media_hash))]:
        try:
            part = record.get(key) if isinstance(record, dict) else None
            if not isinstance(part, dict):
                raise ValueError(f'{key} profile missing')
            _qualified(part, key, reader, qualification)
            output[key] = validator(part)
        except (ValueError, KeyError, TypeError) as exc:
            if required:
                raise ValueError(f'{slug}: {key} profile publication blocked: {exc}') from exc
            output[key] = {'status': 'unavailable'}
    return output


def _configuration(root):
    policy, reviews, taxonomy = (read_json(root / path) for path in (POLICY, REVIEWS, TAXONOMY))
    if (policy.get('schemaVersion') != 1 or not isinstance(policy.get('legacySongs'), dict)
            or reviews.get('schemaVersion') != 1 or not isinstance(reviews.get('profiles'), dict)
            or taxonomy.get('schemaVersion') != 1):
        raise ValueError('shuffle profile configuration schema invalid')
    for queue_id, slug in policy['legacySongs'].items():
        if (not isinstance(slug, str) or Path(slug).name != slug
                or hashlib.blake2s(slug.encode(), digest_size=4).hexdigest() != queue_id):
            raise ValueError('legacy policy song identity invalid')
    return policy, reviews, taxonomy


def recording_sha256(root, slug, reader):
    """Resolve the actual first listener source, never title/duration equivalence."""
    from urllib.parse import urlparse
    sources = reader.get('SONG_META', {}).get('audioSources', [])
    if not sources or not isinstance(sources[0], dict):
        raise ValueError(f'{slug}: listener source missing')
    src = sources[0].get('src', '')
    parsed = urlparse(src)
    if not parsed.scheme and not parsed.netloc:
        if Path(src).name != src or not src.startswith('audio.'):
            raise ValueError(f'{slug}: invalid local listener path')
        return file_hash(root / 'songs' / slug / src)
    manifest_path = root / 'data/media.json'
    manifest = read_json(manifest_path) if manifest_path.is_file() else {}
    matching = [row for row in manifest.get('songs', {}).get(slug, []) if row.get('src') == src]
    if len(matching) != 1:
        raise ValueError(f'{slug}: listener source lacks one exact media-manifest identity')
    fingerprint = matching[0].get('sha256'); require_hash(fingerprint, 'listener media hash')
    local = root / 'songs' / slug / ('audio' + Path(parsed.path).suffix)
    if local.is_file() and file_hash(local) != fingerprint:
        raise ValueError(f'{slug}: local listener bytes differ from published media identity')
    return fingerprint


def require_song_profile(root, slug, reader):
    root = Path(root)
    if not enabled(root):
        return None
    policy, reviews, taxonomy = _configuration(root)
    queue_id = hashlib.blake2s(slug.encode(), digest_size=4).hexdigest()
    required = policy['legacySongs'].get(queue_id) != slug
    try:
        media_hash = recording_sha256(root, slug, reader)
    except (ValueError, OSError):
        if required: raise
        media_hash = None
    return project_song_profile(queue_id, slug, reader, taxonomy, media_hash,
                                reviews['profiles'].get(queue_id, {}), required=required, qualification=policy, root=root)


def parse_javascript_sources(sources):
    """Parse the exact supplied bytes once, with the real JS reader consumer."""
    program = """const fs=require('fs'),vm=require('vm');const input=JSON.parse(fs.readFileSync(0,'utf8'));let out={};for(const [name,source] of Object.entries(input)){let ctx={window:{}};vm.runInNewContext(source,ctx,{filename:name,timeout:1000});out[name]=ctx.window;}process.stdout.write(JSON.stringify(out));"""
    result = subprocess.run(['node', '-e', program], input=json.dumps(sources),
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def load_catalogue(root):
    path = Path(root) / 'data/songs.js'
    return parse_javascript_sources({'catalogue': path.read_text()})['catalogue']


def build_public_profiles(root, catalogue):
    root = Path(root)
    if not enabled(root): return None
    policy, reviews, taxonomy = _configuration(root)
    ids = [row['queueId'] for row in catalogue]
    slugs = [row['slug'] for row in catalogue]
    if len(set(ids)) != len(ids) or len(set(slugs)) != len(slugs):
        raise ValueError('duplicate catalogue profile identity')
    if any(hashlib.blake2s(row['slug'].encode(), digest_size=4).hexdigest() != row['queueId'] for row in catalogue):
        raise ValueError('catalogue profile identity differs from song')
    actual_slugs = {path.parent.name for path in (root / 'songs').glob('*/data.js')}
    if set(slugs) != actual_slugs:
        raise ValueError('catalogue profile population differs from published readers')
    # Retained reviews for withdrawn songs are allowed but never projected.
    raw = {slug: (root / 'songs' / slug / 'data.js').read_bytes() for slug in slugs}
    readers = parse_javascript_sources({slug: value.decode('utf-8') for slug, value in raw.items()})
    projected, dependencies = {}, {}
    for row in catalogue:
        slug, queue_id = row['slug'], row['queueId']; reader = readers[slug]
        required = policy['legacySongs'].get(queue_id) != slug
        try:
            media_hash = recording_sha256(root, slug, reader)
        except (ValueError, OSError):
            if required: raise
            media_hash = None
        projected[queue_id] = project_song_profile(queue_id, slug, reader, taxonomy, media_hash,
            reviews['profiles'].get(queue_id, {}), required=required, qualification=policy, root=root)
        dependencies[queue_id] = {'slug': slug, 'readerSha256': hashlib.sha256(raw[slug]).hexdigest(),
                                  'mediaSha256': media_hash}
    document = {'schemaVersion': 1, 'taxonomyVersion': taxonomy.get('vocabularyVersion'), 'profiles': projected}
    document['revision'] = digest({'projection': document, 'dependencies': dependencies})
    return document


def public_javascript(document):
    return 'window.BHAKTI_SHUFFLE_PROFILES = ' + json.dumps(document, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + ';\n'


def validate_public_profiles(root, *, required=True):
    root = Path(root)
    if not enabled(root):
        if required: raise ValueError('shuffle profile policy required')
        return None
    loaded = load_catalogue(root)
    expected = build_public_profiles(root, loaded.get('BHAKTI_SONGS', []))
    public_path = root / PUBLIC
    if not public_path.is_file(): raise ValueError('shuffle profile public projection missing')
    actual = parse_javascript_sources({'profiles': public_path.read_text()})['profiles'].get('BHAKTI_SHUFFLE_PROFILES')
    if actual != expected or loaded.get('BHAKTI_SHUFFLE_REVISION') != expected['revision']:
        raise ValueError('shuffle profile snapshot or catalogue revision stale; regenerate paired catalogue/profiles')
    return expected


def publish_catalogue(root, catalogue):
    """Prepare both strings first. Assembly rejects any interrupted paired write."""
    root = Path(root)
    document = build_public_profiles(root, catalogue)
    text = 'window.BHAKTI_SONGS = ' + json.dumps(catalogue, ensure_ascii=False, indent=2) + ';\n'
    if document is not None:
        text += 'window.BHAKTI_SHUFFLE_REVISION = ' + json.dumps(document['revision']) + ';\n'
        atomic_text(root / PUBLIC, public_javascript(document))
    atomic_text(root / 'data/songs.js', text)
    return document


def stamp_qualification(part, kind, policy):
    """Attach an approved policy identity; callers still validate its domain."""
    part = copy.deepcopy(part)
    part['qualificationVersion'] = policy.get('qualificationVersion')
    part['evidenceRevision'] = policy.get('methods', {}).get(kind, {}).get('evidenceRevision')
    return part


def store_reviewed_profile(root, slug, reader, media_hash, record):
    """Merge one validated summary without losing another song worker's result."""
    from bhakti_boundary_timebase import boundary_transaction
    root = Path(root)
    with boundary_transaction(root / 'data'):
        policy, reviews, taxonomy = _configuration(root)
        queue_id = hashlib.blake2s(slug.encode(), digest_size=4).hexdigest()
        record = copy.deepcopy(record)
        previous = reviews['profiles'].get(queue_id, {})
        incoming, existing = record.get('semantic'), previous.get('semantic')
        editorial_fields = ('editorialReview', 'editorialAdjustments')
        if (previous.get('slug') == slug and isinstance(incoming, dict) and isinstance(existing, dict)
                and incoming.get('inputHash') == existing.get('inputHash')
                and not any(key in incoming for key in editorial_fields)):
            for key in editorial_fields:
                if key in existing:
                    incoming[key] = copy.deepcopy(existing[key])
        project_song_profile(queue_id, slug, reader, taxonomy, media_hash, record,
                             required=True, qualification=policy, root=root)
        reviews['profiles'][queue_id] = record
        atomic_text(root / REVIEWS, json.dumps(reviews, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def assess_song_profiles(root, slug, reader, audio_path, options, snapshot):
    """Run only the new assessment stages; caller provides a frozen input snapshot.

    The intake coordinator already owns provider spending/deadline/concurrency.
    This function is deliberately absent from all generation-only code paths.
    """
    from bhakti_boundary_timebase import boundary_transaction, require_boundary_snapshot
    import bhakti_shuffle_audio as audio
    import bhakti_shuffle_semantics as semantics
    root = Path(root); song_dir = root / 'songs' / slug
    policy, _, taxonomy = _configuration(root)
    model = options.model
    anticipated = stamp_qualification({'assessment': 'reviewed', 'outcome': 'known', 'method': {
        'id': 'source-grounded-semantic-review', 'version': semantics.METHOD_VERSION,
        'model': model, 'fingerprint': semantics.semantic_method_fingerprint(model),
        'projectionVersion': semantics.PROJECTION_VERSION,
        'projectionFingerprint': semantics.projection_fingerprint()}}, 'semantic', policy)
    _qualified(anticipated, 'semantic', reader, policy)
    cache = song_dir / '.transcription/pipeline/shuffle'
    media_hash = file_hash(Path(audio_path))
    audio_receipt = audio.analyze_audio(Path(audio_path), expected_sha256=media_hash, cache_path=cache / 'audio.json')
    audio_part = stamp_qualification(audio.audio_summary(audio_receipt), 'audio', policy)
    _qualified(audio_part, 'audio', reader, policy)
    semantic_options = semantics.SemanticOptions(model=model, allow_paid=True,
        timeout=getattr(options, 'timeout', 300), deadline_at=getattr(options, 'unit_deadline_at', None))
    semantic_record = semantics.assess_semantics(reader, taxonomy, options=semantic_options, cache_dir=cache / 'semantic')
    semantic_part = stamp_qualification(semantics.semantic_summary(reader, taxonomy, semantic_record), 'semantic', policy)
    record = {'slug': slug, 'semantic': semantic_part, 'audio': audio_part}
    with boundary_transaction(song_dir):
        require_boundary_snapshot(song_dir, snapshot)
        if file_hash(Path(audio_path)) != media_hash:
            raise ValueError('shuffle assessment recording changed before adoption')
        store_reviewed_profile(root, slug, reader, media_hash, record)
    return record

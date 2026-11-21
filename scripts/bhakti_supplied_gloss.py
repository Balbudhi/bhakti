"""Immutable assistant-authored glossary candidates, never provider results.

The document owns all linguistic rows. Normal semantic acceptance still owns
quality approval. File hashes bind the document and its editorial provenance.
"""
import copy
import hashlib
import json
from pathlib import Path


def _read_reference(reference, *, json_document=True):
    if not isinstance(reference, dict) or not isinstance(reference.get('path'), str):
        raise ValueError('provided glossary requires a file reference')
    path = Path(reference['path']).expanduser().resolve()
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != reference.get('sha256'):
        raise ValueError('provided glossary reference changed: ' + path.name)
    return (json.loads(raw) if json_document else raw), {'path': str(path), 'sha256': reference['sha256']}


def freeze_reference(value):
    """Resolve the complete input closure before the existing budget is frozen."""
    if isinstance(value, str):
        path = Path(value).expanduser().resolve()
        value = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    document, reference = _read_reference(value)
    provenance = document.get('provenance')
    if not isinstance(provenance, list) or not {'author', 'review'} <= {
            item.get('role') for item in provenance if isinstance(item, dict)}:
        raise ValueError('provided glossary requires author and review references')
    closure = []
    for item in provenance:
        _, checked = _read_reference(item, json_document=False)
        closure.append({'role': item.get('role'), **checked})
    if 'provenance' in value and value['provenance'] != closure:
        raise ValueError('provided glossary provenance closure changed')
    return {**reference, 'provenance': closure}


def validate_identity(pipeline, song_dir, audited, document):
    semantic = pipeline.bhakti_semantic_repair
    languages = audited['packet'].get('metadata', {}).get('languages')
    if (document.get('version') != 1 or document.get('origin') != 'assistant-editorial'
            or document.get('slug') != song_dir.name
            or document.get('source_languages') != languages
            or document.get('source_sha256') != semantic.digest(semantic.source_evidence(pipeline, song_dir, audited))
            or document.get('policy_sha256') != semantic.digest(pipeline.translation_policy_payload())
            or document.get('gloss_contract_version') != pipeline.GLOSS_CONTRACT_VERSION):
        raise ValueError('provided glossary source, policy or origin mismatch')
    if {'provider', 'resolved_model', 'usage', 'fingerprint', 'producer_fingerprint',
            'semantic_repair_version', 'source_gloss_receipt'} & document.keys():
        raise ValueError('provided glossary cannot claim provider or acceptance provenance')


def load(pipeline, song_dir, audited, job, options):
    if 'providedGlosses' not in job:
        return None
    if not isinstance(job['providedGlosses'], dict):
        raise ValueError('provided glossary must be hash-bound before execution')
    reference = freeze_reference(job['providedGlosses'])
    document, _ = _read_reference(reference)
    validate_identity(pipeline, song_dir, audited, document)
    semantic = pipeline.bhakti_semantic_repair
    languages = audited['packet'].get('metadata', {}).get('languages')
    packet = document.get('packet')
    rows = packet.get('glosses') if isinstance(packet, dict) else None
    lines = audited['packet']['verified_lines']
    if (not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)
            or [row.get('id') for row in rows] != [row['id'] for row in lines]):
        raise ValueError('provided glossary requires complete ordered source IDs')
    errors = pipeline.prepared_gloss_contract_errors(lines, rows, languages, options)
    for row in rows:
        if not isinstance(row.get('grammar_note'), str):
            errors.append(str(row.get('id')) + ' lacks authored grammar')
        if row.get('uncertainty') != '':
            errors.append(str(row.get('id')) + ' has unresolved or missing uncertainty assessment')
    if errors:
        raise ValueError('provided glossary violates current source contract: ' + str(errors[:3]))
    result = {'origin': 'assistant-editorial', 'supplied_input': reference,
              'packet': copy.deepcopy(packet), 'gloss_contract_version': pipeline.GLOSS_CONTRACT_VERSION,
              'sense_languages': languages, 'fingerprint': semantic.digest({'providedGlosses': reference})}
    source = pipeline.bhakti_source_discovery.projected(
        getattr(options, 'automatic_source_discovery', None), [line['id'] for line in lines])
    receipt = pipeline.bhakti_source_discovery.source_gloss_receipt(source)
    if receipt is not None:
        result['source_gloss_receipt'] = receipt
    return result


def assert_locked(glosses, supplied=None):
    """Compare actual authored rows, even if an outer cache checksum was rebuilt."""
    if supplied is None:
        if not isinstance(glosses, dict) or glosses.get('origin') != 'assistant-editorial':
            return
        reference = glosses.get('supplied_input')
    else:
        reference = supplied['supplied_input']
    checked = freeze_reference(reference)
    document, _ = _read_reference(checked)
    if (not isinstance(glosses, dict) or glosses.get('origin') != 'assistant-editorial'
            or glosses.get('supplied_input') != checked
            or glosses.get('packet') != document.get('packet')):
        raise RuntimeError('supplied glossary authored packet changed')
    return document

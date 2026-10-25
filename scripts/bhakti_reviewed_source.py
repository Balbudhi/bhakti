"""Reviewed source annotations for immutable accepted intake evidence.

Opt-in local reviewer declarations derive a separate source view without rewriting
provider results. Source acquisition, timing and semantic review remain separate.

Operations
-------------------
prepare(song_dir, audited) -> effective audited view
    Without .transcription/reviewed-source-corrections.json and without an existing
    derived view: return the supplied audited object unchanged, no writes/calls.
    Otherwise require supplied original == exact stored 02-transcript-audit.json;
    validate its _source_route through router.read_unit_cache, accepted status,
    matching fingerprint/result digest and exact full original result projection.
    Do not treat a caller's recomputed file hash as proof of routed acceptance.

    Declaration format (strict keys):
      {version:1, original_audit_sha256:<exact file bytes>, corrections:[
        {line_id:<existing ID>, before:{roman?:str,language?:str},
         after:{same keys}, evidence:{reviewer:str,source_url:str,
                                    location:str,reason:str}}]}
    Only roman/language are editable. Each line occurs at most once. Before values
    exactly match the original. Reject empty/no-op edits, unknown IDs/keys, stale
    hash, missing reviewer evidence, unrecognized target language, or non-Latin
    romanization. This declaration records human review; a URL alone is not an
    automatic claim that external evidence or the recording was checked.

    A language annotation updates the effective language and canonical
    sourceLanguage together. Rebuild metadata.languages from the complete effective
    vocal-row population, requiring a recognized language for every vocal row when
    any language annotation is supplied. Do not map 'Gurbani' globally to Punjabi;
    assign each reviewed row explicitly. Instrumental rows need no invented language.
    Source native text, IDs, row order, kind, notes, every performance occurrence,
    uncertainty, raw segment evidence and all unrelated fields remain exact.

    Persist the derived view at .transcription/pipeline/02-reviewed-source.json.
    It must NOT expose the old _source_route as though the model produced corrected
    rows. Its reviewed_source declaration binds original/declaration SHA256, embeds
    the reviewed declaration, and binds the effective packet digest; original route
    lives unchanged in the original audit. The embedded prior declaration allows
    validating an older view before a newly reviewed declaration supersedes it.
    Writes are atomic. An existing matching valid view is read without rewriting.
    A changed declaration creates a newly derived view only after validation; retain
    predecessor privately. Corrupted existing content or missing declaration holds.
    Never edit/delete 02, router evidence, source audio, timing or semantic caches.

load(song_dir) -> effective audited view
    Read-only generation/acceptance loader. Without an active declaration or saved
    view, use raw02 as before. With either present, require BOTH original accepted
    raw02 and the current matching saved derived view/declaration; do not recreate
    missing evidence from song-packet.audit or silently rebuild a corrupt view.

require_current(song_dir, audited) -> None
    Read-only final gate: independently reconstruct expected effective view from
    original accepted evidence+current declaration, validate saved derived bytes,
    and require exact supplied effective packet/proof. Original packet cannot bypass
    an active correction. Missing/corrupted declaration/view or underlying routed
    candidate holds. No annotation/view remains a backward-compatible no-op.

Caller joins
-------------------------------------------------------
1. run_one: after validated audit, before align/complete, prepare the effective view.
   Do not run the old mutating apply_verified_text_corrections on routed artifacts.
2. Direct align, complete_semantics and _generate: require_current before any
   cached acceptance, downstream work or writes. semantic_repair.complete also
   validates before its dictionary/model preflight, for callers using it directly.
   semantic_repair.source_evidence validates the supplied effective view before
   hashing; require_acceptance uses load when no audited view was supplied, checks
   explicit supplied views, including the pre-marker legacy return boundary.
   Generate-only reconstructs the same effective view, rather than reading raw02
   and silently reverting corrections. Direct final callers cannot bypass this gate.
   hydrate_pipeline_artifacts must not restore raw02 from a derived summary: an
   active overlay with missing original proof holds before any hydration write.
   _execute_intake_jobs generate-only uses load after hydration. The raw source
   audit operation and its raw02 cache remain unchanged. Historical trim/adoption
   readers are out of scope; no overlay may be treated as a model-source receipt.
3. Existing source_evidence hashes effective rows/order, hence semantic identity
   changes with roman/language. Timing display_occurrences includes roman but not
   language: roman edits invalidate exact timing input; language-only edits reuse
   unchanged timing. Evidence prose changes alone do not change effective inputs.
   No broad cache deletion, hidden source rerun, budget extension, or new model stage.
4. Preserve source metadata/intake identity and immutable absolute proof origins.
   Raw segment audio evidence remains unchanged; it is not relabelled corrected.

Qualification boundaries
------------------------
Tests use genuine synthetic source routes/storage and actual identity/generation
entrypoints, replacing only provider responses and downstream stages outside the
claimed seam. They cannot prove linguistic correctness of an annotation. Review
of source evidence and actual adopted output remains required. This operation does not authorize model calls or publication.
"""

from __future__ import annotations

import copy
import hashlib
import json
import unicodedata
from pathlib import Path

import bhakti_lexical_retrieval as lexical
import bhakti_model_routes as routes
import bhakti_source_stages as stages


def _fail(detail):
    raise ValueError('reviewed source: ' + detail)


def _paths(song_dir):
    private = Path(song_dir) / '.transcription'
    return (private / 'reviewed-source-corrections.json',
            private / 'pipeline/02-transcript-audit.json',
            private / 'pipeline/02-reviewed-source.json')


def active(song_dir):
    declaration, _, derived = _paths(song_dir)
    return declaration.exists() or derived.exists()


def _read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                _fail('duplicate JSON key in ' + path.name)
            result[key] = value
        return result
    try:
        value = json.loads(path.read_text(), object_pairs_hook=unique)
    except (OSError, ValueError) as exc:
        _fail('cannot read ' + path.name + ': ' + str(exc))
    if not isinstance(value, dict):
        _fail(path.name + ' must be an object')
    return value


def _original(path):
    value = _read(path)
    if value.get('segment_audits'):
        _fail('segmented source annotations are not supported by this scoped operation')
    declaration = value.get('_source_route')
    if not isinstance(declaration, dict) or not isinstance(declaration.get('input_fingerprint'), str):
        _fail('original audit has no bound accepted source route')
    try:
        stages._checked_projection(value, declaration['input_fingerprint'])
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        _fail('original routed evidence is invalid: ' + str(exc))
    if stages.source_errors(value, audited=True):
        _fail('original audit has unresolved source structure or uncertainty')
    return value, hashlib.sha256(path.read_bytes()).hexdigest()


def _derive(original, original_sha256, declaration):
    if (set(declaration) != {'version', 'original_audit_sha256', 'corrections'}
            or type(declaration['version']) is not int or declaration['version'] != 1
            or declaration['original_audit_sha256'] != original_sha256):
        _fail('declaration differs from exact original audit')
    corrections = declaration['corrections']
    if not isinstance(corrections, list) or not corrections:
        _fail('corrections must be a nonempty list')
    result = copy.deepcopy(original)
    result.pop('_source_route')
    rows = {row['id']: row for row in result['packet']['verified_lines']}
    seen = set()
    language_changed = False
    for correction in corrections:
        if not isinstance(correction, dict) or set(correction) != {'line_id', 'before', 'after', 'evidence'}:
            _fail('correction has unsupported fields')
        lid = correction['line_id']
        if not isinstance(lid, str) or lid not in rows or lid in seen:
            _fail('correction has duplicate or unknown line ID')
        seen.add(lid)
        before, after, evidence = (correction[key] for key in ('before', 'after', 'evidence'))
        if (not isinstance(before, dict) or not isinstance(after, dict) or not before
                or set(before) != set(after) or set(before) - {'roman', 'language'}
                or before == after):
            _fail('correction must change only explicit roman/language fields')
        if (not isinstance(evidence, dict) or set(evidence) != {'reviewer', 'source_url', 'location', 'reason'}
                or any(not isinstance(value, str) or not value.strip() for value in evidence.values())
                or not evidence['source_url'].startswith(('https://', 'http://'))):
            _fail('correction lacks explicit reviewer/source/location/reason evidence')
        row = rows[lid]
        for key, value in after.items():
            if before[key] != row.get(key) or not isinstance(value, str) or not value.strip():
                _fail('correction before-value is stale or after-value is blank')
            if key == 'roman':
                if any(unicodedata.category(char).startswith('L') and 'LATIN' not in unicodedata.name(char, '')
                       for char in value):
                    _fail('corrected romanization contains non-Latin letters')
            else:
                code = lexical.language(value)
                if not code:
                    _fail('corrected language is unrecognized')
                row['sourceLanguage'] = code
                language_changed = True
            row[key] = value
    if language_changed:
        names = {}
        for name, code in lexical.LANGUAGES.items():
            names.setdefault(code, name.capitalize())
        languages = []
        for row in result['packet']['verified_lines']:
            if row.get('kind') == 'instrumental':
                continue
            code = lexical.language(row.get('sourceLanguage') or row.get('language'))
            if not code:
                _fail('language correction leaves a vocal row without reviewed language')
            if row.get('language') and lexical.language(row['language']) != code:
                _fail('effective source language fields disagree')
            if names[code] not in languages:
                languages.append(names[code])
        result['packet'].setdefault('metadata', {})['languages'] = languages
    result['reviewed_source'] = {
        'version': 1, 'original_audit_sha256': original_sha256,
        'declaration_sha256': stages.digest(declaration), 'declaration': copy.deepcopy(declaration),
        'effective_packet_sha256': stages.digest(result['packet'])}
    return result


def _saved(path, original, original_hash):
    value = _read(path)
    proof = value.get('reviewed_source')
    if not isinstance(proof, dict) or not isinstance(proof.get('declaration'), dict):
        _fail('derived view lacks its reviewed declaration')
    if value != _derive(original, original_hash, proof['declaration']):
        _fail('derived view differs from its original and reviewed declaration')
    return value


def prepare(song_dir, audited):
    """Create/reuse a derived view, preserving all original source route evidence."""
    declaration_path, original_path, target = _paths(song_dir)
    if not active(song_dir):
        return audited
    original, original_hash = _original(original_path)
    if audited != original:
        _fail('preparation requires the exact original accepted audit')
    declaration = _read(declaration_path)
    expected = _derive(original, original_hash, declaration)
    if target.exists():
        saved = _saved(target, original, original_hash)
        if saved == expected:
            return saved
        archive = target.parent / 'reviewed-source-history' / (hashlib.sha256(target.read_bytes()).hexdigest() + '.json')
        if not archive.exists():
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_bytes(target.read_bytes())
    routes.atomic_json(target, expected)
    return expected


def load(song_dir):
    """Read-only selection; missing/corrupt proof never falls back to raw source."""
    declaration_path, original_path, target = _paths(song_dir)
    if not active(song_dir):
        return _read(original_path) if original_path.exists() else None
    original, original_hash = _original(original_path)
    expected = _derive(original, original_hash, _read(declaration_path))
    saved = _saved(target, original, original_hash)
    if saved != expected:
        _fail('saved view does not match the current reviewed declaration; prepare it first')
    return saved


def require_current(song_dir, audited):
    """Verify the effective source at direct timing, semantic and release gates."""
    if not active(song_dir) and not (isinstance(audited, dict) and 'reviewed_source' in audited):
        return
    if not active(song_dir):
        _fail('derived view has no current declaration or saved evidence')
    if audited != load(song_dir):
        _fail('supplied audit is not the current reviewed source view')


def corrected_languages(audited):
    """After require_current, override caller languages only for a language review."""
    proof = audited.get('reviewed_source')
    if proof and any('language' in item['after'] for item in proof['declaration']['corrections']):
        return list(audited['packet']['metadata']['languages'])
    return None

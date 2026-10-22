"""Small, cited lexical candidates and shared Bhakti editorial instructions.

Retrieval does not select a sense or rewrite a lyric. Exact token matching keeps
unrelated compounds and diacritically distinct words out of the candidate set.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_VERSION = 2
RULES = """BHAKTI CONTEXTUAL TRANSLATION POLICY
Read every target and its neighboring lines before choosing meanings. Establish
speaker, addressee, agent, action/state, object, negation, tense and relationship.
Choose the supported contextual sense, not the first dictionary definition or
the most familiar devotional synonym. The primary word gloss is that chosen
meaning. Record materially different supported alternatives and the reason for
the choice in the grammar note; alternatives must not contradict the meaning
actually used in the English. If source or gloss evidence conflicts, flag the
conflict for reconstruction rather than making the English agree with an error.

Translate ordinary words and philosophical concepts into precise English, using
a short contextual phrase when no single word works. A term's membership in the
legacy preserved-term registry is not a command to leave it untranslated. Keep
genuine proper names, with their evidenced identity, relationship or literal
meaning in the clickable gloss. Distinguish a person's name from a descriptive
epithet; explain the epithet's operative meaning rather than flattening every
divine title to Lord. Do not manufacture etymologies from a modern artist name.

Keep the poem's concrete images, repetition, direct address, tenderness, boldness,
wordplay and unusual agency. Supply English function words and natural syntax
without adding theology or replacing the image. Transparent English compounds
are welcome when the source supports their members; obscure invented words are
not a substitute for an intelligible translation. Read across line breaks.

For repeated words, reuse a chosen rendering only when language, grammatical role,
sense and image agree. Identical spelling alone does not establish identity.
Compounds and inflections must contribute all their meaning even when they are
one clickable token. Every meaningful English phrase must point to the correct
source indices; numeric coverage alone does not prove semantic alignment.

Preserve explicitly supplied/owner-approved English exactly. Report a genuine
source/gloss conflict separately; never distort grammar to manufacture agreement.
The two editorial references are Aruṇācala Akṣaramaṇamālai (concrete imagery,
meaningful names) and Koī Hor Nahī Hai Merā (direct address and the owner's English).
They are style references, not evidence for an unrelated lyric's source words.

DICTIONARY EVIDENCE RULE: supplied entries establish possible senses only. Select
by this passage's grammar and imagery, or reject the candidates. Cite only an
entry/sense ID actually supplied, in the private grammar note when used. Do not
invent a dictionary lookup. Absence from this small candidate set is not evidence
that a word or sense does not exist. Do not transfer Hindi evidence to Punjabi,
Sanskrit or another language without separate evidence. The model's unsupported
guess is not dictionary verification. Real uncertainty remains a review finding.

SENSE DECISIONS: the private sense_decisions record binds each chosen meaning to
its exact word index. Check its grammatical_role and contextual_reason against
the actual source and neighbors. The primary gloss and linked English must use
the same contextual sense; a valid dictionary ID does not establish this match.
Check every chosen and rejected alternative rather than accepting the writer's
decision as authority. dictionary_supported means supplied dictionary evidence
exists, not that this interpretation is independently verified. contextual_inference
means the interpretation rests on grammar/context without a selected supplied
sense; it is allowed even when this language has no dictionary candidates, but
still needs independent semantic review. missing_evidence means the meaning
itself remains unresolved, not merely that the small dictionary lacks an entry.
"""


def policy_payload() -> dict:
    return {"version": POLICY_VERSION, "rules": RULES,
            "lexicon": json.loads((ROOT / "data/bhakti_lexicon.json").read_text(encoding="utf-8"))}


def _token(value: str) -> str:
    value = unicodedata.normalize("NFC", value).casefold().strip()
    return value.strip(".,;:!?।॥()[]{}\"'“”‘’")


def dictionary_candidates(lines: list[dict], languages: list[str] | None = None) -> list[dict]:
    # A label on a multilingual recording is not evidence that each line is Hindi.
    labels = {str(language).strip().casefold() for language in (languages or [])}
    if not labels or not labels.issubset({"hi", "hindi", "hindustani", "classical hindi"}):
        return []
    tokens = {_token(token) for line in lines for field in ("roman", "source_text", "source")
              for token in str(line.get(field, "")).split()}
    return [entry for entry in policy_payload()["lexicon"]["entries"]
            if entry["language"] == "hi" and tokens.intersection(
                _token(alias) for alias in entry["source_spellings"] + entry["roman_search_aliases"])]


def guidance(lines: list[dict], languages: list[str] | None = None) -> str:
    return RULES + "\nSUPPLIED DICTIONARY CANDIDATES (unselected):\n" + json.dumps(
        dictionary_candidates(lines, languages), ensure_ascii=False)


def token_candidates(lines: list[dict], languages: list[str] | None = None) -> dict[str, list[dict]]:
    """Bind candidates only to complete roman tokens, never guessed segmentation."""
    entries = dictionary_candidates(lines, languages)
    result = {}
    for line in lines:
        tokens = [token for token in str(line.get('roman', '')).split() if any(c.isalnum() for c in token)]
        result[line['id']] = [{'word_index': index, 'roman': token,
                              'candidates': [entry for entry in entries if _token(token) in
                                             {_token(alias) for alias in entry['roman_search_aliases']} ]}
                             for index, token in enumerate(tokens)]
    return result


def sense_decision_schema() -> dict:
    reference = {'type': 'object', 'properties': {
        'entry_id': {'type': 'string'}, 'sense_id': {'type': 'string'}},
        'required': ['entry_id', 'sense_id'], 'additionalProperties': False}
    rejected = {'type': 'object', 'properties': {
        **reference['properties'], 'reason': {'type': 'string'}},
        'required': ['entry_id', 'sense_id', 'reason'], 'additionalProperties': False}
    properties = {
        'word_index': {'type': 'integer'}, 'roman': {'type': 'string'},
        'evidence_status': {'type': 'string', 'enum': [
            'dictionary_supported', 'contextual_inference', 'missing_evidence']},
        'chosen': {'type': 'array', 'items': reference},
        'rejected': {'type': 'array', 'items': rejected},
        'contextual_reason': {'type': 'string'}, 'grammatical_role': {'type': 'string'},
    }
    return {'type': 'array', 'items': {'type': 'object', 'properties': properties,
            'required': list(properties), 'additionalProperties': False}}


def sense_decision_errors(lines: list[dict], gloss_rows: list[dict],
                          languages: list[str] | None = None) -> list[str]:
    """Validate reference membership/completeness, not semantic truth of a choice."""
    candidates = token_candidates(lines, languages)
    by_id = {row.get('id'): row for row in gloss_rows}
    errors = []
    if [row.get('id') for row in gloss_rows] != [line['id'] for line in lines]:
        errors.append('sense decision line population/order differs from source')
    for line in lines:
        line_id = line['id']
        if line.get('kind') == 'instrumental':
            continue
        expected = candidates[line_id]
        decisions = by_id.get(line_id, {}).get('sense_decisions')
        if not isinstance(decisions, list) or len(decisions) != len(expected):
            errors.append(f'{line_id}: sense decisions do not cover every word')
            continue
        for token, decision in zip(expected, decisions):
            label = f"{line_id}: sense decision {token['word_index']}"
            if (not isinstance(decision, dict) or type(decision.get('word_index')) is not int
                    or decision['word_index'] != token['word_index'] or decision.get('roman') != token['roman']):
                errors.append(f'{label} does not match its exact word index/surface')
                continue
            for field in ('contextual_reason', 'grammatical_role'):
                if not isinstance(decision.get(field), str) or not decision[field].strip():
                    errors.append(f'{label} lacks {field}')
            available = {(entry['entry_id'], sense['sense_id'])
                         for entry in token['candidates'] for sense in entry['senses']}
            chosen, rejected = decision.get('chosen'), decision.get('rejected')
            if not isinstance(chosen, list) or not isinstance(rejected, list):
                errors.append(f'{label} lacks chosen/rejected sense lists')
                continue
            references = []
            for field, rows in [('chosen', chosen), ('rejected', rejected)]:
                for reference in rows:
                    if (not isinstance(reference, dict)
                            or not isinstance(reference.get('entry_id'), str)
                            or not isinstance(reference.get('sense_id'), str)):
                        errors.append(f'{label} has invalid {field} reference')
                        continue
                    pair = (reference['entry_id'], reference['sense_id'])
                    references.append(pair)
                    if pair not in available:
                        errors.append(f'{label} cites a sense not supplied for this token/language: {pair}')
                    if field == 'rejected' and (not isinstance(reference.get('reason'), str)
                                                or not reference['reason'].strip()):
                        errors.append(f'{label} lacks a rejection reason')
            if len(references) != len(set(references)) or set(references) != available:
                errors.append(f'{label} must account for each candidate sense exactly once')
            status = decision.get('evidence_status')
            if status == 'dictionary_supported':
                if not chosen:
                    errors.append(f'{label} claims dictionary support without a chosen sense')
            elif status == 'contextual_inference':
                if chosen:
                    errors.append(f'{label} contextual inference cannot claim a supplied chosen sense')
            elif status == 'missing_evidence':
                errors.append(f'{label} has unresolved meaning needing evidence')
            else:
                errors.append(f'{label} has invalid evidence status')
    return errors

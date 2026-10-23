"""Small, cited lexical candidates and shared Bhakti editorial instructions.

Retrieval does not select a sense or rewrite a lyric. Exact token matching keeps
unrelated compounds and diacritically distinct words out of the candidate set.
"""
from __future__ import annotations

import json
import os
import bhakti_lexical_retrieval as lexical_retrieval
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_VERSION = 8
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
When a name has an evidenced literal or traditional meaning, include that meaning
in its clickable gloss as well as its referent; identity alone is not a substitute
for explaining a known meaning. Mark traditional explanations as such. Do not
invent a name meaning when its formation is unknown or disputed.

Bhakti's default is English, including difficult philosophical words. First seek
an accurate ordinary word; then a short precise phrase; then, if it preserves
meaning or poetry better, a transparent source-supported compound. A missing
one-word equivalent or dictionary entry is not a reason to leave an ordinary
term untranslated. Translate when the English preserves the meaning needed in
this passage; do not force an English substitute or a coined compound that
distorts it. A well-understood term may still lack an adequate compact English
rendering. Compare the best word, phrase or compound with retaining the term,
and explain any consequential loss or misleading implication. Retention of a
non-name needs that explicit contextual reason, an understandable clickable
English explanation, and independent review. The explanation can acknowledge
that it is approximate; it must not pretend a partial gloss exhausts the concept.
This is different from not knowing what the source means: unresolved source
meaning must be reported rather than disguised by retained foreign text.
Owner-approved English remains locked.

For pati or a verified -pati compound, choose the relation supported by the
source language, grammar and passage. Lord or master is permitted when evidenced;
husband/consort, ruler, guardian/protector and leader are other candidate senses,
not compulsory substitutions. Preserve the relation expressed by each compound
member; do not reduce a specific relationship to an unexplained devotional title.
Do not infer a compound or Sanskrit ancestry from a similar spelling.

An identified textual witness may supply a traditional formation or root-based
explanation. Treat it as that witness's traditional analysis, not by itself as
historical etymology or proof of a present-language sense. A Sanskrit explanation
does not establish the meaning of a Hindi, Punjabi or other-language occurrence
without language-specific evidence and context. Preserve a root image when the
passage activates it; do not insert protection into every pati occurrence merely
because a traditional explanation connects it with protecting.

Keep the poem's concrete images, repetition, direct address, tenderness, boldness,
wordplay and unusual agency. Supply English function words and natural syntax
without adding theology or replacing the image. Transparent English compounds
are welcome when the source supports their members; obscure invented words are
not a substitute for an intelligible translation. Read across line breaks.
Compare a proposed compound with its ordinary English paraphrase. Each component
must express supported source meaning, and the joined expression must preserve
their grammatical relation. Reject a coinage that merely sounds poetic but adds
an image, attitude or relationship absent from the source.

Choose a sense before inflecting its English realization. Preserve person, number,
tense, aspect, voice, negation, modality and who does what to whom. For adjectives,
identify what they modify and check whether the proposed English suggests praise,
blame, physical quality or emotional attitude in this passage. English may need
a phrase or a different part of speech to express the same relationship naturally;
do not copy source endings or enforce word-by-word English order. Check the entire
resulting line and its neighbors for grammar, connotation and poetic force.

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
    result = {"version": POLICY_VERSION, "rules": RULES}
    path = os.environ.get("BHAKTI_LEXICAL_INDEX")
    if path:
        with lexical_retrieval.LexicalIndex(path) as index:
            if os.environ.get("BHAKTI_LEXICON_PATH"):
                index.verify_corpus(os.environ["BHAKTI_LEXICON_PATH"])
            result["retrieval"] = index.fingerprint()
            result["retrieval"]["mode"] = "bounded-encoder" if os.environ.get("BHAKTI_EMBEDDING_LEDGER") else "cached-only"
            if result["retrieval"]["mode"] == "cached-only":
                result["retrieval"]["cached_vectors"] = lexical_retrieval.digest(
                    [row[0] for row in index.db.execute("SELECT key FROM vectors ORDER BY key")])
    else:
        result["lexicon"] = json.loads(Path(os.environ.get("BHAKTI_LEXICON_PATH", ROOT / "data/bhakti_lexicon.json")).read_text(encoding="utf-8"))
    return result


def _lexicon_for(lines, languages):
    path = os.environ.get("BHAKTI_LEXICAL_INDEX")
    if path:
        with lexical_retrieval.LexicalIndex(path) as index:
            if os.environ.get("BHAKTI_LEXICON_PATH"):
                index.verify_corpus(os.environ["BHAKTI_LEXICON_PATH"])
            return index.lexicon_for(lines, languages)
    return policy_payload()["lexicon"]


def _token(value: str) -> str:
    value = unicodedata.normalize("NFC", value).casefold().strip()
    return value.strip(".,;:!?।॥()[]{}\"'“”‘’")


def dictionary_candidates(lines: list[dict], languages: list[str] | None = None) -> list[dict]:
    return _dictionary_candidates(lines, languages, _lexicon_for(lines, languages))


def _dictionary_candidates(lines, languages, lexicon):
    found = {}
    native, roman, _ = lexical_retrieval.lookup_tables(lexicon)
    for line in lines:
        code = lexical_retrieval.line_language(line, languages)
        register = line.get("lexicalRegister")
        for field in ("source_text", "source", "roman"):
            table = roman if field == "roman" else native
            for surface in str(line.get(field, "")).split():
                for entry in table.get((code, lexical_retrieval.token(surface)), []):
                    if not register or entry["register"] == register:
                        found[entry["entry_id"]] = entry
    for rows in lexical_retrieval.token_candidates(
            [{**line, "id": line.get("id", str(index))} for index, line in enumerate(lines)],
            languages, lexicon).values():
        for row in rows:
            for entry in row["candidates"]: found[entry["entry_id"]] = entry
    return list(found.values())


def guidance(lines: list[dict], languages: list[str] | None = None, *,
             context_lines: list[dict] | None = None, performance_order: list[dict] | None = None) -> str:
    lexicon = _lexicon_for(lines, languages)
    entries = _dictionary_candidates(lines, languages, lexicon)
    tokens = lexical_retrieval.token_candidates(lines, languages, lexicon)
    ranking = lexical_retrieval.guidance_rankings(lines, languages, lexicon,
        context_lines=context_lines, performance_order=performance_order)
    packet = lexical_retrieval.compact_evidence(entries, tokens,
        ranking if ranking or os.environ.get("BHAKTI_LEXICAL_INDEX") else None)
    instructions = """
CONTEXTUAL SENSE RANKING: retrieval order only; retain and adjudicate every alternative.
The evidence below is normalized, not shortened. An object {"$text":"tN"} means
use the exact complete string in text_blocks[tN]. All entry fields and senses
remain supplied in entries. Each token's candidate_entry_ids binds only those
entries to that exact line/word index, with any reviewed lemma_evidence retained.
Each ranking's context_ref names its language, target and performed neighbors in
contexts; its surface is that ranking's roman. Ranked entry_id/sense_id pairs
refer to the full entry and sense above, including citation, register and source
context. Scores/statuses only report retrieval; an unranked status is not a
missing dictionary definition. Never choose the highest score automatically.
ranking_available=false means no indexed ranking was supplied. Inspect all
candidates even then. Continue using original entry_id/sense_id in decisions,
not text or context reference IDs. No language transfer or top-k omission.
COMPACT LEXICAL EVIDENCE (unselected):
"""
    return RULES + instructions + json.dumps(packet, ensure_ascii=False, separators=(",", ":"))


def word_tokens(line: dict) -> list[str]:
    return lexical_retrieval.word_tokens(line)


def token_candidates(lines: list[dict], languages: list[str] | None = None) -> dict[str, list[dict]]:
    return lexical_retrieval.token_candidates(lines, languages, _lexicon_for(lines, languages))


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

"""Small, cited lexical candidates and shared Bhakti editorial instructions.

Retrieval does not select a sense or rewrite a lyric. Exact token matching keeps
unrelated compounds and diacritically distinct words out of the candidate set.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_VERSION = 1
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

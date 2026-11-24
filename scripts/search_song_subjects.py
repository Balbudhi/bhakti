#!/usr/bin/env python3
"""Read-only lyric search and subject leads for contextual editorial review.

Examples:
  python3 scripts/search_song_subjects.py 'Nil kanth' --context 1
  python3 scripts/search_song_subjects.py --candidates --json

Queries match a folded phrase within an individual lyric/gloss field. Search
never treats credits, titles, unused lines or instrumental descriptions as sung
evidence. Candidate signals intentionally include ambiguous symbols: an absence
of candidates is not a semantic review, and a match never assigns a subject tag.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any
import unicodedata

from bhakti_shuffle_profiles import digest, meaning, parse_javascript_sources, read_json
import naming
import tag_taxonomy

ROOT = Path(__file__).resolve().parents[1]


def _fold(value: str, *, common: bool) -> str:
    value = unicodedata.normalize("NFC", value).casefold()
    if common:
        value = naming.common_romanization(value)
    # Strip Latin accents only. Indic vowel signs and other combining marks
    # carry words' identity and must survive exact native-script searching.
    parts = []
    for character in value:
        if "LATIN" in unicodedata.name(character, ""):
            parts.append(naming.unaccented(character))
        else:
            parts.append(character)
    folded = "".join(parts)
    folded = "".join(character if unicodedata.category(character)[0] in "LMN" else " "
                     for character in folded)
    if common:
        folded = re.sub(r"\b(?:krshna|krsna|krisna)\b", "krishna", folded)
    return " ".join(folded.split())


@lru_cache(maxsize=32768)
def folded_forms(value: str) -> frozenset[str]:
    """Both plain accent-folded and conventional IAST-to-Roman search forms."""
    return frozenset({_fold(value, common=False), _fold(value, common=True)} - {""})


def _matches(text: str, query: str, *, whole: bool = False) -> bool:
    for needle in folded_forms(query):
        for haystack in folded_forms(text):
            matched = f" {needle} " in f" {haystack} " if whole else needle in haystack
            if matched:
                return True
    return False


def performed_lines(reader: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Unique sung/spoken lines in first-performance order; reject broken refs."""
    lines = reader["SONG_LINES"]
    sequence = reader["SONG_SEQUENCE"]
    if not isinstance(lines, dict) or not isinstance(sequence, list):
        raise ValueError("SONG_LINES/SONG_SEQUENCE have invalid types")
    performed = {}
    for entry in sequence:
        ref = entry["ref"]
        if ref not in lines:
            raise ValueError(f"performance references missing line {ref!r}")
        if entry.get("section") != "instrumental":
            if not isinstance(lines[ref], dict):
                raise ValueError(f"performed line {ref!r} is not an object")
            performed.setdefault(ref, lines[ref])
    return list(performed.items())


def lyric_fields(line: dict[str, Any]) -> Iterable[tuple[str, str]]:
    for field in ("source", "roman", "english"):
        value = line.get(field)
        if isinstance(value, str) and value.strip():
            yield field, meaning(field, value)
    for index, word in enumerate(line.get("words", [])):
        for field in ("roman", "gloss"):
            value = word.get(field)
            if isinstance(value, str) and value.strip():
                yield f"words[{index}].{field}", value


def _excerpt(line_id: str, line: dict[str, Any]) -> dict[str, str]:
    return {"lineId": line_id, **{field: meaning(field, line.get(field, ""))
                                 for field in ("source", "roman", "english")}}


def _hit(slug, reader, lines, index, matches, context):
    line_id, line = lines[index]
    result = {"slug": slug, "title": reader["SONG_META"].get("title", ""),
              "lineId": line_id, "tags": list(reader["SONG_META"].get("subjectTags", [])),
              "matches": matches, "line": _excerpt(line_id, line)}
    if context:
        result["context"] = [_excerpt(ref, nearby) for ref, nearby in
                             lines[max(0, index - context):index + context + 1]]
    return result


def search_reader(slug: str, reader: dict[str, Any], query: str, *, context: int = 0) -> list[dict]:
    """Return lyric hits with exact original field text; never mutate the reader."""
    if not folded_forms(query):
        raise ValueError("query must contain letters or numbers")
    if context < 0:
        raise ValueError("context must be nonnegative")
    lines = performed_lines(reader)
    result = []
    for index, (_, line) in enumerate(lines):
        matches = [{"field": field, "snippet": text} for field, text in lyric_fields(line)
                   if _matches(text, query)]
        if matches:
            result.append(_hit(slug, reader, lines, index, matches, context))
    return result


@dataclass(frozen=True)
class Signal:
    tag: str
    kind: str
    reason: str
    terms: tuple[str, ...]


# Finite screening vocabulary, deliberately separate from automatic inference.
# Each signal explains why a reviewer should read the passage, not what the
# passage must mean. In particular a flute, peacock, lotus or named speaker can
# be incidental; these signals may never be used as an automatic tag writer.
SIGNALS = tuple(Signal(tag, "name", "Named form; establish its role in this passage.", aliases)
                for tag, aliases in tag_taxonomy.TAG_ALIASES.items()) + (
    Signal("Kṛṣṇa", "epithet", "Krishna/Vishnu epithet; determine the addressed form.",
           ("banvari", "banwari", "banavari", "banawari", "madhav", "murari", "murar",
            "mukand", "mukunda", "mukund", "shyam", "shyama", "syama", "kanha", "kanhaiya",
            "kannan", "kannane", "gopala", "gobind", "govind", "giridhar", "giridhara", "girdhar")),
    Signal("Kṛṣṇa", "name", "Native-script Krishna name; establish its role.",
           ("कृष्ण", "कान्हा", "श्याम", "ਮਾਧਵ", "ਮੁਰਾਰੀ", "ਬਨਵਾਰੀ", "ਕ੍ਰਿਸ਼ਨ",
            "ਕ੍ਰਿਸ਼ਨ", "ਕ੍ਰਿਸਨ", "ਕਾਨ੍ਹ", "ಕೃಷ್ಣ", "ಕಣ್ಣ", "కృష్ణ", "கண்ணன்", "கண்ணா", "কৃষ্ণ")),
    Signal("Kṛṣṇa", "symbol", "Flute/peacock imagery can evoke Krishna; context is required.",
           ("flute", "flutes", "peacock", "bansuri", "bansi", "murali", "mor mukut",
            "mora mukuta", "वनमाली", "बाँसुरी", "बांसुरी", "मुरली", "ਬੰਸਰੀ")),
    Signal("Kṛṣṇa", "narrative", "Krishna narrative place, relationship or deed.",
           ("govardhan", "govardhana", "vrindavan", "vrindavana", "brindavan", "brindavana",
            "gokul", "gokula", "yashoda", "yasoda", "yashomati", "devaki", "kaliya",
            "gopis", "gopi", "gopika", "गोवर्धन", "वृन्दावन", "वृंदावन", "गोकुल", "यशोदा")),
    Signal("Viṣṇu", "epithet", "Vishnu/Narasimha epithet; review devotional context.",
           ("narayan", "narain", "narhari", "narahari", "narasimha", "narsingh", "nrisimha",
            "madhu mardan", "madhusudan", "madhusudana", "नारायण", "ਨਾਰਾਇਣ", "ਨਰਹਰਿ", "నారాయణ")),
    Signal("Viṣṇu", "symbol", "Conch/discus or serpent-bed imagery may evoke Vishnu.",
           ("conch", "discus", "serpent bed", "shesha", "sesha", "sheshashayi", "padmanabha")),
    Signal("Śiva", "epithet", "Shiva epithet, including split blue-throat forms.",
           ("nil kanth", "neel kanth", "nilkanth", "nilakanth", "neelkanth", "mahadev", "mahadeva",
            "bholenath", "bhola", "bhole", "nataraja", "rudra", "sambhu", "shambhu",
            "ਨੀਲ ਕੰਠ", "नील कंठ", "नीलकंठ", "शिव", "ਸ਼ਿਵ", "ਸ਼ਿਵ", "ಶಿವ", "శివ", "சிவன்")),
    Signal("Śiva", "symbol", "Shiva iconography; establish whether it identifies the subject.",
           ("blue throat", "blue throated", "trident", "matted hair", "matted locks", "crescent moon",
            "damaru", "trishul", "trishula", "kailash", "kailasa", "gangadhar", "gangadhara")),
    Signal("Rāma", "epithet", "Rama epithet or narrative relation.",
           ("raghuvir", "raghuvira", "raghubir", "raghubira", "raghav", "raghava", "raghupati",
            "raghunatha", "siyaram", "siyavar", "dasharath", "dasharatha", "ayodhya", "अवध",
            "अयोध्या", "रघुवीर", "रघुनाथ", "राम", "ਰਾਮ", "రామ", "ராமா")),
    Signal("Sītā", "name", "Sita name; determine subject versus incidental reference.",
           ("sita", "siya", "janaki", "vaidehi", "सीता", "जानकी", "ਸੀਤਾ")),
    Signal("Rādhā", "name", "Radha name; determine subject versus incidental reference.",
           ("radha", "radhika", "राधा", "राधिका", "ਰਾਧਾ")),
    Signal("Hanumān", "epithet", "Hanuman epithet or characteristic narrative.",
           ("hanumana", "hanumanta", "anjani", "anjaniputra", "anjani putra", "bajrang", "marutinandan",
            "sanjivani", "hanumantha", "हनुमान", "हनुमंत", "ਹਨੂਮਾਨ")),
    Signal("Gaṇeśa", "symbol", "Ganesha name or elephant-headed form.",
           ("elephant headed", "elephant head", "vakratunda", "lambodara", "गणेश", "गणपति", "ਗਣੇਸ਼")),
    Signal("Viṭṭhala", "name", "Vitthal/Panduranga name or pilgrimage place.",
           ("vitthal", "vitthala", "vithal", "vithoba", "pandurang", "panduranga", "pandharpur",
            "विठ्ठल", "विठोबा", "पांडुरंग", "ವಿಠ್ಠಲ")),
    Signal("Śakti", "name", "Named goddess form; review identity and prominence.",
           ("jagadamba", "jagadambika", "jagajanani", "rajarajeshwari", "maheshwari", "jwala", "jwalamukhi",
            "sherawali", "sheranwali", "sheronwali", "sherawalee", "दुर्गा", "ਅੰਬਿਕਾ", "ਦੁਰਗਾ")),
    Signal("Durgā", "name", "Durga epithet; review the specific goddess identity.",
           ("durga", "durge", "durgayai", "mahishasuramardini", "mahishasura mardini",
            "chandika", "chamunda", "दुर्गा", "दुर्गे", "ਚੰਡੀ", "ਦੁਰਗਾ")),
    Signal("Pārvatī", "name", "Parvati epithet; determine the subject in context.",
           ("parvati", "parvathi", "parvatiyai", "uma", "gauri", "girija", "giriraj kishori",
            "giriraja kishori", "पार्वती", "गौरी", "गिरिजा", "ਪਾਰਬਤੀ")),
    Signal("Kālī", "epithet", "Named Kali construction, excluding bare Kali-age mentions.",
           ("kali ma", "kali mata", "ma kali", "maa kali", "jai kali", "jaya kali", "he kali",
            "dakshina kali", "dakshinakali", "काली माँ", "काली मां", "जय काली")),
    Signal("Sarasvatī", "name", "Sarasvati name; Sharada needs contextual disambiguation.",
           ("sharada", "sarada", "vidyadani", "saraswati", "sarasvati", "सरस्वती", "शारदा")),
    Signal("Lakṣmī", "name", "Lakshmi name; establish the identity in context.",
           ("lakshmi", "lakshmī", "laksmi", "mahalakshmi", "लक्ष्मी", "लक्ष्मि", "ਲਕਸ਼ਮੀ")),
)


def screen_reader(slug: str, reader: dict[str, Any], *, context: int = 1) -> list[dict]:
    """Missing-tag candidates with evidence; no inferred classifications or writes."""
    if context < 0:
        raise ValueError("context must be nonnegative")
    tags = tag_taxonomy.normalize_subject_tags(reader["SONG_META"].get("subjectTags", []))
    lines = performed_lines(reader)
    results = []
    for index, (_, line) in enumerate(lines):
        fields = list(lyric_fields(line))
        for signal in SIGNALS:
            if signal.tag in tags:
                continue
            matches = []
            for field, text in fields:
                terms = [term for term in signal.terms if _matches(text, term, whole=True)]
                if terms:
                    matches.append({"field": field, "snippet": text, "signals": terms})
            if matches:
                results.append({**_hit(slug, reader, lines, index, matches, context),
                                "candidateTag": signal.tag, "kind": signal.kind,
                                "reason": signal.reason, "requiresReview": True})
    return results


def load_readers(root: Path = ROOT, *, slugs: list[str] | None = None) -> dict[str, dict]:
    paths = sorted((Path(root) / "songs").glob("*/data.js"))
    available = {path.parent.name: path for path in paths}
    if slugs is not None:
        missing = set(slugs) - available.keys()
        if missing:
            raise ValueError(f"unknown song slug(s): {', '.join(sorted(missing))}")
        available = {slug: path for slug, path in available.items() if slug in slugs}
    if not available:
        raise ValueError("no song readers found")
    return parse_javascript_sources({slug: path.read_text(encoding="utf-8")
                                     for slug, path in available.items()})


def subject_input_hash(reader: dict[str, Any], candidate_tag: str) -> str:
    """Bind a tag judgment to all performed meaning, excluding display metadata.

    Line IDs, timing and repeated occurrences do not change the evidence. The
    unique performed lines retain first-performance order; lyric edits, gloss
    edits, additions/removals and changed ordering require another review.
    """
    fields = ("source", "sourceLanguage", "roman", "english", "words", "grammarNote")
    return digest({"version": 1, "candidateTag": candidate_tag,
                   "lines": [{field: meaning(field, line.get(field)) for field in fields}
                             for _, line in performed_lines(reader)]})


def check_candidates(readers: dict[str, dict], registry: dict) -> dict:
    """Require a full-meaning-bound dismissal for each absent candidate tag.

    Registry: {schemaVersion:1, decisions:{slug:{tag:{decision:"dismiss",
    inputHash:subject_input_hash(reader, tag), reason:"contextual rationale"}}}}.
    A tag already present resolves an addition; this operation never adds it.
    """
    if registry.get("schemaVersion") != 1 or not isinstance(registry.get("decisions"), dict):
        raise ValueError("subject-tag review registry needs schemaVersion 1 and decisions object")
    groups = {}
    for slug, reader in readers.items():
        for hit in screen_reader(slug, reader):
            key = (slug, hit["candidateTag"])
            groups.setdefault(key, []).append(hit)
    unresolved = []
    reviewed = 0
    for (slug, tag), evidence in groups.items():
        input_hash = subject_input_hash(readers[slug], tag)
        song_decisions = registry["decisions"].get(slug, {})
        if not isinstance(song_decisions, dict):
            raise ValueError(f"subject-tag decisions for {slug} must be an object")
        decision = song_decisions.get(tag)
        problem = "missing contextual disposition"
        if isinstance(decision, dict):
            if decision.get("decision") != "dismiss" or not isinstance(decision.get("reason"), str) or not decision["reason"].strip():
                problem = "disposition requires decision=dismiss and a contextual reason"
            elif decision.get("inputHash") != input_hash:
                problem = "stale disposition: performed meaning changed"
            else:
                reviewed += 1
                continue
        unresolved.append({"slug": slug, "candidateTag": tag, "inputHash": input_hash,
                           "problem": problem, "evidence": evidence})
    return {"passed": not unresolved, "candidateGroups": len(groups),
            "reviewedGroups": reviewed, "unresolved": unresolved}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("query", nargs="?", help="literal phrase, accent/common-Roman spelling insensitive")
    parser.add_argument("--candidates", action="store_true", help="screen missing-tag leads; never assign tags")
    parser.add_argument("--check", action="store_true", help="fail on missing/stale contextual candidate dispositions")
    parser.add_argument("--reviews", type=Path, help="registry path (default: ROOT/data/subject-tag-review.json)")
    parser.add_argument("--json", action="store_true", help="complete machine-readable results")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--slug", action="append", help="limit to one or more exact slugs")
    parser.add_argument("--context", type=int, default=1, help="neighboring unique performed lines (default: 1)")
    args = parser.parse_args()
    if sum((bool(args.query), args.candidates, args.check)) != 1:
        parser.error("supply exactly one of a query, --candidates or --check")
    if args.context < 0:
        parser.error("--context must be nonnegative")
    readers = load_readers(args.root, slugs=args.slug)
    if args.check:
        registry_path = args.reviews or args.root / "data" / "subject-tag-review.json"
        registry = read_json(registry_path) if registry_path.exists() else {"schemaVersion": 1, "decisions": {}}
        report = {"mode": "check", "songsScanned": len(readers), **check_candidates(readers, registry),
                  "notice": "This checks screened candidates and current dispositions, not exhaustive semantic correctness."}
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"{len(readers)} songs / {report['candidateGroups']} candidate groups / "
                  f"{len(report['unresolved'])} unresolved")
            print(report["notice"])
            for group in report["unresolved"]:
                print(f"{group['slug']}: {group['candidateTag']}: {group['problem']}")
        return 0 if report["passed"] else 1
    results = []
    for slug, reader in readers.items():
        results.extend(screen_reader(slug, reader, context=args.context) if args.candidates else
                       search_reader(slug, reader, args.query, context=args.context))
    report = {"mode": "candidates" if args.candidates else "search", "query": args.query,
              "songsScanned": len(readers),
              "performedLinesScanned": sum(len(performed_lines(reader)) for reader in readers.values()),
              "resultCount": len(results), "results": results}
    if args.candidates:
        report["notice"] = "Review leads only; neither matches nor no matches certify subject classification."
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"{report['songsScanned']} songs / {report['performedLinesScanned']} performed lines / {len(results)} results")
        if args.candidates:
            print(report["notice"])
        for hit in results:
            candidate = f" -> {hit['candidateTag']} [{hit['kind']}; review required]" if args.candidates else ""
            print(f"\n{hit['slug']}:{hit['lineId']} tags={', '.join(hit['tags']) or '(none)'}{candidate}")
            for match in hit["matches"]:
                print(f"  {match['field']}: {match['snippet']}")
            for line in hit.get("context", []):
                if line["lineId"] != hit["lineId"]:
                    print(f"  nearby {line['lineId']}: {line['roman']} | {line['english']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

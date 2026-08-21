#!/usr/bin/env python3
"""Compare the Arunachala song page with an accessible 108-verse witness.

The result is review evidence only. The witness cannot silently override what
the recording sings.
"""

from __future__ import annotations

import difflib
import html
import json
import re
import subprocess
import unicodedata
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SONG = ROOT / "songs" / "arunachala-akshara-mana-malai"
# This archive's edition has stable, numbered transliteration for all 108
# verses.  Unlike the first candidate source, it does not omit verse numbers
# 6, 49, and 84 in its rendered text.  It remains a secondary text witness:
# a recording can deliberately sing a different recension or performance
# variant.
URL = "https://archive.arunachala.org/docs/collected-worm/aksharamanamalai/?fmt=plain"


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    return "".join(ch for ch in value if ch.isalnum() and not unicodedata.combining(ch))


NON_VERSE_REFS = {
    "line-000",  # invocation, before stanza 1
    "line-001",  # invocation, before stanza 1
    "line-002",  # refrain
    "line-039",  # a performance return of the refrain
    "line-112",  # closing benediction
    "line-113",  # closing benediction
    "line-114",  # closing benediction
}


def public_lines() -> list[dict]:
    script = "global.window={};require(process.argv[1]);process.stdout.write(JSON.stringify(window));"
    output = subprocess.run(["node", "-e", script, str(SONG / "data.js")], check=True,
                            capture_output=True, text=True).stdout
    page = json.loads(output)
    seen, rows = set(), []
    for entry in page["SONG_SEQUENCE"]:
        ref = entry["ref"]
        if ref in seen:
            continue
        seen.add(ref)
        line = page["SONG_LINES"][ref]
        rows.append({"id": ref, "roman": line["roman"], "source": line.get("source", "")})
    return rows


def witness_verses(document: str) -> list[dict]:
    """Extract all 108 explicitly numbered stanzas from the archive source.

    The source is old, hand-authored HTML: most verses are ``<p>NUMBER`` but
    v24 has an anchor directly before its bare number.  Parse both forms and
    key the result by its printed number, rather than relying on visual order
    or a fuzzy "Arunachala NUMBER" pattern.  That old extractor silently
    returned 105 verses from a different source and made a bad comparison
    look like 19 lyric discrepancies.
    """
    found: dict[int, str] = {}
    patterns = (
        r'<p\b[^>]*>\s*(\d+)\.\s*<br>\s*<strong[^>]*>(.*?)</strong>',
        r'<a\b[^>]*\bid=["\']v(\d+)["\'][^>]*></a>\s*'
        r'(?:<p\b[^>]*>)?\s*\d+\.\s*<br>\s*<strong[^>]*>(.*?)</strong>',
    )
    for pattern in patterns:
        for number, body in re.findall(pattern, document, flags=re.I | re.S):
            verse = int(number)
            if not 1 <= verse <= 108:
                continue
            text = html.unescape(re.sub(r"<br[^>]*>", " ", body, flags=re.I))
            text = re.sub(r"<[^>]+>", "", text)
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                found[verse] = text
    missing = [number for number in range(1, 109) if number not in found]
    if missing:
        raise RuntimeError(f"canonical witness extraction missed verses: {missing}")
    return [{"verse": number, "roman": found[number]} for number in range(1, 109)]


def main() -> int:
    request = urllib.request.Request(URL, headers={"User-Agent": "Bhakti-witness-audit/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        document = response.read().decode("utf-8", errors="replace")
    witness = witness_verses(document)
    verses = {row["verse"]: row for row in witness}
    public = public_lines()
    canonical = [line for line in public if line["id"] not in NON_VERSE_REFS]
    if len(canonical) != 108:
        raise RuntimeError(f"expected 108 canonical public stanzas, found {len(canonical)}")
    findings = []
    matches = []
    for number, line in enumerate(canonical, start=1):
        matched = verses[number]
        score = difflib.SequenceMatcher(
            None, normalized(line["roman"]), normalized(matched["roman"])
        ).ratio()
        row = {
            "verse": number,
            "line_id": line["id"],
            "public_source": line["source"],
            "public_roman": line["roman"],
            "witness_roman": matched["roman"],
            "similarity": round(score, 3),
        }
        matches.append(row)
        # The archive uses a legacy syllabic spelling, so a fuzzy score alone
        # cannot assert an error.  Below .75 it is useful targeted evidence
        # for the already-required audio recheck; it still cannot alter text.
        if score < 0.75:
            findings.append({**row, "disposition": "needs-audio-and-witness-review"})
    artifact = {"work": "Arunachala Akshara Mana Malai", "witness_url": URL,
                "witness_verse_count": len(witness), "public_unique_line_count": len(public),
                "canonical_public_stanza_count": len(canonical), "matches": matches,
                "findings": findings,
                "policy": "The recording is authoritative for a performance variant; no finding is an automatic public edit.",
                "extraction_note": "The witness contains all explicitly numbered verses 1–108. Intro, refrains, and closing benediction are intentionally excluded from stanza matching."}
    output = SONG / ".transcription" / "witnesses" / "arunachala-comparison.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"witnessVerses": len(witness), "publicLines": len(public_lines()), "findings": len(findings),
                      "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())

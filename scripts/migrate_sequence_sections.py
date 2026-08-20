#!/usr/bin/env python3
"""Add canonical section kinds to legacy SONG_SEQUENCE entries.

The rewrite is deliberately mechanical and preserves all refs, repeats,
ordering, timings, translations, and comments. Obsolete visible section-label
overrides are removed; the section kind remains internal metadata.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFRAIN_OVERRIDES = {
    "baba-tum-antaryami": {"sain_tum_antaryami", "baba_tum_antaryami", "daya_karo_he_swami"},
    "jab-dil-udaas-ho-to": {"jab_dil_udaas_ho_to", "sai_ka_naam_lena", "jeevan_soona_lage_to"},
    "tumhi-mere-lagan-lagai-re": {"tu_hi_more_lagan"},
}
VALID = {"invocation", "refrain", "verse", "bridge", "closing", "spoken", "instrumental"}


def kind(slug: str, ref: str) -> str:
    lower = ref.casefold()
    if ref in REFRAIN_OVERRIDES.get(slug, set()) or lower.startswith("refrain"):
        return "refrain"
    if lower.startswith("invocation"):
        return "invocation"
    if lower.startswith(("closing", "outro")):
        return "closing"
    if lower in {"alap", "ālāp"}:
        return "instrumental"
    return "verse"


def migrate(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    slug = path.parent.name
    sequence_at = text.index("window.SONG_SEQUENCE")
    timing_at = text.index("window.SONG_TIMINGS", sequence_at)
    before, sequence, after = text[:sequence_at], text[sequence_at:timing_at], text[timing_at:]
    original_sequence = sequence
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        body = match.group(0)
        if re.search(r"\bsection\s*:", body):
            return body
        ref_match = re.search(r'\bref\s*:\s*"([^"]+)"', body)
        if not ref_match:
            return body
        section = kind(slug, ref_match.group(1))
        assert section in VALID
        count += 1
        return body.replace(ref_match.group(0), ref_match.group(0) + f', section: "{section}"', 1)

    sequence = re.sub(r"\{[^{}]*\bref\s*:\s*\"[^\"]+\"[^{}]*\}", replace, sequence)
    sequence = re.sub(r',\s*"?sectionLabel"?\s*:\s*"[^"]*"', "", sequence)
    if sequence != original_sequence:
        path.write_text(before + sequence + after, encoding="utf-8")
    return count


def main() -> int:
    total = 0
    for path in sorted((ROOT / "songs").glob("*/data.js")):
        changed = migrate(path)
        if changed:
            print(f"{path.parent.name}: {changed}")
            total += changed
    print(f"updated {total} sequence entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

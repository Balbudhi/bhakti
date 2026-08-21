#!/usr/bin/env python3
"""Conservative deterministic deity tags from explicit lyric names."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

import naming


TAG_ALIASES: dict[str, tuple[str, ...]] = {
    "Rāma": ("ram", "rama", "ramachandra", "rajaram", "rajarama", "raghunath"),
    "Kṛṣṇa": (
        "krishna", "nandalala", "manmohan", "govinda", "gopal", "damodara",
        "vasudeva", "keshava", "achyuta", "madhava", "gopikavallabha",
    ),
    "Viṣṇu": ("vishnu", "narayana", "hari"),
    "Śiva": (
        "shiva", "shiv", "shankara", "shankar", "maheshvara", "maheshwar",
        "umapati", "mallikarjuna", "chennamallikarjuna", "nilakantha",
    ),
    "Jagannātha": ("jagannatha", "jagannath"),
    # Bare `kali` is excluded because devotional corpora frequently mean the
    # Kali age rather than the goddess; require an unambiguous named form.
    "Śakti": ("durga", "mahakali", "vaishno", "jhandewali", "ambika", "bhavani"),
}


def normalized_tokens(value: str) -> set[str]:
    common = naming.unaccented(naming.common_romanization(value)).casefold()
    return set(re.findall(r"[a-z]+", common))


def infer_named_subject_tags(lines: Iterable[dict[str, Any]]) -> list[str]:
    tokens: set[str] = set()
    for line in lines:
        tokens.update(normalized_tokens(str(line.get("roman") or "")))
    inferred = [tag for tag, aliases in TAG_ALIASES.items() if tokens.intersection(aliases)]

    # `sāīṃ` alone is an old North-Indian word for lord/master and appears in
    # Kabir songs unrelated to Shirdi. Require an unambiguous Shirdi form.
    joined = " ".join(tokens)
    if tokens.intersection({"shirdi", "sainath"}) or {"sai", "baba"}.issubset(tokens):
        inferred.append("Śirḍī Sāī")
    return inferred


def merge_subject_tags(explicit: Iterable[object], lines: Iterable[dict[str, Any]]) -> list[str]:
    values = [str(value).strip() for value in explicit if str(value).strip()]
    for tag in infer_named_subject_tags(lines):
        if tag not in values:
            values.append(tag)
    return values

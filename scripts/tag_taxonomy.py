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
    "Viṣṇu": ("vishnu", "narayana"),
    "Nirguṇa": ("nirgun", "nirguna"),
    "Śiva": (
        "shiva", "shiv", "shankara", "shankar", "maheshvara", "maheshwar",
        "umapati", "mallikarjuna", "chennamallikarjuna", "nilakantha",
    ),
    "Jagannātha": ("jagannatha", "jagannath"),
    "Hanumān": ("hanuman", "hanumant", "maruti", "anjaneya", "pavanputra", "pavanaputra", "bajrangbali"),
    "Gaṇeśa": ("ganesha", "ganesh", "ganapati", "ganapat", "gajanana", "gajavadan", "ekadanta", "vinayaka"),
    # Bare Śāradā/Śarada can name Sarasvatī, a textual epithet, or the
    # modern historical Śāradā Devī. Never infer the historical person from
    # that ambiguous surface form; retain her only as an explicit reviewed tag.
    "Sarasvatī": ("saraswati", "sarasvati"),
    # Historical people are editorial subjects, not automatic deity matches.
    # Add them only through an explicit reviewed subject tag.
    # Bare `kali` is excluded because devotional corpora frequently mean the
    # Kali age rather than the goddess; require an unambiguous named form.
    "Śakti": ("durga", "mahakali", "vaishno", "jhandewali", "ambika", "bhavani"),
    "Vaiṣṇo Devī": ("vaishno",),
}

SUBJECT_TAG_ALIASES = {
    "Śrī Śāradā Devī": "Śāradā Devī",
    "Vaishno Devi": "Vaiṣṇo Devī",
}

SARASVATI_SHARADA_MARKERS = {
    "vidya", "vidyadani", "vani", "veena", "vina", "brahma", "brahmani", "hansa",
}


def normalized_tokens(value: str) -> set[str]:
    common = naming.unaccented(naming.common_romanization(value)).casefold()
    return set(re.findall(r"[a-z]+", common))


def infer_named_subject_tags(lines: Iterable[dict[str, Any]]) -> list[str]:
    tokens: set[str] = set()
    for line in lines:
        tokens.update(normalized_tokens(str(line.get("roman") or "")))
    inferred = [tag for tag, aliases in TAG_ALIASES.items() if tokens.intersection(aliases)]

    # Śāradā is an ancient name of Sarasvatī as well as a modern historical
    # person's name.  Infer the goddess only when nearby theological markers
    # make that reading clear.  The historical Śāradā Devī is deliberately
    # never inferred from the bare word: it must be an explicit reviewed tag.
    if tokens.intersection({"sharada", "sarada"}) and tokens.intersection(SARASVATI_SHARADA_MARKERS):
        inferred.append("Sarasvatī")

    # `sāīṃ` alone is an old North-Indian word for lord/master and appears in
    # Kabir songs unrelated to Shirdi. Require an unambiguous Shirdi form.
    joined = " ".join(tokens)
    if tokens.intersection({"shirdi", "sainath"}) or {"sai", "baba"}.issubset(tokens):
        inferred.append("Śirḍī Sāī")
    return list(dict.fromkeys(inferred))


def merge_subject_tags(explicit: Iterable[object], lines: Iterable[dict[str, Any]]) -> list[str]:
    values = []
    for value in explicit:
        label = str(value).strip()
        if not label:
            continue
        label = SUBJECT_TAG_ALIASES.get(label, label)
        if label not in values:
            values.append(label)
    for tag in infer_named_subject_tags(lines):
        if tag not in values:
            values.append(tag)
    return values

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
    # Bare bhāvani is also a Punjabi verb form (“who please”), so it is not
    # a safe automatic match for Bhavānī. Explicit devotional constructions
    # are handled below.
    "Śakti": ("durga", "mahakali", "vaishno", "jhandewali", "ambika"),
    "Kālī": ("mahakali", "bhadrakali", "kalika", "bhavatarini"),
    "Vaiṣṇo Devī": ("vaishno",),
}

SUBJECT_TAG_ALIASES = {
    "Śrī Śāradā Devī": "Śāradā Devī",
    "Vaishno Devi": "Vaiṣṇo Devī",
}

SARASVATI_SHARADA_MARKERS = {
    "vidya", "vidyadani", "vani", "veena", "vina", "brahma", "brahmani", "hansa",
}

# A bare `kālī` can be the Kali age, an adjective meaning black, or a verb in
# several languages. These constructions name the goddess directly and are
# safe to classify without relying on a loose keyword match.
KALI_GODDESS_PATTERNS = (
    r"\b(?:jai|jaya)(?:\s+(?:jai|jaya))?\s+(?:maa\s+|ma\s+)?kali\b",
    r"\b(?:he|karali|kalatita)\s+kali\b",
    r"\bkali\s+(?:mata|maa|asura)\b",
)

SHAKTI_GODDESS_PATTERNS = (
    r"\b(?:maa|ma|mata)\s+bhavani\b",
    r"\bbhavani\s+(?:maa|ma|mata)\b",
    r"\bjai\s+(?:jai\s+)?bhavani\b",
)


def normalized_tokens(value: str) -> set[str]:
    common = naming.unaccented(naming.common_romanization(value)).casefold()
    return set(re.findall(r"[a-z]+", common))


def infer_named_subject_tags(lines: Iterable[dict[str, Any]]) -> list[str]:
    tokens: set[str] = set()
    lyric_text: list[str] = []
    for line in lines:
        roman = str(line.get("roman") or "")
        tokens.update(normalized_tokens(roman))
        lyric_text.append(naming.unaccented(naming.common_romanization(roman)).casefold())
    inferred = [tag for tag, aliases in TAG_ALIASES.items() if tokens.intersection(aliases)]

    if any(re.search(pattern, text) for text in lyric_text for pattern in KALI_GODDESS_PATTERNS):
        inferred.append("Kālī")

    if any(re.search(pattern, text) for text in lyric_text for pattern in SHAKTI_GODDESS_PATTERNS):
        inferred.append("Śakti")

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

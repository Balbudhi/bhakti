#!/usr/bin/env python3
"""Meaning-only tooltip policy for Bhakti word glosses."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PRESERVED = json.loads((ROOT / "data" / "preserved_terms.json").read_text(encoding="utf-8")).get("terms", {})
PLACEHOLDER_GLOSSES = frozenset({"proper name", "proper name or untranslated term", "untranslated term"})

FICTIONAL_COINAGES = {
    "adamantium": "fictional Marvel alloy",
    "vibranium": "fictional Marvel metal",
    "mithril": "fictional Tolkien metal",
}

# Sanskrit pati (and the transparent -pati compounds built with it) ranges over
# guardian, protector, sustaining partner, husband/consort, ruler, and leader.
# English "lord" is too easy a default: it drops the relation named by the
# compound and imports a specifically English feudal/theological overtone.
# This is deliberately a rejection rule rather than a universal replacement;
# a homographic vernacular token still needs its local sense.
PATI_NON_LEMMAS = (
    "patit", "patita", "patitap", "sampati", "kapati", "vipati", "patisahi",
)


def is_pati_lexeme(roman: object) -> bool:
    normalized = key(roman).replace(" ", "")
    if not normalized or normalized.startswith(PATI_NON_LEMMAS):
        return False
    return normalized == "pati" or bool(re.search(r"pati(?:hi|m|na|ne|no|yo|ye)?$", normalized))


def has_flat_pati_lord_gloss(roman: object, gloss: object) -> bool:
    """Whether a pati-term has been flattened to the prohibited bare title."""
    return is_pati_lexeme(roman) and bool(re.search(r"\blord\b", str(gloss or ""), re.I))


def key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def roman_keys(value: object) -> list[str]:
    raw = str(value or "")
    values = [key(raw)]
    if any(mark in raw for mark in ("ṃ", "ṁ")) and values[0].endswith("m"):
        values.append(values[0][:-1])
    if len(values[0]) > 4 and values[0].endswith("a"):
        values.append(values[0][:-1])
    return [value for value in dict.fromkeys(values) if value]


PRESERVED_HINTS = {
    key(alias): str(entry.get("shortGlossHint") or "").strip()
    for entry in PRESERVED.values()
    for alias in entry.get("aliases", [])
    if str(entry.get("shortGlossHint") or "").strip()
}

# These are explanations, never definitions that merely repeat the visible
# Roman token. Context-specific generated glosses that are already meaningful
# remain untouched; this table is used only when the old gloss begins by
# repeating the token itself.
MEANING_ONLY = {
    "baba": "father; revered master",
    "bhavani": "the Goddess; Śakti as the source of being",
    "dha": "sixth note of the Indian scale",
    "damaru": "hourglass drum associated with Śiva",
    "datta": "Lord Dattātreya",
    "durga": "the inaccessible, protecting Goddess",
    "ganga": "the sacred river descended from heaven",
    "ganu": "devotee-poet",
    "guru": "spiritual teacher",
    "hari": "Lord Viṣṇu; remover of suffering",
    "hanuman": "monkey-god; son of the Wind",
    "hindu": "follower of the dharma",
    "holika": "bonfire; destructive blaze",
    "jagannatha": "Lord of the universe",
    "jhandewali": "the Goddess of Jhandewalan",
    "kabir": "poet-saint",
    "lanka": "island kingdom of Rāvaṇa",
    "madhava": "the poet's signature-name",
    "maharaja": "great king; revered sovereign",
    "manda": "a proper name here",
    "nama": "poet-saint",
    "narayana": "Lord Viṣṇu",
    "ramadhava": "Lord Viṣṇu",
    "rudra": "fierce form of Śiva",
    "sai": "holy master",
    "sainath": "Lord Sai",
    "shiva": "the auspicious one; deity of transformation and yogic asceticism",
    "siva": "the auspicious one; deity of transformation and yogic asceticism",
    "sivasankara": "Śiva as the auspicious maker of good",
    "sudama": "impoverished devotee and friend of Kṛṣṇa",
    "tunga": "lofty; high",
    "vasko": "the poet's name",
}


def is_self_referential(roman: object, gloss: object) -> bool:
    def loose(value: str) -> str:
        # Model output often substitutes English digraphs for IAST letters:
        # śivaśaṅkara → Shiva-Shankara. This remains repetition, not meaning.
        return value.replace(" ", "").replace("sh", "s")

    gloss_key = loose(key(gloss))
    return any(
        len(roman_key) >= 3 and (
            gloss_key == loose(roman_key)
            or gloss_key.startswith(loose(roman_key))
        )
        for roman_key in roman_keys(roman)
    )


def is_placeholder_gloss(gloss: object) -> bool:
    """Whether a gloss tells the listener nothing about the displayed word."""
    return str(gloss or "").strip().casefold() in PLACEHOLDER_GLOSSES


def meaning_only_gloss(roman: object, gloss: object, concept_key: object = "") -> str:
    text = str(gloss or "").strip()
    if not is_self_referential(roman, text):
        return text
    concept_hint = str(PRESERVED.get(str(concept_key or ""), {}).get("shortGlossHint") or "").strip()
    hint = concept_hint or next((PRESERVED_HINTS.get(candidate) or MEANING_ONLY.get(candidate)
                                 for candidate in roman_keys(roman)
                                 if PRESERVED_HINTS.get(candidate) or MEANING_ONLY.get(candidate)), "")
    if hint:
        return hint
    # A previously unseen proper name may still have useful explanatory text
    # after its repeated label. Retain that explanation when possible.
    tail = re.split(r"\s*[,(/\[]\s*", text, maxsplit=1)
    if len(tail) == 2:
        candidate = tail[1].rstrip(")] ").strip()
        if candidate and not is_self_referential(roman, candidate):
            return candidate
    raise ValueError(
        f"unresolved self-referential gloss for {roman!r}; provide an identity or contextual meaning before publication"
    )


def clean_word(word: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(word)
    cleaned["gloss"] = meaning_only_gloss(
        cleaned.get("roman", ""), cleaned.get("gloss", ""), cleaned.get("concept_key", ""),
    )
    return cleaned


def fictional_coinages(value: object) -> list[str]:
    tokens = re.findall(r"[a-z]+", str(value or "").casefold())
    return sorted(set(tokens).intersection(FICTIONAL_COINAGES))

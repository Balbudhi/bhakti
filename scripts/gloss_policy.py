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

def key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def roman_keys(value: object) -> list[str]:
    raw = str(value or "")
    values = [key(raw)]
    # Source-evidenced Awadhi nominative रामु names Rāma, not a new entity.
    if values[0] == "ramu":
        values.append("rama")
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

# Historical vocabulary retained for reference. These hints are not evidence for
# an occurrence and must never replace a supplied gloss during normalization or
# final reader generation. The cleaner below uses only the supplied explanation.
MEANING_ONLY = {
    "baba": "father; revered master",
    "angada": "Vānara prince and envoy of Rāma",
    "asoka": "the Aśoka tree; in the name of Sītā’s grove",
    "bhavani": "the Goddess; Śakti as the source of being",
    "bhesaja": "medicine; remedy",
    "brahma": "the creator deity Brahmā",
    "dha": "sixth note of the Indian scale",
    "dandaka": "the Dandaka forest of Rāma’s exile",
    "damaru": "hourglass drum associated with Śiva",
    "datta": "Lord Dattātreya",
    "durga": "the inaccessible, protecting Goddess",
    "dusana": "a demon commander slain by Rāma",
    "ganga": "the sacred river descended from heaven",
    "ganu": "devotee-poet",
    "gur": "spiritual guide; revered teacher",
    "gura": "spiritual guide; revered teacher",
    "guri": "by the spiritual guide",
    "guru": "spiritual teacher",
    "hari": "Lord Viṣṇu; remover of suffering",
    "hanuman": "monkey-god; son of the Wind",
    "hanu": "the Vānara hero and Rāma’s devoted envoy",
    "jambavan": "the wise bear-king who counsels Hanumān",
    "janaki": "daughter of King Janaka; Sītā",
    "hindu": "follower of the dharma",
    "holika": "bonfire; destructive blaze",
    "jagannatha": "Lord of the universe",
    "jhandewali": "the Goddess of Jhandewalan",
    "kabir": "poet-saint",
    "khara": "Rāvaṇa’s demon kinsman slain by Rāma",
    "kinnara": "celestial musician; mythical human-bird being",
    "lanka": "island kingdom of Rāvaṇa",
    "madhava": "the poet's signature-name",
    "maharaja": "great king; revered sovereign",
    "manda": "a proper name here",
    "mainaka": "the mountain who rises from the sea to offer Hanumān rest",
    "mainak": "the mountain who rises from the sea to offer Hanumān rest",
    "meghanada": "Rāvaṇa’s son, famed as a warrior",
    "nanak": "Nānak, the devotee-poet",
    "nama": "poet-saint",
    "narayana": "Lord Viṣṇu",
    "vishnu": "the all-pervading divine reality",
    "visnu": "the all-pervading divine reality",
    "naga": "serpent being; dragon-like guardian",
    "purana": "ancient sacred narrative and teaching tradition",
    "patha": "recitation; devotional reading aloud",
    "rama": "hero of the Rāmāyaṇa and Viṣṇu’s avatāra",
    "ramadhava": "Lord Viṣṇu",
    "ravana": "king of Laṅkā and Sītā’s captor",
    "rudra": "fierce form of Śiva",
    "sai": "holy master",
    "sainath": "Lord Sai",
    "sankara": "Śiva; the beneficent deity",
    "sita": "Rāma’s wife and heroine of the Rāmāyaṇa",
    "shiva": "the auspicious one; deity of transformation and yogic asceticism",
    "siva": "the auspicious one; deity of transformation and yogic asceticism",
    "sivasankara": "Śiva as the auspicious maker of good",
    "sudama": "impoverished devotee and friend of Kṛṣṇa",
    "sugriva": "Vānara king and ally of Rāma",
    "surasa": "serpent-mother who tests Hanumān on his journey",
    "vibhishana": "Rāvaṇa’s brother who seeks refuge with Rāma",
    "tunga": "lofty; high",
    "trisira": "a three-headed demon commander slain by Rāma",
    "uma": "Pārvatī, Śiva’s consort",
    "vasko": "the poet's name",
    "vyasa": "poet of the Mahābhārata",
}


def _same_label(roman: object, text: object) -> bool:
    # Accept ordinary English digraphs as spelling variants of an IAST label.
    # This compares labels only; it does not select a referent or word sense.
    def loose(value: str) -> str:
        return value.replace(" ", "").replace("sh", "s")

    candidate = loose(key(text))
    return any(len(label) >= 3 and bool(re.fullmatch(r"(?:" + re.escape(loose(label)) + r")+", candidate))
               for label in roman_keys(roman))


def _supplied_tail(roman: object, text: str) -> str | None:
    # Only an explicit label separator permits presentation-only removal.
    # Name-leading prose ("Mādhava is ...", "Rāma's ...") remains exact.
    for separator in re.finditer(r"\s*[,(:/\[—–]\s*|\s+-\s+", text):
        if _same_label(roman, text[:separator.start()]):
            tail = text[separator.end():].strip()
            opener = separator.group().strip()
            if opener in ("(", "["):
                # Strip a wrapper only when its matching close ends the gloss.
                # Mixed prose such as '(Kṛṣṇa), the cowherd' remains exact.
                stack = [opener]
                for index, character in enumerate(tail):
                    if character in "([":
                        stack.append(character)
                    elif character in ")]":
                        if not stack or stack.pop() != {')': '(', ']': '['}[character]:
                            return None
                        if not stack:
                            return tail[:-1].strip() if index == len(tail) - 1 else None
                return None
            return tail
    return None


def is_self_referential(roman: object, gloss: object) -> bool:
    text = str(gloss or "").strip()
    while text:
        if _same_label(roman, text) or is_placeholder_gloss(text):
            return True
        tail = _supplied_tail(roman, text)
        if tail is None:
            return False
        if not tail:
            return True
        text = tail
    return False


def is_placeholder_gloss(gloss: object) -> bool:
    """Whether a gloss tells the listener nothing about the displayed word."""
    return str(gloss or "").strip().casefold() in PLACEHOLDER_GLOSSES


def meaning_only_gloss(roman: object, gloss: object, concept_key: object = "") -> str:
    """Keep supplied meaning; never infer a sense or identity from the label.

    ``concept_key`` remains an API-compatible bookkeeping argument, not authority
    to replace this occurrence with a registry hint. Missing context must return
    to source review, including for historical cached readers.
    """
    text = str(gloss or "").strip()
    if is_self_referential(roman, text) or is_placeholder_gloss(text):
        raise ValueError(
            f"unresolved self-referential gloss for {roman!r}; provide an identity or contextual meaning before publication"
        )
    tail = _supplied_tail(roman, text)
    return tail if tail is not None else text


def clean_word(word: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(word)
    cleaned["gloss"] = meaning_only_gloss(
        cleaned.get("roman", ""), cleaned.get("gloss", ""), cleaned.get("concept_key", ""),
    )
    return cleaned


def fictional_coinages(value: object) -> list[str]:
    tokens = re.findall(r"[a-z]+", str(value or "").casefold())
    return sorted(set(tokens).intersection(FICTIONAL_COINAGES))

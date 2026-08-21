#!/usr/bin/env python3
"""Deterministic display/search naming helpers for generated Bhakti readers."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


IAST_TO_COMMON = str.maketrans({
    "ā": "a", "ī": "i", "ū": "u", "ṛ": "r", "ṝ": "r", "ḷ": "l", "ḹ": "l",
    "ṅ": "ng", "ñ": "ny", "ṇ": "n", "ṃ": "m", "ṁ": "m", "ḥ": "h",
    "ś": "sh", "ṣ": "sh", "ṭ": "t", "ḍ": "d", "ḻ": "l",
    "Ā": "A", "Ī": "I", "Ū": "U", "Ṛ": "R", "Ṝ": "R", "Ḷ": "L", "Ḹ": "L",
    "Ṅ": "Ng", "Ñ": "Ny", "Ṇ": "N", "Ṃ": "M", "Ṁ": "M", "Ḥ": "H",
    "Ś": "Sh", "Ṣ": "Sh", "Ṭ": "T", "Ḍ": "D", "Ḻ": "L",
})


PERSON_CANONICALS = {
    "satpathy baba": ("Shri Chandra Bhanu Satpathy", ("Satpathy Baba",)),
    "shri chandra bhanu satpathy": ("Shri Chandra Bhanu Satpathy", ("Satpathy Baba",)),
}


def compact(value: str) -> str:
    """Collapse punctuation/spacing for comparisons without changing display text."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)).strip().casefold()


def unaccented(value: str) -> str:
    return "".join(character for character in unicodedata.normalize("NFKD", value)
                   if not unicodedata.combining(character))


def common_romanization(value: str) -> str:
    """Return a search spelling, not a replacement for reviewed display IAST."""
    return value.translate(IAST_TO_COMMON).replace("ngg", "ng").replace("Ngg", "Ng")


def canonical_person(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    canonical, _ = PERSON_CANONICALS.get(text.casefold(), (text, ()))
    return canonical


def person_search_aliases(values: Iterable[object]) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        _, extras = PERSON_CANONICALS.get(text.casefold(), (text, ()))
        for alias in extras:
            key = compact(alias)
            if key and key not in seen:
                aliases.append(alias)
                seen.add(key)
    return aliases


def search_aliases(values: Iterable[object], extra: Iterable[object] = ()) -> list[str]:
    """Generate stable ordinary-spelling aliases while preserving explicit aliases."""
    originals = [str(value).strip() for value in values if value is not None and str(value).strip()]
    explicit = [str(value).strip() for value in extra if value is not None and str(value).strip()]
    original_keys = {compact(value) for value in originals}
    aliases: list[str] = []
    seen = set(original_keys)
    for value in originals:
        for candidate in (common_romanization(value), unaccented(value)):
            candidate = re.sub(r"\s+", " ", candidate).strip()
            key = compact(candidate)
            if key and key not in seen:
                aliases.append(candidate)
                seen.add(key)
    # User-/source-supplied aliases remain searchable even if they do not
    # follow mechanically from IAST (Ishwar/Īśvar, Jhoothe/Jhūṭhe, and so on).
    for candidate in explicit:
        key = compact(candidate)
        if key and key not in seen:
            aliases.append(candidate)
            seen.add(key)
    return aliases


def slugify(value: str) -> str:
    common = unaccented(common_romanization(value)).casefold()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", common)).strip("-")

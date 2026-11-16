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
    "shurjo bhattacharya": ("Shurjo Bhattacharya", ("Surjho Bhattacharya", "Surjoo Bhattacharya")),
    "surjho bhattacharya": ("Shurjo Bhattacharya", ("Surjho Bhattacharya", "Surjoo Bhattacharya")),
    "surjoo bhattacharya": ("Shurjo Bhattacharya", ("Surjho Bhattacharya", "Surjoo Bhattacharya")),
}


# Reviewed identities share a display credit; familiar spellings remain aliases.
# Match complete names only: never merge people by a surname or phonetic guess.
PERSON_GROUPS = {
    "Gurū Gobind Siṅgh": ("Guru Gobind Singh", "Guru Gobind", "Guru Govind Singh"),
    "Gurū Nānak": ("Guru Nanak", "Nanak", "Nānak", "Guru Nanak Dev", "Nanak Dev"),
    "Gurū Aṅgad": ("Guru Angad", "Guru Angad Dev", "Angad Dev"),
    "Gurū Amar Dās": ("Guru Amar Das", "Guru Amardas", "Amar Das", "Amardas"),
    "Gurū Rām Dās": ("Guru Ram Das", "Guru Ramdas", "Ram Das", "Ramdas"),
    "Gurū Arjan": ("Guru Arjan", "Guru Arjan Dev", "Guru Arjun Dev", "Arjan Dev", "Arjun Dev"),
    "Gurū Teg Bahādar": ("Guru Teg Bahadar", "Guru Tegh Bahadur", "Guru Teg Bahadur", "Tegh Bahadur", "Teg Bahadur"),
    "Nāmadev": ("Namadev", "Namdev", "Nāmdev", "Sant Namdev", "Namadeva", "Bhagat Namdev"),
    "Tukārām": ("Tukaram", "Sant Tukaram", "Tukaram Maharaj"),
    "Sūrdās": ("Surdas", "Sur Das"),
    "Tulsīdās": ("Tulsidas", "Tulasīdāsa", "Tulasidas", "Tulsi Das", "Goswami Tulsidas"),
    "Kabīr": ("Kabir", "Kabir Das", "Kabirdas", "Sant Kabir", "Bhagat Kabir"),
    "Annamācārya": ("Annamacharya", "Annamayya", "Tallapaka Annamacharya"),
    "Tyāgarāja": ("Tyagaraja", "Thyagaraja", "Thyagarajar"),
    "Purandaradāsa": ("Purandaradasa", "Purandara Dasa"),
    "Mīrābāī": ("Mirabai", "Meera", "Meera Bai", "Mira Bai"),
    "Nammāḻvār": ("Nammalvar", "Nammalwar", "Nammazhwar"),
    "M. S. Subbulakshmi": ("MS Subbulakshmi", "M S Subbulakshmi", "M.S. Subbulakshmi", "M S Subbulaxmi", "MS Subbulaxmi"),
    "Sadhana Sargam": ("Sadhna Sargam",),
    "Āṇḍāḷ": ("Andal", "Aandal"),
    "Ādi Śaṅkarācārya": ("Adi Shankaracharya", "Adi Sankaracharya", "Adi Shankara"),
}
# Bare Ramdas can denote other poets; it is a search alias, not an identity rule.
SEARCH_ONLY_NAMES = {"ram das", "ramdas", "amar das", "amardas"}
for _display, _aliases in PERSON_GROUPS.items():
    for _name in (_display, *_aliases):
        if _name.casefold() not in SEARCH_ONLY_NAMES:
            PERSON_CANONICALS[_name.casefold()] = (_display, _aliases)

PERSON_SEPARATOR = re.compile(r"(\s*(?:·|;|&|,|\band\b)\s*)", re.IGNORECASE)


def compact(value: str) -> str:
    """Collapse punctuation/spacing for comparisons without changing display text."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)).strip().casefold()


def unaccented(value: str) -> str:
    return "".join(character for character in unicodedata.normalize("NFKD", value)
                   if not unicodedata.combining(character))


def common_romanization(value: str) -> str:
    """Return a search spelling, not a replacement for reviewed display IAST."""
    return value.translate(IAST_TO_COMMON).replace("ngg", "ng").replace("Ngg", "Ng")


def canonical_iast(value: object) -> str:
    """Normalize model-produced vocalic r/l combining rings to standard IAST."""
    text = str(value or "")
    replacements = (
        ("r\u0325\u0304", "ṝ"), ("r\u0304\u0325", "ṝ"),
        ("R\u0325\u0304", "Ṝ"), ("R\u0304\u0325", "Ṝ"),
        ("l\u0325\u0304", "ḹ"), ("l\u0304\u0325", "ḹ"),
        ("L\u0325\u0304", "Ḹ"), ("L\u0304\u0325", "Ḹ"),
        ("r\u0325", "ṛ"), ("R\u0325", "Ṛ"),
        ("l\u0325", "ḷ"), ("L\u0325", "Ḷ"),
    )
    for source, target in replacements:
        text = text.replace(source, target)
    return unicodedata.normalize("NFC", text)


def canonical_person(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parts = PERSON_SEPARATOR.split(text)
    return "".join(part if index % 2 else PERSON_CANONICALS.get(
        part.strip().casefold(), (part, ()))[0]
        for index, part in enumerate(parts))


def person_search_aliases(values: Iterable[object]) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    for value in (part for value in values
                  for part in PERSON_SEPARATOR.split(str(value or ""))[::2]):
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

#!/usr/bin/env python3
"""Conservative deterministic deity tags from explicit lyric names."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import naming

ROOT = Path(__file__).resolve().parents[1]


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


def _unique_registry_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate reviewed-tag registry key {key!r}")
        result[key] = value
    return result


def apply_reviewed_subject_tags(
    meta: dict[str, Any], slug: str, lines: Mapping[str, dict[str, Any]],
    sequence: list[dict[str, Any]], *, root: Path = ROOT,
) -> None:
    """Apply researched tag changes while their exact performed text remains.

    The registry owns contextual classification; this operation does not infer
    identities from author metadata or keywords. Evidence lineId is an optional
    locator, not identity: regeneration may renumber lines. Every evidence source
    must match a complete line referenced by sequence, without normalization.
    Validate all applicable evidence before changing meta. Removals require an
    explicit remove witness; surviving tags keep their order before additions.
    A stale witness requires fresh review, even when a removal is already applied.
    """
    path = Path(root) / "data" / "song_tag_overrides.json"
    try:
        registry = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_registry_object)
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid reviewed-tag registry {path}: {exc}") from exc
    if (not isinstance(registry, dict) or type(registry.get("version")) is not int
            or registry["version"] != 1 or not isinstance(registry.get("songs"), dict)):
        raise ValueError(f"invalid reviewed-tag registry structure: {path}")
    for song, record in registry["songs"].items():
        if not isinstance(song, str) or not song.strip() or not isinstance(record, dict):
            raise ValueError(f"invalid reviewed-tag record: {song!r}")
        additions, removals = record.get("addTags"), record.get("removeTags", [])
        evidence = record.get("evidence")
        if (not isinstance(additions, list) or not isinstance(removals, list)
                or not (additions or removals)
                or any(not isinstance(tag, str) or not tag.strip() for tag in [*additions, *removals])
                or len(set(additions)) != len(additions) or len(set(removals)) != len(removals)
                or set(additions).intersection(removals)
                or not isinstance(evidence, list) or not evidence):
            raise ValueError(f"{song}: invalid reviewed tags or evidence")
        actions = {("add", tag) for tag in additions} | {("remove", tag) for tag in removals}
        covered = set()
        for witness in evidence:
            if (not isinstance(witness, dict)
                    or any(not isinstance(witness.get(field), str) or not witness[field].strip()
                           for field in ("tag", "source", "reason"))
                    or not isinstance(witness.get("operation", "add"), str)
                    or (witness.get("operation", "add"), witness["tag"]) not in actions
                    or ("lineId" in witness and
                        (not isinstance(witness["lineId"], str) or not witness["lineId"].strip()))):
                raise ValueError(f"{song}: invalid reviewed-tag witness")
            covered.add((witness.get("operation", "add"), witness["tag"]))
        if covered != actions:
            raise ValueError(f"{song}: every reviewed tag action needs source evidence")
    record = registry["songs"].get(slug)
    if record is None:
        return
    if not isinstance(lines, Mapping) or not isinstance(sequence, list):
        raise ValueError(f"{slug}: invalid lines or sequence for reviewed tags")
    performed_sources = set()
    for entry in sequence:
        ref = entry.get("ref") if isinstance(entry, dict) else None
        if not isinstance(ref, str) or ref not in lines or not isinstance(lines[ref], Mapping):
            raise ValueError(f"{slug}: invalid performed reference {ref!r}")
        source = lines[ref].get("source")
        if not isinstance(source, str):
            raise ValueError(f"{slug}:{ref}: missing performed source")
        performed_sources.add(source)
    for witness in record["evidence"]:
        if witness["source"] not in performed_sources:
            raise ValueError(f"{slug}: {witness['tag']} evidence changed or is not performed; review its tag")
    existing = meta.get("subjectTags", [])
    if not isinstance(existing, list) or any(not isinstance(tag, str) for tag in existing):
        raise ValueError(f"{slug}: invalid existing subjectTags")
    removed = set(record.get("removeTags", []))
    meta["subjectTags"] = list(dict.fromkeys([
        *(tag for tag in existing if tag not in removed), *record["addTags"],
    ]))

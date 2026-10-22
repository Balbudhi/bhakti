"""Enforce saved owner English while allowing changes to word-link indices.

The registry's plainEnglishByLine is the immutable editorial reference for a
registered song. Never derive the reference from a current reader at write time:
that reader may already have been changed. This guard protects visible English,
not source text, grammar, audio, or semantic correctness of new word links.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SLOT = re.compile(r'\{\s*[0-9]+(?:\s*,\s*[0-9]+)*\s*:([^{}]*)\}')


def plain_english(value: str) -> str:
    """Remove valid link notation only; preserve all visible characters exactly."""
    return SLOT.sub(r'\1', value)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate key {key!r}')
        result[key] = value
    return result


def load_baselines(root: Path = ROOT) -> dict[str, dict[str, Any]]:
    """Read and validate the whole registry, failing closed on missing data."""
    path = Path(root) / 'data' / 'editorial_baselines.json'
    try:
        registry = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f'invalid editorial baseline registry: {path}: {exc}') from exc
    if (not isinstance(registry, dict) or type(registry.get('version')) is not int
            or registry['version'] != 1 or not isinstance(registry.get('songs'), dict)):
        raise RuntimeError(f'invalid editorial baseline registry structure: {path}')
    songs = registry['songs']
    for slug, entry in songs.items():
        if (not isinstance(slug, str) or not slug.strip() or not isinstance(entry, dict)
                or entry.get('policy') != 'preserve_english'
                or not isinstance(entry.get('englishSha256'), str)
                or not re.fullmatch(r'[0-9a-f]{64}', entry['englishSha256'])
                or not isinstance(entry.get('plainEnglishByLine'), dict)
                or not entry['plainEnglishByLine']):
            raise RuntimeError(f'invalid editorial baseline for {slug!r}: {path}')
        for line_id, english in entry['plainEnglishByLine'].items():
            if (not isinstance(line_id, str) or not line_id.strip()
                    or not isinstance(english, str) or not english.strip()
                    or plain_english(english) != english):
                raise RuntimeError(f'invalid saved English for {slug}:{line_id}')
    return songs


def assert_english_preserved(
    slug: str, new_lines: Mapping[str, Any], *, root: Path = ROOT,
) -> None:
    """Reject a changed English population/text for an owner-designated song.

    Caller supplies the complete proposed SONG_LINES map before any write. Line
    dictionary order and valid word-link grouping may change; line IDs and the
    exact visible English must match the saved baseline. Unregistered songs pass
    after registry validation. The original indexed-English hash is provenance,
    not the comparison key, because link-only corrections must remain possible.
    """
    baseline = load_baselines(root).get(slug)
    if baseline is None:
        return
    if not isinstance(new_lines, Mapping):
        raise RuntimeError(f'{slug}: proposed lines are not a mapping')
    expected = baseline['plainEnglishByLine']
    missing = set(expected) - set(new_lines)
    extra = set(new_lines) - set(expected)
    if missing or extra:
        raise RuntimeError(
            f'{slug}: protected English line population changed '
            f'(missing={sorted(missing)}, extra={sorted(extra, key=str)})'
        )
    for line_id, saved in expected.items():
        line = new_lines[line_id]
        english = line.get('english') if isinstance(line, Mapping) else None
        if not isinstance(english, str) or plain_english(english) != saved:
            raise RuntimeError(
                f'{slug}:{line_id}: owner-designated English changed; '
                'preserve the saved wording and report source/gloss conflicts separately'
            )

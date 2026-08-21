#!/usr/bin/env python3
"""Deterministically link source-script tokens to public word-gloss indices."""

from __future__ import annotations

import unicodedata
from functools import lru_cache
from typing import Any

try:
    from indic_transliteration import sanscript
except ImportError:  # The common whitespace-preserving path needs no package.
    sanscript = None


SCRIPT_RANGES = (
    (0x0900, 0x097F, "DEVANAGARI"),
    (0x0A00, 0x0A7F, "GURMUKHI"),
    (0x0B00, 0x0B7F, "ORIYA"),
    (0x0C80, 0x0CFF, "KANNADA"),
)


def lexical_tokens(value: str) -> list[str]:
    return [token for token in str(value).split() if any(character.isalnum() for character in token)]


def _normal(value: str) -> str:
    return "".join(
        character for character in unicodedata.normalize("NFKD", str(value)).casefold()
        if character.isalnum()
    )


def _source_scheme(value: str) -> Any:
    if sanscript is None:
        return None
    for character in value:
        point = ord(character)
        for lower, upper, name in SCRIPT_RANGES:
            if lower <= point <= upper:
                return getattr(sanscript, name)
    return None


def _edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_character in enumerate(left, 1):
        current = [left_index]
        for right_index, right_character in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[right_index] + 1,
                previous[right_index - 1] + (left_character != right_character),
            ))
        previous = current
    return previous[-1]


def _compound_alignment(source: str, source_tokens: list[str], words: list[dict[str, Any]]) -> list[tuple[int, int, int, int]]:
    if sanscript is None:
        raise RuntimeError(
            "indic-transliteration is required when source-script and romanized whitespace differ"
        )
    scheme = _source_scheme(source)
    if scheme is None:
        raise RuntimeError("source-script mapping cannot identify the Indic script")
    source_forms = [
        _normal(sanscript.transliterate(token, scheme, sanscript.IAST))
        for token in source_tokens
    ]
    roman_forms = [_normal(word.get("roman", "")) for word in words]
    source_count, word_count = len(source_tokens), len(words)

    @lru_cache(maxsize=None)
    def solve(source_index: int, word_index: int) -> tuple[float, tuple[tuple[int, int, int, int], ...]]:
        if source_index == source_count and word_index == word_count:
            return 0.0, ()
        best_cost = float("inf")
        best_path: tuple[tuple[int, int, int, int], ...] = ()
        for source_size in range(1, min(5, source_count - source_index) + 1):
            for word_size in range(1, min(5, word_count - word_index) + 1):
                source_form = "".join(source_forms[source_index:source_index + source_size])
                roman_form = "".join(roman_forms[word_index:word_index + word_size])
                distance = _edit_distance(source_form, roman_form) / max(1, len(source_form), len(roman_form))
                # Strongly prefer the smallest local grouping. Larger groups
                # are selected only when source compounds or roman phrases
                # make them materially better matches.
                local_cost = distance + 0.35 * (source_size + word_size - 2)
                tail_cost, tail_path = solve(source_index + source_size, word_index + word_size)
                if local_cost + tail_cost < best_cost:
                    best_cost = local_cost + tail_cost
                    best_path = ((source_index, source_size, word_index, word_size), *tail_path)
        return best_cost, best_path

    _, path = solve(0, 0)
    if not path:
        raise RuntimeError("source-script mapping could not align source and romanized words")
    return list(path)


def build_source_words(source: str, words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return exact source surfaces linked to one or more word indices."""
    source_tokens = lexical_tokens(source)
    if not source_tokens or not words:
        return []
    roman_widths = [max(1, len(lexical_tokens(str(word.get("roman", ""))))) for word in words]
    if sum(roman_widths) == len(source_tokens):
        path = []
        source_index = 0
        for word_index, width in enumerate(roman_widths):
            path.append((source_index, width, word_index, 1))
            source_index += width
    else:
        path = _compound_alignment(source, source_tokens, words)

    mapped: list[dict[str, Any]] = []
    for source_index, source_size, word_index, word_size in path:
        indices = list(range(word_index, word_index + word_size))
        if source_size == word_size:
            for offset in range(source_size):
                mapped.append({"text": source_tokens[source_index + offset], "wordIndices": [word_index + offset]})
        else:
            for offset in range(source_size):
                mapped.append({"text": source_tokens[source_index + offset], "wordIndices": indices})
    covered = {index for item in mapped for index in item["wordIndices"]}
    if covered != set(range(len(words))):
        raise RuntimeError("source-script mapping does not cover every public word index")
    return mapped


def validate_source_words(source: str, words: list[dict[str, Any]], mapped: Any) -> list[str]:
    if not isinstance(mapped, list) or not mapped:
        return ["sourceWords is missing"]
    expected_surfaces = lexical_tokens(source)
    observed_surfaces = []
    covered: set[int] = set()
    for item in mapped:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            return ["sourceWords contains an invalid entry"]
        indices = item.get("wordIndices")
        if (not isinstance(indices, list) or not indices
                or any(not isinstance(index, int) or not 0 <= index < len(words) for index in indices)):
            return ["sourceWords contains invalid word indices"]
        observed_surfaces.append(item["text"])
        covered.update(indices)
    errors = []
    if observed_surfaces != expected_surfaces:
        errors.append("sourceWords does not preserve source-script token order")
    if covered != set(range(len(words))):
        errors.append("sourceWords does not cover every public word index")
    return errors

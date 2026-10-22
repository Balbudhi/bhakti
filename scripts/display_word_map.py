"""Remove hidden structural markers without inventing lexical word links."""

from __future__ import annotations

import copy
import re
import unicodedata


def _number(value: str) -> str | None:
    value = value.strip(" \t\r\n.।॥|")
    if not value or not all(character.isdecimal() for character in value):
        return None
    return "".join(str(unicodedata.decimal(character)) for character in value)


def clean_display_word_map(line: dict) -> tuple[dict, dict]:
    """Drop only absent numeric markers and empty, explicitly metrical entries.

    The caller must already have finalized source and roman display text. English
    is retained verbatim when its only link disappears, and reported for review.
    A source token losing all lexical support is an error, never a guessed link.
    """
    result = copy.deepcopy(line)
    words = line["words"]
    visible_numbers = {
        number for field in ("source", "roman")
        for token in line.get(field, "").split()
        if (number := _number(token)) is not None
    }
    removed = []
    for index, word in enumerate(words):
        roman = word.get("roman", "").strip()
        number = _number(roman)
        empty_meter = not roman and re.search(
            r"\b(?:meter|metre|metrical|chhand)\b", word.get("gloss", ""), re.I
        )
        if (number is not None and number not in visible_numbers) or empty_meter:
            removed.append(index)
    report = {"removedWordIndices": removed, "unlinkedEnglish": []}
    if not removed:
        return result, report
    removed_set = set(removed)
    mapping = {old: new for new, old in enumerate(
        index for index in range(len(words)) if index not in removed_set
    )}

    def remap(indices):
        if any(type(index) is not int or not 0 <= index < len(words) for index in indices):
            raise ValueError("word index is outside the original word map")
        return [mapping[index] for index in indices if index in mapping]

    result["words"] = [word for index, word in enumerate(result["words"]) if index in mapping]
    for token in result.get("sourceWords", []):
        indices = remap(token["wordIndices"])
        if not indices:
            raise ValueError(f"source token loses all word support: {token['text']!r}")
        token["wordIndices"] = indices

    def english_link(match):
        indices = remap([int(index.strip()) for index in match[1].split(",")])
        if not indices:
            report["unlinkedEnglish"].append(match[2])
            return match[2]
        return "{" + ",".join(map(str, indices)) + ":" + match[2] + "}"

    result["english"] = re.sub(r"\{([\d,\s]+):([^}]*)\}", english_link, line["english"])
    return result, report

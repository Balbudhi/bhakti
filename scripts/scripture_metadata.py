"""Apply researched scripture citations using the existing section-notice UI."""

import json
from pathlib import Path


REGISTRY = Path(__file__).resolve().parents[1] / "data" / "scripture_metadata.json"


def apply(meta: dict, slug: str, sequence: list[dict]) -> None:
    """Retain tags and aliases; fail if a reviewed passage boundary has moved."""
    record = json.loads(REGISTRY.read_text(encoding="utf-8")).get(slug)
    if not record:
        return
    notices = []
    for notice in record["sectionNotices"]:
        index = notice["sequenceIndex"]
        if not 0 <= index < len(sequence) or sequence[index]["ref"] != notice["expectedRef"]:
            raise ValueError(f"{slug}: scripture boundary {index} needs review")
        notices.append({key: notice[key] for key in ("sequenceIndex", "title", "poet", "note")})
    old_writer = meta.get("writer", "")
    meta["writer"] = record["writer"]
    if old_writer:
        meta["credit"] = meta.get("credit", "").replace(old_writer, record["writer"])
    meta["subjectTags"] = list(dict.fromkeys([*meta.get("subjectTags", []), "Gurbāṇī"]))
    meta["searchAliases"] = list(dict.fromkeys([
        *meta.get("searchAliases", []), "Gurbani", "Sikh", "Sikhi", "Sikhī",
        "Guru Granth Sahib", record["writer"],
    ]))
    meta["sectionNotices"] = notices

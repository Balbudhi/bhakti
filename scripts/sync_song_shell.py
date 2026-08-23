#!/usr/bin/env python3
"""Regenerate every song shell from the one authoritative page template."""

from __future__ import annotations

from pathlib import Path

import audit_bhakti_contract as audit
import bhakti_pipeline as pipeline


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    for index_path in sorted((ROOT / "songs").glob("*/index.html")):
        data = audit.load_data(index_path.with_name("data.js"))
        index_path.write_text(pipeline.page_html(data["SONG_META"]), encoding="utf-8")
    pipeline.write_catalogue()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

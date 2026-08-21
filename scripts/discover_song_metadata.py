#!/usr/bin/env python3
"""Build a zero-cost official-source review queue for incomplete song credits.

Search results are evidence to review, never automatic public writer/singer
claims. This uses YouTube search metadata only; it makes no model/API calls.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import difflib
import unicodedata
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    return " ".join("".join(ch for ch in token if ch.isalnum() and not unicodedata.combining(ch))
                    for token in value.split())


def catalogue() -> list[dict[str, Any]]:
    script = "global.window={};require(process.argv[1]);process.stdout.write(JSON.stringify(window.BHAKTI_SONGS));"
    output = subprocess.run(["node", "-e", script, str(ROOT / "data" / "songs.js")], check=True,
                            capture_output=True, text=True).stdout
    return json.loads(output)


def search(song: dict[str, Any]) -> dict[str, Any]:
    missing = [role for role in ("writer", "singer", "composer") if not str(song.get(role) or "").strip()]
    query = " ".join(part for part in (normalized(str(song.get("title") or "")),
                                         normalized(str(song.get("singer") or ""))) if part).strip()
    result = subprocess.run(["yt-dlp", "--flat-playlist", "--dump-single-json", f"ytsearch3:{query}"],
                            capture_output=True, text=True)
    candidates = []
    if result.returncode == 0:
        try:
            payload = json.loads(result.stdout)
            title = normalized(str(song.get("title") or ""))
            for item in payload.get("entries", []):
                candidate_title = normalized(str(item.get("title") or ""))
                score = difflib.SequenceMatcher(None, title, candidate_title).ratio()
                if score < 0.42:
                    continue
                candidates.append({**{key: item.get(key) for key in ("id", "title", "channel", "uploader", "duration")},
                                   "title_similarity": round(score, 3)})
        except json.JSONDecodeError:
            pass
    return {"slug": song["slug"], "title": song.get("title"), "missing_roles": missing,
            "query": query, "candidates": candidates,
            "instruction": "Review title, official channel/Topic provenance, description credits, and a lyric witness before publishing any role."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    targets = [song for song in catalogue() if any(not str(song.get(role) or "").strip()
               for role in ("writer", "singer", "composer"))]
    if args.limit:
        targets = targets[:args.limit]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        rows = list(pool.map(search, targets))
    output = ROOT / ".transcription" / "metadata-discovery-queue.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps({"count": len(rows), "items": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"queued": len(rows), "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())

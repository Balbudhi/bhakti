#!/usr/bin/env python3
"""Create an audio-only, review-first Bhakti song intake from a YouTube URL."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="YouTube or another yt-dlp-supported media URL")
    parser.add_argument("song_dir", type=Path, help="New local Bhakti directory to create")
    parser.add_argument("--skip-transcription", action="store_true", help="Download and capture metadata only")
    parser.add_argument("--model", default="google/gemini-3.6-flash")
    return parser.parse_args()


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=True)


def main() -> int:
    args = parse_args()
    song_dir = args.song_dir.resolve()
    if song_dir.exists() and any(song_dir.iterdir()):
        raise SystemExit(f"refusing to overwrite a non-empty song directory: {song_dir}")
    song_dir.mkdir(parents=True, exist_ok=True)

    metadata: dict[str, Any] = json.loads(
        run(["yt-dlp", "--no-playlist", "--dump-single-json", "--skip-download", args.url]).stdout
    )
    review_dir = song_dir / ".transcription"
    review_dir.mkdir(exist_ok=True)
    source = {
        "source_url": metadata.get("webpage_url") or args.url,
        "title": metadata.get("title"),
        "uploader": metadata.get("uploader"),
        "channel": metadata.get("channel"),
        "upload_date": metadata.get("upload_date"),
        "duration_seconds": metadata.get("duration"),
        "description": metadata.get("description"),
        "extractor_key": metadata.get("extractor_key"),
        "id": metadata.get("id"),
        "review_note": "Source metadata is evidence to verify, not an automatic public credit or translation source.",
    }
    (review_dir / "source.json").write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    run(["yta", args.url, "--output-dir", str(song_dir)])
    downloads = list(song_dir.glob("*.m4a"))
    if len(downloads) != 1:
        raise RuntimeError(f"expected exactly one downloaded M4A file, found {len(downloads)}")
    downloads[0].replace(song_dir / "audio.m4a")

    if not args.skip_transcription:
        subprocess.run(
            [sys.executable, str(Path(__file__).with_name("transcribe_bhakti_openrouter.py")), str(song_dir), "--model", args.model],
            check=True,
        )
    print(f"Created audio-only intake at {song_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

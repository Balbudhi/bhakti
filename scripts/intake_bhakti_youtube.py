#!/usr/bin/env python3
"""Create an audio-only, review-first Bhakti song intake from a YouTube URL.

The helper accepts YouTube Music watch/share URLs and records the canonical
YouTube watch URL that yt-dlp resolves before the download step.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


AUDIO_SUFFIXES = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav", ".webm"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="YouTube or another yt-dlp-supported media URL")
    parser.add_argument("song_dir", type=Path, help="New local Bhakti directory to create")
    parser.add_argument("--skip-transcription", action="store_true", help="Download and capture metadata only")
    parser.add_argument("--model", default="google/gemini-3.7-flash")
    return parser.parse_args()


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=True)


def canonical_source_url(metadata: dict[str, Any], requested_url: str) -> str:
    webpage = str(metadata.get("webpage_url") or "").strip()
    if webpage:
        return webpage
    requested = requested_url.strip()
    if "music.youtube.com" in requested.casefold() and metadata.get("id"):
        return f"https://www.youtube.com/watch?v={metadata['id']}"
    return requested


def downloaded_audio_files(song_dir: Path) -> list[Path]:
    return sorted(
        path for path in song_dir.glob("audio.*")
        if path.is_file() and path.suffix.casefold() in AUDIO_SUFFIXES
    )


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
    source_url = canonical_source_url(metadata, args.url)
    source = {
        "requested_source_url": args.url,
        "source_url": source_url,
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

    run(["yta", source_url, "--output-dir", str(song_dir)])
    downloads = downloaded_audio_files(song_dir)
    if len(downloads) != 1:
        raise RuntimeError(f"expected exactly one downloaded audio file, found {len(downloads)}")
    primary = downloads[0]
    preserved = song_dir / f"audio{primary.suffix.casefold()}"
    if primary != preserved:
        primary.replace(preserved)
        primary = preserved
    if primary.suffix.casefold() != ".m4a":
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(primary),
                "-vn", "-c:a", "aac", "-b:a", "192k", str(song_dir / "audio.m4a"),
            ],
            check=True,
        )
    elif primary.name != "audio.m4a":
        primary.replace(song_dir / "audio.m4a")

    if not args.skip_transcription:
        subprocess.run(
            [sys.executable, str(Path(__file__).with_name("transcribe_bhakti_openrouter.py")), str(song_dir), "--model", args.model],
            check=True,
        )
    print(f"Created audio-only intake at {song_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

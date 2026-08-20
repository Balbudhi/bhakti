#!/usr/bin/env python3
"""Report listener-audio codec quality and missing YouTube best-stream files."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import bhakti_pipeline as pipeline


ROOT = Path(__file__).resolve().parents[1]


def probe(path: Path) -> dict:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                             "format=duration,size,bit_rate:stream=codec_name,sample_rate,channels,bit_rate",
                             "-of", "json", str(path)], check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    stream, fmt = data["streams"][0], data["format"]
    return {"file": path.name, "codec": stream.get("codec_name"), "sample_rate": int(stream.get("sample_rate", 0)),
            "channels": stream.get("channels"), "bit_rate": int(stream.get("bit_rate") or fmt.get("bit_rate") or 0),
            "duration": float(fmt["duration"]), "size": int(fmt["size"])}


def main() -> int:
    reports = []
    errors = []
    for song in sorted((ROOT / "songs").iterdir()):
        if not song.is_dir():
            continue
        source_path = song / ".transcription" / "source.json"
        source = json.loads(source_path.read_text(encoding="utf-8")) if source_path.is_file() else {}
        files = [song / item["src"] for item in pipeline.listener_audio_sources(song)]
        if not files:
            errors.append(f"{song.name}: no listener audio")
            continue
        if "youtube.com" in str(source.get("source_url", "")) and not (song / "audio.webm").is_file():
            errors.append(f"{song.name}: YouTube source lacks preserved best Opus stream")
        reports.append({"slug": song.name, "preferred": files[0].name, "sources": [probe(path) for path in files]})
    print(json.dumps({"songs": reports, "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

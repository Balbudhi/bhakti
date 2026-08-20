#!/usr/bin/env python3
"""Create a complete, reviewable song packet with Gemini Flash through OpenRouter.

The pipeline deliberately uses three different tasks, not duplicate generic
passes: full-song transcription, lyric-aware full-song alignment, then
translation/glossing. Nothing edits a public reader until the resulting packet
has passed review.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import subprocess


MODEL = "google/gemini-3.6-flash"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_KEY = Path.home() / "Dev" / "openrouter.key"


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("song_dir", type=Path, help="Contains audio.m4a")
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--provided-translation", type=Path, help="Optional user translation JSON/text for comparison")
    parser.add_argument("--timeout", type=float, default=300)
    return parser.parse_args()


def key() -> str:
    value = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if value:
        return value
    path = Path(os.environ.get("OPENROUTER_API_KEY_FILE", DEFAULT_KEY)).expanduser()
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise RuntimeError(f"refusing insecure key file: {path}")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError("OpenRouter key is empty")
    return value


def call(model: str, api_key: str, prompt: str, *, audio: Path | None, timeout: float) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if audio:
        content.append({
            "type": "input_audio",
            "input_audio": {"data": base64.b64encode(audio.read_bytes()).decode("ascii"), "format": audio.suffix.removeprefix(".")},
        })
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [{"role": "user", "content": content}],
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "HTTP-Referer": "https://bhakti.eeshan.xyz/", "X-Title": "Bhakti song processing"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OpenRouter HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:800]}") from exc
    try:
        text = result["choices"][0]["message"]["content"]
        if isinstance(text, list):
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(text).strip())
        parsed = json.loads(text)
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("Gemini did not return the required JSON packet") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Gemini JSON packet must be an object")
    return {"packet": parsed, "usage": result.get("usage", {}), "resolved_model": result.get("model", model)}


def source_metadata(song_dir: Path) -> dict[str, Any]:
    source = song_dir / ".transcription" / "source.json"
    if not source.is_file():
        return {}
    data = json.loads(source.read_text(encoding="utf-8"))
    return {key: data.get(key) for key in ("source_url", "title", "uploader", "channel", "description", "duration_seconds")}


def duration_seconds(audio: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nokey=1:noprint_wrappers=1", str(audio)],
        check=True, capture_output=True, text=True,
    )
    return float(result.stdout.strip())


def validate_alignment(packet: dict[str, Any], duration: float) -> list[str]:
    errors: list[str] = []
    previous = -0.001
    for index, entry in enumerate(packet.get("sequence", [])):
        try:
            start, end = float(entry["start"]), float(entry["end"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"sequence[{index}] has no numeric start/end")
            continue
        if not 0 <= start <= duration or not 0 <= end <= duration:
            errors.append(f"sequence[{index}] exceeds audio duration ({start}–{end} vs {duration})")
        if end < start:
            errors.append(f"sequence[{index}] ends before it starts")
        if start + 0.01 < previous:
            errors.append(f"sequence[{index}] is out of order")
        previous = max(previous, start)
    return errors


def main() -> int:
    options = args()
    song_dir = options.song_dir.resolve()
    audio = (options.audio or song_dir / "audio.m4a").resolve()
    if not audio.is_file():
        raise SystemExit("audio.m4a is required")
    out = song_dir / ".transcription" / "gemini-song-packet"
    out.mkdir(parents=True, exist_ok=True)
    source = source_metadata(song_dir)
    duration = duration_seconds(audio)
    api_key = key()

    transcription_prompt = f"""You are performing the primary transcription of one complete devotional song. Listen to the ENTIRE attached recording carefully. Do not omit a single sung, spoken, call-and-response, invocation, refrain, verse, tag, or returning line. Do not infer repeat counts. Do not translate yet.

Use the source metadata only as a lead; do not invent singers or credits from it:
{json.dumps(source, ensure_ascii=False)}

Return strict JSON: {{"metadata":{{"languages":[],"script":"","singer_candidates":[],"credit_evidence":[]}},"lines":[{{"id":"stable-kebab-id","source_text":"exact heard text in source script when known","roman":"careful transliteration","kind":"invocation|refrain|verse|bridge|closing|spoken|instrumental|uncertain","notes":""}}],"performance_order":[{{"line_id":"id","occurrence":1,"notes":""}}],"uncertainties":[]}}. The performance_order must include every return as a separate item."""
    print("Gemini stage 1/3: complete transcription…", file=sys.stderr)
    transcription = call(options.model, api_key, transcription_prompt, audio=audio, timeout=options.timeout)
    (out / "01-transcription.json").write_text(json.dumps(transcription, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    alignment_prompt = f"""You are verifying a complete lyric transcript against the ENTIRE attached recording. The recording duration is exactly {duration:.3f} seconds. The candidate transcript is below. Listen from start to finish and return the corrected canonical lyrics plus the actual performance order and first-syllable absolute source time for every displayed entry.

Critical rules: do not drop a line; do not replace a lead pickup with a later chorus; do not merge a returning line with an earlier occurrence; do not guess repeat counts. A timing starts at the first audible syllable of that exact displayed lyric. Repeats may only cover immediately contiguous identical performances. Include spoken invocations and genuine vocal tags; leave instrumental gaps unlabelled. Every start/end must be between 0 and {duration:.3f}; an output outside that range is invalid.

Candidate transcript:
{json.dumps(transcription['packet'], ensure_ascii=False)}

Return strict JSON: {{"verified_lines":[{{"id":"","source_text":"","roman":"","kind":"","translation_notes":""}}],"sequence":[{{"ref":"id","section":"invocation|refrain|verse|bridge|closing|spoken|instrumental","repeats":1,"start":0.0,"end":0.0,"evidence":""}}],"missing_or_changed":[],"trim":{{"recommended":false,"start":null,"end":null,"reason":""}}}}."""
    print("Gemini stage 2/3: lyric-aware timing and sequence…", file=sys.stderr)
    alignment = call(options.model, api_key, alignment_prompt, audio=audio, timeout=options.timeout)
    (out / "02-alignment.json").write_text(json.dumps(alignment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    alignment_errors = validate_alignment(alignment["packet"], duration)
    if alignment_errors:
        packet = {"source": source, "model_requested": options.model, "duration_seconds": duration, "created_at": time.time(), "transcription": transcription, "alignment": alignment, "validation_errors": alignment_errors, "publication_status": "blocked"}
        (out / "song-packet.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Alignment is invalid; translation skipped and publication blocked.", file=sys.stderr)
        return 2

    provided = options.provided_translation.read_text(encoding="utf-8") if options.provided_translation else None
    translation_prompt = f"""Translate the verified devotional lyrics below. Produce a literal, grammar-faithful English rendering that preserves poetic imagery and devotional register, plus concise word-level glosses. Never omit a line or add doctrinal interpretation. Treat uncertainty honestly.

When a supplied translation exists, compare it as an independent witness: retain good wording, identify material differences, and explain each change. Do not treat it as automatically correct or automatically disposable.

Verified lyrics:
{json.dumps(alignment['packet'].get('verified_lines', []), ensure_ascii=False)}

Supplied translation (optional):
{provided or '(none)'}

Return strict JSON: {{"translations":[{{"id":"","literal_english":"","poetic_english":"","word_glosses":[{{"roman":"","gloss":""}}],"uncertainty":""}}],"comparison":[{{"id":"","supplied":"","chosen":"","reason":""}}]}}."""
    print("Gemini stage 3/3: translation and comparison…", file=sys.stderr)
    translation = call(options.model, api_key, translation_prompt, audio=None, timeout=options.timeout)
    (out / "03-translation.json").write_text(json.dumps(translation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    packet = {"source": source, "model_requested": options.model, "duration_seconds": duration, "created_at": time.time(), "transcription": transcription, "alignment": alignment, "translation": translation, "publication_status": "review-required"}
    (out / "song-packet.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote review packet: {out / 'song-packet.json'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

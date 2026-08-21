#!/usr/bin/env python3
"""Compare direct Google and OpenRouter on one short audio/schema request."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

import process_song_gemini as gemini


SCHEMA = {
    "type": "object",
    "properties": {
        "candidate_is_exact": {"type": "boolean"},
        "first_complete_line_source": {"type": "string"},
        "first_complete_line_roman": {"type": "string"},
        "contains_music": {"type": "boolean"},
    },
    "required": ["candidate_is_exact", "first_complete_line_source", "first_complete_line_roman", "contains_music"],
    "additionalProperties": False,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--duration", type=float, default=16.0)
    parser.add_argument("--source", required=True)
    parser.add_argument("--roman", required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    options = parse_args()
    prompt = f"""Listen to the complete attached devotional-song excerpt carefully.

Candidate first complete sung line:
Source: {options.source}
Roman: {options.roman}

Decide whether the candidate exactly matches the first complete sung line. Return the exact source-script line and careful Roman transliteration heard in the audio. Do not translate or add commentary. Return strict JSON only."""
    with tempfile.TemporaryDirectory(prefix="bhakti-provider-probe-") as temporary:
        clip = Path(temporary) / "probe.m4a"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{options.start:.3f}",
            "-i", str(options.audio), "-t", f"{options.duration:.3f}", "-vn", "-c:a", "aac", "-b:a", "192k", str(clip),
        ], check=True)
        results = {}
        errors = {}
        for provider in ("google", "openrouter"):
            os.environ["BHAKTI_GEMINI_PROVIDER"] = provider
            try:
                response = gemini.call(
                    gemini.MODEL, gemini.key(), prompt, audio=clip, timeout=300,
                    response_schema=SCHEMA, schema_name="bhakti_provider_probe",
                    reasoning_effort="high", max_completion_tokens=4096,
                )
                results[provider] = response
            except RuntimeError as exc:
                errors[provider] = str(exc)
    packets = {provider: result["packet"] for provider, result in results.items()}
    expected = {"candidate_is_exact": True, "first_complete_line_source": options.source,
                "first_complete_line_roman": options.roman, "contains_music": True}
    artifact = {
        "model": gemini.MODEL,
        "clip": {"source": str(options.audio), "start": options.start, "duration": options.duration},
        "expected": expected,
        "providers": {
            provider: {"packet": result["packet"], "usage": result.get("usage", {}),
                       "resolved_model": result.get("resolved_model", "")}
            for provider, result in results.items()
        },
        "errors": errors,
        "exact_provider_match": set(packets) == {"google", "openrouter"} and packets["google"] == packets["openrouter"],
        "both_match_expected": set(packets) == {"google", "openrouter"} and all(packet == expected for packet in packets.values()),
    }
    rendered = json.dumps(artifact, ensure_ascii=False, indent=2) + "\n"
    if options.output:
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if artifact["exact_provider_match"] and artifact["both_match_expected"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

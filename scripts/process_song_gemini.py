#!/usr/bin/env python3
"""Create a complete, reviewable song packet with Gemini Flash.

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
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import subprocess


MODEL = "google/gemini-3.7-flash"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
GOOGLE_API_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
BATCH_API_URL = "https://openrouter.ai/api/beta/batches"
AUTH_KEY_URL = "https://openrouter.ai/api/v1/auth/key"
CREDITS_URL = "https://openrouter.ai/api/v1/credits"
# Keys are never stored in the repository. Set OPENROUTER_API_KEY / GEMINI_API_KEY,
# or point OPENROUTER_API_KEY_FILE / GEMINI_API_KEY_FILE at an owner-only file.
KEY_DIR = Path(os.environ.get("BHAKTI_KEY_DIR") or (Path.home() / ".config" / "bhakti")).expanduser()
DEFAULT_KEY = KEY_DIR / "openrouter.key"
DEFAULT_GOOGLE_KEY = KEY_DIR / "gemini.key"
API_MAX_CONCURRENCY = max(1, int(os.environ.get("BHAKTI_API_MAX_CONCURRENCY", "4")))
BATCH_MAX_CONCURRENCY = max(1, int(os.environ.get("BHAKTI_BATCH_MAX_CONCURRENCY", "32")))
API_MIN_START_INTERVAL = max(0.0, float(os.environ.get("BHAKTI_API_MIN_START_INTERVAL", "0.35")))
_API_SLOTS = threading.BoundedSemaphore(API_MAX_CONCURRENCY)
_BATCH_SLOTS = threading.BoundedSemaphore(BATCH_MAX_CONCURRENCY)
_API_START_LOCK = threading.Lock()
_LAST_API_START = 0.0


def _wait_for_api_start() -> None:
    global _LAST_API_START
    with _API_START_LOCK:
        delay = API_MIN_START_INTERVAL - (time.monotonic() - _LAST_API_START)
        if delay > 0:
            time.sleep(delay)
        _LAST_API_START = time.monotonic()


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("song_dir", type=Path, help="Contains audio.m4a")
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--provided-translation", type=Path, help="Optional user translation JSON/text for comparison")
    parser.add_argument("--timeout", type=float, default=300)
    return parser.parse_args()


def provider_name() -> str:
    value = os.environ.get("BHAKTI_GEMINI_PROVIDER", "openrouter").strip().casefold()
    if value not in {"openrouter", "google"}:
        raise RuntimeError("BHAKTI_GEMINI_PROVIDER must be 'openrouter' or 'google'")
    return value


def _secure_key(environment: str, file_environment: str, default_path: Path, label: str) -> str:
    value = os.environ.get(environment, "").strip()
    if value:
        return value
    path = Path(os.environ.get(file_environment, default_path)).expanduser()
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise RuntimeError(f"refusing insecure key file: {path}")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"{label} key is empty")
    return value


def key() -> str:
    if provider_name() == "google":
        return _secure_key("GEMINI_API_KEY", "GEMINI_API_KEY_FILE", DEFAULT_GOOGLE_KEY, "Gemini")
    return _secure_key("OPENROUTER_API_KEY", "OPENROUTER_API_KEY_FILE", DEFAULT_KEY, "OpenRouter")


def provider_model(model: str, provider: str) -> str:
    model = batch_base_model(model)
    if provider == "google":
        return model.removeprefix("google/")
    return model


def request_headers(provider: str, api_key: str) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if provider == "openrouter":
        headers.update({"HTTP-Referer": "https://bhakti.eeshan.xyz/", "X-Title": "Bhakti song processing"})
    return headers


def permanent_provider_error(provider: str, status: int, detail: str) -> bool:
    lowered = detail.casefold()
    return provider == "google" and status == 429 and "prepayment credits are depleted" in lowered


def parse_json_packet(content: object) -> dict[str, Any]:
    text = str(content or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as original:
        if '\\"' not in text:
            raise original
        try:
            decoded = json.loads('"' + text.replace("\r", "\\r").replace("\n", "\\n") + '"')
            parsed = json.loads(decoded)
        except (TypeError, ValueError, json.JSONDecodeError):
            raise original
    if not isinstance(parsed, dict):
        raise RuntimeError("Gemini JSON packet must be an object")
    return parsed


def encoded_audio(audio: Path, provider: str) -> tuple[str, str]:
    """Return an OpenAI-compatible audio payload without changing song time.

    OpenRouter accepts the listener's native container. Google's compatibility
    documentation demonstrates WAV and its native API does not list WebM/Opus
    or M4A containers. For direct Google requests, use the original MP3 or make
    an in-memory mono MP3 at a rate well above Gemini's documented internal
    audio resolution. This avoids persistent duplicate files and stays under
    the 20 MB inline-request limit for the pipeline's <=15 minute core jobs.
    """
    if provider == "openrouter":
        encoded = base64.b64encode(audio.read_bytes()).decode("ascii")
        return encoded, audio.suffix.removeprefix(".")
    if audio.suffix.casefold() == ".mp3":
        raw = audio.read_bytes()
    else:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(audio), "-vn",
             "-ac", "1", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "112k", "-f", "mp3", "pipe:1"],
            check=True,
            capture_output=True,
        )
        raw = result.stdout
    encoded = base64.b64encode(raw).decode("ascii")
    if len(encoded) > 18_000_000:
        raise RuntimeError("direct Google inline audio exceeds the safe request budget; segment the audio first")
    return encoded, "mp3"


def _json_request(url: str, api_key: str, *, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"OpenRouter endpoint returned a non-object payload: {url}")
    return payload


def openrouter_account_status(api_key: str, *, timeout: float = 20.0) -> dict[str, Any]:
    auth = _json_request(AUTH_KEY_URL, api_key, timeout=timeout).get("data", {})
    credits = _json_request(CREDITS_URL, api_key, timeout=timeout).get("data", {})
    limit_remaining = auth.get("limit_remaining")
    total_credits = credits.get("total_credits")
    total_usage = credits.get("total_usage")
    exhausted = (
        isinstance(total_credits, (int, float))
        and isinstance(total_usage, (int, float))
        and total_usage >= total_credits
    )
    return {
        "label": auth.get("label"),
        "limit_remaining": limit_remaining,
        "total_credits": total_credits,
        "total_usage": total_usage,
        "credits_exhausted": exhausted,
    }


def batch_base_model(model: str) -> str:
    return model.removesuffix(":batch")


def extract_batch_result(batch: dict[str, Any], custom_id: str) -> dict[str, Any]:
    for item in batch.get("results") or []:
        if item.get("custom_id") != custom_id:
            continue
        response = item.get("response") or {}
        if response.get("status_code") != 200:
            raise RuntimeError(f"OpenRouter batch request failed: {item.get('error') or response}")
        body = response.get("body")
        if not isinstance(body, dict):
            raise RuntimeError("OpenRouter batch result has no response body")
        usage = dict(body.get("usage") or {})
        usage.update(batch.get("usage") or {})
        body["usage"] = usage
        return body
    raise RuntimeError(f"OpenRouter batch result omitted {custom_id}")


def call_batch(payload: dict[str, Any], api_key: str, *, timeout: float) -> dict[str, Any]:
    custom_id = f"bhakti-{uuid.uuid4().hex}"
    base_model = batch_base_model(str(payload["model"]))
    body = {**payload, "model": base_model}
    request = urllib.request.Request(
        BATCH_API_URL,
        data=json.dumps({
            "endpoint": "/v1/chat/completions",
            "model": base_model,
            "requests": [{"custom_id": custom_id, "body": body}],
        }).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=min(timeout, 60.0)) as response:
        batch = json.loads(response.read().decode("utf-8"))
    batch_id = batch.get("id")
    if not batch_id:
        raise RuntimeError(f"OpenRouter did not create the batch: {batch}")

    deadline = time.monotonic() + max(timeout, float(os.environ.get("BHAKTI_BATCH_TIMEOUT", "86400")))
    while time.monotonic() < deadline:
        time.sleep(float(os.environ.get("BHAKTI_BATCH_POLL_INTERVAL", "5")))
        poll = urllib.request.Request(
            f"{BATCH_API_URL}/{batch_id}", headers={"Authorization": f"Bearer {api_key}"}, method="GET",
        )
        try:
            with urllib.request.urlopen(poll, timeout=min(timeout, 60.0)) as response:
                batch = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:  # brief propagation delay after creation
                continue
            raise
        status = batch.get("status")
        if status == "completed":
            return extract_batch_result(batch, custom_id)
        if status in {"failed", "cancelled", "expired"}:
            raise RuntimeError(f"OpenRouter batch ended as {status}: {batch.get('error')}")
    raise RuntimeError(f"OpenRouter batch {batch_id} exceeded its polling deadline")


def call(
    model: str,
    api_key: str,
    prompt: str,
    *,
    audio: Path | None,
    timeout: float,
    response_schema: dict[str, Any] | None = None,
    schema_name: str = "bhakti_response",
    reasoning_effort: str | None = None,
    max_completion_tokens: int | None = None,
    max_attempts: int = 6,
) -> dict[str, Any]:
    provider = provider_name()
    requested_batch = model.endswith(":batch")
    # OpenRouter Batch rejects every multimodal content part. Economy mode is
    # therefore hybrid: audio-dependent stages use the synchronous base model,
    # while later text-only gloss/translation stages retain Batch pricing.
    effective_model = batch_base_model(model) if requested_batch and audio is not None else model
    if provider == "google" and effective_model.endswith(":batch"):
        raise RuntimeError("direct Google Batch is not enabled; use OpenRouter for --economy")
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if audio:
        audio_data, audio_format = encoded_audio(audio, provider)
        content.append({
            "type": "input_audio",
            "input_audio": {"data": audio_data, "format": audio_format},
        })
    payload = {
        "model": provider_model(effective_model, provider),
        "temperature": 0,
        "messages": [{"role": "user", "content": content}],
        "response_format": ({"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": response_schema}}
                            if response_schema else {"type": "json_object"}),
    }
    if provider == "openrouter":
        payload["provider"] = {
            "allow_fallbacks": True,
            "sort": os.environ.get("OPENROUTER_PROVIDER_SORT", "throughput"),
        }
        if response_schema:
            payload["provider"]["require_parameters"] = True
        if reasoning_effort:
            payload["reasoning"] = {"effort": reasoning_effort}
    elif reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    if max_completion_tokens:
        payload["max_tokens"] = max_completion_tokens
    if provider == "openrouter" and effective_model.endswith(":batch"):
        with _BATCH_SLOTS:
            _wait_for_api_start()
            result = call_batch(payload, api_key, timeout=timeout)
    else:
        result = None
    request = urllib.request.Request(
        GOOGLE_API_URL if provider == "google" else API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers(provider, api_key),
        method="POST",
    )
    # Long source-controlled work is checkpointed by its caller.  Let those
    # callers fail one bounded request rather than silently holding a worker in
    # a multi-minute retry loop while no completed unit can be saved.
    attempts = max(1, int(max_attempts))
    for attempt in range(attempts) if result is None else []:
        try:
            with _API_SLOTS:
                _wait_for_api_start()
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    result = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            if permanent_provider_error(provider, exc.code, detail):
                raise RuntimeError(f"{provider} HTTP {exc.code}: {detail}") from exc
            if exc.code in {429, 502, 503, 504} and attempt < attempts - 1:
                retry_after = 0.0
                try:
                    retry_after = float(exc.headers.get("Retry-After", 0) or 0)
                except (TypeError, ValueError):
                    pass
                time.sleep(max(retry_after, min(32, 2 ** (attempt + 1))))
                continue
            raise RuntimeError(f"{provider} HTTP {exc.code}: {detail}") from exc
    if result is None:
        raise RuntimeError(f"{provider} returned no response after retries")
    try:
        text = result["choices"][0]["message"]["content"]
        if isinstance(text, list):
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
        parsed = parse_json_packet(text)
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        preview = str(locals().get("text", ""))[:800]
        raise RuntimeError(f"Gemini did not return the required JSON packet; content preview: {preview!r}") from exc
    return {"packet": parsed, "usage": result.get("usage", {}), "resolved_model": result.get("model", effective_model)}


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
    translation_prompt = f"""Translate the verified devotional lyrics below in this mandatory order:
1. Segment every source line into its actual words or meaningful grammatical units and give a concise literal gloss for each unit.
2. State any idiom, ellipsis, agreement, or syntax needed to combine those glosses.
3. Write the literal English line ONLY from that word map and stated grammar. Do not replace a gloss with a looser synonym (for example, do not turn “causing longing to take hold” into “awakening” unless the word map itself supports that change).
4. Optionally give a poetic English rendering, clearly separate from the literal line.

Preserve poetic imagery and devotional register, but never omit a line or add doctrinal interpretation. Treat uncertainty honestly.

When a supplied translation exists, compare it as an independent witness: retain good wording, identify material differences, and explain each change. Do not treat it as automatically correct or automatically disposable.

Verified lyrics:
{json.dumps(alignment['packet'].get('verified_lines', []), ensure_ascii=False)}

Supplied translation (optional):
{provided or '(none)'}

Return strict JSON: {{"translations":[{{"id":"","word_glosses":[{{"roman":"","gloss":""}}],"grammar_note":"","literal_english":"","poetic_english":"","uncertainty":""}}],"comparison":[{{"id":"","supplied":"","chosen":"","reason":""}}]}}."""
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

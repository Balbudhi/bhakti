#!/usr/bin/env python3
"""Provider client and legacy complete-song packet processing.

OpenRouter/Gemini is the default audio and text route. Together remains an
explicit text-only option; it has no qualified song-audio route. The historical filename remains for existing script imports.

The pipeline deliberately uses three different tasks, not duplicate generic
passes: full-song transcription, lyric-aware full-song alignment, then
translation/glossing. Nothing edits a public reader until the resulting packet
has passed review.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import fcntl
import hashlib
import json
import math
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


TOGETHER_MODEL = "openai/gpt-oss-120b"
GEMINI_MODEL = "google/gemini-3.7-flash"
MODEL = os.environ.get("BHAKTI_MODEL") or (TOGETHER_MODEL if os.environ.get("BHAKTI_GEMINI_PROVIDER", "openrouter").strip().casefold() == "together" else GEMINI_MODEL)
API_URL = "https://openrouter.ai/api/v1/chat/completions"
GOOGLE_API_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
TOGETHER_API_URL = "https://api.together.ai/v1/chat/completions"
BATCH_API_URL = "https://openrouter.ai/api/beta/batches"
AUTH_KEY_URL = "https://openrouter.ai/api/v1/auth/key"
CREDITS_URL = "https://openrouter.ai/api/v1/credits"
# Keys are never stored in the repository. Set the selected provider's
# API_KEY variable or API_KEY_FILE reference to an owner-only file.
KEY_DIR = Path(os.environ.get("BHAKTI_KEY_DIR") or (Path.home() / ".config" / "bhakti")).expanduser()
DEFAULT_KEY = KEY_DIR / "openrouter.key"
DEFAULT_GOOGLE_KEY = KEY_DIR / "gemini.key"
DEFAULT_TOGETHER_KEY = KEY_DIR / "together.key"
API_MAX_CONCURRENCY = max(1, int(os.environ.get("BHAKTI_API_MAX_CONCURRENCY", "3")))
BATCH_MAX_CONCURRENCY = max(1, int(os.environ.get("BHAKTI_BATCH_MAX_CONCURRENCY", "32")))
API_MIN_START_INTERVAL = max(0.0, float(os.environ.get("BHAKTI_API_MIN_START_INTERVAL", "0.35")))
_API_SLOTS = threading.BoundedSemaphore(API_MAX_CONCURRENCY)
_BATCH_SLOTS = threading.BoundedSemaphore(BATCH_MAX_CONCURRENCY)
_API_START_LOCK = threading.Lock()
_LAST_API_START = 0.0
_LEDGER_LOCK = threading.Lock()
_ABORTED_RUNS: set[str] = set()

# The child receives headers through an anonymous pipe, never an argument,
# environment addition, cache file or log. Only provider response bytes persist.
_BOUNDED_HTTP_WORKER = r"""
import json, os, sys, urllib.request, urllib.error
from pathlib import Path
job = json.load(sys.stdin)
request = urllib.request.Request(job['url'], data=json.dumps(job['payload']).encode(),
                                 headers=job['headers'], method='POST')
try:
    response = urllib.request.urlopen(request, timeout=job['timeout'])
except urllib.error.HTTPError as error:
    response = error
with response:
    raw = response.read()
    path = Path(job['response_path'])
    with open(path, 'wb') as output:
        os.chmod(path, 0o600)
        output.write(raw)
    print(json.dumps({'http_status': response.code}))
"""


def _private_json(path: Path, value: Any) -> None:
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with open(temporary, "w", encoding="utf-8") as output:
        os.chmod(temporary, 0o600)
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")
    temporary.replace(path)


@contextlib.contextmanager
def _locked_run_ledger(path: Path, budget: float):
    """Serialize reservations across song threads and cooperating processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LEDGER_LOCK, open(path.with_suffix(path.suffix + ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ledger = (json.loads(path.read_text()) if path.exists() else
                  {"version": 1, "budget_usd": budget, "requests": [], "blocked": False})
        if ledger.get("version") != 1 or ledger.get("budget_usd") != budget:
            raise RuntimeError("bounded API ledger version/budget differs; review before resuming")
        yield ledger
        _private_json(path, ledger)


def _bounded_update(path: Path, budget: float, request_id: str, *, block: bool = False,
                    **fields: Any) -> None:
    if block:
        # Even an unwritable ledger must stop this process dispatching again.
        _ABORTED_RUNS.add(str(path))
    with _locked_run_ledger(path, budget) as ledger:
        row = next(item for item in ledger["requests"] if item["id"] == request_id)
        row.update(fields)
        if block:
            ledger["blocked"] = True



def _remaining_timeout(timeout: float, deadline_at: float | None) -> float:
    if deadline_at is None:
        return timeout
    if not math.isfinite(deadline_at):
        raise RuntimeError('invalid absolute API deadline')
    remaining = deadline_at - time.time()
    if remaining <= 0:
        raise RuntimeError('absolute API deadline exceeded before dispatch')
    return min(timeout, remaining)


def _bounded_call(payload: dict[str, Any], api_key: str, audio: Path | None,
                  timeout: float, deadline_at: float | None = None) -> tuple[dict[str, Any], tuple[Path, float, str]]:
    """Opt-in synchronous 3.7 run with prepaid reservations and hard deadlines.

    BHAKTI_API_RUN_LEDGER and BHAKTI_API_RUN_BUDGET_USD enable this path.
    Every failure blocks further dispatch through that ledger, including a
    pipeline-level retry. Already active calls may finish and retain evidence.
    Unknown outcomes keep their full reservation until explicit reconciliation.
    """
    path = Path(os.environ["BHAKTI_API_RUN_LEDGER"]).expanduser().resolve()
    if str(path) in _ABORTED_RUNS:
        raise RuntimeError("bounded API run is blocked; review saved evidence before another dispatch")
    budget = float(os.environ.get("BHAKTI_API_RUN_BUDGET_USD", "0"))
    cap = payload.get("max_tokens")
    if (provider_name() != "openrouter" or payload.get("model") != GEMINI_MODEL
            or not math.isfinite(budget) or budget <= 0
            or type(cap) is not int or not 0 < cap <= 65536
            or not math.isfinite(timeout) or timeout <= 0):
        raise RuntimeError("bounded API requires OpenRouter Gemini 3.7, positive budget/deadline and explicit max_tokens <=65536")
    # Reserve a conservative upper bound: UTF-8 bytes bound text tokens, and
    # Google documents 32 tokens/second for native audio. No cache discount.
    evidence = json.loads(json.dumps(payload))
    for message in evidence.get("messages", []):
        for part in message.get("content", []):
            if part.get("type") == "input_audio":
                encoded = part["input_audio"]["data"]
                part["input_audio"]["data"] = {"base64_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
                                                "base64_bytes": len(encoded)}
    audio_tokens = math.ceil(duration_seconds(audio) * 32) if audio is not None else 0
    input_bound = len(json.dumps(evidence, ensure_ascii=False).encode()) + 1024 + audio_tokens
    reservation = math.ceil((input_bound * .75 + cap * 3.75) / 1_000_000 * 1e8) / 1e8
    payload["provider"] = {"only": ["google-ai-studio"], "order": ["google-ai-studio"],
                           "ignore": ["google-ai-studio/flex", "google-ai-studio/priority"],
                           "allow_fallbacks": False, "require_parameters": True,
                           "max_price": {"prompt": .75, "completion": 3.75}}
    evidence["provider"] = payload["provider"]
    request_id = uuid.uuid4().hex
    artifacts = path.parent / (path.stem + "-responses")
    artifacts.mkdir(mode=0o700, exist_ok=True)
    response_path = artifacts / (request_id + ".response.json")
    with _locked_run_ledger(path, budget) as ledger:
        _remaining_timeout(timeout, deadline_at)
        if ledger.get("blocked"):
            raise RuntimeError("bounded API run is blocked; review saved evidence before another dispatch")
        committed = sum(row.get("reported_cost_usd", row["reservation_usd"]) for row in ledger["requests"])
        if committed + reservation > budget:
            raise RuntimeError("bounded API budget exhausted; no request sent")
        ledger["requests"].append({"id": request_id, "status": "reserved", "started_at": time.time(),
                                   "model": payload["model"], "reservation_usd": reservation,
                                   "input_token_upper_bound": input_bound, "max_tokens": cap,
                                   "response_path": str(response_path)})
    started = time.monotonic()
    job = {"url": API_URL, "payload": payload, "headers": request_headers("openrouter", api_key),
           "response_path": str(response_path), "timeout": timeout}
    worker = None
    try:
        _private_json(artifacts / (request_id + ".request.json"), evidence)
        # A sibling may fail after this request reserves funds. Recheck while
        # holding the same interprocess lock through the actual child launch.
        with _locked_run_ledger(path, budget) as ledger:
            if ledger.get("blocked") or str(path) in _ABORTED_RUNS:
                raise RuntimeError("bounded API run blocked before dispatch")
            job['timeout'] = _remaining_timeout(timeout, deadline_at)
            worker = subprocess.Popen([sys.executable, "-c", _BOUNDED_HTTP_WORKER],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            row = next(item for item in ledger["requests"] if item["id"] == request_id)
            row.update(status="dispatched", worker_pid=worker.pid)
        stdout, _stderr = worker.communicate(input=json.dumps(job).encode(), timeout=_remaining_timeout(timeout, deadline_at))
        if worker.returncode:
            raise RuntimeError("bounded HTTP worker failed")
        status = json.loads(stdout)["http_status"]
        raw = response_path.read_bytes()  # Exact bytes already persisted by child.
        _bounded_update(path, budget, request_id, status="response-received", http_status=status,
                        elapsed_seconds=round(time.monotonic() - started, 3))
        result = json.loads(raw)
        fields: dict[str, Any] = {"status": "response-received", "http_status": status,
                                  "elapsed_seconds": round(time.monotonic() - started, 3),
                                  "resolved_model": result.get("model"), "provider": result.get("provider"),
                                  "usage": result.get("usage", {})}
        cost = result.get("usage", {}).get("cost")
        if type(cost) in (int, float) and math.isfinite(cost) and cost >= 0:
            fields["reported_cost_usd"] = cost
        _bounded_update(path, budget, request_id, **fields)
        if status != 200:
            raise RuntimeError(f"bounded API HTTP {status}; response retained")
        return result, (path, budget, request_id)
    except subprocess.TimeoutExpired as exc:
        # Stop the network worker before touching storage: ledger I/O must not
        # extend the deadline or leave an upstream request running locally.
        if worker is not None and worker.poll() is None:
            worker.kill()
            worker.communicate()
        _bounded_update(path, budget, request_id, block=True, status="unknown-outcome",
                        elapsed_seconds=round(time.monotonic() - started, 3),
                        error="hard wall deadline exceeded; upstream outcome and charge unknown")
        raise RuntimeError("bounded API hard wall deadline exceeded; reservation retained, run blocked") from exc
    except Exception as exc:
        if worker is not None and worker.poll() is None:
            worker.kill()
            worker.communicate()
        _bounded_update(path, budget, request_id, block=True, status="invalid-response",
                        elapsed_seconds=round(time.monotonic() - started, 3), error=type(exc).__name__)
        raise RuntimeError("bounded API response invalid; evidence retained and run blocked") from exc
    finally:
        if worker is not None and worker.poll() is None:
            worker.kill()
            worker.communicate()


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
    if value not in {"together", "openrouter", "google"}:
        raise RuntimeError("BHAKTI_GEMINI_PROVIDER must be 'together', 'openrouter', or 'google'")
    return value


def default_model() -> str:
    return os.environ.get("BHAKTI_MODEL") or (TOGETHER_MODEL if provider_name() == "together" else GEMINI_MODEL)


def _secure_key(environment: str, file_environment: str, default_path: Path, label: str) -> str:
    value = os.environ.get(environment, "").strip()
    if value:
        return value
    path = Path(os.environ.get(file_environment, default_path)).expanduser()
    if not path.is_file():
        raise RuntimeError(f"{label} credential is missing; set {environment} or {file_environment} to an owner-only key file")
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise RuntimeError(f"refusing insecure key file: {path}")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"{label} key is empty")
    return value


def key() -> str:
    if provider_name() == "together":
        return _secure_key("TOGETHER_API_KEY", "TOGETHER_API_KEY_FILE", DEFAULT_TOGETHER_KEY, "Together")
    if provider_name() == "google":
        return _secure_key("GEMINI_API_KEY", "GEMINI_API_KEY_FILE", DEFAULT_GOOGLE_KEY, "Gemini")
    return _secure_key("OPENROUTER_API_KEY", "OPENROUTER_API_KEY_FILE", DEFAULT_KEY, "OpenRouter")


def provider_model(model: str, provider: str) -> str:
    model = batch_base_model(model)
    if provider == "google":
        return model.removeprefix("google/")
    return model


def request_headers(provider: str, api_key: str) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
               "User-Agent": "Bhakti-song-processing/1.0"}
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
    deadline_at: float | None = None,
) -> dict[str, Any]:
    provider = provider_name()
    if provider == "together" and audio is not None:
        raise RuntimeError("Together text chat cannot perform the required audio-aware audit or lyric-start verification. Use a separately validated Together speech-evidence workflow; audio is never replaced by text silently.")
    requested_batch = model.endswith(":batch")
    if provider == "together" and requested_batch:
        raise RuntimeError("Together Batch is not enabled in this client; omit --economy")
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
    elif provider == "together" and reasoning_effort:
        # Reasoning controls belong to the selected model, not the provider.
        if effective_model in {"openai/gpt-oss-120b", "openai/gpt-oss-20b"}:
            payload["reasoning_effort"] = reasoning_effort
        elif effective_model in {"Qwen/Qwen3.6-Plus", "Qwen/Qwen3.5-9B"}:
            payload["reasoning"] = {"enabled": True}
    elif reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    if max_completion_tokens:
        payload["max_tokens"] = max_completion_tokens
    bounded_context = None
    if os.environ.get("BHAKTI_API_RUN_LEDGER"):
        with _API_SLOTS:
            _wait_for_api_start()
            effective_timeout = _remaining_timeout(timeout, deadline_at)
            if deadline_at is None:
                result, bounded_context = _bounded_call(payload, api_key, audio, effective_timeout)
            else:
                result, bounded_context = _bounded_call(payload, api_key, audio, effective_timeout, deadline_at=deadline_at)
    elif provider == "openrouter" and effective_model.endswith(":batch"):
        if deadline_at is not None:
            raise RuntimeError('absolute API deadline requires synchronous transport, not batch polling')
        with _BATCH_SLOTS:
            _wait_for_api_start()
            result = call_batch(payload, api_key, timeout=timeout)
    else:
        result = None
    request = urllib.request.Request(
        {"google": GOOGLE_API_URL, "together": TOGETHER_API_URL, "openrouter": API_URL}[provider],
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
                with urllib.request.urlopen(request, timeout=_remaining_timeout(timeout, deadline_at)) as response:
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
                wait_seconds = max(retry_after, min(32, 2 ** (attempt + 1)))
                if deadline_at is not None and _remaining_timeout(wait_seconds, deadline_at) < wait_seconds:
                    raise RuntimeError('absolute API deadline would expire during retry wait') from exc
                time.sleep(wait_seconds)
                continue
            raise RuntimeError(f"{provider} HTTP {exc.code}: {detail}") from exc
    if result is None:
        raise RuntimeError(f"{provider} returned no response after retries")
    try:
        text = result["choices"][0]["message"]["content"]
        if isinstance(text, list):
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
        parsed = parse_json_packet(text)
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
        if bounded_context:
            _bounded_update(*bounded_context, block=True, status="invalid-response",
                            error="model content was not the required JSON object")
            raise RuntimeError("bounded API response invalid; raw response retained and run blocked") from exc
        if isinstance(exc, RuntimeError):
            raise  # Preserve the unbounded client's previous exception behavior.
        preview = str(locals().get("text", ""))[:800]
        raise RuntimeError(f"{provider} model did not return the required JSON packet; content preview: {preview!r}") from exc
    if bounded_context:
        try:
            _bounded_update(*bounded_context, status="parsed")
        except Exception as exc:
            # The response may be valid, but it cannot be treated as a safely
            # checkpointed success. Poison this run even if storage stays down.
            _ABORTED_RUNS.add(str(bounded_context[0]))
            try:
                _bounded_update(*bounded_context, block=True, status="invalid-response",
                                error="could not finalize successful response in run ledger")
            except Exception:
                pass
            raise RuntimeError("bounded API ledger finalization failed; run blocked") from exc
    return {"packet": parsed, "usage": result.get("usage", {}), "resolved_model": result.get("model", effective_model), "provider": provider}


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

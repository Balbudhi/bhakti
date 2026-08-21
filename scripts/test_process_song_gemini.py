#!/usr/bin/env python3
"""Provider-contract tests for the Bhakti Gemini client."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import process_song_gemini as gemini


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def completion(model: str) -> FakeResponse:
    return FakeResponse({
        "model": model,
        "choices": [{"message": {"content": '{"ok": true}'}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
    })


class ProviderTests(unittest.TestCase):
    def test_google_audio_is_normalized_in_memory_to_supported_mp3(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            audio = Path(temporary) / "audio.webm"
            audio.write_bytes(b"native-opus")
            with mock.patch.object(gemini.subprocess, "run", return_value=mock.Mock(stdout=b"normalized-mp3")) as run:
                encoded, audio_format = gemini.encoded_audio(audio, "google")
        self.assertEqual(audio_format, "mp3")
        self.assertEqual(encoded, "bm9ybWFsaXplZC1tcDM=")
        self.assertIn("libmp3lame", run.call_args.args[0])

    def test_openrouter_keeps_native_listener_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            audio = Path(temporary) / "audio.webm"
            audio.write_bytes(b"native-opus")
            encoded, audio_format = gemini.encoded_audio(audio, "openrouter")
        self.assertEqual(audio_format, "webm")
        self.assertEqual(encoded, "bmF0aXZlLW9wdXM=")

    def test_google_uses_direct_endpoint_and_openai_compatible_fields(self) -> None:
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
                  "required": ["ok"], "additionalProperties": False}
        with mock.patch.dict(os.environ, {"BHAKTI_GEMINI_PROVIDER": "google"}), \
                mock.patch.object(gemini, "_wait_for_api_start"), \
                mock.patch("urllib.request.urlopen", return_value=completion("gemini-3.7-flash")) as opened:
            result = gemini.call(
                "google/gemini-3.7-flash", "secret", "Return JSON", audio=None, timeout=5,
                response_schema=schema, reasoning_effort="high", max_completion_tokens=4096,
            )
        request = opened.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, gemini.GOOGLE_API_URL)
        self.assertEqual(payload["model"], "gemini-3.7-flash")
        self.assertEqual(payload["reasoning_effort"], "high")
        self.assertEqual(payload["max_tokens"], 4096)
        self.assertNotIn("provider", payload)
        self.assertEqual(result["packet"], {"ok": True})

    def test_openrouter_keeps_routing_and_reasoning_contract(self) -> None:
        with mock.patch.dict(os.environ, {"BHAKTI_GEMINI_PROVIDER": "openrouter"}), \
                mock.patch.object(gemini, "_wait_for_api_start"), \
                mock.patch("urllib.request.urlopen", return_value=completion("google/gemini-3.7-flash")) as opened:
            gemini.call(
                "google/gemini-3.7-flash", "secret", "Return JSON", audio=None, timeout=5,
                reasoning_effort="high",
            )
        request = opened.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, gemini.API_URL)
        self.assertEqual(payload["model"], "google/gemini-3.7-flash")
        self.assertEqual(payload["reasoning"], {"effort": "high"})
        self.assertTrue(payload["provider"]["allow_fallbacks"])
        self.assertIn("http-referer", {key.casefold(): value for key, value in request.headers.items()})

    def test_google_key_file_must_be_private(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "gemini.key"
            path.write_text("test-key\n", encoding="utf-8")
            path.chmod(0o600)
            with mock.patch.dict(os.environ, {
                "BHAKTI_GEMINI_PROVIDER": "google",
                "GEMINI_API_KEY_FILE": str(path),
            }, clear=False):
                self.assertEqual(gemini.key(), "test-key")

    def test_google_batch_is_not_silently_emulated(self) -> None:
        with mock.patch.dict(os.environ, {"BHAKTI_GEMINI_PROVIDER": "google"}):
            with self.assertRaisesRegex(RuntimeError, "Google Batch is not enabled"):
                gemini.call("google/gemini-3.7-flash:batch", "secret", "x", audio=None, timeout=5)

    def test_depleted_google_prepay_is_not_retried(self) -> None:
        self.assertTrue(gemini.permanent_provider_error(
            "google", 429, "Your prepayment credits are depleted.",
        ))
        self.assertFalse(gemini.permanent_provider_error("google", 429, "Temporary rate limit"))


if __name__ == "__main__":
    unittest.main()

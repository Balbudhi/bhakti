#!/usr/bin/env python3
"""Provider-contract tests for the Bhakti Gemini client."""

from __future__ import annotations

import json
import io
import os
import tempfile
import unittest
import urllib.error
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
    def test_default_provider_and_model_are_together(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(gemini.provider_name(), "together")
            self.assertEqual(gemini.default_model(), "openai/gpt-oss-120b")

    def test_together_text_preserves_schema_and_uses_documented_reasoning(self) -> None:
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
        with mock.patch.dict(os.environ, {"BHAKTI_GEMINI_PROVIDER": "together"}), \
                mock.patch.object(gemini, "_wait_for_api_start"), \
                mock.patch("urllib.request.urlopen", return_value=completion("openai/gpt-oss-120b")) as opened:
            result = gemini.call("openai/gpt-oss-120b", "secret", "Return JSON", audio=None,
                                 timeout=5, response_schema=schema, reasoning_effort="high", max_completion_tokens=4096)
        request = opened.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.together.ai/v1/chat/completions")
        self.assertEqual(payload["response_format"]["json_schema"]["schema"], schema)
        self.assertEqual(payload["reasoning_effort"], "high")
        self.assertNotIn("reasoning", payload)
        self.assertNotIn("provider", payload)
        self.assertEqual(payload["max_tokens"], 4096)
        self.assertEqual(result["provider"], "together")

    def test_together_audio_and_batch_fail_before_encoding_or_request(self) -> None:
        with mock.patch.dict(os.environ, {"BHAKTI_GEMINI_PROVIDER": "together"}), \
                mock.patch.object(gemini, "encoded_audio") as encode, \
                mock.patch("urllib.request.urlopen") as opened:
            with self.assertRaisesRegex(RuntimeError, "audio-aware audit"):
                gemini.call("Qwen/Qwen3.6-Plus", "secret", "Listen", audio=Path('/missing/audio.m4a'), timeout=5)
            with self.assertRaisesRegex(RuntimeError, "Together Batch is not enabled"):
                gemini.call("Qwen/Qwen3.6-Plus:batch", "secret", "x", audio=None, timeout=5)
        encode.assert_not_called()
        opened.assert_not_called()

    def test_together_secure_key_file_and_missing_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "together.key"
            with mock.patch.dict(os.environ, {"BHAKTI_GEMINI_PROVIDER": "together", "TOGETHER_API_KEY_FILE": str(path)}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "TOGETHER_API_KEY"):
                    gemini.key()
                path.write_text("test-key")
                path.chmod(0o644)
                with self.assertRaisesRegex(RuntimeError, "insecure key file"):
                    gemini.key()
                path.chmod(0o600)
                self.assertEqual(gemini.key(), "test-key")

    def test_together_privacy_rejection_does_not_retry_or_change_provider(self) -> None:
        error = urllib.error.HTTPError("https://api.together.ai/v1/chat/completions", 403, "Forbidden", {},
                                       io.BytesIO(b'{"error":{"code":"third_party_data_sharing_blocked"}}'))
        with mock.patch.dict(os.environ, {"BHAKTI_GEMINI_PROVIDER": "together"}), \
                mock.patch.object(gemini, "_wait_for_api_start"), \
                mock.patch("urllib.request.urlopen", side_effect=error) as opened, \
                mock.patch.object(gemini.time, "sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "third_party_data_sharing_blocked"):
                gemini.call("Qwen/Qwen3.6-Plus", "secret", "x", audio=None, timeout=5)
        opened.assert_called_once()
        sleep.assert_not_called()

    def test_together_reasoning_controls_follow_selected_model(self) -> None:
        with mock.patch.dict(os.environ, {"BHAKTI_GEMINI_PROVIDER": "together"}), \
                mock.patch.object(gemini, "_wait_for_api_start"), \
                mock.patch("urllib.request.urlopen", return_value=completion("Qwen/Qwen3.5-9B")) as opened:
            gemini.call("Qwen/Qwen3.5-9B", "secret", "Return JSON", audio=None, timeout=5, reasoning_effort="high")
        payload = json.loads(opened.call_args.args[0].data)
        self.assertEqual(payload["reasoning"], {"enabled": True})
        self.assertNotIn("reasoning_effort", payload)

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

    def test_openrouter_economy_keeps_audio_stages_synchronous(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            audio = Path(temporary) / "audio.m4a"
            audio.write_bytes(b"audio")
            with mock.patch.dict(os.environ, {"BHAKTI_GEMINI_PROVIDER": "openrouter"}), \
                    mock.patch.object(gemini, "_wait_for_api_start"), \
                    mock.patch.object(gemini, "call_batch") as batch, \
                    mock.patch("urllib.request.urlopen", return_value=completion("google/gemini-3.7-flash")) as opened:
                gemini.call("google/gemini-3.7-flash:batch", "secret", "x", audio=audio, timeout=5)
        batch.assert_not_called()
        payload = json.loads(opened.call_args.args[0].data)
        self.assertEqual(payload["model"], "google/gemini-3.7-flash")
        self.assertEqual(payload["messages"][0]["content"][1]["type"], "input_audio")

    def test_openrouter_economy_batches_text_only_stages(self) -> None:
        result = {
            "model": "google/gemini-3.7-flash",
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "usage": {"cost": 0.1},
        }
        with mock.patch.dict(os.environ, {"BHAKTI_GEMINI_PROVIDER": "openrouter"}), \
                mock.patch.object(gemini, "_wait_for_api_start"), \
                mock.patch.object(gemini, "call_batch", return_value=result) as batch:
            parsed = gemini.call(
                "google/gemini-3.7-flash:batch", "secret", "x", audio=None, timeout=5,
            )
        batch.assert_called_once()
        self.assertEqual(parsed["packet"], {"ok": True})

    def test_depleted_google_prepay_is_not_retried(self) -> None:
        self.assertTrue(gemini.permanent_provider_error(
            "google", 429, "Your prepayment credits are depleted.",
        ))
        self.assertFalse(gemini.permanent_provider_error("google", 429, "Temporary rate limit"))

    def test_double_escaped_json_packet_is_accepted(self) -> None:
        self.assertEqual(gemini.parse_json_packet(r'{\n  \"ok\": true\n}'), {"ok": True})


if __name__ == "__main__":
    unittest.main()

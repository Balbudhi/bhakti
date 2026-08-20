#!/usr/bin/env python3
"""Deterministic integration tests for the one-command Bhakti pipeline."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import bhakti_pipeline as pipeline


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bhakti-pipeline-test-")
        self.root = Path(self.temp.name)
        self.original_root = pipeline.ROOT
        pipeline.ROOT = self.root
        (self.root / "songs").mkdir()
        (self.root / "data").mkdir()
        (self.root / "data" / "songs.js").write_text("window.BHAKTI_SONGS = [];\n", encoding="utf-8")

    def tearDown(self) -> None:
        pipeline.ROOT = self.original_root
        self.temp.cleanup()

    def test_local_mp3_is_transcoded_to_real_m4a(self) -> None:
        source = self.root / "input.mp3"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2",
            "-c:a", "libmp3lame", str(source),
        ], check=True)
        song, _ = pipeline.intake({"slug": "local-test", "source": str(source)}, force=False)
        format_name = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=format_name", "-of", "default=nokey=1:noprint_wrappers=1",
            str(song / "audio.m4a"),
        ], check=True, capture_output=True, text=True).stdout
        self.assertIn("mp4", format_name)

    def test_generation_uses_roles_and_canonical_reader_contract(self) -> None:
        song = self.root / "songs" / "sample-song"
        song.mkdir()
        audited = {"packet": {"metadata": {"languages": ["Hindi"]}, "uncertainties": [], "verified_lines": [
            {"id": "line-one", "source_text": "साईं", "roman": "Sāīṃ", "kind": "refrain"}
        ]}}
        timing = {"sequence": [{"ref": "line-one", "start": 1.25, "end": 2.5}], "validation_errors": []}
        glosses = {"packet": {"glosses": [{"id": "line-one", "word_glosses": [{"roman": "Sāīṃ", "gloss": "Sai"}], "grammar_note": "", "uncertainty": ""}]}}
        translations = {"packet": {"translations": [{"id": "line-one", "literal_english": "Sai.", "segments": [{"text": "Sai", "word_indices": [0]}, {"text": ".", "word_indices": []}], "uncertainty": ""}]}}
        job = {"slug": "sample-song", "source": "unused", "title": "Sample Song", "writer": "Writer", "singer": "Singer",
               "languages": ["Hindi"], "subjectTags": ["Śirḍī Sāī"]}
        pipeline.generate(song, job, {}, audited, timing, glosses, translations)
        page = (song / "index.html").read_text(encoding="utf-8")
        data = (song / "data.js").read_text(encoding="utf-8")
        self.assertIn("Writer · Singer", (self.root / "data" / "songs.js").read_text(encoding="utf-8"))
        self.assertIn("<p class=\"song-credit\">Singer</p>", page)
        self.assertIn('"sourceLanguage": "hi"', data)
        self.assertIn('"section": "refrain"', data)
        self.assertIn("manifest.webmanifest", page)

    def test_publication_gate_rejects_uncertainty(self) -> None:
        audited = {"packet": {"verified_lines": [], "uncertainties": ["unclear word"]}}
        timing = {"sequence": [], "validation_errors": []}
        glosses = {"packet": {"glosses": []}}
        translations = {"packet": {"translations": []}}
        self.assertIn("audited transcription has unresolved uncertainties",
                      pipeline.publication_errors(audited, timing, glosses, translations))


if __name__ == "__main__":
    unittest.main()

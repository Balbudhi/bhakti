#!/usr/bin/env python3
"""Static contract checks for every generated song shell."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SongUiContractTests(unittest.TestCase):
    def test_every_song_shell_has_one_pwa_and_reader_control_set(self) -> None:
        pages = sorted((ROOT / "songs").glob("*/index.html"))
        self.assertGreater(len(pages), 0)
        for path in pages:
            text = path.read_text(encoding="utf-8")
            with self.subTest(song=path.parent.name):
                self.assertEqual(text.count('name="theme-color"'), 1)
                self.assertEqual(text.count('rel="icon"'), 1)
                self.assertEqual(text.count('rel="apple-touch-icon"'), 1)
                self.assertEqual(text.count('rel="manifest"'), 1)
                self.assertEqual(text.count('class="song-home"'), 1)
                self.assertEqual(text.count('id="apTime"'), 1)
                self.assertEqual(text.count('id="apElapsed"'), 1)
                self.assertEqual(text.count('id="apDuration"'), 1)
                self.assertIn('song.js?v=contract-20260821-1', text)
                self.assertIn('data.js?v=contract-20260821-1', text)
                self.assertEqual(text.count('class="song-meta"'), 1)
                self.assertNotIn('class="song-attrib"', text)
                self.assertNotIn('class="song-credit"', text)

    def test_seeking_is_bound_to_the_dedicated_control(self) -> None:
        script = (ROOT / "assets" / "song.js").read_text(encoding="utf-8")
        self.assertIn('class="line-seek"', script)
        self.assertIn('const seekButton = e.target.closest(".line-seek")', script)
        self.assertIn('if (!seekButton) return;', script)
        self.assertIn('const elapsed = document.getElementById("apElapsed")', script)
        self.assertIn('const duration = document.getElementById("apDuration")', script)

    def test_homepage_preface_and_disclosure_follow_the_ui_contract(self) -> None:
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "assets" / "library.js").read_text(encoding="utf-8")
        self.assertIn('class="library-invocation-roman"', page)
        self.assertIn('class="preface-word"', page)
        self.assertIn('class="preface-meaning"', page)
        self.assertIn('इन भजनों के कवियों तथा गायन-वादन से इन्हें साकार करने वाले कलाकारों को कोटि-कोटि प्रणाम।', page)
        self.assertIn('Countless</span>', page)
        self.assertIn('class="about-toggle"', page)
        self.assertIn('AI-based transcription, timing, and translation pipeline', page)
        self.assertIn('not to the poet, singer, or musician', page)
        self.assertNotIn('please forgive', page.casefold())
        self.assertNotIn('corrections are welcome', page.casefold())
        self.assertIn('song.singer || song.credit', script)

    def test_hosted_intake_is_owner_only_and_public_media_only(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "run-bhakti-intake.yml").read_text(encoding="utf-8")
        self.assertIn("if: github.actor == github.repository_owner", workflow)
        self.assertIn('if len(lines) > 50:', workflow)
        self.assertIn('parsed.scheme != "https"', workflow)
        self.assertIn('ipaddress.ip_address', workflow)
        self.assertIn('.is_global', workflow)
        self.assertIn('parsed.username or parsed.password', workflow)
        self.assertIn("BHAKTI_GEMINI_PROVIDER: openrouter", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("repository_dispatch:", workflow)

    def test_composite_liturgy_source_notices_are_supported(self) -> None:
        script = (ROOT / "assets" / "song.js").read_text(encoding="utf-8")
        data = (ROOT / "songs" / "kakad-aarti" / "data.js").read_text(encoding="utf-8")
        self.assertIn("function renderSourceNotice", script)
        self.assertIn("adaptedSequenceIndices", script)
        self.assertIn('"title": "Kākaḍ Āratī"', data)
        self.assertIn('"sectionNotices"', data)
        self.assertIn('>Sai adaptation</span>', script)


if __name__ == "__main__":
    unittest.main()

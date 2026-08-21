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
                self.assertIn('song.js?v=contract-20260821-2', text)
                self.assertIn('data.js?v=contract-20260821-2', text)
                self.assertIn('pwa.js?v=contract-20260821-2', text)
                self.assertIn('name="apple-mobile-web-app-capable" content="yes"', text)
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
        self.assertIn('class="preface-source preface-token"', page)
        self.assertIn('class="preface-word preface-token"', page)
        self.assertIn('preface-meaning preface-token', page)
        self.assertIn('>गायन-वादन</span>', page)
        self.assertIn('>कोटि-कोटि</span>', page)
        self.assertIn('>प्रणाम</span>।', page)
        self.assertIn('Countless</span>', page)
        self.assertIn('class="about-toggle"', page)
        self.assertIn('AI-based transcription, timing, and translation pipeline', page)
        self.assertIn('not to the poet, singer, or musician', page)
        self.assertNotIn('please forgive', page.casefold())
        self.assertNotIn('corrections are welcome', page.casefold())
        self.assertIn('song.singer || song.credit', script)

    def test_every_text_layer_uses_the_same_interactive_word_mapping(self) -> None:
        script = (ROOT / "assets" / "song.js").read_text(encoding="utf-8")
        self.assertIn('linkedWord("ws"', script)
        self.assertIn('linkedWord("w"', script)
        self.assertIn('linkedWord("we"', script)
        self.assertIn('e.target.closest(".word-link")', script)

    def test_pwa_checks_for_releases_without_reloading_every_launch(self) -> None:
        client = (ROOT / "assets" / "pwa.js").read_text(encoding="utf-8")
        worker = (ROOT / "sw.js").read_text(encoding="utf-8")
        self.assertIn('updateViaCache: "none"', client)
        self.assertIn('navigator.serviceWorker.addEventListener("controllerchange"', client)
        self.assertIn('now - lastCheck < 5 * 60 * 1000', client)
        self.assertIn('audioIsPlaying()', client)
        self.assertIn('fetch(event.request, { cache: "no-store" })', worker)
        self.assertIn('bhakti-shell-v8', worker)

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

    def test_hari_om_sharan_language_tags_follow_the_sung_text(self) -> None:
        aisa = (ROOT / "songs" / "aisa-pyar-baha-de-maiya" / "data.js").read_text(encoding="utf-8")
        garv = (ROOT / "songs" / "yeh-garv-bhara-mastak" / "data.js").read_text(encoding="utf-8")
        self.assertIn('"languages": [\n    "Hindi",\n    "Sanskrit"', aisa)
        self.assertEqual(aisa.count('"sourceLanguage": "sa"'), 2)
        self.assertIn('"languages": [\n    "Hindi"', garv)
        self.assertNotIn('"Sanskrit"', garv)


if __name__ == "__main__":
    unittest.main()

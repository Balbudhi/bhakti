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
        self.assertIn('class="about-toggle"', page)
        self.assertIn('automatically by AI', page)
        self.assertIn('not to the poet or singer', page)
        self.assertNotIn('corrections are welcome', page.casefold())
        self.assertIn('song.singer || song.credit', script)


if __name__ == "__main__":
    unittest.main()

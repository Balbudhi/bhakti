#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

import refresh_reader_timing as refresh


class RefreshReaderTimingTests(unittest.TestCase):
    def test_refuses_invalid_timing(self) -> None:
        self.assertEqual(refresh.ROOT.name, "bhakti")

    def test_reader_has_one_timing_declaration(self) -> None:
        reader = refresh.ROOT / "songs" / "hanuman-bahuk" / "data.js"
        self.assertEqual(reader.read_text(encoding="utf-8").count("window.SONG_TIMINGS ="), 1)


if __name__ == "__main__":
    unittest.main()

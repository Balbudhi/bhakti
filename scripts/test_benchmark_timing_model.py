#!/usr/bin/env python3

from __future__ import annotations

import io
import unittest
from pathlib import Path
from unittest import mock

import benchmark_timing_model as script


class BenchmarkTimingModelTests(unittest.TestCase):
    def test_missing_reviewed_packet_lists_available_slugs(self) -> None:
        root = Path("/tmp/fake-bhakti-root")
        timing_path = root / "songs" / "ready-song" / ".transcription" / "pipeline" / "03-timing.json"
        with mock.patch.object(script.pipeline, "ROOT", root), \
             mock.patch.object(script.pipeline, "read_packet", return_value=None), \
             mock.patch("pathlib.Path.glob", return_value=[timing_path]), \
             mock.patch("sys.argv", ["benchmark_timing_model.py", "missing-song"]), \
             self.assertRaises(SystemExit) as raised:
            script.main()
        self.assertIn("available slugs: ready-song", str(raised.exception))


if __name__ == "__main__":
    unittest.main()

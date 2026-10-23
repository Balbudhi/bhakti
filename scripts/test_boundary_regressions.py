"""Offline regressions through existing trim callers. No model/audio-network calls.

Run: PYTHONPATH=scripts python3 -m unittest discover -s /tmp/bhakti-boundary-redesign -p test_boundary_regressions.py -v
Synthetic FFmpeg fixtures establish file/timing behavior, not musical classification.
"""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import audit_youtube_trims as release_audit
import bhakti_pipeline as pipeline
import repair_existing_youtube_trims as repair


def edge_artifact(duration=1000., start=0., end=None, outside_type='channel_promotion', confidence='high'):
    end = duration if end is None else end
    length = min(75., duration)
    return {'duration': duration,
            'start': {'edge': 'start', 'clip_start': 0., 'response': {'packet': {
                'edge': 'start', 'decision': 'keep' if start == 0 else 'trim',
                'boundary': start, 'outside_type': outside_type if start else 'none',
                'confidence': confidence, 'reason': 'Fixture'}}},
            'end': {'edge': 'end', 'clip_start': duration-length, 'response': {'packet': {
                'edge': 'end', 'decision': 'keep' if end == duration else 'trim',
                'boundary': end-(duration-length), 'outside_type': outside_type if end < duration else 'none',
                'confidence': confidence, 'reason': 'Fixture'}}}}


class BoundaryRegressions(unittest.TestCase):
    def test_legacy_unrelated_musical_outro_is_unresolved_not_silently_kept(self):
        # A category alone does not establish that a musical transition is unrelated.
        actual = pipeline.normalize_trim_artifact(edge_artifact(end=990., outside_type='unrelated_music'))
        self.assertTrue(actual['validation_errors'])
        self.assertNotEqual(actual['status'], 'reviewed')

    def test_uncertain_removal_cannot_become_reviewed_keep(self):
        actual = pipeline.normalize_trim_artifact(edge_artifact(start=10., confidence='low'))
        self.assertTrue(actual['validation_errors'])
        self.assertNotEqual(actual['status'], 'reviewed')

    def test_boundary_outside_observed_start_clip_is_rejected(self):
        actual = pipeline.normalize_trim_artifact(edge_artifact(start=80.))
        self.assertTrue(actual['validation_errors'])

    def test_boundary_before_observed_end_clip_is_rejected(self):
        actual = pipeline.normalize_trim_artifact(edge_artifact(end=924.))
        self.assertTrue(actual['validation_errors'])

    def test_release_audit_rejects_unapplied_end_only_trim(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            review = root / 'songs' / 'example' / '.transcription' / 'trim-review.json'
            review.parent.mkdir(parents=True)
            review.write_text(json.dumps(edge_artifact(end=990.)))
            with mock.patch.object(release_audit, 'ROOT', root), contextlib.redirect_stdout(io.StringIO()) as output:
                result = release_audit.main()
            self.assertEqual(result, 1)
            self.assertEqual(len(json.loads(output.getvalue())['failures']), 1)




if __name__ == '__main__':
    unittest.main()

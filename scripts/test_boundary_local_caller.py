import argparse
from pathlib import Path
import unittest
from unittest import mock
import bhakti_pipeline as pipeline

class BoundaryRequestCallers(unittest.TestCase):
    def test_local_intake_runs_boundary_detection_before_transcription(self):
        order=[]
        song=Path('/tmp/nonexistent-bhakti-boundary-caller')
        source={'source_file':'local.m4a','title':'Fixture'}
        def detect(*args):order.append('detect');return {'fixture':'accepted'}
        def apply(*args):order.append('apply')
        def transcript(*args):order.append('transcript');raise RuntimeError('stop at actual transcription boundary')
        with mock.patch.object(pipeline,'intake',return_value=(song,source)), \
             mock.patch.object(pipeline,'detect_youtube_trim',side_effect=detect), \
             mock.patch.object(pipeline,'apply_lossless_trim',side_effect=apply), \
             mock.patch.object(pipeline,'preferred_listener_audio',return_value=song/'audio.m4a'), \
             mock.patch.object(pipeline,'transcript',side_effect=transcript):
            with self.assertRaisesRegex(RuntimeError,'stop at actual transcription boundary'):
                pipeline.run_one({'slug':'fixture'},argparse.Namespace(force=False))
        self.assertEqual(order,['detect','apply','transcript'])

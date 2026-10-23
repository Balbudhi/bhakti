"""Actual public callers must not consume a half-installed historical bundle."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import bhakti_pipeline as p

class HistoricalBoundaryPending(unittest.TestCase):
    def setup_song(self,root):
        song=root/'songs'/'fixture';packet=song/'.transcription/pipeline';packet.mkdir(parents=True)
        # This models an interruption after one media replacement but before
        # source/timing replacement. Content validation is downstream of the
        # pending gate, so none of it may be consumed as a candidate here.
        (song/'audio.m4a').write_bytes(b'new candidate audio bytes')
        (song/'data.js').write_bytes(b'original reader bytes')
        for name in ['01-transcript.json','02-transcript-audit.json','03-timing.json','04-glosses.json','05-translation.json','song-packet.json']:
            (packet/name).write_text(json.dumps({'original_cached_artifact':name}))
        (song/'.transcription/trim-applied.json').write_text(json.dumps({'application_version':2,
            'status':'pending','applied':False,'adoption':{'status':'pending','operation_id':'fixture'}}))
        return song

    def test_generate_only_holds_pending_bundle_before_hydration_or_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);song=self.setup_song(root);before={str(f.relative_to(song)):f.read_bytes() for f in song.rglob('*') if f.is_file()}
            args=['bhakti_pipeline.py','--song','fixture=unused','--generate-only']
            with mock.patch.object(p,'ROOT',root),mock.patch('sys.argv',args), \
                 mock.patch.object(p,'preflight_blocked_reason',return_value=None), \
                 mock.patch.object(p,'hydrate_pipeline_artifacts') as hydrate, \
                 mock.patch.object(p,'generate') as generate,mock.patch.object(p,'write_catalogue'), \
                 mock.patch.object(p.gemini,'call',side_effect=AssertionError('pending/generate-only must not dispatch')), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(p.main(),1)
                hydrate.assert_not_called();generate.assert_not_called()
            self.assertEqual({str(f.relative_to(song)):f.read_bytes() for f in song.rglob('*') if f.is_file()},before)

    def test_ordinary_intake_requires_local_recovery_before_new_boundary_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            song=self.setup_song(Path(tmp));before={str(f.relative_to(song)):f.read_bytes() for f in song.rglob('*') if f.is_file()}
            with mock.patch.object(p,'intake',return_value=(song,{})), \
                 mock.patch.object(p,'detect_youtube_trim',side_effect=AssertionError('must recover before another model boundary call')) as detect:
                with self.assertRaisesRegex(RuntimeError,'(?i)(pending|recover|adoption)'):
                    p.run_one({'slug':'fixture'},argparse.Namespace(force=False))
                detect.assert_not_called()
            self.assertEqual({str(f.relative_to(song)):f.read_bytes() for f in song.rglob('*') if f.is_file()},before)

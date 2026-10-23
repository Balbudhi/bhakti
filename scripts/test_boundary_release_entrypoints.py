"""Actual callers must stop before publishing/consuming pending adoption state.

Only external commands and later consumers are replaced. Every repository-like
file belongs to an isolated temporary tree; no network or main writes occur.
"""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import bhakti_pipeline as p
import publish_media_release as media
import rebuild_public_readers as rebuild
import repair_existing_youtube_trims as legacy
import test_historical_boundary_pending as helpers


def require_hold(test,operation):
    try:result=operation()
    except (RuntimeError,ValueError,SystemExit) as exc:
        test.assertRegex(str(exc),'(?i)(pending|recover|adoption)')
    else:test.assertNotEqual(result,0,'pending bundle must produce a blocking result')


class BoundaryReleaseEntrypoints(unittest.TestCase):
    def setup_song(self,root):
        return helpers.HistoricalBoundaryPending.setup_song(self,root)

    def test_media_publish_holds_before_remote_release_lookup_or_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);song=self.setup_song(root);(root/'data').mkdir();manifest=root/'data/media.json'
            manifest.write_text('{"schemaVersion":2,"songs":{}}\n');before=manifest.read_bytes()
            args=['publish_media_release.py','--repository','fixture/repository','--song','fixture']
            with mock.patch.object(media,'ROOT',root),mock.patch.object(media,'MANIFEST',manifest),mock.patch('sys.argv',args), \
                 mock.patch.object(media,'release_assets',return_value={}) as remote, \
                 mock.patch.object(media,'command',return_value='') as command,contextlib.redirect_stdout(io.StringIO()):
                require_hold(self,media.main)
                remote.assert_not_called();command.assert_not_called()
            self.assertEqual(manifest.read_bytes(),before)

    def test_manifest_only_cannot_authorize_pending_local_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.setup_song(root);(root/'data').mkdir();manifest=root/'data/media.json'
            manifest.write_text('{"schemaVersion":2,"songs":{}}\n');before=manifest.read_bytes()
            args=['publish_media_release.py','--repository','fixture/repository','--song','fixture','--manifest-only']
            with mock.patch.object(media,'ROOT',root),mock.patch.object(media,'MANIFEST',manifest),mock.patch('sys.argv',args), \
                 mock.patch.object(media,'command',side_effect=AssertionError('manifest-only must be offline')),contextlib.redirect_stdout(io.StringIO()):
                require_hold(self,media.main)
            self.assertEqual(manifest.read_bytes(),before)

    def test_reader_rebuild_checks_pending_before_parsing_or_rewriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);song=self.setup_song(root);before=(song/'data.js').read_bytes()
            with mock.patch.object(rebuild.audit,'load_data',return_value={'SONG_META':{},'SONG_LINES':{}}) as load, \
                 mock.patch.object(p,'published_audio_sources',return_value=[]), \
                 mock.patch.object(p,'page_html',return_value='candidate html'):
                with self.assertRaisesRegex(RuntimeError,'(?i)(pending|recover|adoption)'):
                    rebuild.rebuild(song)
                load.assert_not_called()
            self.assertEqual((song/'data.js').read_bytes(),before)
            self.assertFalse((song/'index.html').exists())

    def test_legacy_repair_cannot_bypass_pending_recovery_into_detection_or_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);song=self.setup_song(root);before=(song/'data.js').read_bytes()
            # Later legacy reader parsing is isolated: an early pending check
            # must happen before this consumer, irrespective of packet content.
            with mock.patch.object(legacy,'ROOT',root),mock.patch.object(legacy,'load_song_page',return_value={'SONG_TIMINGS':[],'SONG_SEQUENCE':[]}) as load, \
                 mock.patch.object(p,'detect_youtube_trim',return_value={'trim_start':0.,'validation_errors':[]}) as detect, \
                 mock.patch.object(p,'apply_lossless_trim') as apply:
                with self.assertRaisesRegex(RuntimeError,'(?i)(pending|recover|adoption)'):
                    legacy.repair('fixture')
                detect.assert_not_called();apply.assert_not_called();load.assert_not_called()
            self.assertEqual((song/'data.js').read_bytes(),before)

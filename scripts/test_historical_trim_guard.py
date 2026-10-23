"""Actual run_one boundary before mutation; provider and later stages are not used."""
import argparse
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import bhakti_pipeline as p
from test_boundary_application import create_audio,accepted_crop

class ReachedTranscript(Exception):pass


def keep_artifact(song):
    artifact=accepted_crop(song)
    for edge in ('start','end'):
        row=artifact[edge];row.pop('verification')
        row['response']['packet'].update(decision='keep',relationship='attached_to_work',
            boundary=0. if edge=='start' else artifact['duration'],excluded_evidence='')
    return p.normalize_trim_artifact(artifact)


class HistoricalTrimGuard(unittest.TestCase):
    def call(self,song,artifact):
        with mock.patch.object(p,'intake',return_value=(song,{'source_file':'fixture.m4a'})), \
             mock.patch.object(p,'detect_youtube_trim',return_value=artifact), \
             mock.patch.object(p,'apply_lossless_trim',wraps=p.apply_lossless_trim) as apply, \
             mock.patch.object(p,'transcript',side_effect=ReachedTranscript('transcript reached')) as transcript:
            try:result=p.run_one({'slug':'fixture'},argparse.Namespace(force=False))
            except (RuntimeError,ReachedTranscript) as exc:result=exc
            return result,apply.call_count,transcript.call_count

    def test_changed_interval_with_source_or_public_reader_holds_before_any_audio_mutation(self):
        for dependent in ('01-transcript.json','02-transcript-audit.json','03-timing.json','song-packet.json','data.js'):
            with self.subTest(dependent=dependent),tempfile.TemporaryDirectory() as tmp:
                song=Path(tmp);originals=create_audio(song);artifact=accepted_crop(song)
                path=song/dependent if dependent=='data.js' else song/'.transcription'/'pipeline'/dependent
                path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{"unchanged":"dependency"}')
                before=path.read_bytes()
                result,applied,transcribed=self.call(song,artifact)
                if isinstance(result,RuntimeError):self.assertIn('adoption',str(result).lower())
                else:
                    self.assertIsInstance(result,dict)
                    self.assertEqual(result['status'],'blocked')
                    self.assertIn('adoption',result.get('error','').lower())
                self.assertEqual((applied,transcribed),(0,0))
                self.assertEqual(path.read_bytes(),before)
                self.assertEqual({n:hashlib.sha256(b).hexdigest() for n,b in originals.items()},
                                 {n:hashlib.sha256((song/n).read_bytes()).hexdigest() for n in originals})

    def test_unchanged_applied_interval_with_existing_source_can_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            song=Path(tmp);create_audio(song);artifact=accepted_crop(song);p.apply_lossless_trim(song,artifact)
            path=song/'.transcription'/'pipeline'/'01-transcript.json';path.parent.mkdir();path.write_text('{"retained":true}')
            before={r['src']:hashlib.sha256((song/r['src']).read_bytes()).hexdigest() for r in p.listener_audio_sources(song)}
            result,applied,transcribed=self.call(song,artifact)
            self.assertIsInstance(result,ReachedTranscript)
            self.assertEqual((applied,transcribed),(1,1))
            self.assertEqual(before,{n:hashlib.sha256((song/n).read_bytes()).hexdigest() for n in before})

    def test_no_crop_on_still_original_audio_with_source_cache_can_continue(self):
        with tempfile.TemporaryDirectory() as tmp:
            song=Path(tmp);create_audio(song);artifact=keep_artifact(song)
            path=song/'.transcription'/'pipeline'/'01-transcript.json';path.parent.mkdir();path.write_text('{"retained":true}')
            result,applied,transcribed=self.call(song,artifact)
            self.assertIsInstance(result,ReachedTranscript)
            self.assertEqual((applied,transcribed),(1,1))

    def test_restoring_whole_original_with_old_dependent_timing_requires_adoption(self):
        with tempfile.TemporaryDirectory() as tmp:
            song=Path(tmp);create_audio(song);p.apply_lossless_trim(song,accepted_crop(song));artifact=keep_artifact(song)
            path=song/'.transcription'/'pipeline'/'03-timing.json';path.parent.mkdir();path.write_text('{"old":true}')
            before={r['src']:hashlib.sha256((song/r['src']).read_bytes()).hexdigest() for r in p.listener_audio_sources(song)}
            result,applied,transcribed=self.call(song,artifact)
            if isinstance(result,RuntimeError):self.assertIn('adoption',str(result).lower())
            else:
                self.assertIsInstance(result,dict);self.assertEqual(result['status'],'blocked')
            self.assertEqual((applied,transcribed),(0,0))
            self.assertEqual(before,{n:hashlib.sha256((song/n).read_bytes()).hexdigest() for n in before})

    def test_fresh_intake_can_apply_accepted_interval_before_transcription(self):
        with tempfile.TemporaryDirectory() as tmp:
            song=Path(tmp);create_audio(song);artifact=accepted_crop(song)
            result,applied,transcribed=self.call(song,artifact)
            self.assertIsInstance(result,ReachedTranscript)
            self.assertEqual((applied,transcribed),(1,1))
            self.assertAlmostEqual(p.gemini.duration_seconds(p.preferred_listener_audio(song)),26.,delta=.2)

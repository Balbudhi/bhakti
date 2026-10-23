"""Additional primitive boundary cases inspected before their dependent changes."""
import json
import tempfile
from pathlib import Path
import unittest
from unittest import mock
import bhakti_pipeline as p
from test_historical_boundary_media import native_fixture

class HistoricalBoundaryPrimitives(unittest.TestCase):
    def test_available_manifest_requires_verification_not_original_reacquisition(self):
        with tempfile.TemporaryDirectory() as tmp:
            song,artifact=native_fixture(Path(tmp));(song/'.transcription/trim-review.json').write_text(json.dumps(artifact));before={str(f.relative_to(song)):f.read_bytes() for f in song.rglob('*') if f.is_file()}
            with mock.patch.object(p.gemini,'call',side_effect=AssertionError('inventory must be read-only')):
                result=p.inspect_historical_boundary(song)
            self.assertEqual(result['status'],'needs-original-verification')
            self.assertIn('verify-preserved-originals-and-current-outputs',result['remaining_obligations'])
            self.assertNotIn('original-audio-identity',result['remaining_obligations'])
            self.assertFalse(result['publicationEligible'])
            self.assertEqual({str(f.relative_to(song)):f.read_bytes() for f in song.rglob('*') if f.is_file()},before)

    def test_identical_original_restoration_has_zero_offset_and_no_decoder_prefix_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            song,_=native_fixture(Path(tmp));original=song/'.transcription/original-audio/audio.m4a'
            result=p.measure_boundary_timebase(original,original,requested_start=0.)
            self.assertEqual(result['status'],'verified')
            self.assertEqual(result['source_offset_samples'],0)
            self.assertEqual(result['decoded_source_offset_seconds'],0.)
            self.assertEqual(result['unmatched_decoder_prefix_samples'],0)
            self.assertEqual(result['waveform_tolerance'],'exact-f32le-bytes')
            self.assertEqual(result['offset_error_seconds'],1/result['source_clock']['sample_rate'])
            expected=(result['source_clock']['frame_clock_bound_seconds']+
                      result['output_clock']['frame_clock_bound_seconds']+result['offset_error_seconds'])
            self.assertEqual(result['timeline_error_seconds'],expected)

    def test_decoder_initialization_prefix_is_excluded_and_all_later_pcm_is_exact(self):
        from test_historical_boundary_media import pcm
        with tempfile.TemporaryDirectory() as tmp:
            song,artifact=native_fixture(Path(tmp))
            for name in ['audio.m4a','audio.webm']:
                with self.subTest(format=name):
                    original=song/'.transcription/original-audio'/name;output=song/name
                    result=p.measure_boundary_timebase(original,output,requested_start=artifact['trim_start'])
                    self.assertEqual(result['status'],'verified')
                    source=pcm(original);candidate=pcm(output);offset=result['source_offset_samples']
                    mismatches=[index for index in range(48000) if source[index+offset]!=candidate[index]]
                    self.assertTrue(mismatches,'fixture should expose decoder reset, not certify the first samples')
                    prefix=max(mismatches)+1
                    self.assertEqual(result['unmatched_decoder_prefix_samples'],prefix)
                    self.assertAlmostEqual(result['verified_output_interval']['start'],prefix/48000,places=10)
                    self.assertEqual(source[offset+prefix:offset+len(candidate)],candidate[prefix:])

    def test_nonzero_stereo_pts_maps_native_timeline_separately_from_decoded_samples(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);original=root/'original.m4a';output=root/'shifted.m4a'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',
                "aevalsrc='0.1*sin(2*PI*(220*t+11*t*t))|0.1*sin(2*PI*(331*t+7*t*t))':s=48000:d=6",
                '-c:a','aac','-output_ts_offset','3',str(original)],check=True)
            subprocess.run(['ffmpeg','-v','error','-i',str(original),'-map','0:a:0','-c','copy',
                '-output_ts_offset','5',str(output)],check=True)
            def origin(path):
                packet=json.loads(subprocess.run(['ffprobe','-v','error','-select_streams','a:0',
                    '-show_frames','-show_entries','frame=best_effort_timestamp_time',
                    '-of','json',str(path)],capture_output=True,text=True,check=True).stdout)
                return float(packet['frames'][0]['best_effort_timestamp_time'])
            before,after=origin(original),origin(output)
            self.assertGreater(before,0.);self.assertGreater(after-before,1.)
            def decoded(path):
                return subprocess.run(['ffmpeg','-v','error','-i',str(path),'-map','0:a:0',
                    '-c:a','pcm_f32le','-f','f32le','-'],capture_output=True,check=True).stdout
            self.assertEqual(decoded(original),decoded(output),'fixture requires identical interleaved stereo PCM')
            result=p.measure_boundary_timebase(original,output,requested_start=3.)
            self.assertEqual(result['status'],'verified')
            self.assertEqual(result['source_clock']['channels'],2)
            self.assertEqual(result['output_clock']['channels'],2)
            self.assertEqual(result['decoded_source_offset_seconds'],0.)
            self.assertAlmostEqual(result['timeline_source_offset_seconds'],before-after,places=9)
            self.assertAlmostEqual(result['verified_output_interval']['start'],after,places=9)
            # Source native-PTS onset translates to output native PTS. Neither
            # this test nor FFprobe certifies browser currentTime normalization.
            original_onset=before+2.
            self.assertAlmostEqual(original_onset-result['timeline_source_offset_seconds'],after+2.,places=9)
            self.assertNotAlmostEqual(original_onset-result['decoded_source_offset_seconds'],after+2.,places=3)

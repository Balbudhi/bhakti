"""Pre-implementation actual-media contracts; no provider or public writes.

Missing-operation assertions are intentional. Existing trim application creates
real AAC/Opus fixtures; PCM peak positions give an independent timing oracle.
"""
import array
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import bhakti_pipeline as p
from test_boundary_application import accepted_crop


def pcm(path):
    result=subprocess.run(['ffmpeg','-v','error','-i',str(path),'-map','0:a:0',
        '-ac','1','-f','f32le','-'],capture_output=True,check=True)
    data=array.array('f');data.frombytes(result.stdout);return data


def peak_time(path,around,rate=48000):
    samples=pcm(path);left=int((around-.12)*rate);right=int((around+.12)*rate)
    return max(range(left,right),key=lambda i:abs(samples[i]))/rate


def native_fixture(root):
    song=root/'song';song.mkdir();(song/'.transcription').mkdir()
    # A unique impulse is a timebase fixture, not simulated linguistic evidence.
    expression='0.02*sin(2*PI*(220*t+11*t*t))+if(between(t,6,6.0001),0.8,0)+if(between(t,20,20.0001),0.6,0)'
    for name,codec in [('audio.m4a','aac'),('audio.webm','libopus')]:
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f"aevalsrc='{expression}':s=48000:d=30",
            '-c:a',codec,str(song/name)],check=True)
    artifact=accepted_crop(song,start=2.137,end=28.341)
    p.apply_lossless_trim(song,artifact)
    return song,artifact


class HistoricalBoundaryMedia(unittest.TestCase):
    def operation(self):
        operation=getattr(p,'measure_boundary_timebase',None)
        self.assertTrue(callable(operation),'decoded historical boundary timebase operation is missing')
        return operation

    def test_native_formats_use_measured_decoded_offset_not_requested_cue(self):
        with tempfile.TemporaryDirectory() as tmp:
            song,artifact=native_fixture(Path(tmp))
            operation=self.operation()
            for name in ('audio.m4a','audio.webm'):
                with self.subTest(format=name):
                    original=song/'.transcription/original-audio'/name;output=song/name
                    oracle=peak_time(original,6.)-peak_time(output,6.-artifact['trim_start'])
                    self.assertGreater(abs(oracle-artifact['trim_start']),1/48000,
                        'fixture must distinguish requested cue from actual decoded timeline')
                    result=operation(original,output,requested_start=artifact['trim_start'])
                    self.assertEqual(result['status'],'verified')
                    self.assertEqual(result['source_sha256'],hashlib.sha256(original.read_bytes()).hexdigest())
                    self.assertEqual(result['output_sha256'],hashlib.sha256(output.read_bytes()).hexdigest())
                    self.assertAlmostEqual(result['decoded_source_offset_seconds'],oracle,delta=1/48000)
                    self.assertGreaterEqual(len(result['sample_windows']),3)
                    self.assertLessEqual(result['offset_error_seconds'],1/48000)
                    # A second separated impulse must obey the SAME map.
                    self.assertAlmostEqual(peak_time(original,20.)-peak_time(output,20.-artifact['trim_start']),oracle,delta=1/48000)

    def test_silent_ambiguous_content_does_not_fabricate_a_unique_timebase(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);original=root/'original.m4a';output=root/'output.m4a'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','anullsrc=r=48000:cl=mono',
                '-t','30','-c:a','aac',str(original)],check=True)
            subprocess.run(['ffmpeg','-v','error','-i',str(original),'-ss','2.137','-to','28.341',
                '-c','copy','-avoid_negative_ts','make_zero',str(output)],check=True)
            result=self.operation()(original,output,requested_start=2.137)
            self.assertEqual(result['status'],'unresolved')
            self.assertTrue(result['issues'])
            self.assertNotIn('decoded_source_offset_seconds',result)

    def test_changed_native_content_is_not_a_valid_constant_timebase(self):
        with tempfile.TemporaryDirectory() as tmp:
            song,artifact=native_fixture(Path(tmp));operation=self.operation()
            wrong=Path(tmp)/'wrong.m4a'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=997:duration=26.204:sample_rate=48000','-c:a','aac',str(wrong)],check=True)
            result=operation(song/'.transcription/original-audio/audio.m4a',wrong,requested_start=artifact['trim_start'])
            self.assertEqual(result['status'],'unresolved')
            self.assertTrue(result['issues'])
            self.assertNotIn('decoded_source_offset_seconds',result)

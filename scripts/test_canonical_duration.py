"""Actual canonicalization regression; no browser/provider-origin claim."""
import array,json,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import bhakti_pipeline as pipeline

def decoded(path):
    raw=subprocess.run(['ffmpeg','-v','error','-i',str(path),'-ac','1','-ar','48000','-f','f32le','-'],capture_output=True,check=True).stdout
    samples=array.array('f');samples.frombytes(raw);return samples

def peaks(samples,seconds):
    return [max(range(int((point-.2)*48000),min(len(samples),int((point+.2)*48000))),key=lambda i:abs(samples[i]))/48000 for point in seconds]

class CanonicalDurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.fixture_temp.cleanup)
        cls.media=Path(cls.fixture_temp.name)
        expression='0.02*sin(2*PI*(220*t+11*t*t))+if(between(t,2,2.0001),0.8,0)+if(between(t,9,9.0001),0.6,0)'
        for ext,codec in [('m4a','aac'),('webm','libopus')]:
            for prefix,offset in [('zero-original',0),('pts3',3)]:
                subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f"aevalsrc='{expression}|{expression}':s=48000:d=12",
                    '-c:a',codec,'-output_ts_offset',str(offset),str(cls.media/f'{prefix}.{ext}')],check=True)
            subprocess.run(['ffmpeg','-v','error','-i',str(cls.media/f'pts3.{ext}'),'-map','0:a:0','-c','copy',
                '-output_ts_offset','5',str(cls.media/f'pts5.{ext}')],check=True)
    def test_nonzero_opus_metadata_offset_is_not_added_to_decoded_audio_length(self):
        for name in ['pts3.webm','pts5.webm']:
            with self.subTest(file=name),tempfile.TemporaryDirectory() as temp:
                original=self.media/name;before=original.read_bytes()
                samples=decoded(original);self.assertEqual(len(samples)/48000,12.)
                # Existing known source/output span is the independent expected invariant.
                result=pipeline.canonical_timing_audio(original,Path(temp)/'canonical.m4a')
                after=decoded(result)
                self.assertLessEqual(abs(len(after)-len(samples))/48000,.1)
                for a,b in zip(peaks(samples,[2.,9.]),peaks(after,[2.,9.])):
                    self.assertAlmostEqual(a,b,delta=.003)
                self.assertEqual(original.read_bytes(),before)
    def test_zero_origin_and_nonzero_aac_keep_current_valid_canonicalization(self):
        for name,markers in [('zero-original.m4a',[2.,9.]),('zero-original.webm',[2.,9.]),('pts3.m4a',[2.,9.]),('pts5.m4a',[2.,9.])]:
            with self.subTest(file=name),tempfile.TemporaryDirectory() as temp:
                original=self.media/name;samples=decoded(original)
                output=pipeline.canonical_timing_audio(original,Path(temp)/'canonical.m4a');after=decoded(output)
                self.assertLessEqual(abs(len(after)-len(samples))/48000,.1)
                for a,b in zip(peaks(samples,markers),peaks(after,markers)):
                    self.assertAlmostEqual(a,b,delta=.003)
    def test_actual_truncated_canonical_output_still_fails_duration_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            original=self.media/'pts3.webm';target=Path(temp)/'truncated.m4a'
            real_run=subprocess.run
            def truncated(command,*args,**kwargs):
                if command[0]=='ffmpeg' and str(target)==command[-1]:
                    command=command[:-1]+['-t','8',command[-1]]
                return real_run(command,*args,**kwargs)
            with patch.object(pipeline.subprocess,'run',side_effect=truncated):
                with self.assertRaisesRegex((ValueError,RuntimeError),'duration|length'):
                    pipeline.canonical_timing_audio(original,target)
            self.assertGreater(len(decoded(original))-len(decoded(target)),3*48000)

    def test_multistream_input_cannot_compare_first_stream_against_automatically_selected_other_stream(self):
        with tempfile.TemporaryDirectory() as temp:
            original=Path(temp)/'two-streams.mka';target=Path(temp)/'canonical.m4a'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=220:sample_rate=48000:duration=2',
                '-f','lavfi','-i','sine=frequency=880:sample_rate=48000:duration=2',
                '-map','0:a:0','-map','1:a:0','-c:a','aac','-ac:a:1','2','-disposition:a:0','0','-disposition:a:1','0',str(original)],check=True)
            info=json.loads(subprocess.run(['ffprobe','-v','error','-select_streams','a','-show_entries',
                'stream=channels:stream_disposition=default','-of','json',str(original)],capture_output=True,text=True,check=True).stdout)
            self.assertEqual([row['channels'] for row in info['streams']],[1,2])
            self.assertEqual([row['disposition']['default'] for row in info['streams']],[0,0])
            with self.assertRaisesRegex((ValueError,RuntimeError),'multiple|unique|single|ambiguous'):
                pipeline.canonical_timing_audio(original,target)
            self.assertFalse(target.exists(),'unknown selected input must hold before conversion')

if __name__=='__main__':unittest.main()

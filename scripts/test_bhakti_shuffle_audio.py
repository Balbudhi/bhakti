"""Audio contract tests: real decoder/math fixtures, no network or paid calls."""
import hashlib
import copy
import json
import math
import shutil
import struct
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import bhakti_shuffle_audio as audio


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class AudioMeasurementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def wav(self, name='tone.wav', seconds=4, amplitude=.5, channels=1, antiphase=False, sample_rate=16000):
        path = self.root / name
        with wave.open(str(path), 'wb') as out:
            out.setnchannels(channels)
            out.setsampwidth(2)
            out.setframerate(sample_rate)
            data = bytearray()
            for i in range(round(seconds * sample_rate)):
                sample = round(32767 * amplitude * math.sin(2 * math.pi * 1000 * i / sample_rate))
                for ch in range(channels):
                    data.extend(struct.pack('<h', -sample if antiphase and ch else sample))
            out.writeframes(data)
        return path

    def physical(self, receipt):
        self.assertEqual(receipt['components']['physical']['status'], 'measured', receipt)
        self.assertEqual(receipt['components']['rhythm']['status'], 'not_established')
        json.dumps(receipt, allow_nan=False)
        return receipt['components']['physical']

    def test_whole_sine_rms_and_frequency_use_real_samples(self):
        p = self.wav(seconds=4.037)
        r = self.physical(audio.analyze_audio(p, window_seconds=1))
        self.assertAlmostEqual(r['whole']['rmsDbfs'], 20 * math.log10(.5 / math.sqrt(2)), delta=.02)
        self.assertAlmostEqual(r['whole']['centroidHz'], 1000, delta=20)
        self.assertAlmostEqual(r['coverageSeconds'], 4.037, delta=1/16000)
        self.assertAlmostEqual(r['profiles']['end']['endSeconds'], 4.037, delta=1/16000)

    def test_nonstationary_profiles_observe_actual_start_and_end(self):
        p=self.root/'changing.wav'
        with wave.open(str(p),'wb') as out:
            out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000)
            for hz,amp in [(500,.1),(1000,.25),(2000,.5)]:
                out.writeframes(b''.join(struct.pack('<h',round(32767*amp*math.sin(2*math.pi*hz*i/16000))) for i in range(32000)))
        f=self.physical(audio.analyze_audio(p,window_seconds=1))
        head=f['profiles']['beginning'];tail=f['profiles']['end']
        self.assertAlmostEqual(head['centroidHz'],500,delta=30)
        self.assertAlmostEqual(tail['centroidHz'],2000,delta=30)
        self.assertAlmostEqual(tail['rmsDbfs']-head['rmsDbfs'],20*math.log10(5),delta=.05)
        self.assertNotEqual(head['rmsDbfs'],f['profiles']['body']['rmsDbfs'])

    def test_long_logging_decode_does_not_deadlock_stderr(self):
        p=self.wav(seconds=90);start=time.monotonic()
        f=self.physical(audio.analyze_audio(p))
        self.assertAlmostEqual(f['coverageSeconds'],90,delta=.001)
        self.assertLess(time.monotonic()-start,10,'local90second fixture must not hit pipe deadlock/timeout')

    def test_invalid_windows_rejected_before_effects(self):
        for value in [0,-1,float('nan'),float('inf')]:
            with self.subTest(value=value),self.assertRaises(ValueError):
                audio.analyze_audio(self.root/'missing.wav',window_seconds=value)

    def test_media_change_during_measurement_cannot_be_cached_as_success(self):
        p=self.wav();cache=self.root/'receipt.json';real=audio._decode
        def mutate(*args,**kwargs):
            result=real(*args,**kwargs)
            self.wav(amplitude=.25)
            return result
        with patch.object(audio,'_decode',side_effect=mutate):
            r=audio.analyze_audio(p,cache_path=cache)
        self.assertEqual(r['components']['physical']['status'],'failed')
        self.assertFalse(cache.exists())

    def test_constant_nonzero_samples_are_not_discarded_as_silence(self):
        p=self.root/'dc.wav'
        with wave.open(str(p),'wb') as out:
            out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000)
            out.writeframes(struct.pack('<h',8192)*16000)
        f=self.physical(audio.analyze_audio(p))
        self.assertAlmostEqual(f['whole']['rmsDbfs'],20*math.log10(.25),delta=.001)

    def test_gain_changes_native_loudness_by_six_db(self):
        loud = self.physical(audio.analyze_audio(self.wav('loud.wav', amplitude=.5)))
        quiet = self.physical(audio.analyze_audio(self.wav('quiet.wav', amplitude=.25)))
        self.assertAlmostEqual(loud['whole']['integratedLufs'] - quiet['whole']['integratedLufs'], 20*math.log10(2), delta=.2)

    def test_antiphase_stereo_loudness_survives_mono_diagnostic_cancellation(self):
        p = self.wav(channels=2, antiphase=True)
        r = audio.analyze_audio(p)
        features = self.physical(r)
        self.assertIsNotNone(features['whole']['integratedLufs'])
        self.assertGreater(features['whole']['integratedLufs'], -30)
        self.assertIsNone(features['whole']['rmsDbfs'])
        self.assertIsNone(features['whole']['centroidHz'])
        self.assertEqual(r['media']['channels'], 2)
        self.assertIn('channel_layouts=stereo', r['settings']['filterGraph'])

    def test_silence_is_measured_with_undefined_values_not_zero_or_bpm(self):
        f = self.physical(audio.analyze_audio(self.wav(amplitude=0)))
        self.assertIsNone(f['whole']['rmsDbfs'])
        self.assertIsNone(f['whole']['integratedLufs'])
        self.assertIsNone(f['whole']['centroidHz'])
        self.assertTrue(f['validity'])

    def test_subframe_recording_includes_remainder(self):
        f = self.physical(audio.analyze_audio(self.wav(seconds=.03125)))
        self.assertAlmostEqual(f['coverageSeconds'], .03125, delta=1/16000)
        self.assertIsNotNone(f['whole']['rmsDbfs'])
        self.assertEqual(f['profiles']['beginning']['startSeconds'], 0)
        self.assertAlmostEqual(f['profiles']['end']['endSeconds'], .03125, delta=1/16000)

    def test_missing_empty_and_corrupt_are_explicit_failures(self):
        empty = self.root/'empty.wav'; empty.write_bytes(b'')
        corrupt = self.root/'corrupt.wav'; corrupt.write_bytes(b'not an audio recording')
        for path in [self.root/'missing.wav', empty, corrupt]:
            with self.subTest(path=path):
                r = audio.analyze_audio(path)
                self.assertEqual(r['components']['physical']['status'], 'failed')
                self.assertTrue(r['components']['physical']['reason'])
                json.dumps(r, allow_nan=False)

    def test_truncated_declared_pcm_is_not_success(self):
        p = self.wav(seconds=4)
        p.write_bytes(p.read_bytes()[:-71])
        r = audio.analyze_audio(p)
        self.assertEqual(r['components']['physical']['status'], 'failed', r)

    def test_wrong_expected_hash_does_not_decode(self):
        p = self.wav()
        with patch.object(audio, '_decode', side_effect=AssertionError('must reject identity first')):
            r = audio.analyze_audio(p, expected_sha256='0'*64)
        self.assertEqual(r['media']['identityStatus'], 'mismatch')
        self.assertEqual(r['components']['physical']['status'], 'failed')

    def test_cache_reuses_exact_identity_then_invalidates_bytes_and_recipe(self):
        p = self.wav(); cache = self.root/'receipt.json'
        first = audio.analyze_audio(p, cache_path=cache)
        with patch.object(audio, '_decode', side_effect=AssertionError('unchanged cache should be reused')):
            second = audio.analyze_audio(p, cache_path=cache)
        self.assertTrue(second['cacheHit'])
        self.assertEqual(first['inputFingerprint'], second['inputFingerprint'])
        self.wav(amplitude=.25)
        third = audio.analyze_audio(p, cache_path=cache)
        self.assertFalse(third['cacheHit'])
        self.assertNotEqual(first['inputFingerprint'], third['inputFingerprint'])
        fourth = audio.analyze_audio(p, cache_path=cache, window_seconds=1)
        self.assertNotEqual(third['inputFingerprint'], fourth['inputFingerprint'])
        self.assertAlmostEqual(fourth['components']['physical']['profiles']['beginning']['endSeconds'], 1)

    def test_malformed_or_nonfinite_cache_is_not_accepted(self):
        p=self.wav(); cache=self.root/'receipt.json'
        first=audio.analyze_audio(p, cache_path=cache)
        first['components']['physical']['whole']['rmsDbfs']=float('nan')
        cache.write_text(json.dumps(first))
        repaired=audio.analyze_audio(p, cache_path=cache)
        self.assertFalse(repaired['cacheHit']); self.physical(repaired)
        cache.write_text('{')
        self.assertFalse(audio.analyze_audio(p, cache_path=cache)['cacheHit'])

    def test_missing_tool_does_not_turn_into_silence(self):
        with patch.object(audio.shutil, 'which', return_value=None):
            r=audio.analyze_audio(self.wav())
        self.assertEqual(r['components']['physical']['status'], 'unavailable')
        self.assertTrue(r['components']['physical']['reason'])

    def test_cache_rejects_non_numeric_metrics_and_malformed_intervals(self):
        p=self.wav();cache=self.root/'receipt.json';first=audio.analyze_audio(p,cache_path=cache)
        for field,value in [('whole','not-a-number'),('whole',True),('whole',{}),('profile','bad'),('interval',-3),('coverage',False)]:
            bad=copy.deepcopy(first);f=bad['components']['physical']
            if field=='whole':f['whole']['rmsDbfs']=value
            elif field=='profile':f['profiles']['end']=value
            elif field=='interval':f['profiles']['end']['startSeconds']=value
            else:f['coverageSeconds']=value
            cache.write_text(json.dumps(bad))
            with self.subTest(field=field,value=value):
                repaired=audio.analyze_audio(p,cache_path=cache)
                self.assertFalse(repaired['cacheHit']);self.physical(repaired)

    def test_declared_nonstandard_two_channel_layout_is_rejected(self):
        p=self.wav(channels=2)
        payload={'streams':[{'codec_name':'pcm_s16le','sample_rate':'16000','channels':2,'channel_layout':'stereo_downmix'}],'format':{'duration':'4'}}
        with patch.object(audio.subprocess,'run',return_value=audio.subprocess.CompletedProcess([],0,json.dumps(payload),'')):
            with self.assertRaisesRegex(ValueError,'layout'):
                audio._probe(p)

    def test_public_summary_is_sanitized_measured_only_and_recipe_bound(self):
        receipt=audio.analyze_audio(self.wav(),expected_sha256=hashlib.sha256(self.wav().read_bytes()).hexdigest())
        summary=audio.audio_summary(receipt)
        self.assertEqual(summary['assessment'],'measured')
        self.assertEqual(summary['method']['id'],'physical')
        self.assertEqual(summary['method']['version'],audio.EXTRACTOR_VERSION)
        self.assertEqual(summary['method']['fingerprint'],audio.audio_method_fingerprint())
        self.assertEqual(summary['domain']['channels'],1)
        self.assertEqual(len(summary['receiptHash']),64)
        self.assertNotIn(str(self.root),json.dumps(summary))
        self.assertNotIn('review',summary)
        wrong_identity=copy.deepcopy(receipt);wrong_identity['media']['sha256']='0'*64
        with self.assertRaises(ValueError):audio.audio_summary(wrong_identity)
        wrong_input=copy.deepcopy(receipt);wrong_input['inputFingerprint']='0'*64
        with self.assertRaises(ValueError):audio.audio_summary(wrong_input)
        receipt['settings']['sampleRate']=8000
        with self.assertRaises(ValueError):audio.audio_summary(receipt)

    def test_summary_rejects_all_null_silence_and_failed_extraction(self):
        silent=audio.analyze_audio(self.wav(amplitude=0))
        with self.assertRaises(ValueError):audio.audio_summary(silent)
        failed=audio.analyze_audio(self.root/'absent.wav')
        with self.assertRaises(ValueError):audio.audio_summary(failed)

    def test_method_identity_binds_dsp_constants_and_rejects_unqualified_window(self):
        original=audio.audio_method_fingerprint()
        with patch.object(audio,'SAMPLE_RATE',8000):
            self.assertNotEqual(original,audio.audio_method_fingerprint())
        with patch.object(audio,'EXTRACTOR_VERSION','changed-method'):
            self.assertNotEqual(original,audio.audio_method_fingerprint())
        with patch.object(audio,'FILTER_GRAPH_TEMPLATE','changed-native-loudness-graph'):
            self.assertNotEqual(original,audio.audio_method_fingerprint())
        with self.assertRaises(ValueError):
            audio.audio_summary(audio.analyze_audio(self.wav(),window_seconds=1))

    def test_algorithm_revision_invalidates_old_receipt_and_cache_without_relabeling(self):
        p=self.wav();cache=self.root/'receipt.json';first=audio.analyze_audio(p,cache_path=cache)
        previous=first['algorithmFingerprint']
        with patch.object(audio,'_ALGORITHM_SOURCE_HASH','f'*64):
            with self.assertRaises(ValueError):audio.audio_summary(first)
            real=audio._decode
            with patch.object(audio,'_decode',wraps=real) as decode:
                second=audio.analyze_audio(p,cache_path=cache)
                self.assertEqual(decode.call_count,1)
            self.assertFalse(second['cacheHit'])
            self.assertNotEqual(previous,second['algorithmFingerprint'])
            self.assertNotEqual(first['inputFingerprint'],second['inputFingerprint'])

    def test_method_fingerprint_does_not_reread_source_after_import(self):
        with patch.object(audio.inspect,'getsource',side_effect=AssertionError('source must be captured at import')):
            self.assertEqual(len(audio.audio_method_fingerprint()),64)

    def test_mp3_packet_duration_beats_inaccurate_container_estimate(self):
        wav=self.wav(seconds=4.037);mp3=self.root/'encoded.mp3'
        audio.subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-i',str(wav),'-ar','44100',
                              '-c:a','libmp3lame','-b:a','128k',str(mp3)],check=True,capture_output=True)
        real=audio.subprocess.run
        def bad_container_duration(command,*args,**kwargs):
            result=real(command,*args,**kwargs)
            if command[0]=='ffprobe' and any(str(x).startswith('format=duration:stream=') for x in command):
                payload=json.loads(result.stdout);payload['format']['duration']=str(float(payload['format']['duration'])+10)
                return audio.subprocess.CompletedProcess(command,result.returncode,json.dumps(payload),result.stderr)
            return result
        with patch.object(audio.subprocess,'run',side_effect=bad_container_duration):
            receipt=audio.analyze_audio(mp3)
        f=self.physical(receipt)
        self.assertAlmostEqual(f['coverageSeconds'],4.037,delta=.002)
        self.assertAlmostEqual(receipt['media']['durationSeconds'],4.037,delta=.002)
        self.assertGreater(receipt['media']['containerDurationSeconds'],14)
        self.assertEqual(receipt['media']['durationSource'],'mp3_packet_durations')
        self.assertGreater(receipt['media']['durationEvidence']['skipSamples'],0)

    def test_packet_duration_requires_finite_positive_complete_evidence(self):
        p=self.wav()
        for packet_duration in [None,'0','-1','N/A']:
            packet={} if packet_duration is None else {'duration':packet_duration}
            payload={'streams':[{'time_base':'1/44100'}],'packets':[packet]}
            with self.subTest(packet_duration=packet_duration),patch.object(audio.subprocess,'run',return_value=audio.subprocess.CompletedProcess([],0,json.dumps(payload),'')):
                with self.assertRaises(ValueError):audio._mp3_packet_duration(p,44100)

    def test_packet_timebase_padding_and_empty_stream_are_rejected_when_invalid(self):
        valid={'streams':[{'time_base':'1/44100'}],'packets':[{'duration':1152}]}
        invalid=[]
        for value in ['0/1','-1/1','1/0','N/A']:
            item=copy.deepcopy(valid);item['streams'][0]['time_base']=value;invalid.append(item)
        item=copy.deepcopy(valid);item['packets']=[];invalid.append(item)
        for value in [-1,1153,'N/A',True]:
            item=copy.deepcopy(valid);item['packets'][0]['side_data_list']=[{'skip_samples':value}];invalid.append(item)
        for payload in invalid:
            with self.subTest(payload=payload),patch.object(audio.subprocess,'run',return_value=audio.subprocess.CompletedProcess([],0,json.dumps(payload),'')):
                with self.assertRaises(ValueError):audio._mp3_packet_duration(self.root/'unused.mp3',44100)


if __name__ == '__main__':
    unittest.main()

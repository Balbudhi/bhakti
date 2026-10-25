"""Actual source routes and request dispatch; synthetic model output, no API calls.

Medium reasoning applies only to transcription/audit, leaving output capacity and
source uncertainty gates intact. Exact accepted high evidence is reusable; failed
high work is never relabelled or accepted under the corrected request.
"""
import copy
import unittest
from unittest.mock import patch

import bhakti_pipeline as pipeline
import bhakti_source_stages as stages
import test_source_bootstrap_design as short_fixture
import test_long_source_bootstrap_design as long_fixture


class SourceReasoningContract(unittest.TestCase):
    def fixture(self, kind):
        fixture = kind(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def capture(self, fixture):
        calls = []
        def provider(model, key, prompt, **kwargs):
            calls.append((model, kwargs))
            return fixture.provider(model, key, prompt, **kwargs)
        return calls, provider

    def test_whole_flash_and_pro_dispatch_medium_with_full_output_capacity(self):
        f = self.fixture(short_fixture.SourceStageTests)
        f.bad_first = True
        f.audit_uncertain = True
        calls, provider = self.capture(f)
        with patch.object(pipeline.gemini, 'call', side_effect=provider):
            raw = f.transcribe()
            result = f.audit(raw)
        self.assertEqual([model for model, _ in calls],
                         [f.options.model, f.options.pro_model] * 2)
        self.assertFalse(result['packet']['uncertainties'])
        for _, kwargs in calls:
            self.assertEqual(kwargs['reasoning_effort'], 'medium')
            self.assertEqual(kwargs['max_completion_tokens'], 65536)
        self.assertEqual(calls[-1][1]['response_schema'], pipeline.audited_transcript_schema())

    def test_long_transcript_and_audit_flash_pro_requests_and_free_resume(self):
        f = self.fixture(long_fixture.LongSourceBootstrapTests)
        f.bad_second_first = True
        f.uncertain_second = True
        calls, provider = self.capture(f)
        with patch.object(pipeline.gemini, 'call', side_effect=provider):
            raw = pipeline.transcript(f.song, {}, f.audio, f.options)
            result = pipeline.audit_transcript(f.song, raw, f.audio, f.options)
        self.assertEqual(len(calls), 6)
        self.assertEqual(sum(model == f.options.pro_model for model, _ in calls), 2)
        self.assertFalse(result['packet']['uncertainties'])
        for _, kwargs in calls:
            self.assertEqual(kwargs['reasoning_effort'], 'medium')
            self.assertEqual(kwargs['max_completion_tokens'], 32768)
            self.assertEqual(kwargs['response_schema'], pipeline.segment_transcript_schema())
        with patch.object(pipeline.gemini, 'call', side_effect=AssertionError('accepted request replay')):
            self.assertEqual(pipeline.transcript(f.song, {}, f.audio, f.options), raw)
            self.assertEqual(pipeline.audit_transcript(f.song, raw, f.audio, f.options), result)

    def test_old_high_whole_accepted_projections_reuse_without_rewriting(self):
        f = self.fixture(short_fixture.SourceStageTests)
        original_transcript = pipeline.transcript_request_contract
        original_audit = pipeline.audited_source_request_contract
        def high_transcript(*args, **kwargs):
            return {**original_transcript(*args, **kwargs), 'reasoning_effort': 'high'}
        def high_audit(*args, **kwargs):
            return {**original_audit(*args, **kwargs), 'reasoning_effort': 'high'}
        with patch.object(pipeline, 'transcript_request_contract', side_effect=high_transcript), \
             patch.object(pipeline, 'audited_source_request_contract', side_effect=high_audit):
            raw = f.transcribe()
            audited = f.audit(raw)
        files = list((f.song / '.transcription/pipeline').rglob('*.json'))
        original = {p: p.read_bytes() for p in files}
        with patch.object(pipeline.gemini, 'call', side_effect=AssertionError('contract drift cannot dispatch')):
            self.assertEqual(f.transcribe(), raw)
            self.assertEqual(f.audit(raw), audited)
        self.assertEqual({p: p.read_bytes() for p in files}, original)

    def test_old_high_segment_accepted_projections_reuse_without_rewriting(self):
        f = self.fixture(long_fixture.LongSourceBootstrapTests)
        original_request = stages.segment_request
        def high_request(p, song, audio, clip, stage, segment, request, options, **kwargs):
            request = {**copy.deepcopy(request), 'reasoning_effort': 'high'}
            return original_request(p, song, audio, clip, stage, segment, request, options, **kwargs)
        with patch.object(stages, 'segment_request', side_effect=high_request):
            raw = pipeline.transcribe_long_audio(f.song, {}, f.audio, f.options)
            audited = pipeline.audit_long_transcript(f.song, raw, f.audio, f.options)
        files = list((f.song / '.transcription/pipeline').rglob('*.json'))
        original = {p: p.read_bytes() for p in files}
        with patch.object(pipeline.gemini, 'call', side_effect=AssertionError('old segment cannot replay')):
            self.assertEqual(pipeline.transcribe_long_audio(f.song, {}, f.audio, f.options), raw)
            self.assertEqual(pipeline.audit_long_transcript(f.song, raw, f.audio, f.options), audited)
        self.assertEqual({p: p.read_bytes() for p in files}, original)


    def test_old_high_reuse_requires_exact_input_and_immutable_result(self):
        f = self.fixture(short_fixture.SourceStageTests)
        original_request = pipeline.transcript_request_contract
        def high(*args, **kwargs):
            return {**original_request(*args, **kwargs), 'reasoning_effort': 'high'}
        with patch.object(pipeline, 'transcript_request_contract', side_effect=high):
            raw = f.transcribe()
        with patch.object(pipeline.gemini, 'call', side_effect=AssertionError('invalid cache must hold')):
            with self.assertRaisesRegex(ValueError, 'inputs changed'):
                pipeline.transcript(f.song, {'title': 'different'}, f.audio, f.options)
            def changed(*args, **kwargs):
                request = original_request(*args, **kwargs)
                return {**request, 'prompt': request['prompt'] + ' changed request'}
            with patch.object(pipeline, 'transcript_request_contract', side_effect=changed):
                with self.assertRaisesRegex(ValueError, 'inputs changed'):
                    f.transcribe()
            original_audio = f.audio.read_bytes()
            f.audio.write_bytes(original_audio + b'changed')
            with self.assertRaisesRegex(ValueError, 'inputs changed'):
                f.transcribe()
            f.audio.write_bytes(original_audio)
            target = f.song / '.transcription/pipeline/01-transcript.json'
            tampered = copy.deepcopy(raw)
            tampered['packet']['lines'][0]['source_text'] = 'अन्य'
            pipeline.write_json(target, tampered)
            with self.assertRaisesRegex(ValueError, 'routed evidence'):
                f.transcribe()

    def test_failed_high_audit_is_not_reused_or_relabelled_medium(self):
        f = self.fixture(short_fixture.SourceStageTests)
        raw = f.transcribe()
        original_request = pipeline.audited_source_request_contract
        def high(*args, **kwargs):
            return {**original_request(*args, **kwargs), 'reasoning_effort': 'high'}
        f.all_audits_uncertain = True
        with patch.object(pipeline, 'audited_source_request_contract', side_effect=high):
            with self.assertRaises(short_fixture.routes.UnitUnresolved):
                f.audit(raw)
        files = list((f.song / '.transcription/pipeline/source-stages').rglob('*.json'))
        original = {p: p.read_bytes() for p in files}
        f.all_audits_uncertain = False
        calls, provider = self.capture(f)
        with patch.object(pipeline.gemini, 'call', side_effect=provider):
            result = f.audit(raw)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]['reasoning_effort'], 'medium')
        self.assertFalse(result['packet']['uncertainties'])
        self.assertEqual({p: p.read_bytes() for p in files}, original)


if __name__ == '__main__':
    unittest.main()

"""Local-clock routing contracts; canned starts prove arithmetic, not acoustic quality."""
import argparse
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import bhakti_pipeline as p
import bhakti_model_routes as routes

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/satgur-timing.json').read_text())


class ClipClockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.audio = self.root / 'audio.m4a'
        self.audio.write_bytes(b'clock-contract-fixture-not-real-audio')
        # Three actual singleton targets isolate clock arithmetic from repeat expansion.
        self.occ = copy.deepcopy([row for row in FIXTURE['timing']['ordered_occurrences']
                                  if row['repeats'] == 1][:3])
        self.assertEqual(len(self.occ), 3)
        self.before = {**copy.deepcopy(self.occ[0]), 'occurrence_id': 'preceding',
                       'coarse_source_start': 931.125, 'routing_only': True}
        self.after = {**copy.deepcopy(self.occ[-1]), 'occurrence_id': 'following',
                      'coarse_source_start': 932.125, 'routing_only': True}
        self.region = {'index': 0, 'clip_start': 105.0, 'clip_end': 189.0,
                       'target_occurrences': self.occ, 'preceding_context': self.before,
                       'following_context': self.after, 'max_completion_tokens': 4096,
                       'reasoning_effort': 'medium'}
        self.options = argparse.Namespace(model=routes.PRO_MODEL, pro_model=routes.PRO_MODEL,
                                         timeout=180, timing_deadline_at=time.time()+600, force=False)
        self.source_identity = {'trim': {'applied': False}}

    def invoke(self):
        return p.run_joint_timing_unit(self.root, self.audio, self.region, 400.0,
                                       self.options, self.source_identity)

    def packet(self, starts):
        return {'packet': {'starts': [
            {'timing_id': row['timing_id'], 'start': start,
             'uncertainty': '', 'onset_at_clip_start': False}
            for row, start in zip(p.expanded_timing_targets(self.occ), starts)]}}

    def replies(self):
        # First clip105–189; second95–189. Both encode absolute130.6,137.8,145.1.
        return [self.packet([25.6, 32.8, 40.1]), self.packet([35.6, 42.8, 50.1])]

    def mocks(self, replies):
        return (patch.object(p.subprocess, 'run'),
                patch.object(p.gemini, 'key', return_value='offline-fixture'),
                patch.object(p.gemini, 'call', side_effect=replies))

    def test_v2_only_exposes_local_clock_and_preserves_source_context(self):
        self.region['prompt_version'] = 2
        for row in self.occ:
            row.update(coarse_source_start=933.125, routing_only=True)
        ffmpeg, key, provider = self.mocks(self.replies())
        with ffmpeg, key, provider as call:
            result = self.invoke()
        self.assertEqual(call.call_count, 2)
        for item, duration in zip(call.call_args_list, (84.0, 94.0)):
            prompt = item.args[2]
            self.assertIn(f'EXCERPT CLOCK: 0.000–{duration:.3f} seconds.', prompt)
            for forbidden in ('SOURCE CLIP:', '105.000', '189.000', '95.000',
                              'coarse_source_start', 'routing_only', '931.125', '932.125', '933.125'):
                self.assertNotIn(forbidden, prompt)
            for row in [self.before, *self.occ, self.after]:
                self.assertIn(row['source_text'], prompt)
                self.assertIn(row['roman'], prompt)
            start_schema = item.kwargs['response_schema']['properties']['starts']['items']['properties']['start']
            self.assertEqual(start_schema, {'type': 'number', 'minimum': 0, 'maximum': duration})
            self.assertEqual(item.kwargs['max_completion_tokens'], 4096)
            self.assertEqual(item.kwargs['reasoning_effort'], 'medium')
        self.assertEqual([x['start'] for x in result['expanded_starts']], [130.6, 137.8, 145.1])
        self.assertEqual([x['region']['clip_start'] for x in result['passes']], [105.0, 95.0])
        self.assertEqual(self.region['preceding_context']['coarse_source_start'], 931.125)
        self.assertEqual(self.region['following_context']['coarse_source_start'], 932.125)
        self.assertEqual(self.occ[0]['coarse_source_start'], 933.125)

    def test_omitted_version_preserves_original_prompt_and_schema(self):
        ffmpeg, key, provider = self.mocks(self.replies())
        with ffmpeg, key, provider as call:
            self.invoke()
        for index, item in enumerate(call.call_args_list):
            role = ('PRIMARY ONSET MEASUREMENT' if index == 0 else
                    'INDEPENDENT FIRST-SYLLABLE AUDIT: re-listen and derive every start anew')
            expanded = p.expanded_timing_targets(self.occ)
            left = 105.0 if index == 0 else 95.0
            expected = f'''TASK: {role}.
Listen independently to this complete contextual excerpt. The transcript and order are fixed. Do not correct, normalize, regroup, drop or add lyrics. Only locate each exact first audible syllable, including every explicit consecutive repetition listed separately below. Embedded repetitions in a target's source text remain one target. Lead, response and pickup starts count. Return times relative to this clip, never a later repetition. If the requested initial syllable is cut off, masked, absent or ambiguous, declare uncertainty; do not guess.
SOURCE CLIP: {left:.3f}–189.000 seconds.
PRECEDING CONTEXT ONLY: {json.dumps(self.before,ensure_ascii=False)}
EXACT ORDERED TIMING TARGETS: {json.dumps(expanded,ensure_ascii=False)}
FOLLOWING CONTEXT ONLY: {json.dumps(self.after,ensure_ascii=False)}
Return every timing_id exactly once in order, with start, uncertainty, and onset_at_clip_start. The last boolean may be true only when a COMPLETE initial syllable begins at the clip boundary. Already ongoing syllables are uncertain, not clear zero starts. Return JSON {{"starts":[{{"timing_id":"{expanded[0]['timing_id']}","start":0.0,"uncertainty":"","onset_at_clip_start":false}}]}}.'''
            self.assertEqual(item.args[2], expected)
            self.assertEqual(item.kwargs['response_schema']['properties']['starts']['items']['properties']['start'],
                             {'type': 'number'})

    def test_v2_has_distinct_identity_and_free_resume(self):
        ffmpeg, key, provider = self.mocks(self.replies()+self.replies())
        with ffmpeg, key, provider as call:
            old = self.invoke()
            self.region['prompt_version'] = 2
            revised = self.invoke()
            self.assertEqual(self.invoke(), revised)
        self.assertEqual(call.call_count, 4)
        self.assertNotEqual(old['input_fingerprint'], revised['input_fingerprint'])
        self.assertEqual(len(list(self.root.rglob('accepted-result.json'))), 2)

    def test_invalid_version_rejected_before_identity_audio_or_route(self):
        for version in (True, False, None, 0, 4, 1.0, '2', [], {}):
            self.region['prompt_version'] = version
            with self.subTest(version=version), patch.object(p, 'timing_input_identity',
                    side_effect=AssertionError('invalid version reached audio identity')):
                with self.assertRaises(ValueError):
                    self.invoke()
        self.assertFalse(list(self.root.rglob('route-state.json')))

    def test_exact_clip_end_is_rejected_despite_inclusive_schema_maximum(self):
        self.region['prompt_version'] = 2
        # Both relative endpoints denote absolute189, outside the playable excerpt.
        replies = [self.packet([25.6, 32.8, 84.0]), self.packet([35.6, 42.8, 94.0])]
        ffmpeg, key, provider = self.mocks(replies)
        with ffmpeg, key, provider as call:
            with self.assertRaises(routes.UnitUnresolved):
                self.invoke()
            with self.assertRaises(routes.UnitUnresolved):
                self.invoke()
        self.assertEqual(call.call_count, 2)
        saved = json.loads(next(self.root.rglob('candidate.json')).read_text())
        self.assertEqual(saved['expanded_starts'], [])
        for report, endpoint in zip(saved['passes'], (84.0, 94.0)):
            self.assertEqual(report['response']['packet']['starts'][-1]['start'], endpoint)
            self.assertEqual(report['validation']['starts'], [])
            self.assertTrue(any('out of clip' in error for error in report['validation']['validation_errors']))

    def test_absolute_out_of_clip_response_holds_without_subtraction_or_replay(self):
        self.region['prompt_version'] = 2
        # Real failure shape: second model answered on recording clock, not excerpt clock.
        replies = [self.replies()[0], self.packet([130.8, 137.8, 144.8])]
        ffmpeg, key, provider = self.mocks(replies)
        with ffmpeg, key, provider as call:
            with self.assertRaises(routes.UnitUnresolved):
                self.invoke()
            with self.assertRaises(routes.UnitUnresolved):
                self.invoke()
        self.assertEqual(call.call_count, 2)
        saved = json.loads(next(self.root.rglob('candidate.json')).read_text())
        self.assertEqual(saved['expanded_starts'], [])
        self.assertTrue(any('out of clip' in error for error in saved['validation_errors']))
        self.assertEqual([r['start'] for r in saved['passes'][1]['response']['packet']['starts']],
                         [130.8, 137.8, 144.8])


if __name__ == '__main__':
    unittest.main()

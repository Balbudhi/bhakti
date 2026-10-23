"""Optional route context reaches real stage calls; legacy behavior is unchanged."""
import argparse
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import bhakti_pipeline as pipeline
from test_sense_decisions import decisions_for
import prepare_library_review
import retranslate_bhakti


class StageContextTests(unittest.TestCase):
    def options(self, routed=True):
        result = argparse.Namespace(model='google/gemini-3.7-flash', timeout=600,
                                    force=False, source_witness_audit=False)
        if routed:
            result.unit_context = {'unit_id': 'fixture', 'attempt_id': 'flash', 'state_path': 'private'}
            result.unit_deadline_at = time.time() + 20
        return result

    def test_real_ask_forwards_context_and_deadline_without_prompt_changes(self):
        options = self.options(); before = copy.deepcopy(options)
        with patch.object(pipeline.gemini, 'key', return_value='unused'), patch.object(pipeline.gemini, 'call', return_value={'packet': {}}) as call:
            pipeline.ask('unchanged source prompt', None, options)
        self.assertEqual(call.call_args.args[2], 'unchanged source prompt')
        self.assertEqual(call.call_args.kwargs['unit_context'], options.unit_context)
        self.assertEqual(call.call_args.kwargs['deadline_at'], options.unit_deadline_at)
        self.assertLessEqual(call.call_args.kwargs['timeout'], 20)
        self.assertEqual(vars(before), vars(options))

    def test_legacy_ask_does_not_acquire_route_context(self):
        with patch.object(pipeline.gemini, 'key', return_value='unused'), patch.object(pipeline.gemini, 'call', return_value={}) as call:
            pipeline.ask('old prompt', None, self.options(False))
        self.assertNotIn('unit_context', call.call_args.kwargs)
        self.assertEqual(call.call_args.kwargs['timeout'], 600)

    def test_routed_transcript_does_not_retry_or_transcode_after_transport_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(pipeline.gemini, 'duration_seconds', return_value=200), patch.object(pipeline.gemini, 'key', return_value='unused'), patch.object(pipeline.gemini, 'call', side_effect=RuntimeError('required JSON packet')) as call, patch.object(pipeline, 'normalized_transcript_audio', side_effect=AssertionError('retry forbidden')):
                with self.assertRaisesRegex(RuntimeError, 'required JSON packet'):
                    pipeline.transcript(Path(temporary), {}, Path(temporary) / 'audio.m4a', self.options())
                self.assertEqual(call.call_count, 1)

    def test_source_first_reviewer_receives_context_with_no_attempt_ids_in_prompt(self):
        options = self.options()
        options.semantic_full_source = [{'id': 'line', 'source_text': 'मन', 'roman': 'mana'}]
        options.semantic_performance_order = [{'line_id': 'line', 'occurrence': 1}]
        options.semantic_deadline_at = options.unit_deadline_at
        options.semantic_original_reader = {'line': {'english': '{0:mind}'}}
        options.semantic_confirmed_issues = [{'kind': 'english_realization', 'evidence': 'source agency'}]
        response = {'packet': {'reviews': [{'id': 'line', 'passes': True,
                                            'human_review_recommended': False, 'issues': []}]}}
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(pipeline.gemini, 'key', return_value='unused'), patch.object(pipeline.gemini, 'call', return_value=response) as call:
                reviews, _ = pipeline.independently_review_translations(Path(temporary),
                    options.semantic_full_source, [{'id': 'line', 'word_glosses': [{'roman': 'mana', 'gloss': 'mind'}]}],
                    [{'id': 'line', 'literal_english': 'mind', 'english_segments': [{'text': 'mind', 'word_indices': [0]}]}],
                    '(none supplied)', options, languages=['Hindi'])
        self.assertEqual(reviews[0]['id'], 'line')
        self.assertEqual(call.call_args.kwargs['unit_context'], options.unit_context)
        prompt = call.call_args.args[2]
        self.assertIn('मन', prompt); self.assertIn('mind', prompt)
        self.assertIn('ORIGINAL READER ROWS', prompt); self.assertIn('source agency', prompt)
        self.assertNotIn('attempt_id', prompt); self.assertNotIn('state_path', prompt)

    def test_original_comparison_evidence_is_in_cache_policy_but_attempt_identity_is_not(self):
        options = self.options(); options.semantic_deadline_at = options.unit_deadline_at
        original = pipeline.semantic_stage_policy(options)
        options.unit_context = {'attempt_id': 'different-attempt'}
        self.assertEqual(original, pipeline.semantic_stage_policy(options))
        options.semantic_original_reader = {'line': {'english': 'preserved image'}}
        self.assertNotEqual(original, pipeline.semantic_stage_policy(options))

    def test_gloss_request_and_validator_keep_existing_compound_word_division(self):
        lines = [{'id': 'line', 'source_text': 'पौत्रमकल्मषम्', 'roman': 'pautramakalmaṣam',
                  'lexical_tokens': ['pautram', 'akalmaṣam']}]
        words = [{'roman': token, 'gloss': meaning, 'concept_key': '', 'preserve_in_english': False}
                 for token, meaning in [('pautram', 'grandson'), ('akalmaṣam', 'spotless')]]
        packet = {'packet': {'glosses': [{'id': 'line', 'word_glosses': words,
            'semantic_frame': {field: '' for field in pipeline.SEMANTIC_FRAME_FIELDS},
            'grammar_note': '', 'uncertainty': '', 'sense_decisions': decisions_for(lines, ['Sanskrit'])['line']}]}}
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(pipeline.gemini, 'key', return_value='unused'), patch.object(pipeline.gemini, 'call', return_value=packet) as call:
                result = pipeline.gloss(Path(temporary), {'packet': {'verified_lines': lines,
                    'metadata': {'languages': ['Sanskrit']}, 'performance_order': [{'line_id': 'line'}]}}, self.options())
        self.assertEqual([word['roman'] for word in result['packet']['glosses'][0]['word_glosses']], ['pautram', 'akalmaṣam'])
        self.assertIn('When a source line supplies lexical_tokens', call.call_args.args[2])
        self.assertIn('"lexical_tokens": ["pautram", "akalmaṣam"]', call.call_args.args[2])

    def test_real_vishnu_invocation_three_prompt_and_contract_use_all_nine_reader_tokens(self):
        data = prepare_library_review.load_javascript((pipeline.ROOT / 'songs/vishnu-sahasranama/data.js').read_bytes())
        line_id = 'invocation-3'; line = data['SONG_LINES'][line_id]
        focused = {**data, 'SONG_LINES': {line_id: line},
                   'SONG_SEQUENCE': [{'ref': line_id, 'section': 'invocation', 'repeats': 1}]}
        lines = retranslate_bhakti.source_lines(focused)
        expected = [word['roman'] for word in line['words']]
        self.assertEqual(len(expected), 9)
        words = [{'roman': token, 'gloss': 'contextual meaning', 'concept_key': '', 'preserve_in_english': False}
                 for token in expected]
        response = {'packet': {'glosses': [{'id': line_id, 'word_glosses': words,
            'semantic_frame': {field: '' for field in pipeline.SEMANTIC_FRAME_FIELDS},
            'grammar_note': '', 'uncertainty': '', 'sense_decisions': decisions_for(lines, ['Sanskrit'])[line_id]}]}}
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(pipeline.gemini, 'key', return_value='unused'), patch.object(pipeline.gemini, 'call', return_value=response) as call:
                result = pipeline.gloss(Path(temporary), {'packet': {'verified_lines': lines,
                    'metadata': {'languages': ['Sanskrit']}, 'performance_order': [{'line_id': line_id}]}}, self.options())
        prompt = call.call_args.args[2]
        actual = json.JSONDecoder().raw_decode(prompt.split('TARGET LYRICS (return these IDs only):\n', 1)[1].lstrip())[0]
        self.assertEqual(actual[0]['surface_tokens'], expected)
        self.assertEqual(actual[0]['lexical_tokens'], expected)
        self.assertEqual(pipeline.gloss_surface_errors(lines, result['packet']['glosses']), [])


if __name__ == '__main__': unittest.main()

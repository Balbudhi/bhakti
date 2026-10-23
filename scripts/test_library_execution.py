"""Actual current-content stage and persisted router path, with fake transport only."""
import argparse
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import bhakti_library_pass as library
from test_bhakti_library_pass import reader
from test_sense_decisions import decisions_for


def review(line_id='one', issues=None):
    issues = issues or []
    return {'id': line_id, 'passes': not issues, 'agency_preserved': not issues,
            'imagery_preserved': True, 'all_meaning_accounted_for': True,
            'unsupported_additions': [], 'human_review_recommended': False,
            'material_choice': '', 'reason': 'Source and indexed meaning checked.', 'issues': issues}


class CurrentContentExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.options = argparse.Namespace(model='google/gemini-3.7-flash', pro_model='google/gemini-3.1-pro-preview',
                                          timeout=600, force=False)
        self.deadline = time.time() + 60

    def execute(self, data):
        return library.audit_current_reader(data, slug='fixture', workspace=self.directory / 'song',
            route_dir=self.directory / 'routes', options=self.options,
            dependency_fingerprint='frozen-recording-and-source', deadline_at=self.deadline)

    def test_real_source_first_review_preserves_legacy_reader_and_resumes_without_call(self):
        data = reader(); original = copy.deepcopy(data)
        response = {'packet': {'reviews': [review()]}}
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), patch.object(library.pipeline.gemini, 'call', return_value=response) as transport:
            first = self.execute(data)
            second = self.execute(data)
        self.assertEqual(first, second); self.assertEqual(transport.call_count, 1)
        self.assertEqual(data, original)
        self.assertEqual(first['issues'], [])
        self.assertEqual(first['reader_digest'], library.prepare.json_digest(original))
        prompt = transport.call_args.args[2]
        self.assertIn('मन', prompt); self.assertIn('mana', prompt); self.assertIn('mind', prompt)
        self.assertEqual(transport.call_args.kwargs['schema_name'], 'bhakti_translation_review')
        self.assertIn('unit_context', transport.call_args.kwargs)
        self.assertTrue(first['attempt_id'])
        self.assertFalse((self.directory / 'song/data.js').exists())

    def test_concrete_existing_defect_is_preserved_as_evidence_not_erased_by_pro_review(self):
        data = reader(); data['SONG_LINES']['one']['english'] = '{0:body}'
        issue = {'kind': 'english_realization', 'target_line_ids': ['one'],
                 'references': [{'line_id': 'one', 'domain': 'word_glosses', 'word_indices': [0], 'source_quote': 'मन'}],
                 'explanation': 'The English says body but the source denotes mind.',
                 'evidence': 'मन has the supported current gloss mind.', 'hold_reason': '', 'needed_evidence': ''}
        response = {'packet': {'reviews': [review(issues=[issue])]}}
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), patch.object(library.pipeline.gemini, 'call', return_value=response) as transport:
            result = self.execute(data)
        self.assertEqual(transport.call_count, 1)
        self.assertEqual(result['issues'], [issue])
        self.assertEqual(data['SONG_LINES']['one']['english'], '{0:body}')
        self.assertEqual(result['reviewPurpose'], 'identify-current-defects')

    def test_changed_current_gloss_cannot_reuse_previous_review(self):
        data = reader(); response = {'packet': {'reviews': [review()]}}
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), patch.object(library.pipeline.gemini, 'call', return_value=response) as transport:
            before = self.execute(data)
            data['SONG_LINES']['one']['words'][0]['gloss'] = 'the mind'
            after = self.execute(data)
        self.assertEqual(transport.call_count, 2)
        self.assertNotEqual(before['reader_digest'], after['reader_digest'])

    def test_real_reviewer_missing_ids_is_typed_quality_failure_then_one_pro(self):
        responses = [{'packet': {'reviews': []}}, {'packet': {'reviews': [review()]}}]
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), patch.object(library.pipeline.gemini, 'call', side_effect=responses) as transport:
            result = self.execute(reader())
        self.assertEqual(transport.call_count, 2)
        self.assertEqual([call.args[0] for call in transport.call_args_list], [self.options.model, self.options.pro_model])
        self.assertEqual(result['issues'], [])

    def test_null_issues_container_is_typed_quality_failure_not_iteration_error(self):
        responses = [{'packet': {'reviews': [{**review(), 'issues': None}]}}, {'packet': {'reviews': [review()]}}]
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), patch.object(library.pipeline.gemini, 'call', side_effect=responses) as transport:
            result = self.execute(reader())
        self.assertEqual(transport.call_count, 2); self.assertEqual(result['issues'], [])

    def test_malformed_fidelity_fields_cannot_be_cached_as_valid_pre_review(self):
        for bad_fields in ({'material_choice': None}, {'unsupported_additions': None},
                           {'material_choice': 'two unresolved agency choices'}):
            with self.subTest(fields=bad_fields), tempfile.TemporaryDirectory() as temporary:
                self.directory = Path(temporary)
                malformed = {**review(), **bad_fields}
                responses = [{'packet': {'reviews': [malformed]}}, {'packet': {'reviews': [review()]}}]
                with patch.object(library.pipeline.gemini, 'key', return_value='unused'), patch.object(library.pipeline.gemini, 'call', side_effect=responses) as transport:
                    result = self.execute(reader())
                self.assertEqual(transport.call_count, 2); self.assertEqual(result['reviews'][0], review())


class TargetedRepairExecutionTests(CurrentContentExecutionTests):
    def setUp(self):
        super().setUp()
        self.data = reader(); self.data['SONG_LINES']['one']['english'] = '{0:body}'
        self.data['SONG_LINES']['two'] = copy.deepcopy(reader()['SONG_LINES']['one'])
        self.data['SONG_SEQUENCE'].append({'ref': 'two', 'section': 'verse', 'repeats': 1})
        self.data['SONG_TIMINGS'].append({'start': 5, 'end': 10})
        self.issue = {'kind': 'english_realization', 'target_line_ids': ['one'],
            'references': [{'line_id': 'one', 'domain': 'word_glosses', 'word_indices': [0], 'source_quote': 'मन'}],
            'explanation': 'body conflicts with the noun mind', 'evidence': 'मन and its retained gloss mean mind',
            'hold_reason': '', 'needed_evidence': ''}
        self.schemas = []; self.target_populations = []; self.reject_flash_post = False
        self.reject_all_posts = False
        self.review_evidence = []
        self.bad_flash_gloss = False

    def provider(self, model, key, prompt, **kwargs):
        schema = kwargs['schema_name']; self.schemas.append((model, schema))
        if schema == 'bhakti_translation_review':
            evidence = json.JSONDecoder().raw_decode(prompt.split('EVIDENCE:\n', 1)[1].lstrip())[0]
            self.review_evidence.append(copy.deepcopy(evidence))
            rows = []
            for item in evidence:
                bad = item['draft']['literal_english'] == 'body'
                if (self.reject_all_posts or (self.reject_flash_post and model.endswith('3.7-flash'))) and 'ORIGINAL READER ROWS' in prompt:
                    original = json.JSONDecoder().raw_decode(prompt.split('ORIGINAL READER ROWS FOR REPAIR COMPARISON:\n', 1)[1].lstrip())[0]
                    bad = bad or bool(original)
                rows.append(review(item['source']['id'], [self.issue] if bad else []))
            return {'packet': {'reviews': rows}}
        is_gloss = 'word_gloss' in schema
        marker = 'TARGET LYRICS (return these IDs only):\n' if is_gloss else 'TARGET audited source lines (return these IDs only):\n'
        targets = json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1].lstrip())[0]
        self.target_populations.append([line['id'] for line in targets])
        if is_gloss:
            decisions = decisions_for(targets, ['Hindi'])
            return {'packet': {'glosses': [{'id': line['id'],
                'word_glosses': [{'roman': 'mana', 'gloss': '' if self.bad_flash_gloss and model.endswith('3.7-flash') else 'mind', 'concept_key': '', 'preserve_in_english': False}],
                'semantic_frame': {field: '' for field in library.pipeline.SEMANTIC_FRAME_FIELDS},
                'grammar_note': 'Noun.', 'uncertainty': '', 'sense_decisions': decisions[line['id']]}
                for line in targets]}}
        return {'packet': {'translations': [{'id': line['id'], 'literal_english': 'mind',
            'segments': [{'text': 'mind', 'word_indices': [0]}],
            'fidelity': {'agency_and_image_preserved': True, 'all_meaning_accounted_for': True, 'unsupported_additions': []},
            'human_review_recommended': False, 'material_alternatives': [], 'choice_note': '', 'uncertainty': ''}
            for line in targets], 'comparison': []}}

    def repair(self, pre):
        return library.repair_current_reader(self.data, slug='fixture', pre_review=pre,
            workspace=self.directory / 'song', route_dir=self.directory / 'routes', options=self.options,
            dependency_fingerprint='frozen-recording-and-source', deadline_at=self.deadline)

    def test_failed_target_only_reaches_actual_gloss_translation_and_independent_guard(self):
        original = copy.deepcopy(self.data)
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), patch.object(library.pipeline.gemini, 'call', side_effect=self.provider):
            pre = self.execute(self.data); result = self.repair(pre)
        self.assertEqual(result['reader']['SONG_LINES']['one']['english'], '{0:mind}')
        self.assertEqual(result['reader']['SONG_LINES']['one']['words'], original['SONG_LINES']['one']['words'])
        self.assertEqual(result['reader']['SONG_LINES']['two'], original['SONG_LINES']['two'])
        self.assertEqual(result['reader']['SONG_TIMINGS'], original['SONG_TIMINGS'])
        self.assertEqual(self.target_populations, [['one'], ['one']])
        self.assertEqual(result['authorization']['confirmed_changes'], {'one': ['english']})
        self.assertNotEqual(pre['attempt_id'], result['post_review']['attempt_id'])
        self.assertEqual(self.data, original)
        actual_evidence = self.review_evidence[-1][0]['gloss']
        self.assertEqual(actual_evidence['word_glosses'], result['reader']['SONG_LINES']['one']['words'])
        self.assertEqual(actual_evidence['grammar_note'], result['reader']['SONG_LINES']['one'].get('grammarNote', ''))

    def test_actual_invalid_gloss_origin_routes_once_to_pro_before_translation(self):
        self.bad_flash_gloss = True
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), patch.object(library.pipeline.gemini, 'call', side_effect=self.provider) as transport:
            pre = self.execute(self.data); result = self.repair(pre)
        self.assertEqual(transport.call_count, 5)
        self.assertEqual(self.schemas, [(self.options.model, 'bhakti_translation_review'),
            (self.options.model, 'bhakti_word_glosses'), (self.options.pro_model, 'bhakti_word_glosses'),
            (self.options.pro_model, 'bhakti_literal_translation'), (self.options.pro_model, 'bhakti_translation_review')])
        self.assertEqual(result['authorization']['confirmed_changes'], {'one': ['english']})

    def test_null_gloss_containers_are_typed_at_actual_stage_boundary(self):
        for field in ('glosses', 'word_glosses'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                self.directory = Path(temporary)
                def malformed(model, key, prompt, **kwargs):
                    response = self.provider(model, key, prompt, **kwargs)
                    if model == self.options.model and kwargs['schema_name'] == 'bhakti_word_glosses':
                        if field == 'glosses': response['packet']['glosses'] = None
                        else: response['packet']['glosses'][0]['word_glosses'] = None
                    return response
                with patch.object(library.pipeline.gemini, 'key', return_value='unused'), patch.object(library.pipeline.gemini, 'call', side_effect=malformed) as transport:
                    pre = self.execute(self.data); result = self.repair(pre)
                self.assertEqual(transport.call_count, 5)
                self.assertEqual(result['authorization']['confirmed_changes'], {'one': ['english']})

    def test_both_models_rejected_keeps_evidence_without_candidate_and_cannot_retry(self):
        import bhakti_model_routes as routes
        self.reject_all_posts = True
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), patch.object(library.pipeline.gemini, 'call', side_effect=self.provider) as transport:
            pre = self.execute(self.data)
            with self.assertRaises(routes.UnitUnresolved): self.repair(pre)
            count = transport.call_count
            with self.assertRaises(routes.UnitUnresolved): self.repair(pre)
        self.assertEqual(count, 7); self.assertEqual(transport.call_count, count)
        states = [json.loads(path.read_text()) for path in (self.directory / 'routes').rglob('route-state.json')]
        failed = [state for state in states if state['unit_id'].endswith(':targeted-semantics')]
        self.assertEqual(len(failed), 1); self.assertEqual(failed[0]['status'], 'unresolved')
        self.assertEqual(len(failed[0]['attempts']), 2)
        self.assertFalse((self.directory / 'song/data.js').exists())

    def test_failed_independent_postreview_escalates_one_semantic_unit_not_source_or_good_lines(self):
        self.reject_flash_post = True
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), patch.object(library.pipeline.gemini, 'call', side_effect=self.provider) as transport:
            pre = self.execute(self.data); result = self.repair(pre); count = transport.call_count
            resumed = self.repair(pre)
        self.assertEqual(result, resumed); self.assertEqual(transport.call_count, count)
        self.assertEqual(count, 7)  # one current review + two three-call repair attempts
        self.assertEqual(set(model for model, _ in self.schemas), {self.options.model, self.options.pro_model})
        self.assertEqual(self.target_populations, [['one'], ['one'], ['one'], ['one']])
        self.assertEqual(result['authorization']['confirmed_changes'], {'one': ['english']})


if __name__ == '__main__': unittest.main()

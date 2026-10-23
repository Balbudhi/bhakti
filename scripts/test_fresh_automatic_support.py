"""Fresh-source automatic support through real routes/storage, canned provider only."""
import copy
import json
import os
from pathlib import Path
import shutil
import time
import unittest
from unittest.mock import patch

import bhakti_pipeline as pipeline
import bhakti_library_source_pass as source
import bhakti_model_routes as routes
import test_automatic_semantic_lexical as fixture


class FreshAutomaticSupportTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.AutomaticSemanticLexicalTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        c = self.case
        c.options.model = pipeline.MODEL
        c.options.pro_model = routes.PRO_MODEL
        retained = {**copy.deepcopy(c.lines[0]), 'id': 'q'}
        self.plan = {'lines': [retained, *copy.deepcopy(c.lines)], 'new_target_ids': ['v'],
                     'performance_order': [{'line_id': 'q', 'occurrence': 1}, {'line_id': 'v', 'occurrence': 1}],
                     'reuse_by_id': {'q': {'source': 'वज्र', 'roman': 'vajra', 'sourceLanguage': 'hi',
                         'english': '{0:OWNER ENGLISH}', 'words': [{'roman': 'vajra', 'gloss': 'OWNER GLOSS'}],
                         'sourceWords': [{'text': 'वज्र', 'wordIndices': [0]}]}}}
        self.route_dir = c.root / 'routes'
        self.original_plan = copy.deepcopy(self.plan)

    def run_target(self):
        return source.process_new_targets(self.case.song, self.plan, {'languages': ['Hindi']},
                                          self.case.options, self.route_dir, time.time() + 120)

    def test_actual_target_evidence_owner_context_and_cached_reconstruction(self):
        c = self.case
        first = self.run_target()
        self.assertEqual(c.kinds(), ['bhakti_word_glosses', 'bhakti_literal_translation', 'bhakti_translation_review'])
        self.assertNotIn('support_decisions', first['glosses']['packet']['glosses'][0])
        self.assertEqual(self.plan, self.original_plan)
        self.assertIn('OWNER ENGLISH', c.calls[-1]['prompt'])
        self.assertIn('OWNER GLOSS', c.calls[-1]['prompt'])
        for call in c.calls[1:]:
            packet = json.JSONDecoder().raw_decode(call['prompt'].split('TARGETED LEXICAL SUPPORT:\n', 1)[1])[0]
            self.assertEqual([t['line_id'] for t in packet['targets']], ['v'])
            self.assertIn('having the hardness of a diamond', call['prompt'])
        producer = pipeline.bhakti_lexical_producer
        with patch.object(producer, 'prepare_translation', wraps=producer.prepare_translation) as reconstruct:
            self.assertEqual(self.run_target(), first)
        self.assertGreater(reconstruct.call_count, 0, 'Accepted route must reconstruct current dictionary support.')
        self.assertEqual(len(c.calls), 3)
        self.assertEqual(self.plan, self.original_plan)
        self.assertFalse(hasattr(c.options, 'semantic_lexical_support'))

    def test_relocated_corpus_reuses_changed_english_only_regenerates_wording_review(self):
        c = self.case
        first = self.run_target()
        moved = c.root / 'relocated-wordnet'
        shutil.copytree(c.wn, moved)
        os.environ['BHAKTI_WORDNET_DIR'] = str(moved)
        self.assertEqual(self.run_target(), first)
        self.assertEqual(len(c.calls), 3)
        c.change_english_definition()
        second = self.run_target()
        self.assertEqual(c.kinds()[3:], ['bhakti_literal_translation', 'bhakti_translation_review'])
        self.assertEqual(second['glosses'], first['glosses'])
        self.assertIn('having the hardness of a crystal', c.calls[-1]['prompt'])
        self.assertEqual(self.plan, self.original_plan)
        count = len(c.calls)
        self.assertEqual(self.run_target(), second)
        self.assertEqual(len(c.calls), count)

    def test_accepted_missing_wording_decision_is_rejected_without_dispatch(self):
        c = self.case
        self.run_target()
        state_path = next(self.route_dir.rglob('route-state.json'))
        state = json.loads(state_path.read_text())
        result_path = state_path.parent / 'accepted-result.json'
        value = json.loads(result_path.read_text())
        value['translations']['packet']['translations'][0].pop('wording_decisions')
        result_path.write_text(json.dumps(value))
        state['accepted_sha256'] = routes._digest(value)
        state_path.write_text(json.dumps(state))
        with patch.object(pipeline.gemini, 'call', side_effect=AssertionError('Invalid acceptance must not dispatch.')):
            with self.assertRaisesRegex((ValueError, RuntimeError), 'decision|target|support'):
                self.run_target()
        self.assertEqual(len(c.calls), 3)

    def test_cached_english_evidence_corruption_is_checked_before_acceptance(self):
        c = self.case
        self.run_target()
        path = next((c.root / 'lookup-cache' / 'english').glob('*/*.json'))
        value = json.loads(path.read_text())
        value['evidence'][0]['gloss'] = 'Unwitnessed invented definition'
        path.write_text(json.dumps(value))
        with patch.object(pipeline.gemini, 'call', side_effect=AssertionError('Corrupt cache must not dispatch.')):
            with self.assertRaisesRegex((ValueError, RuntimeError), 'cache|content|identity'):
                self.run_target()
        self.assertEqual(len(c.calls), 3)

    def test_corrupt_corpus_fails_before_cached_acceptance_and_new_gloss(self):
        c = self.case
        self.run_target()
        path = c.wn / 'data.adj'
        original = path.read_bytes()
        path.write_bytes(original + b'\n')
        with self.assertRaisesRegex((ValueError, RuntimeError), 'hash|witness|WordNet'):
            self.run_target()
        self.assertEqual(len(c.calls), 3)
        path.write_bytes(original)
        self.run_target()
        self.assertEqual(len(c.calls), 3)

    def test_invalid_corpus_blocks_before_first_provider_dispatch(self):
        c = self.case
        path = c.wn / 'data.adj'
        path.write_bytes(path.read_bytes() + b'\n')
        with patch.object(pipeline.gemini, 'call', side_effect=AssertionError('Preflight must precede dispatch.')):
            with self.assertRaisesRegex((ValueError, RuntimeError), 'hash|witness|WordNet'):
                self.run_target()
        self.assertEqual(c.calls, [])

    def test_changed_producing_model_cannot_relabel_cached_glossary(self):
        c = self.case
        first = self.run_target()
        original = copy.deepcopy(first['glosses'])
        c.options.model = routes.PRO_MODEL
        second = self.run_target()
        self.assertEqual(c.kinds()[3:], ['bhakti_word_glosses', 'bhakti_literal_translation', 'bhakti_translation_review'])
        self.assertNotEqual(first['glosses']['fingerprint'], second['glosses']['fingerprint'])
        self.assertEqual(first['glosses'], original)

    def test_changed_owner_reading_context_invalidates_gloss_cache(self):
        c = self.case
        self.run_target()
        self.plan['reuse_by_id']['q']['english'] = '{0:DIFFERENT OWNER CONTEXT}'
        self.run_target()
        self.assertEqual(c.kinds()[3:], ['bhakti_word_glosses', 'bhakti_literal_translation', 'bhakti_translation_review'])
        self.assertIn('DIFFERENT OWNER CONTEXT', c.calls[-1]['prompt'])
        self.assertEqual(self.plan['reuse_by_id']['q']['english'], '{0:DIFFERENT OWNER CONTEXT}')


if __name__ == '__main__':
    unittest.main()

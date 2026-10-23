"""Lossless source evidence projection; no model-quality or audio claim."""
import copy
import json
from types import SimpleNamespace
import unittest

import bhakti_pipeline as pipeline


class SemanticSourceContextTests(unittest.TestCase):
    def setUp(self):
        self.lines = [
            {'id': 'one', 'source_text': 'वन', 'roman': 'vana', 'sourceLanguage': 'hi',
             'sourceWords': [{'text': 'वन', 'wordIndices': [0]}],
             'lexical_tokens': ['vana'], 'lexicalRegister': 'poetic',
             'performed_context': [{'after': [{'id': 'two', 'source_text': 'घर'}]}]},
            {'id': 'two', 'source_text': 'घर', 'roman': 'ghara',
             'performed_context': [{'before': [{'id': 'one', 'source_text': 'वन'}]}]},
        ]
        self.order = [{'ref': 'one', 'repeats': 2}, {'ref': 'two'}, {'ref': 'one'}]
        self.options = SimpleNamespace(semantic_full_source=self.lines,
                                       semantic_performance_order=self.order)

    def section(self, prompt, label):
        return json.JSONDecoder().raw_decode(prompt.split(label + '\n', 1)[1])[0]

    def test_source_projection_retains_fields_and_neighbor_relations_without_duplicate_text(self):
        original = copy.deepcopy(self.lines)
        prompt = pipeline.semantic_repair_prompt(self.options)
        actual = self.section(prompt, 'FULL AUDITED SOURCE CONTEXT (not additional output targets):')
        expected = copy.deepcopy(self.lines)
        expected[0]['performed_context'] = [{'after': [{'id': 'two'}]}]
        expected[1]['performed_context'] = [{'before': [{'id': 'one'}]}]
        self.assertEqual(actual, expected)
        self.assertEqual(self.lines, original)

    def test_exact_order_and_repetitions_survive_without_repeated_source_definitions(self):
        prompt = pipeline.semantic_repair_prompt(self.options)
        self.assertEqual(self.section(prompt, 'AUDITED PERFORMANCE ORDER:'), self.order)
        self.assertEqual(prompt.count('"source_text": "वन"'), 1)
        self.assertEqual(prompt.count('"source_text": "घर"'), 1)

    def test_unbound_or_variant_neighbor_is_not_lost(self):
        self.lines[0]['performed_context'][0]['after'].extend([
            {'id': 'missing', 'source_text': 'अन्य'},
            {'id': 'two', 'source_text': 'variant'},
        ])
        prompt = pipeline.semantic_repair_prompt(self.options)
        rows = self.section(prompt, 'FULL AUDITED SOURCE CONTEXT (not additional output targets):')
        self.assertEqual(rows[0]['performed_context'][0]['after'][1:],
                         self.lines[0]['performed_context'][0]['after'][1:])

    def test_feedback_and_prior_gloss_are_not_removed_by_source_projection(self):
        self.options.semantic_repair_feedback = [{'line_id': 'one', 'detail': 'Keep the forest image.'}]
        self.options.semantic_prior_gloss = [{'id': 'one', 'word_glosses': [{'gloss': 'forest'}]}]
        prompt = pipeline.semantic_repair_prompt(self.options)
        self.assertEqual(self.section(prompt, 'REPAIR FEEDBACK:'), self.options.semantic_repair_feedback)
        self.assertEqual(self.section(prompt, 'PRIOR TARGET/REFERENCED GLOSS EVIDENCE:'),
                         self.options.semantic_prior_gloss)


if __name__ == '__main__':
    unittest.main()

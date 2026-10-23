"""Retention controls: real wording validation/callers, synthetic linguistic judgments.

The fixture words are transport controls, not recommendations to retain them.
"""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bhakti_lexical_support as support
import bhakti_pipeline as pipeline
from test_lexical_support import fixture
import test_translation_cache_identity as cache_fixture


class ContextualRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        _, self.lines, _ = fixture(root)
        self.packet = support.build_support(root / 'manifest.json', self.lines, ['Sanskrit'])
        self.gloss = [{'id': 'p', 'word_glosses': [{'roman': 'pati', 'gloss': 'husband; consort'}],
            'support_decisions': [{'target_id': 'choice-p', 'used_evidence_ids': [],
                'role': 'background_only', 'reason': 'Structural test only.'}]}]
        self.draft = [{'id': 'p', 'literal_english': 'pati',
            'segments': [{'text': 'pati', 'word_indices': [0]}],
            'wording_decisions': [{'target_id': 'choice-p', 'chosen_candidate_id': None,
                'expression': 'pati', 'kind': 'retained_term', 'english_evidence_ids': [],
                'word_indices': [0], 'ordinary_paraphrase': 'husband; consort',
                'component_word_indices': [],
                'reason': 'Synthetic comparison for transport only; linguistic acceptance remains independent.'}]}]

    def test_explained_retention_preserves_source_indices_without_invented_english_entry(self):
        original = copy.deepcopy((self.packet, self.gloss, self.draft))
        self.assertEqual(support.support_decision_errors(self.packet, self.gloss, self.draft), [])
        self.assertEqual((self.packet, self.gloss, self.draft), original)
        schema = {'properties': {'translations': {'items': {'properties': {}}}}}
        kinds = support.extend_schema(schema, self.packet, 'translation')['properties']['translations']['items']['properties']['wording_decisions']['items']['properties']['kind']['enum']
        self.assertIn('retained_term', kinds)

    def test_retention_requires_explanation_paraphrase_and_exact_source_spelling(self):
        for mutation in ['empty_gloss', 'repeated_gloss', 'empty_paraphrase', 'repeated_paraphrase', 'foreign_expression', 'invented_candidate']:
            with self.subTest(mutation=mutation):
                gloss, draft = copy.deepcopy(self.gloss), copy.deepcopy(self.draft)
                decision = draft[0]['wording_decisions'][0]
                if mutation == 'empty_gloss': gloss[0]['word_glosses'][0]['gloss'] = ''
                if mutation == 'repeated_gloss': gloss[0]['word_glosses'][0]['gloss'] = 'pati'
                if mutation == 'empty_paraphrase': decision['ordinary_paraphrase'] = ''
                if mutation == 'repeated_paraphrase': decision['ordinary_paraphrase'] = 'pati'
                if mutation == 'foreign_expression':
                    decision['expression'] = 'jīva'
                    draft[0]['literal_english'] = 'jīva'; draft[0]['segments'][0]['text'] = 'jīva'
                if mutation == 'invented_candidate': decision['chosen_candidate_id'] = 'c-governable'
                self.assertTrue(support.support_decision_errors(self.packet, gloss, draft))

    def caller(self):
        case = cache_fixture.TranslationCacheIdentityTests()
        case.setUp(); self.addCleanup(case.doCleanups)
        case.lines[0].update(source_text='माया', roman='māyā', sourceLanguage='sa')
        case.audited['packet']['metadata'] = {'languages': ['Sanskrit']}
        gloss = {'packet': {'glosses': case.rows(case.lines)}}
        gloss['packet']['glosses'][0]['word_glosses'][0]['gloss'] = 'worldly appearance and attachment'
        original = case.provider
        def provider(model, key, prompt, **kwargs):
            result = original(model, key, prompt, **kwargs)
            if kwargs['schema_name'] == 'bhakti_literal_translation':
                row = result['packet']['translations'][0]
                row.update(literal_english='māyā', segments=[{'text': 'māyā', 'word_indices': [0]}],
                    choice_note='Synthetic retention comparison; explains limits of worldly appearance for this fixture.')
            return result
        mock = patch.object(pipeline.gemini, 'call', side_effect=provider)
        mock.start(); self.addCleanup(mock.stop)
        return case, gloss

    def test_real_writer_and_reviewer_receive_retention_with_meaning_first_gloss(self):
        case, gloss = self.caller()
        output = case.translate(gloss)
        self.assertEqual(output['packet']['translations'][0]['literal_english'], 'māyā')
        prompt = case.calls[-1][1]
        self.assertNotIn('Retain a concept in IAST only when explicitly supplied locked English', prompt)
        self.assertIn('choice_note', prompt)
        args = pipeline.independently_review_translations.call_args.args
        self.assertEqual(args[3][0]['literal_english'], 'māyā')
        self.assertEqual(args[2][0]['word_glosses'][0]['gloss'], 'worldly appearance and attachment')
        self.assertFalse(args[2][0]['word_glosses'][0]['preserve_in_english'])

    def test_retention_does_not_bypass_failed_independent_review(self):
        case, gloss = self.caller()
        def reject(*args, **kwargs):
            rows, packets = case.review(*args, **kwargs)
            rows[0].update(passes=False, human_review_recommended=True)
            return rows, packets
        with patch.object(pipeline, 'independently_review_translations', side_effect=reject):
            with self.assertRaisesRegex(RuntimeError, 'fresh contract'):
                case.translate(gloss)
        self.assertFalse((case.song / '.transcription/pipeline/05-translation.json').exists())


if __name__ == '__main__':
    unittest.main()

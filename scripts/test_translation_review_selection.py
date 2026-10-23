"""Select semantic review records by explicit IDs, never by response position."""
import argparse
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import bhakti_pipeline as pipeline

FIXTURE = Path(__file__).parent / 'fixtures/rehna-overcomplete-review.json'

class TranslationReviewSelectionTests(unittest.TestCase):
    def setUp(self):
        self.actual = json.loads(FIXTURE.read_text())
        self.rows = self.actual['packet']['reviews']
        self.targets = self.actual['target_ids']
        self.context = self.actual['context_ids']

    def select(self, rows=None, targets=None):
        return pipeline.select_translation_review_rows(
            self.rows if rows is None else rows,
            self.targets if targets is None else targets, self.context)

    def test_actual_known_extra_row_is_excluded_without_editing_raw_or_flags(self):
        original = copy.deepcopy(self.rows)
        selected = self.select()
        self.assertEqual([r['id'] for r in selected], self.targets)
        self.assertEqual(selected, self.rows[:10])
        self.assertEqual(self.rows, original)
        self.assertEqual(len(self.rows), 11)
        self.assertTrue(all(r['material_choice'] == 'None' for r in selected))

    def test_reordered_exact_target_rows_are_selected_by_id(self):
        self.assertEqual(self.select(list(reversed(self.rows[:10]))), self.rows[:10])

    def test_missing_target_is_rejected_even_with_extra_context(self):
        with self.assertRaises(ValueError): self.select(self.rows[1:])

    def test_duplicate_target_and_duplicate_context_are_rejected(self):
        for row in (self.rows[0], self.rows[-1]):
            with self.subTest(id=row['id']), self.assertRaises(ValueError):
                self.select(self.rows + [copy.deepcopy(row)])

    def test_unknown_id_is_not_silently_discarded(self):
        with self.assertRaises(ValueError): self.select(self.rows + [{'id': 'invented'}])

    def test_malformed_rows_or_ids_are_rejected(self):
        for row in (None, [], {}, {'id': ''}, {'id': None}, {'id': []}):
            with self.subTest(row=row), self.assertRaises(ValueError): self.select(self.rows + [row])
        with self.assertRaises(ValueError): self.select({'reviews': self.rows})

    def test_duplicate_requested_id_is_rejected(self):
        with self.assertRaises(ValueError): self.select(targets=self.targets + [self.targets[0]])

    def run_actual_caller(self, directory, provider, *, all_context=False):
        evidence = copy.deepcopy(self.actual['target_evidence'])
        if all_context:
            source = self.actual['source_context'][-1]
            evidence.append({'source': source, 'gloss': {'id': source['id'], 'word_glosses': []},
                             'draft': {'id': source['id'], 'literal_english': 'Instrumental outro'}})
        options = argparse.Namespace(model=self.actual['model'], force=False, timeout=1,
                                     semantic_full_source=self.actual['source_context'])
        with patch.object(pipeline.gemini, 'key', return_value='test-not-a-key'), \
             patch.object(pipeline.gemini, 'call', side_effect=provider), \
             patch.object(pipeline, 'translation_policy_payload', return_value={}), \
             patch.object(pipeline.bhakti_translation_policy, 'guidance', return_value='offline test'):
            return pipeline.independently_review_translations(
                directory, [r['source'] for r in evidence], [r['gloss'] for r in evidence],
                [r['draft'] for r in evidence], '(none supplied)', options, languages=['Hindi'])

    def test_real_caller_preserves_full_response_and_explicit_targets(self):
        raw = {'packet': copy.deepcopy(self.actual['packet']), 'usage': self.actual['usage']}
        prompts = []
        def provider(model, key, prompt, **kwargs):
            prompts.append(prompt)
            return raw
        with tempfile.TemporaryDirectory() as temporary:
            song = Path(temporary)
            reviews, packets = self.run_actual_caller(song, provider)
            self.assertEqual(reviews, self.rows[:10])
            self.assertEqual(raw['packet']['reviews'], self.rows)
            candidate = json.loads((song / '.transcription/pipeline/translation-review-batches/candidate-0.json').read_text())
            self.assertEqual(candidate, raw)
            self.assertEqual(packets[0]['response']['review_selection']['excluded_context_ids'], ['outro-instrumental'])
            marker = 'OUTPUT TARGET IDS (return exactly these, once each):\n'
            self.assertIn(marker, prompts[0])
            self.assertEqual(json.JSONDecoder().raw_decode(prompts[0].split(marker, 1)[1])[0], self.targets)
            with patch.object(pipeline.gemini, 'call', side_effect=AssertionError('no paid replay')):
                # Nested helper patches call too, so its provider independently fails.
                cached, _ = self.run_actual_caller(song, lambda *a, **k: self.fail('cache dispatched'))
            self.assertEqual(cached, reviews)

    def test_cached_parent_cannot_bypass_missing_or_duplicate_id_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            song = Path(temporary)
            self.run_actual_caller(song, lambda *a, **k: {'packet': copy.deepcopy(self.actual['packet'])})
            path = song / '.transcription/pipeline/translation-review-batches/batch-000.json'
            original = json.loads(path.read_text())
            for rows in (self.rows[1:10], self.rows[:10] + [self.rows[0]]):
                changed = copy.deepcopy(original); changed['response']['packet']['reviews'] = rows
                path.write_text(json.dumps(changed))
                with self.subTest(count=len(rows)), self.assertRaises((RuntimeError, ValueError)):
                    self.run_actual_caller(song, lambda *a, **k: self.fail('invalid cache dispatched'))

    def test_cached_child_is_validated_before_merging_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            song = Path(temporary)
            reviews, _ = self.run_actual_caller(song, lambda *a, **k: {
                'packet': copy.deepcopy(self.actual['packet'])}, all_context=True)
            self.assertEqual(reviews, self.rows)
            cache = song / '.transcription/pipeline/translation-review-batches'
            (cache / 'batch-000.json').unlink()
            child = cache / 'batch-000-00.json'
            value = json.loads(child.read_text())
            value['response']['packet']['reviews'].append(copy.deepcopy(self.rows[0]))
            child.write_text(json.dumps(value))
            with self.assertRaises((RuntimeError, ValueError)):
                self.run_actual_caller(song, lambda *a, **k: self.fail('invalid child dispatched'), all_context=True)

if __name__ == '__main__': unittest.main()

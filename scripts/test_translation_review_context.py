"""Review requests retain source neighbors across cached parent/child boundaries."""
from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bhakti_pipeline as pipeline


class TranslationReviewContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.song = Path(self.temp.name)
        self.lines = [{'id': f'line-{i}', 'source_text': f'neighbor source {i}',
                       'roman': f'token{i}', 'kind': 'verse'} for i in range(25)]
        self.calls = []
        self.options = argparse.Namespace(model='test-model', force=False, timeout=1)
        for target in [
            patch.object(pipeline, 'translation_policy_payload', return_value={}),
            patch.object(pipeline.gemini, 'key', return_value='test-only'),
            patch.object(pipeline.gemini, 'call', side_effect=self.provider),
        ]:
            target.start()
            self.addCleanup(target.stop)

    def provider(self, model, key, prompt, **kwargs):
        evidence = json.JSONDecoder().raw_decode(prompt.split('EVIDENCE:\n', 1)[1].lstrip())[0]
        self.calls.append({'ids': [r['source']['id'] for r in evidence], 'prompt': prompt})
        return {'packet': {'reviews': [{'id': row['source']['id'], 'passes': True}
                                       for row in evidence]}}

    def run_review(self):
        glosses = [{'id': line['id'], 'word_glosses': [], 'semantic_frame': {'agent': 'draft claim'}}
                   for line in self.lines]
        translations = [{'id': line['id'], 'literal_english': 'draft'} for line in self.lines]
        return pipeline.independently_review_translations(
            self.song, self.lines, glosses, translations, '(none supplied)', self.options,
        )

    def context(self, call):
        marker = 'ENGLISH READING CONTEXT (context only; target obligations unchanged):\n'
        self.assertIn(marker, call['prompt'])
        reading = json.JSONDecoder().raw_decode(call['prompt'].split(marker, 1)[1].lstrip())[0]
        return [row['source'] for row in reading['context_rows']]

    def test_each_child_and_direct_request_has_its_actual_adjacent_source(self):
        reviews, _ = self.run_review()
        self.assertEqual([r['id'] for r in reviews], [line['id'] for line in self.lines])
        calls = {c['ids'][0]: c for c in self.calls}
        expected = {'line-0': [10, 11, 12], 'line-10': [7, 8, 9, 20, 21, 22], 'line-20': [17, 18, 19]}
        self.assertEqual(set(calls), set(expected))
        for first, positions in expected.items():
            self.assertEqual(self.context(calls[first]), [self.lines[i] for i in positions])
            self.assertTrue(set(calls[first]['ids']).isdisjoint(x['id'] for x in self.context(calls[first])))
        prompt = calls['line-10']['prompt']
        self.assertIn('derive agency and grammatical attachment from the source', prompt)
        self.assertIn('before comparing the supplied semantic frame', prompt)
        self.assertIn('uncertainty', prompt)
        self.assertIn('merely repeats', prompt)
        self.assertIn('unsupported claims in the frame', prompt)

    def test_changed_child_neighbor_invalidates_child_but_reuses_unaffected_parent(self):
        self.run_review()
        self.calls.clear()
        self.run_review()
        self.assertEqual(self.calls, [])
        self.lines[10]['source_text'] = 'corrected neighboring subject'
        self.run_review()
        self.assertEqual({c['ids'][0] for c in self.calls}, {'line-0', 'line-10'})
        self.assertEqual(self.context(next(c for c in self.calls if c['ids'][0] == 'line-0'))[0],
                         self.lines[10])

    def test_changed_parent_neighbor_invalidates_direct_request_and_target_child_only(self):
        self.run_review()
        self.calls.clear()
        self.lines[19]['source_text'] = 'corrected previous antecedent'
        self.run_review()
        self.assertEqual({c['ids'][0] for c in self.calls}, {'line-10', 'line-20'})
        direct = next(c for c in self.calls if c['ids'][0] == 'line-20')
        self.assertEqual(self.context(direct), self.lines[17:20])

    def test_short_song_has_explicit_empty_context_and_target_ids_only(self):
        self.lines = self.lines[:2]
        reviews, _ = self.run_review()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.context(self.calls[0]), [])
        self.assertEqual([r['id'] for r in reviews], ['line-0', 'line-1'])


if __name__ == '__main__':
    unittest.main()

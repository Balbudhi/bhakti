"""Existing-reader repair uses production text stages and never publishes."""
import argparse
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bhakti_pipeline as pipeline
import retranslate_bhakti as repair


class ExistingReaderRepairTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.song = self.root / 'songs' / 'sample'
        self.song.mkdir(parents=True)
        (self.root / 'data').mkdir()
        self.baselines = {'version': 1, 'songs': {}}
        self.write_baselines()
        self.reader = {
            'SONG_META': {'title': 'Keep title', 'languages': ['Hindi'], 'audioSources': ['audio.m4a']},
            'SONG_LINES': {
                'a': {'source': 'मन', 'roman': 'man', 'english': '{0:Old mind}',
                      'words': [{'roman': 'man', 'gloss': 'old'}],
                      'sourceWords': [{'text': 'मन', 'wordIndices': [0]}]},
                'b': {'source': 'राम', 'roman': 'rāma', 'english': '{0:Old name}',
                      'words': [{'roman': 'rāma', 'gloss': 'old'}],
                      'sourceWords': [{'text': 'राम', 'wordIndices': [0]}]},
            },
            'SONG_SEQUENCE': [{'ref': 'b', 'section': 'refrain'}, {'ref': 'a', 'section': 'verse'},
                              {'ref': 'b', 'section': 'refrain'}],
            'SONG_TIMINGS': [{'start': 0, 'end': 2}, {'start': 2, 'end': 4}, {'start': 4, 'end': 6}],
        }
        self.write_reader()
        self.options = argparse.Namespace(model=pipeline.MODEL, timeout=10, reuse_glosses=False)
        self.calls = []
        self.english = {'a': 'Mind', 'b': 'Rāma'}
        self.review_passes = True
        for target, name, kwargs in [
            (repair, 'ROOT', {'new': self.root}),
            (pipeline.gemini, 'key', {'return_value': 'not-a-key'}),
            (pipeline.gemini, 'call', {'side_effect': self.provider}),
        ]:
            p = patch.object(target, name, **kwargs)
            p.start(); self.addCleanup(p.stop)

    def write_baselines(self):
        (self.root / 'data' / 'editorial_baselines.json').write_text(json.dumps(self.baselines))

    def write_reader(self):
        self.path = self.song / 'data.js'
        self.path.write_text('\n'.join('window.' + key + ' = ' + json.dumps(value, ensure_ascii=False) + ';'
                                      for key, value in self.reader.items()))

    def provider(self, model, key, prompt, **kwargs):
        schema = kwargs['schema_name']
        self.calls.append((schema, prompt))
        if schema == 'bhakti_translation_review':
            rows = json.JSONDecoder().raw_decode(prompt.split('EVIDENCE:\n', 1)[1].lstrip())[0]
            return {'packet': {'reviews': [{
                'id': row['source']['id'], 'passes': self.review_passes,
                'human_review_recommended': False, 'agency_preserved': self.review_passes,
                'imagery_preserved': True, 'all_meaning_accounted_for': True,
                'unsupported_additions': [], 'material_choice': '', 'reason': 'Source checked',
            } for row in rows]}}
        is_gloss = 'word_gloss' in schema
        marker = ('TARGET LYRICS (return these IDs only):\n' if is_gloss else
                  'TARGET audited source lines (return these IDs only):\n')
        lines = json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1].lstrip())[0]
        if is_gloss:
            return {'packet': {'glosses': [{
                'id': line['id'], 'word_glosses': [{'roman': token, 'gloss': 'contextual meaning',
                    'concept_key': '', 'preserve_in_english': False} for token in line['roman'].split()],
                'semantic_frame': {field: '' for field in pipeline.SEMANTIC_FRAME_FIELDS},
                'grammar_note': 'Reviewed syntax', 'uncertainty': '',
            } for line in lines]}}
        return {'packet': {'translations': [{
            'id': line['id'], 'literal_english': self.english[line['id']],
            'segments': [{'text': self.english[line['id']], 'word_indices': [0]}],
            'fidelity': {'agency_and_image_preserved': True, 'all_meaning_accounted_for': True,
                         'unsupported_additions': []},
            'human_review_recommended': False, 'material_alternatives': [],
            'choice_note': '', 'uncertainty': '',
        } for line in lines], 'comparison': []}}

    def report(self):
        path = self.song / '.transcription' / 'translation-review-gloss-first' / 'review.json'
        return json.loads(path.read_text())

    def test_real_entrypoint_runs_shared_policy_frames_and_independent_review_privately(self):
        public = self.path.read_bytes()
        result = repair.run_slug('sample', self.options)
        self.assertEqual(result['status'], 'review-required')
        self.assertEqual([name for name, _ in self.calls], [
            'bhakti_word_glosses', 'bhakti_literal_translation', 'bhakti_translation_review'])
        report = self.report()
        self.assertEqual([line['id'] for line in report['source_lines']], ['b', 'a'])
        self.assertTrue(report['translations']['packet']['translations'][0]['independent_review']['passes'])
        self.assertIn('hi.man.mind', self.calls[0][1])
        self.assertIn('semantic_frame', self.calls[0][1])
        self.assertIn('No human translation is supplied', self.calls[1][1])
        candidate = report['candidate_reader']
        for key in ['SONG_META', 'SONG_SEQUENCE', 'SONG_TIMINGS']:
            self.assertEqual(candidate[key], self.reader[key])
        for line_id, line in candidate['SONG_LINES'].items():
            for key in ['source', 'roman', 'sourceWords']:
                self.assertEqual(line[key], self.reader['SONG_LINES'][line_id][key])
            self.assertEqual(line['english'], '{0:' + self.english[line_id] + '}')
        self.assertEqual(self.path.read_bytes(), public)
        self.assertFalse((self.song / '.transcription' / 'pipeline').exists())

    def test_reuse_validates_real_disk_cache_and_changed_source_invalidates(self):
        repair.run_slug('sample', self.options)
        self.options.reuse_glosses = True
        self.calls.clear()
        repair.run_slug('sample', self.options)
        self.assertFalse(any('word_gloss' in name for name, _ in self.calls))
        self.reader['SONG_LINES']['a']['source'] = 'मन्'
        self.reader['SONG_LINES']['a']['sourceWords'][0]['text'] = 'मन्'
        self.write_reader()
        self.calls.clear()
        repair.run_slug('sample', self.options)
        self.assertTrue(any('word_gloss' in name and 'मन्' in prompt for name, prompt in self.calls))

    def test_legacy_review_is_never_reused_as_gloss_evidence(self):
        path = self.song / '.transcription' / 'translation-review-gloss-first' / 'review.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'glosses': {'packet': {'glosses': []}}}))
        self.options.reuse_glosses = True
        repair.run_slug('sample', self.options)
        self.assertTrue(any('word_gloss' in name for name, _ in self.calls))

    def test_policy_revision_invalidates_reused_glosses(self):
        repair.run_slug('sample', self.options)
        self.options.reuse_glosses = True
        policy = copy.deepcopy(pipeline.translation_policy_payload())
        policy['test_revision'] = 2
        self.calls.clear()
        with patch.object(pipeline, 'translation_policy_payload', return_value=policy):
            repair.run_slug('sample', self.options)
        self.assertTrue(any('word_gloss' in name for name, _ in self.calls))

    def test_saved_owner_baseline_is_supplied_not_current_reader_wording(self):
        self.baselines['songs']['sample'] = {'policy': 'preserve_english', 'englishSha256': '0' * 64,
                                          'plainEnglishByLine': self.english.copy()}
        self.write_baselines()
        repair.run_slug('sample', self.options)
        self.assertIn('A human translation is supplied and LOCKED', self.calls[1][1])
        baseline = self.calls[1][1].split('Supplied translation:\n', 1)[1]
        self.assertIn('Mind', baseline)
        self.assertNotIn('Old mind', baseline)
        self.english['a'] = 'Changed owner wording'
        self.options.reuse_glosses = True
        with self.assertRaisesRegex(RuntimeError, 'owner-designated English changed'):
            repair.run_slug('sample', self.options)

    def test_failed_independent_review_never_emits_candidate(self):
        self.review_passes = False
        public = self.path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'independent'):
            repair.run_slug('sample', self.options)
        self.assertEqual(self.report()['status'], 'blocked')
        self.assertNotIn('candidate_reader', self.report())
        self.assertEqual(self.path.read_bytes(), public)

    def test_failed_rerun_replaces_old_success_with_blocked_status(self):
        repair.run_slug('sample', self.options)
        self.review_passes = False
        with self.assertRaisesRegex(RuntimeError, 'independent'):
            repair.run_slug('sample', self.options)
        self.assertEqual(self.report()['status'], 'blocked')
        self.assertNotIn('candidate_reader', self.report())

    def test_missing_reader_rerun_invalidates_previous_success(self):
        repair.run_slug('sample', self.options)
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            repair.run_slug('sample', self.options)
        self.assertEqual(self.report()['status'], 'blocked')
        self.assertIsNone(self.report()['reader_sha256'])
        self.assertNotIn('candidate_reader', self.report())

    def test_corrupt_existing_source_map_is_held_before_calls(self):
        for mapping in ([{'text': 'मन', 'wordIndices': [9]}],
                        [{'text': 'wrong', 'wordIndices': [0]}]):
            with self.subTest(mapping=mapping):
                self.reader['SONG_LINES']['a']['sourceWords'] = mapping
                self.write_reader()
                with self.assertRaisesRegex(RuntimeError, 'sourceWords'):
                    repair.run_slug('sample', self.options)
                self.assertEqual(self.calls, [])

    def test_comparison_covers_all_lines_without_model_comparison(self):
        repair.run_slug('sample', self.options)
        rows = self.report()['comparison']
        self.assertEqual([row['id'] for row in rows], ['b', 'a'])
        self.assertEqual(rows[1]['published'], 'Old mind')
        self.assertEqual(rows[1]['proposed'], 'Mind')
        self.assertTrue(rows[1]['changed'])

    def test_explicit_human_translation_metadata_is_locked(self):
        self.reader['SONG_META']['humanTranslation'] = self.english.copy()
        self.write_reader()
        repair.run_slug('sample', self.options)
        self.assertIn('A human translation is supplied and LOCKED', self.calls[1][1])
        self.english['a'] = 'Changed wording'
        with self.assertRaisesRegex(RuntimeError, 'owner-designated English changed'):
            repair.run_slug('sample', self.options)

    def test_supplied_poem_assigns_complete_lines_and_cannot_swap_them(self):
        self.reader['SONG_META']['providedTranslation'] = 'Rāma\nMind'
        self.write_reader()
        repair.run_slug('sample', self.options)
        self.english = {'a': 'Rāma', 'b': 'Mind'}
        with self.assertRaisesRegex(RuntimeError, 'owner-designated English changed'):
            repair.run_slug('sample', self.options)

    def test_unaligned_supplied_poem_is_held_before_calls(self):
        self.reader['SONG_META']['providedTranslation'] = 'A poem with no recoverable line boundaries'
        self.write_reader()
        with self.assertRaisesRegex(RuntimeError, 'line-ID mapping'):
            repair.run_slug('sample', self.options)
        self.assertEqual(self.calls, [])

    def test_source_changed_during_review_cannot_emit_current_candidate(self):
        original_provider = self.provider
        def concurrent_change(*args, **kwargs):
            result = original_provider(*args, **kwargs)
            if kwargs['schema_name'] == 'bhakti_translation_review':
                self.path.write_text(self.path.read_text() + '\n// concurrent change\n')
            return result
        with patch.object(pipeline.gemini, 'call', side_effect=concurrent_change):
            with self.assertRaisesRegex(RuntimeError, 'reader changed during review'):
                repair.run_slug('sample', self.options)
        self.assertEqual(self.report()['status'], 'blocked')
        self.assertNotIn('candidate_reader', self.report())

    def test_incompatible_existing_word_map_is_held_before_paid_work(self):
        self.reader['SONG_LINES']['a']['words'] = [{'roman': 'ma', 'gloss': 'x'}, {'roman': 'n', 'gloss': 'y'}]
        self.write_reader()
        with self.assertRaisesRegex(RuntimeError, 'word map'):
            repair.run_slug('sample', self.options)
        self.assertEqual(self.calls, [])

    def test_refrain_context_preserves_each_distinct_performed_neighbor(self):
        repair.run_slug('sample', self.options)
        b = self.report()['source_lines'][0]
        self.assertEqual(b['performed_context'], [
            {'before': [], 'after': [{'id': 'a', 'source_text': 'मन', 'roman': 'man'},
                                      {'id': 'b', 'source_text': 'राम', 'roman': 'rāma'}]},
            {'before': [{'id': 'b', 'source_text': 'राम', 'roman': 'rāma'},
                        {'id': 'a', 'source_text': 'मन', 'roman': 'man'}], 'after': []},
        ])


if __name__ == '__main__':
    unittest.main()

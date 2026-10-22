"""Cache regressions: real JSON persistence, only provider calls replaced."""
import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import bhakti_pipeline as pipeline
from test_sense_decisions import decisions_for

REAL_REVIEW = pipeline.independently_review_translations


class TranslationCacheIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.song = Path(self.temp.name)
        self.options = argparse.Namespace(model='google/test-model', force=False, timeout=1,
                                          gloss_batch_size=3, gloss_workers=1, max_attempts=1)
        self.lines = [{'id': 'line-0', 'source_text': 'ਪ੍ਰੇਮ', 'roman': 'prema', 'kind': 'verse'}]
        self.audited = {'packet': {'verified_lines': self.lines}}
        self.calls = []
        self.policy = {'registry': 'one'}
        self.start_patch('translation_policy_payload', side_effect=lambda: self.policy, create=True)
        self.start_patch('supplied_translation', wraps=pipeline.supplied_translation)
        key_patch = patch.object(pipeline.gemini, 'key', return_value='test-placeholder')
        key_patch.start(); self.addCleanup(key_patch.stop)
        call_patch = patch.object(pipeline.gemini, 'call', side_effect=self.provider)
        call_patch.start(); self.addCleanup(call_patch.stop)
        self.start_patch('independently_review_translations', side_effect=self.review)

    def start_patch(self, name, **kwargs):
        p = patch.object(pipeline, name, **kwargs)
        value = p.start(); self.addCleanup(p.stop)
        return value

    def rows(self, lines):
        decisions = decisions_for(lines, self.audited.get('packet', {}).get('metadata', {}).get('languages'))
        return [{'id': line['id'], 'word_glosses': [
                    {'roman': token, 'gloss': 'contextual meaning', 'concept_key': '', 'preserve_in_english': False}
                    for token in line['roman'].split()],
                 'semantic_frame': {key: '' for key in pipeline.SEMANTIC_FRAME_FIELDS},
                 'grammar_note': '', 'uncertainty': '',
                 'sense_decisions': decisions[line['id']]} for line in lines]

    def provider(self, model, key, prompt, **kwargs):
        self.calls.append((kwargs['schema_name'], prompt))
        if kwargs['schema_name'] == 'bhakti_translation_review':
            evidence = json.JSONDecoder().raw_decode(prompt.split('EVIDENCE:\n', 1)[1].lstrip())[0]
            return {'packet': {'reviews': self.review(None, [row['source'] for row in evidence],
                                                     None, None, None, None)[0]}}
        is_gloss = 'word_gloss' in kwargs['schema_name']
        marker = ('TARGET LYRICS (return these IDs only):\n' if is_gloss else
                  'TARGET audited source lines (return these IDs only):\n')
        lines = json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1].lstrip())[0]
        if is_gloss:
            return {'packet': {'glosses': self.rows(lines)}}
        translations = [{'id': line['id'], 'literal_english': 'meaning',
                         'segments': [{'text': 'meaning', 'word_indices': list(range(len(line['roman'].split())))}],
                         'human_review_recommended': False, 'material_alternatives': [], 'choice_note': '',
                         'uncertainty': '', 'fidelity': {'agency_and_image_preserved': True,
                             'all_meaning_accounted_for': True, 'unsupported_additions': []}} for line in lines]
        return {'packet': {'translations': translations, 'comparison': [{'id': line['id']} for line in lines]}}

    @staticmethod
    def review(song_dir, lines, glosses, translations, baseline, options, languages=None):
        return ([{'id': line['id'], 'passes': True, 'agency_preserved': True,
                  'imagery_preserved': True, 'all_meaning_accounted_for': True,
                  'unsupported_additions': [], 'human_review_recommended': False} for line in lines], [])

    def gloss(self):
        return pipeline.gloss(self.song, self.audited, self.options)

    def translate(self, glosses=None, job=None):
        return pipeline.translate(self.song, self.audited,
                                  glosses or {'packet': {'glosses': self.rows(self.lines)}},
                                  job or {}, self.options)

    def test_unchanged_gloss_and_translation_hit_real_disk_caches(self):
        glosses = self.gloss(); first = self.translate(glosses)
        count = len(self.calls)
        self.assertEqual(self.gloss(), glosses)
        self.assertEqual(self.translate(glosses), first)
        self.assertEqual(len(self.calls), count)

    def test_same_id_and_token_count_source_change_invalidates_both_stages(self):
        self.gloss(); self.translate()
        self.lines[0].update(source_text='ਪ੍ਰਿਅ', roman='pria')
        before = len(self.calls)
        glosses = self.gloss(); self.translate(glosses)
        self.assertEqual(len(self.calls), before + 2)
        self.assertEqual(glosses['packet']['glosses'][0]['word_glosses'][0]['roman'], 'pria')

    def test_changed_gloss_and_frame_invalidate_translation(self):
        glosses = {'packet': {'glosses': self.rows(self.lines)}}
        self.translate(glosses)
        for mutate in [lambda: glosses['packet']['glosses'][0]['word_glosses'][0].update(gloss='beloved'),
                       lambda: glosses['packet']['glosses'][0]['semantic_frame'].update(agent='the Guru')]:
            before = len(self.calls); mutate(); self.translate(glosses)
            self.assertEqual(len(self.calls), before + 1)

    def test_locked_baseline_file_content_invalidation(self):
        baseline = self.song / 'human.txt'; baseline.write_text('First wording')
        job = {'providedTranslation': str(baseline)}
        self.translate(job=job); before = len(self.calls)
        baseline.write_text('Second wording')
        self.translate(job=job)
        self.assertEqual(len(self.calls), before + 1)

    def test_model_and_policy_invalidate_both_stages(self):
        self.gloss(); self.translate()
        for mutate in [lambda: setattr(self.options, 'model', 'google/other-model'),
                       lambda: self.policy.update(registry='two')]:
            before = len(self.calls); mutate(); self.gloss(); self.translate()
            self.assertEqual(len(self.calls), before + 2)

    def test_fingerprintless_legacy_cache_is_not_certified(self):
        self.gloss(); self.translate()
        for name in ['04-glosses.json', '05-translation.json']:
            path = self.song / '.transcription' / 'pipeline' / name
            data = json.loads(path.read_text()); data.pop('fingerprint', None)
            path.write_text(json.dumps(data))
        before = len(self.calls); self.gloss(); self.translate()
        self.assertEqual(len(self.calls), before + 2)

    def test_normalization_never_relabels_a_changed_surface(self):
        old = self.rows(self.lines)
        changed = [dict(self.lines[0], roman='pria')]
        normalized = pipeline.normalize_gloss_rows(changed, old)
        self.assertEqual(normalized[0]['word_glosses'][0]['roman'], 'prema')
        self.assertTrue(pipeline.gloss_surface_errors(changed, normalized))
        self.assertEqual(old[0]['word_glosses'][0]['roman'], 'prema')

    def test_missing_and_reordered_tokens_fail_even_when_substrings_map(self):
        lines = [dict(self.lines[0], roman='prema pria')]
        self.assertTrue(pipeline.gloss_surface_errors(lines, self.rows(self.lines)))
        wrong = self.rows([dict(self.lines[0], roman='pria prema')])
        self.assertTrue(pipeline.gloss_surface_errors(lines, wrong))

    def set_long_song(self):
        self.lines[:] = [{'id': f'line-{i}', 'source_text': f'ਪ੍ਰੇਮ {i}', 'roman': f'prema {i}', 'kind': 'verse'}
                         for i in range(85)]

    def test_custom_gloss_batch_context_uses_actual_start(self):
        self.set_long_song(); self.gloss()
        prompt = next(prompt for _, prompt in self.calls if '"id": "line-3"' in prompt.split(
            'TARGET LYRICS (return these IDs only):\n', 1)[1].split('NEARBY CONTEXT', 1)[0])
        context = json.JSONDecoder().raw_decode(prompt.split(
            'NEARBY CONTEXT (do not return these IDs unless also targets):\n', 1)[1].lstrip())[0]
        self.assertEqual([line['id'] for line in context], ['line-1', 'line-2', 'line-6', 'line-7'])

    def test_wrong_surface_provider_response_is_rejected_not_relabelled(self):
        self.lines[0].update(source_text='ਪ੍ਰਿਅ', roman='pria')
        wrong = {'packet': {'glosses': self.rows([dict(self.lines[0], roman='prema')])}}
        with patch.object(pipeline.gemini, 'call', return_value=wrong):
            with self.assertRaisesRegex(RuntimeError, 'source contract'):
                self.gloss()
        self.assertFalse((self.song / '.transcription' / 'pipeline' / '04-glosses.json').exists())

    def test_neighbor_change_invalidates_affected_gloss_batch(self):
        self.set_long_song(); self.gloss(); before = len(self.calls)
        self.lines[2].update(source_text='ਪ੍ਰਿਅ 2', roman='pria 2')
        self.gloss()
        targets = []
        for _, prompt in self.calls[before:]:
            batch = json.JSONDecoder().raw_decode(prompt.split(
                'TARGET LYRICS (return these IDs only):\n', 1)[1].lstrip())[0]
            targets.append([line['id'] for line in batch])
        self.assertIn(['line-3', 'line-4', 'line-5'], targets)
        self.assertNotIn(['line-30', 'line-31', 'line-32'], targets)

    def test_changed_gloss_invalidates_translation_child_but_reuses_other_children(self):
        self.set_long_song()
        glosses = {'packet': {'glosses': self.rows(self.lines)}}
        self.translate(glosses); before = len(self.calls)
        glosses['packet']['glosses'][0]['word_glosses'][0]['gloss'] = 'love'
        self.translate(glosses)
        self.assertEqual(len(self.calls), before + 1)
        target = json.JSONDecoder().raw_decode(self.calls[-1][1].split(
            'TARGET audited source lines (return these IDs only):\n', 1)[1].lstrip())[0]
        self.assertEqual([line['id'] for line in target], [f'line-{i}' for i in range(20)])

    def test_stale_child_caches_cannot_bypass_changed_inputs(self):
        self.set_long_song(); self.options.gloss_batch_size = 40
        self.gloss(); self.translate(); before = len(self.calls)
        self.lines[0].update(source_text='ਪ੍ਰਿਅ 0', roman='pria 0')
        self.gloss(); self.translate()
        self.assertGreater(len(self.calls), before)
        new = self.calls[before:]
        self.assertTrue(any('word_gloss' in name and '"roman": "pria 0"' in prompt for name,prompt in new))
        self.assertTrue(any('translation' in name and '"roman": "pria 0"' in prompt for name,prompt in new))


    def test_language_changes_invalidate_gloss_and_translation(self):
        self.gloss(); self.translate()
        self.audited['packet']['metadata'] = {'languages': ['Hindi']}
        before = len(self.calls)
        self.gloss(); self.translate(job={'languages': ['Hindi']})
        self.assertEqual(len(self.calls), before + 2)

    def test_provider_changes_invalidate_gloss_and_translation(self):
        with patch.object(pipeline.gemini, 'provider_name', return_value='openrouter'):
            self.gloss(); self.translate()
        before = len(self.calls)
        with patch.object(pipeline.gemini, 'provider_name', return_value='google'):
            self.gloss(); self.translate()
        self.assertEqual(len(self.calls), before + 2)

    def test_prompts_choose_gloss_sense_explain_names_and_translate_concepts(self):
        self.gloss(); self.translate()
        for _, prompt in self.calls:
            self.assertIn('primary word gloss is that chosen', prompt)
            self.assertIn('supported alternatives', prompt)
            self.assertIn('genuine proper names', prompt)
            self.assertIn('dictionary lookup', prompt)
            self.assertIn('short contextual phrase', prompt)
        gloss_prompt, translation_prompt = self.calls[0][1], self.calls[1][1]
        self.assertNotIn('For a matching term, set `concept_key`, set `preserve_in_english=true`', gloss_prompt)
        self.assertIn('preserve_in_english=false', gloss_prompt)
        self.assertIn('sacred sight or encounter', translation_prompt)
        self.assertNotIn('Retain darshan', translation_prompt)

    def test_dictionary_candidates_require_stage_explicit_hindi_language(self):
        self.lines[0].update(source_text='मन', roman='man')
        self.audited['packet']['metadata'] = {'languages': ['Hindi']}
        self.gloss(); self.translate()
        self.assertIn('hi.man.mind', self.calls[0][1])
        self.assertIn('hi.man.mind', self.calls[1][1])
        self.translate(job={'languages': ['Hindi']})
        self.assertIn('hi.man.mind', self.calls[-1][1])
        with self.assertRaisesRegex(RuntimeError, 'language'):
            self.translate(job={'languages': ['Punjabi', 'Hindi']})

    def real_review(self, languages=None):
        translations = [{'id': line['id'], 'literal_english': 'meaning'} for line in self.lines]
        return REAL_REVIEW(self.song, self.lines, self.rows(self.lines), translations,
                           '(none supplied)', self.options, languages=languages)

    def test_fresh_translation_rejects_missing_review_before_write(self):
        pipeline.independently_review_translations.side_effect = lambda *args, **kwargs: ([], [])
        with self.assertRaisesRegex(RuntimeError, 'independent_review'):
            self.translate()
        self.assertFalse((self.song / '.transcription' / 'pipeline' / '05-translation.json').exists())

    def test_fresh_translation_rejects_empty_fidelity_and_segment_mismatch(self):
        original_provider = self.provider
        for defect in ['fidelity', 'segments']:
            with self.subTest(defect=defect):
                def invalid_provider(*args, **kwargs):
                    response = original_provider(*args, **kwargs)
                    row = response['packet']['translations'][0]
                    if defect == 'fidelity':
                        row['fidelity'] = {}
                    else:
                        row['segments'][0]['text'] = 'different meaning'
                    return response
                with patch.object(pipeline.gemini, 'call', side_effect=invalid_provider):
                    with self.assertRaisesRegex(RuntimeError, defect):
                        self.translate()
                self.assertFalse((self.song / '.transcription' / 'pipeline' / '05-translation.json').exists())

    def test_matching_translation_cache_is_revalidated(self):
        self.translate()
        path = self.song / '.transcription' / 'pipeline' / '05-translation.json'
        packet = json.loads(path.read_text())
        packet['packet']['translations'][0].pop('independent_review')
        path.write_text(json.dumps(packet))
        before = len(self.calls)
        with self.assertRaisesRegex(RuntimeError, 'independent_review'):
            self.translate()
        self.assertEqual(len(self.calls), before)

    def test_fresh_translation_uses_display_spacing_and_strict_review_evidence(self):
        row = self.translate()['packet']['translations'][0]
        row['literal_english'] = 'Beloved, come.'
        row['segments'] = [{'text': 'Beloved', 'word_indices': [0]},
                           {'text': ',', 'word_indices': []},
                           {'text': 'come', 'word_indices': []},
                           {'text': '.', 'word_indices': []}]
        self.assertEqual(pipeline.fresh_translation_contract_errors(
            self.lines, self.rows(self.lines), [row]), [])
        for field, bad in [('fidelity', {'agency_and_image_preserved': 'true',
                                        'all_meaning_accounted_for': True, 'unsupported_additions': []}),
                           ('independent_review', {}),
                           ('fidelity', {'agency_and_image_preserved': True,
                                         'all_meaning_accounted_for': True})]:
            with self.subTest(field=field, bad=bad):
                changed = dict(row, **{field: bad})
                self.assertTrue(pipeline.fresh_translation_contract_errors(
                    self.lines, self.rows(self.lines), [changed]))
        uncertain = dict(row, uncertainty='unresolved source sense')
        self.assertTrue(pipeline.fresh_translation_contract_errors(
            self.lines, self.rows(self.lines), [uncertain]))
        legacy = dict(row); legacy.pop('fidelity'); legacy.pop('independent_review')
        self.assertEqual(pipeline.validate_line_contract(self.lines, self.rows(self.lines), [legacy]), [])

    def test_fresh_preservation_flag_rejected_before_accepted_packet_write(self):
        self.lines[0].update(source_text='माया', roman='māyā')
        rows = self.rows(self.lines)
        rows[0]['word_glosses'][0].update(concept_key='maya', preserve_in_english=True,
                                        gloss='worldly appearance and attachment')
        # Legacy reviewed packets may still retain their explicitly approved term.
        self.assertEqual(pipeline.gloss_contract_errors(self.lines, rows), [])
        with patch.object(pipeline.gemini, 'call', return_value={'packet': {'glosses': rows}}):
            with self.assertRaisesRegex(RuntimeError, 'fresh gloss.*preserv'):
                self.gloss()
        self.assertFalse((self.song / '.transcription' / 'pipeline' / '04-glosses.json').exists())

    def test_fresh_gate_is_conditional_and_cannot_be_bypassed_by_cache(self):
        self.lines[0].update(source_text='माया', roman='māyā')
        result = self.gloss()
        rows = result['packet']['glosses']
        rows[0]['word_glosses'][0].update(concept_key='maya', preserve_in_english=True,
                                        gloss='worldly appearance and attachment')
        legacy = dict(pipeline.preserved_term_registry())
        legacy.pop('defaultTreatment', None)
        with patch.object(pipeline, 'preserved_term_registry', return_value=legacy):
            self.assertEqual(pipeline.fresh_gloss_contract_errors(self.lines, rows), [])
        path = self.song / '.transcription' / 'pipeline' / '04-glosses.json'
        path.write_text(json.dumps(result))
        before = len(self.calls)
        refreshed = self.gloss()
        self.assertEqual(len(self.calls), before + 1)
        self.assertFalse(refreshed['packet']['glosses'][0]['word_glosses'][0]['preserve_in_english'])

    def test_locked_baseline_retaining_concept_stays_explicitly_locked(self):
        self.lines[0].update(source_text='माया', roman='māyā')
        glosses = {'packet': {'glosses': self.rows(self.lines)}}
        glosses['packet']['glosses'][0]['word_glosses'][0].update(concept_key='maya',
            gloss='worldly appearance and attachment', preserve_in_english=False)
        self.translate(glosses, job={'providedTranslation': 'māyā'})
        prompt = self.calls[-1][1]
        self.assertIn('A human translation is supplied and LOCKED. Copy its wording exactly', prompt)
        self.assertIn('Supplied translation:\nmāyā', prompt)
        self.assertEqual(pipeline.independently_review_translations.call_args.args[4], 'māyā')

    def test_translation_threads_job_language_into_independent_review(self):
        self.translate(job={'languages': ['Punjabi']})
        self.assertEqual(pipeline.independently_review_translations.call_args.kwargs,
                         {'languages': ['Punjabi']})

    def test_review_dictionary_candidates_respect_language(self):
        self.lines[0].update(source_text='मन', roman='man')
        self.real_review()
        self.assertNotIn('hi.man.mind', self.calls[-1][1])
        self.real_review(['Hindi'])
        self.assertIn('hi.man.mind', self.calls[-1][1])
        self.real_review(['Punjabi'])
        self.assertNotIn('hi.man.mind', self.calls[-1][1])

    def test_review_parent_and_children_invalidate_policy_language_and_provider(self):
        self.lines[:] = [dict(self.lines[0], id=f'line-{i}') for i in range(11)]
        self.real_review(); count = len(self.calls)
        self.real_review(); self.assertEqual(len(self.calls), count)
        self.policy.update(registry='new')
        self.real_review(); self.assertEqual(len(self.calls), count + 2)
        self.real_review(['Hindi']); self.assertEqual(len(self.calls), count + 4)
        with patch.object(pipeline.gemini, 'provider_name', return_value='google'):
            self.real_review(['Hindi'])
        self.assertEqual(len(self.calls), count + 6)
        self.assertTrue(all('primary word gloss is that chosen' in prompt for _, prompt in self.calls))

if __name__ == '__main__':
    unittest.main()

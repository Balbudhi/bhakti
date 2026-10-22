"""Contract proposal: referenced senses are evidence, not semantic certification.

Uses the five actual dictionary entries. Provider fixtures are source-neutral
contract examples; they do not establish a correct devotional interpretation.
"""
import argparse
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import bhakti_pipeline as pipeline
import bhakti_translation_policy as policy


def decisions_for(lines, languages):
    """Fixture: choose first supplied sense, or explicitly infer without one."""
    result = {}
    for line_id, tokens in policy.token_candidates(lines, languages).items():
        result[line_id] = []
        for token in tokens:
            references = [{'entry_id': entry['entry_id'], 'sense_id': sense['sense_id']}
                          for entry in token['candidates'] for sense in entry['senses']]
            result[line_id].append({
                'word_index': token['word_index'], 'roman': token['roman'],
                'evidence_status': 'dictionary_supported' if references else 'contextual_inference',
                'chosen': references[:1],
                'rejected': [{**reference, 'reason': 'This competing sense does not fit the addressed subject.'}
                             for reference in references[1:]],
                'contextual_reason': 'The surrounding clause addresses this noun as its subject.',
                'grammatical_role': 'addressed subject',
            })
    return result


class SenseDecisionContractTests(unittest.TestCase):
    def setUp(self):
        self.lines = [{'id': 'a', 'source_text': 'मन हार', 'roman': 'man hār'}]
        self.languages = ['Hindi']

    def rows(self):
        decisions = decisions_for(self.lines, self.languages)
        return [{'id': line['id'], 'sense_decisions': decisions[line['id']]} for line in self.lines]

    def errors(self, rows):
        return policy.sense_decision_errors(self.lines, rows, self.languages)

    def test_all_real_entries_have_distinct_stable_ids_and_source_locators(self):
        entries = policy.policy_payload()['lexicon']['entries']
        self.assertEqual(len(entries), 5)
        self.assertEqual(len({entry['entry_id'] for entry in entries}), 5)
        self.assertEqual(sum(len(entry['senses']) for entry in entries), 19)
        for entry in entries:
            self.assertTrue(entry['entry_id'])
            self.assertTrue(entry['dictionary']['entry_locator'])
            self.assertTrue(entry['dictionary']['print_page'])

    def test_candidate_binding_keeps_repeated_words_and_exact_diacritics(self):
        lines = [{'id': 'a', 'source_text': 'मन मन ।', 'roman': 'man man ।'},
                 {'id': 'b', 'source_text': 'हर करनहार', 'roman': 'har karan-hār'}]
        actual = policy.token_candidates(lines, self.languages)
        self.assertEqual([(row['word_index'], row['roman']) for row in actual['a']], [(0, 'man'), (1, 'man')])
        self.assertEqual(len(actual['a'][0]['candidates'][0]['senses']), 4)
        self.assertEqual(actual['a'][0]['candidates'], actual['a'][1]['candidates'])
        self.assertEqual([row['candidates'] for row in actual['b']], [[], []])

    def test_valid_decisions_account_for_all_homograph_alternatives(self):
        self.assertEqual(self.errors(self.rows()), [])
        row = self.rows()[0]['sense_decisions'][1]
        ids = {ref['sense_id'] for ref in row['chosen'] + row['rejected']}
        self.assertEqual(ids, {'hi.har.garland', 'hi.har.defeat', 'hi.har.overcome', 'hi.har.agent_suffix'})

    def test_multiple_activated_senses_allowed_with_contextual_reason(self):
        rows = self.rows()
        decision = rows[0]['sense_decisions'][0]
        second = decision['rejected'].pop(0)
        decision['chosen'].append({key: second[key] for key in ['entry_id', 'sense_id']})
        decision['contextual_reason'] = 'Both perception and feeling are activated in this stated reading.'
        self.assertEqual(self.errors(rows), [])

    def test_no_dictionary_does_not_force_semantic_uncertainty(self):
        for languages, source, roman in [(['Tamil'], 'அன்பே', 'aṉpē'),
                                          (['Punjabi'], 'ਮਨ', 'man'),
                                          (['Hindi', 'Punjabi'], 'ਮਨ', 'man')]:
            with self.subTest(languages=languages):
                self.languages = languages
                self.lines = [{'id': 'a', 'source_text': source, 'roman': roman}]
                rows = self.rows()
                decision = rows[0]['sense_decisions'][0]
                self.assertEqual(decision['evidence_status'], 'contextual_inference')
                self.assertEqual(decision['chosen'], [])
                self.assertEqual(self.errors(rows), [])

    def test_candidates_can_all_be_rejected_for_supported_contextual_inference(self):
        rows = self.rows()
        decision = rows[0]['sense_decisions'][0]
        decision['rejected'] += [{**reference, 'reason': 'This usage requires a separately argued sense.'}
                                 for reference in decision['chosen']]
        decision['chosen'] = []
        decision['evidence_status'] = 'contextual_inference'
        self.assertEqual(self.errors(rows), [])

    def test_decision_population_indices_and_surface_are_exact(self):
        for mutate in [
            lambda rows: rows[0].pop('sense_decisions'),
            lambda rows: rows[0]['sense_decisions'].pop(),
            lambda rows: rows[0]['sense_decisions'].reverse(),
            lambda rows: rows[0]['sense_decisions'].append(copy.deepcopy(rows[0]['sense_decisions'][0])),
            lambda rows: rows[0]['sense_decisions'][0].update(word_index=True),
            lambda rows: rows[0]['sense_decisions'][0].update(word_index=8),
            lambda rows: rows[0]['sense_decisions'][0].update(roman='hār'),
        ]:
            rows = self.rows(); mutate(rows)
            self.assertTrue(self.errors(rows), rows)

    def test_gloss_line_population_cannot_hide_duplicate_or_extra_decisions(self):
        rows = self.rows()
        self.assertTrue(self.errors(rows + copy.deepcopy(rows)))
        self.assertTrue(self.errors(rows + [{'id': 'outside', 'sense_decisions': []}]))
        self.assertTrue(self.errors([]))

    def test_references_must_belong_to_exact_entry_token_and_language(self):
        for kind in ['invented', 'entry', 'token', 'language']:
            with self.subTest(kind=kind):
                rows = self.rows()
                reference = rows[0]['sense_decisions'][0]['chosen'][0]
                if kind == 'invented': reference['sense_id'] = 'invented.meaning'
                if kind == 'entry': reference['entry_id'] = 'not-the-source-entry'
                if kind == 'token': reference.update(rows[0]['sense_decisions'][1]['chosen'][0])
                languages = ['Punjabi'] if kind == 'language' else self.languages
                self.assertTrue(policy.sense_decision_errors(self.lines, rows, languages))

    def test_every_alternative_has_one_disposition_and_reason(self):
        for mutate in [
            lambda d: d['rejected'].pop(),
            lambda d: d['rejected'].append({**d['chosen'][0], 'reason': 'Contradiction'}),
            lambda d: d['chosen'].append(copy.deepcopy(d['chosen'][0])),
            lambda d: d['rejected'][0].update(reason=''),
            lambda d: d.update(contextual_reason=''),
            lambda d: d.update(grammatical_role=''),
        ]:
            rows = self.rows(); mutate(rows[0]['sense_decisions'][0])
            self.assertTrue(self.errors(rows), rows)

    def test_evidence_status_cannot_overclaim_or_hide_unresolved_meaning(self):
        for status in ['contextual_inference', 'missing_evidence', 'verified', '']:
            rows = self.rows(); rows[0]['sense_decisions'][0]['evidence_status'] = status
            self.assertTrue(self.errors(rows), status)
        self.languages = ['Tamil']
        rows = self.rows()
        rows[0]['sense_decisions'][0]['evidence_status'] = 'dictionary_supported'
        self.assertTrue(self.errors(rows))


class SenseDecisionStageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.song = Path(tmp.name)
        self.options = argparse.Namespace(model=pipeline.MODEL, force=False, timeout=1,
                                          gloss_batch_size=40, gloss_workers=1, max_attempts=1)
        self.lines = [{'id': 'a', 'source_text': 'मन', 'roman': 'man', 'kind': 'verse'}]
        self.languages = ['Hindi']
        self.calls = []
        for name, kwargs in [('key', {'return_value': 'fixture-not-key'}),
                             ('call', {'side_effect': self.provider})]:
            p = patch.object(pipeline.gemini, name, **kwargs); p.start(); self.addCleanup(p.stop)

    def provider(self, model, key, prompt, **kwargs):
        schema = kwargs['schema_name']; self.calls.append((schema, prompt, kwargs['response_schema']))
        if schema == 'bhakti_translation_review':
            evidence = json.JSONDecoder().raw_decode(prompt.split('EVIDENCE:\n', 1)[1].lstrip())[0]
            return {'packet': {'reviews': [{'id': row['source']['id'], 'passes': True,
                'human_review_recommended': False, 'agency_preserved': True, 'imagery_preserved': True,
                'all_meaning_accounted_for': True, 'unsupported_additions': [],
                'material_choice': '', 'reason': 'Fixture reviewed.'} for row in evidence]}}
        is_gloss = 'word_gloss' in schema
        marker = ('TARGET LYRICS (return these IDs only):\n' if is_gloss else
                  'TARGET audited source lines (return these IDs only):\n')
        lines = json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1].lstrip())[0]
        if is_gloss:
            decisions = decisions_for(lines, self.languages)
            return {'packet': {'glosses': [{'id': line['id'],
                'word_glosses': [{'roman': token, 'gloss': 'contextual meaning', 'concept_key': '',
                                 'preserve_in_english': False} for token in line['roman'].split()],
                'semantic_frame': {field: '' for field in pipeline.SEMANTIC_FRAME_FIELDS},
                'grammar_note': 'Fixture grammar', 'uncertainty': '',
                'sense_decisions': decisions[line['id']]} for line in lines]}}
        return {'packet': {'translations': [{'id': line['id'], 'literal_english': 'meaning',
            'segments': [{'text': 'meaning', 'word_indices': list(range(len(line['roman'].split())))}],
            'human_review_recommended': False, 'material_alternatives': [], 'choice_note': '', 'uncertainty': '',
            'fidelity': {'agency_and_image_preserved': True, 'all_meaning_accounted_for': True,
                         'unsupported_additions': []}} for line in lines], 'comparison': []}}

    def gloss(self):
        return pipeline.gloss(self.song, {'packet': {'verified_lines': self.lines,
                              'metadata': {'languages': self.languages}}}, self.options)

    def translate(self, glosses):
        return pipeline.translate(self.song, {'packet': {'verified_lines': self.lines}}, glosses,
                                  {'languages': self.languages}, self.options)

    def test_same_decisions_reach_generation_review_and_structured_schema(self):
        glosses = self.gloss(); self.translate(glosses)
        schema = self.calls[0][2]['properties']['glosses']['items']
        self.assertIn('sense_decisions', schema['required'])
        for _, prompt, _ in self.calls:
            self.assertIn('sense_decisions', prompt)
        for _, prompt, _ in self.calls[1:]:
            self.assertIn('hi.man.mind', prompt)
            self.assertIn('contextual_reason', prompt)
        self.assertEqual(len(self.calls), 3)  # no new sense-selection API round

    def test_noncandidate_languages_complete_existing_three_stages(self):
        for languages in [['Tamil'], ['Punjabi']]:
            self.languages = languages
            self.options.force = True
            self.calls.clear()
            result = self.translate(self.gloss())
            self.assertTrue(result['packet']['translations'][0]['independent_review']['passes'])
            self.assertEqual(len(self.calls), 3)

    def test_missing_decision_rejected_before_accepted_gloss_write(self):
        original = self.provider
        def broken(*args, **kwargs):
            response = original(*args, **kwargs)
            response['packet']['glosses'][0].pop('sense_decisions')
            return response
        with patch.object(pipeline.gemini, 'call', side_effect=broken):
            with self.assertRaisesRegex(RuntimeError, 'sense'):
                self.gloss()
        self.assertFalse((self.song / '.transcription/pipeline/04-glosses.json').exists())

    def test_direct_translation_rejects_forged_references_before_provider(self):
        glosses = self.gloss()
        glosses['packet']['glosses'][0]['sense_decisions'][0]['chosen'][0]['sense_id'] = 'invented'
        self.calls.clear()
        with self.assertRaisesRegex(RuntimeError, 'sense'):
            self.translate(glosses)
        self.assertEqual(self.calls, [])

    def test_translation_inherits_audited_language_when_job_omits_it(self):
        glosses = self.gloss()
        result = pipeline.translate(self.song, {'packet': {'verified_lines': self.lines,
                                    'metadata': {'languages': self.languages}}}, glosses, {}, self.options)
        self.assertTrue(result['packet']['translations'][0]['independent_review']['passes'])
        self.assertIn('hi.man.mind', self.calls[-1][1])

    def test_conflicting_explicit_language_is_rejected_before_translation(self):
        glosses = self.gloss(); self.calls.clear()
        with self.assertRaisesRegex(RuntimeError, 'language'):
            pipeline.translate(self.song, {'packet': {'verified_lines': self.lines,
                               'metadata': {'languages': ['Hindi']}}}, glosses,
                               {'languages': ['Punjabi']}, self.options)
        self.assertEqual(self.calls, [])

    def test_cached_missing_decisions_cannot_bypass_new_contract(self):
        self.gloss()
        path = self.song / '.transcription/pipeline/04-glosses.json'
        cached = json.loads(path.read_text())
        cached['packet']['glosses'][0].pop('sense_decisions')
        path.write_text(json.dumps(cached)); self.calls.clear()
        result = self.gloss()
        self.assertIn('sense_decisions', result['packet']['glosses'][0])
        self.assertEqual(len(self.calls), 1)

    def test_changed_choice_invalidates_translation_and_independent_review(self):
        glosses = self.gloss(); self.translate(glosses); self.calls.clear()
        d = glosses['packet']['glosses'][0]['sense_decisions'][0]
        new_choice = d['rejected'].pop(0)
        d['rejected'].append({**d['chosen'][0], 'reason': 'New source context selects the alternative.'})
        d['chosen'] = [{key: new_choice[key] for key in ['entry_id', 'sense_id']}]
        self.translate(glosses)
        self.assertEqual([name for name, _, _ in self.calls],
                         ['bhakti_literal_translation', 'bhakti_translation_review'])

    def test_stale_child_gloss_cache_cannot_bypass_sense_validation(self):
        self.lines = [dict(self.lines[0], id=f'line-{i}') for i in range(85)]
        self.gloss()
        root_path = self.song / '.transcription/pipeline/04-glosses.json'
        root = json.loads(root_path.read_text()); root['packet']['glosses'][0].pop('sense_decisions')
        root_path.write_text(json.dumps(root))
        directory = self.song / '.transcription/pipeline/gloss-batches'
        for name in ['batch-000.json', 'batch-000-00.json']:
            path = directory / name; packet = json.loads(path.read_text())
            packet['response']['packet']['glosses'][0].pop('sense_decisions')
            path.write_text(json.dumps(packet))
        self.calls.clear()
        result = self.gloss()
        self.assertTrue(all('sense_decisions' in row for row in result['packet']['glosses']))
        self.assertEqual(len(self.calls), 1)

    def test_legacy_generation_contract_remains_separate(self):
        rows = self.gloss()['packet']['glosses']
        rows[0].pop('sense_decisions')
        self.assertEqual(pipeline.gloss_contract_errors(self.lines, rows), [])


if __name__ == '__main__':
    unittest.main()

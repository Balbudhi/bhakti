"""Round-zero and accepted-state identity at the actual semantic caller.

Real files, fingerprints, support validation, and orchestration; only provider
output is canned. Compositional support fixture makes no dictionary/quality claim.
"""
import copy
import json
import unittest
from unittest.mock import patch

import bhakti_pipeline as pipeline
import test_automatic_semantic_repair as fixtures


class SemanticAdoptionSupportTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.AutomaticRepairTests('test_accepted_resume_validates_manifest_without_paid_calls')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        original_rows = self.f.rows
        self.f.patch(self.f, 'rows', side_effect=lambda lines, repaired=False: original_rows(lines, True))
        original_provider = self.f.provider

        def provider(*args, **kwargs):
            result = original_provider(*args, **kwargs)
            packet = getattr(self.f.options, 'semantic_lexical_support', None)
            if packet is None and getattr(self.f.options, 'lexical_support', None):
                packet = json.loads(self.f.options.lexical_support.read_text())
            if packet:
                target = packet['targets'][0]; candidate = target['english_candidates'][0]
                if 'word_gloss' in kwargs['schema_name']:
                    for row in result['packet']['glosses']:
                        row['support_decisions'] = [{'target_id': target['id'], 'used_evidence_ids': [],
                            'role': 'operative_meaning', 'reason': 'Contextual compositional fixture.'}]
                elif kwargs['schema_name'] == 'bhakti_literal_translation':
                    for row in result['packet']['translations']:
                        row['wording_decisions'] = [{'target_id': target['id'], 'chosen_candidate_id': candidate['id'],
                            'expression': candidate['expression'], 'kind': candidate['kind'], 'english_evidence_ids': [],
                            'word_indices': target['word_indices'], 'ordinary_paraphrase': 'The breath leaves its possessor.',
                            'component_word_indices': [[0, 1], [2, 3, 4]], 'reason': 'Fixture preserves all source roles.'}]
            return result
        self.f.patch(pipeline.gemini, 'call', side_effect=provider)

    def support(self, candidate_id='candidate-one'):
        return {'version': 1, 'evidence': [], 'targets': [{
            'id': 'breath-choice', 'line_id': 'a', 'word_indices': list(range(5)),
            'surfaces': self.f.lines[0]['roman'].split(), 'source_language': 'hi',
            'source_evidence_ids': [], 'background_evidence_ids': [], 'language_link_evidence_ids': [],
            'english_candidates': [{'id': candidate_id, 'expression': 'My breath abandons me.',
                'kind': 'compositional_phrase', 'english_evidence_ids': []}]}]}

    def context(self, english='My breath abandons me.'):
        line = dict(self.f.lines[0], id='context-b')
        return [{'source': line, 'gloss': self.f.rows([line], True)[0],
                 'draft': dict(self.f.translation(line, True), literal_english=english,
                               segments=[{'text': english, 'word_indices': list(range(5))}])}]

    def assert_new_review(self, old_identity, count):
        self.assertNotEqual(self.f.state()['run_id'], old_identity)
        self.assertTrue(any(call['name'] == 'bhakti_translation_review' for call in self.f.calls[count:]))

    def test_adding_support_to_accepted_run_requires_new_review_and_bound_decisions(self):
        self.f.complete(); old = self.f.state()['run_id']; count = len(self.f.calls)
        self.f.options.semantic_lexical_support = self.support()
        gloss, draft = self.f.complete()
        self.assert_new_review(old, count)
        self.assertEqual(gloss['packet']['glosses'][0]['support_decisions'][0]['target_id'], 'breath-choice')
        self.assertEqual(draft['packet']['translations'][0]['wording_decisions'][0]['chosen_candidate_id'], 'candidate-one')

    def test_identical_support_reuses_accepted_run_without_calls(self):
        self.f.options.semantic_lexical_support = self.support()
        first = self.f.complete(); identity = self.f.state()['run_id']; count = len(self.f.calls)
        self.f.options.semantic_lexical_support = copy.deepcopy(self.support())
        self.assertEqual(self.f.complete(), first)
        self.assertEqual(self.f.state()['run_id'], identity); self.assertEqual(len(self.f.calls), count)

    def test_changed_support_cannot_reuse_accepted_candidate_decision(self):
        self.f.options.semantic_lexical_support = self.support()
        self.f.complete(); old = self.f.state()['run_id']; count = len(self.f.calls)
        self.f.options.semantic_lexical_support = self.support('candidate-two')
        _, draft = self.f.complete()
        self.assert_new_review(old, count)
        self.assertEqual(draft['packet']['translations'][0]['wording_decisions'][0]['chosen_candidate_id'], 'candidate-two')

    def test_removing_support_changes_accepted_run_identity(self):
        self.f.options.semantic_lexical_support = self.support()
        self.f.complete(); old = self.f.state()['run_id']; count = len(self.f.calls)
        del self.f.options.semantic_lexical_support
        self.f.complete(); self.assert_new_review(old, count)

    def test_file_support_is_loaded_before_accepted_run_lookup(self):
        self.f.complete(); old = self.f.state()['run_id']; count = len(self.f.calls)
        path = self.f.root / 'support.json'; path.write_text(json.dumps(self.support()))
        self.f.options.lexical_support = path
        _, draft = self.f.complete(); self.assert_new_review(old, count)
        self.assertEqual(draft['packet']['translations'][0]['wording_decisions'][0]['target_id'], 'breath-choice')

    def test_invalid_support_cannot_hide_behind_accepted_run(self):
        self.f.complete(); count = len(self.f.calls)
        packet = self.support(); packet['targets'][0]['surfaces'][0] = 'wrong'
        self.f.options.semantic_lexical_support = packet
        with self.assertRaisesRegex((ValueError, RuntimeError), 'surface|support'):
            self.f.complete()
        self.assertEqual(len(self.f.calls), count)

    def test_historical_no_support_seed_cannot_skip_new_support_validation(self):
        gloss = pipeline.gloss(self.f.song, self.f.audit, self.f.options)
        pipeline.translate(self.f.song, self.f.audit, gloss, {}, self.f.options)
        # Exact old v8 contract, not a random stale hash: legitimate compatibility
        # must remain unavailable after adding evidence not in that contract.
        path = self.f.packets / '05-translation.json'; draft = json.loads(path.read_text())
        inputs = {'lines': self.f.lines, 'glosses': gloss['packet']['glosses'],
                  'provided_translation': '(none supplied)', 'languages': ['Hindi']}
        import hashlib
        old = {'stage': 'translation', 'gloss_version': 6, 'translation_version': 8,
               'model': pipeline.gemini.batch_base_model(self.f.options.model),
               'provider': pipeline.gemini.provider_name(), 'policy': {'test': 'fixed-policy'}, 'inputs': inputs}
        draft['fingerprint'] = hashlib.sha256(json.dumps(old, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        draft['input_contract_version'] = 8; path.write_text(json.dumps(draft))
        self.f.options.semantic_lexical_support = self.support(); self.f.calls.clear()
        gloss, draft = self.f.complete()
        self.assertTrue(any('word_gloss' in call['name'] for call in self.f.calls))
        self.assertTrue(any(call['name'] == 'bhakti_translation_review' for call in self.f.calls))
        self.assertEqual(pipeline.bhakti_lexical_support.support_decision_errors(self.support(), gloss['packet']['glosses'], draft['packet']['translations']), [])

    def test_current_supported_stages_are_adopted_without_reconstruction(self):
        self.f.options.semantic_lexical_support = self.support()
        gloss = pipeline.gloss(self.f.song, self.f.audit, self.f.options)
        original = pipeline.translate(self.f.song, self.f.audit, gloss, {}, self.f.options)
        self.f.calls.clear(); _, adopted = self.f.complete()
        self.assertEqual(adopted['packet'], original['packet']); self.assertEqual([call['name'] for call in self.f.calls], [])

    def test_accepted_artifact_hash_does_not_replace_support_decision_validation(self):
        # Matching aggregate hashes prove bytes, not the underlying contract.
        for artifact, field, hash_field in [('04-glosses.json', 'support_decisions', 'gloss_sha256'),
                                             ('05-translation.json', 'wording_decisions', 'translation_sha256')]:
            with self.subTest(artifact=artifact):
                # Separate fixture per corruption; a previous hold must not be reused.
                other = SemanticAdoptionSupportTests('test_identical_support_reuses_accepted_run_without_calls')
                other.setUp()
                try:
                    f = other.f; f.options.semantic_lexical_support = other.support(); f.complete()
                    path = f.packets / artifact; value = json.loads(path.read_text())
                    rows = value['packet']['glosses' if artifact.startswith('04') else 'translations']
                    rows[0][field] = []; path.write_text(json.dumps(value))
                    manifest = f.packets / 'semantic-acceptance.json'; saved = json.loads(manifest.read_text())
                    saved[hash_field] = fixtures.digest(value); manifest.write_text(json.dumps(saved))
                    count = len(f.calls)
                    with self.assertRaisesRegex((ValueError, RuntimeError), 'support|decision|target'):
                        f.complete()
                    self.assertEqual(len(f.calls), count)
                finally: other.doCleanups()

    def test_changed_reading_evidence_invalidates_accepted_run(self):
        self.f.options.semantic_context_evidence = self.context()
        self.f.complete(); old = self.f.state()['run_id']; count = len(self.f.calls)
        self.f.options.semantic_context_evidence = self.context('The breath leaves me.')
        self.f.complete(); self.assert_new_review(old, count)

    def test_same_current_reading_evidence_adopts_existing_stage(self):
        self.f.options.semantic_context_evidence = self.context()
        gloss = pipeline.gloss(self.f.song, self.f.audit, self.f.options)
        original = pipeline.translate(self.f.song, self.f.audit, gloss, {}, self.f.options)
        self.f.calls.clear(); _, adopted = self.f.complete()
        self.assertEqual(adopted['packet'], original['packet']); self.assertEqual([call['name'] for call in self.f.calls], [])

    def test_changed_reading_evidence_cannot_adopt_old_stage_candidate(self):
        self.f.options.semantic_context_evidence = self.context()
        gloss = pipeline.gloss(self.f.song, self.f.audit, self.f.options)
        pipeline.translate(self.f.song, self.f.audit, gloss, {}, self.f.options)
        self.f.options.semantic_context_evidence = self.context('The breath leaves me.')
        self.f.calls.clear(); self.f.complete()
        self.assertTrue(any(call['name'] == 'bhakti_literal_translation' for call in self.f.calls))
        self.assertTrue(any(call['name'] == 'bhakti_translation_review' for call in self.f.calls))


if __name__ == '__main__': unittest.main()

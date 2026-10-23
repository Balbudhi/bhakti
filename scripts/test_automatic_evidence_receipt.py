"""Accepted semantics renew only the downstream work whose model evidence changed."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_automatic_semantic_lexical as fixture


class AutomaticEvidenceReceiptTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.AutomaticSemanticLexicalTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.ranking = None
        original = fixture.pipeline.bhakti_lexical_producer.prepare_translation
        def materialize(*args, **kwargs):
            options, gloss = original(*args, **kwargs)
            # The real dictionary view/validators remain in use. This models
            # target-specific vector acquisition, not its remote transport.
            options = copy.copy(options)
            options.semantic_lexical_support = copy.deepcopy(options.semantic_lexical_support)
            target = options.semantic_lexical_support['targets'][0]
            target['english_discovery'] = {'scores': [{'evidence_id': 'wordnet:3.1:a:01154749',
                'score': self.ranking, 'status': 'ranked' if self.ranking is not None else 'query_not_cached'}]}
            options.automatic_lexical_identity = fixture.pipeline.bhakti_lexical_support.content_digest(
                options.semantic_lexical_support)
            return options, gloss
        wrapper = patch.object(fixture.pipeline.bhakti_lexical_producer, 'prepare_translation', side_effect=materialize)
        wrapper.start(); self.addCleanup(wrapper.stop)

    def test_accepted_changed_target_ranking_renews_english_review_then_zero_call_resume(self):
        c = self.case
        first = c.complete()
        source_gloss = copy.deepcopy(first[0]['packet'])
        first_state = c.state(); calls = len(c.calls)
        self.ranking = .25
        changed = c.complete()
        self.assertEqual(c.kinds()[calls:], ['bhakti_literal_translation', 'bhakti_translation_review'])
        self.assertNotEqual(c.state()['run_id'], first_state['run_id'])
        self.assertEqual(changed[0]['packet'], source_gloss)
        self.assertIn('"score":0.25', c.calls[-1]['prompt'])
        calls = len(c.calls); state = c.state()
        self.assertEqual(c.complete(), changed)
        self.assertEqual(c.state(), state)
        self.assertEqual(len(c.calls), calls)

    def test_unrelated_cache_growth_does_not_reclaim_or_repeat_accepted_run(self):
        c = self.case
        first = c.complete(); calls = len(c.calls); state = c.state()
        fixture.pipeline.bhakti_lexical_producer.lookup_english_cached(
            c.wn, ['fond'], edition='3.1', cache_dir=c.root/'lookup-cache')
        self.assertTrue(list((c.root/'lookup-cache'/'english').glob('*/*.json')))
        self.assertEqual(c.complete(), first)
        self.assertEqual(c.state(), state)
        self.assertEqual(len(c.calls), calls)

    def test_invalid_bound_receipt_is_rejected_without_model_calls(self):
        c = self.case
        c.complete(); calls = len(c.calls)
        path = c.packets / '05-translation.json'
        value = json.loads(path.read_text())
        value['automatic_evidence_receipt'] = {'lexical_support': 'not-a-content-digest'}
        path.write_text(json.dumps(value))
        path = c.packets / 'semantic-acceptance.json'
        manifest = json.loads(path.read_text())
        manifest['translation_sha256'] = fixture.pipeline.bhakti_semantic_repair.digest(value)
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex((ValueError, RuntimeError), 'receipt|evidence'):
            c.complete()
        self.assertEqual(len(c.calls), calls)

    def test_evidence_renewal_interruption_preserves_seed_and_does_not_reset_resume_deadline(self):
        c = self.case
        first = c.complete(); old_id = c.state()['run_id']; calls = len(c.calls)
        self.ranking = .25
        original = fixture.pipeline.semantic_write_json
        def interrupt(path, value):
            original(path, value)
            if Path(path).name == 'semantic-repair-state.json' and value.get('run_id') != old_id:
                raise KeyboardInterrupt('after new evidence run state is durable')
        with patch.object(fixture.pipeline, 'semantic_write_json', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                c.complete()
        interrupted = c.state()
        self.assertEqual(len(c.calls), calls)
        changed = c.complete()
        self.assertEqual(c.kinds()[calls:], ['bhakti_literal_translation', 'bhakti_translation_review'])
        self.assertEqual(changed[0]['packet'], first[0]['packet'])
        self.assertEqual(c.state()['deadline_at_epoch'], interrupted['deadline_at_epoch'])
        calls = len(c.calls)
        self.assertEqual(c.complete(), changed)
        self.assertEqual(len(c.calls), calls)

    def test_target_change_during_interrupted_revision_holds_without_paid_reconstruction(self):
        c = self.case
        c.complete(); old_id = c.state()['run_id']; calls = len(c.calls)
        self.ranking = .25
        original = fixture.pipeline.semantic_write_json
        def interrupt(path, value):
            original(path, value)
            if Path(path).name == 'semantic-repair-state.json' and value.get('run_id') != old_id:
                raise KeyboardInterrupt('evidence revision claimed')
        with patch.object(fixture.pipeline, 'semantic_write_json', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                c.complete()
        self.ranking = .75
        with self.assertRaisesRegex((ValueError, RuntimeError), 'receipt|evidence'):
            c.complete()
        self.assertEqual(len(c.calls), calls)


if __name__ == '__main__': unittest.main()

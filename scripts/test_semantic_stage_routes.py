"""Real semantic callers/routes/storage; only remote provider answers are canned.

Partitions: glossary failure, English failure, adversarial English issue,
materialized-evidence renewal, expired deadline, unknown dispatched outcome.
The fixture's original Sanskrit/Hindi evidence and owner context are retained.
"""
import copy
import hashlib
import json
from pathlib import Path
import time
import importlib.util
import unittest
from unittest.mock import patch

import bhakti_pipeline as pipeline
import bhakti_model_routes as routes
import test_fresh_automatic_support as fresh_fixture


class SemanticStageRoutesTests(unittest.TestCase):
    def setUp(self):
        self.fresh = fresh_fixture.FreshAutomaticSupportTests()
        self.fresh.setUp()
        self.addCleanup(self.fresh.doCleanups)
        self.c = self.fresh.case
        self.calls = []
        self.fail_kind = None
        self.fail_kinds = set()
        self.fail_type = 'shape'
        original = self.c.transport
        def call(model, key, prompt, **kw):
            self.calls.append({'model': model, 'kind': kw['schema_name'],
                               'context': copy.deepcopy(kw.get('unit_context')),
                               'deadline_at': kw.get('deadline_at'), 'prompt': prompt})
            if model == routes.FLASH_MODEL and (kw['schema_name'] == self.fail_kind or kw['schema_name'] in self.fail_kinds):
                if self.fail_type == 'unknown':
                    raise routes.UnitTransportFailure('unknown-outcome', request_id='dispatched-unknown',
                                                      worker_terminated=False)
                if self.fail_type == 'shape':
                    field = {'bhakti_word_glosses': 'glosses', 'bhakti_literal_translation': 'translations', 'bhakti_translation_review':'reviews'}[kw['schema_name']]
                    return {'packet': {field: None}, 'resolved_model': model}
            value = original(model, key, prompt, **kw)
            value['resolved_model'] = model
            if (model == routes.FLASH_MODEL and kw['schema_name'] == self.fail_kind
                    and self.fail_type in {'english_review', 'source_review', 'unresolved_review'} and
                    sum(c['kind']=='bhakti_translation_review' for c in self.calls)==1):
                row = value['packet']['reviews'][0]
                row.update(passes=False, human_review_recommended=self.fail_type=='unresolved_review',
                    issues=[{'kind':({'source_review':'gloss_sense','unresolved_review':'unresolved_evidence'}.get(self.fail_type,'english_realization')),'target_line_ids':['v'],
                        'references':[{'line_id':'v','domain':'word_glosses','word_indices':[0], 'source_quote':'वज्र'}],
                        'explanation':'The English changes the physical modifier to a moral property.',
                        'evidence':'The source contextual gloss is physical hardness.',
                        'needed_evidence':'Verified source agency' if self.fail_type=='unresolved_review' else '',
                        'hold_reason':'external_evidence_missing' if self.fail_type=='unresolved_review' else ''}])
                component = 'gloss' if self.fail_type=='source_review' else 'english'
                row['component_judgments'][component] = {
                    'status':'unresolved' if self.fail_type=='unresolved_review' else 'defect',
                    'reason':row['issues'][0]['explanation']}
            return value
        p = patch.object(pipeline.gemini, 'call', side_effect=call)
        p.start(); self.addCleanup(p.stop)

    def run_case(self, caller):
        if caller == 'complete':
            return self.c.complete()
        result = self.fresh.run_target()
        return result['glosses'], result['translations']

    def sequence(self):
        return [(x['model'], x['kind']) for x in self.calls]

    def assert_contexts(self):
        for call in self.calls:
            self.assertIsInstance(call['context'], dict, 'Actual dispatch must be bound to a persisted stage attempt.')
            self.assertEqual(call['context']['model'], call['model'])
            self.assertIsInstance(call['deadline_at'], (int, float))

    def english_failure(self, caller):
        self.fail_kind = 'bhakti_literal_translation'
        result = self.run_case(caller)
        self.assertEqual(self.sequence(), [
            (routes.FLASH_MODEL, 'bhakti_word_glosses'),
            (routes.FLASH_MODEL, 'bhakti_literal_translation'),
            (routes.PRO_MODEL, 'bhakti_literal_translation'),
            (routes.FLASH_MODEL, 'bhakti_translation_review')])
        self.assertEqual(result[0]['resolved_model'], routes.FLASH_MODEL)
        self.assertEqual(result[1]['resolved_model'], routes.PRO_MODEL)
        self.assert_contexts()
        snapshot = copy.deepcopy(result); count = len(self.calls)
        self.assertEqual(self.run_case(caller), snapshot)
        self.assertEqual(len(self.calls), count)

    def test_complete_english_failure_retains_flash_gloss_provenance(self):
        self.english_failure('complete')

    def test_fresh_english_failure_retains_flash_gloss_provenance(self):
        self.english_failure('fresh')

    def glossary_failure(self, caller):
        self.fail_kind = 'bhakti_word_glosses'
        result = self.run_case(caller)
        self.assertEqual(self.sequence(), [
            (routes.FLASH_MODEL, 'bhakti_word_glosses'),
            (routes.PRO_MODEL, 'bhakti_word_glosses'),
            (routes.FLASH_MODEL, 'bhakti_literal_translation'),
            (routes.FLASH_MODEL, 'bhakti_translation_review')])
        self.assertEqual(result[0]['resolved_model'], routes.PRO_MODEL)
        self.assertEqual(result[1]['resolved_model'], routes.FLASH_MODEL)
        self.assert_contexts()

    def test_complete_gloss_failure_escalates_only_glossary(self):
        self.glossary_failure('complete')

    def test_fresh_gloss_failure_escalates_only_glossary(self):
        self.glossary_failure('fresh')

    def review_failure(self, caller):
        self.fail_kind = 'bhakti_translation_review'; self.fail_type = 'english_review'
        result = self.run_case(caller)
        self.assertEqual(self.sequence(), [
            (routes.FLASH_MODEL, 'bhakti_word_glosses'),
            (routes.FLASH_MODEL, 'bhakti_literal_translation'),
            (routes.FLASH_MODEL, 'bhakti_translation_review'),
            (routes.PRO_MODEL, 'bhakti_literal_translation'),
            (routes.FLASH_MODEL, 'bhakti_translation_review')])
        self.assertEqual(result[0]['resolved_model'], routes.FLASH_MODEL)
        self.assertTrue(result[1]['packet']['translations'][0]['independent_review']['passes'])
        self.assertIn('physical modifier', self.c.calls[-2]['prompt'])
        self.assert_contexts()

    def test_complete_failed_english_review_retries_only_english_with_actual_feedback(self):
        self.review_failure('complete')

    def test_fresh_failed_english_review_retries_only_english_with_actual_feedback(self):
        self.review_failure('fresh')

    def malformed_review(self, caller):
        self.fail_kind = 'bhakti_translation_review'
        result = self.run_case(caller)
        self.assertEqual(self.sequence(), [
            (routes.FLASH_MODEL, 'bhakti_word_glosses'),
            (routes.FLASH_MODEL, 'bhakti_literal_translation'),
            (routes.FLASH_MODEL, 'bhakti_translation_review'),
            (routes.PRO_MODEL, 'bhakti_translation_review')])
        self.assertEqual(result[1]['resolved_model'], routes.FLASH_MODEL)
        self.assertEqual(result[1]['review_responses'][0]['response']['resolved_model'], routes.PRO_MODEL)
        self.assertEqual(result[1]['packet']['translations'][0]['literal_english'], 'Adamantine')
        self.assert_contexts()
        count = len(self.calls)
        self.assertEqual(self.run_case(caller), result)
        self.assertEqual(len(self.calls), count)

    def test_complete_malformed_reviewer_only_escalates_review(self):
        self.malformed_review('complete')

    def test_fresh_malformed_reviewer_only_escalates_review(self):
        self.malformed_review('fresh')

    def test_complete_typed_source_finding_repairs_gloss_before_new_english(self):
        self.fail_kind = 'bhakti_translation_review'; self.fail_type = 'source_review'
        result = self.run_case('complete')
        self.assertEqual(self.sequence(), [
            (routes.FLASH_MODEL, 'bhakti_word_glosses'),
            (routes.FLASH_MODEL, 'bhakti_literal_translation'),
            (routes.FLASH_MODEL, 'bhakti_translation_review'),
            (routes.PRO_MODEL, 'bhakti_word_glosses'),
            (routes.FLASH_MODEL, 'bhakti_literal_translation'),
            (routes.FLASH_MODEL, 'bhakti_translation_review')])
        self.assertEqual(result[0]['resolved_model'], routes.PRO_MODEL)
        self.assertEqual(result[1]['resolved_model'], routes.FLASH_MODEL)
        self.assertIn('gloss_sense', self.c.calls[3]['prompt'])
        self.assert_contexts()

    def test_valid_unresolved_evidence_holds_without_retry_and_preserves_typed_outcome(self):
        self.fail_kind = 'bhakti_translation_review'; self.fail_type = 'unresolved_review'
        with self.assertRaises(RuntimeError) as caught:
            self.run_case('complete')
        self.assertEqual(self.sequence(), [(routes.FLASH_MODEL,'bhakti_word_glosses'),
            (routes.FLASH_MODEL,'bhakti_literal_translation'), (routes.FLASH_MODEL,'bhakti_translation_review')])
        self.assertEqual(type(caught.exception).__name__, 'SemanticQualityHold')
        self.assertEqual(caught.exception.issues[0]['kind'], 'unresolved_evidence')
        self.assertEqual(caught.exception.issues[0]['hold_reason'], 'external_evidence_missing')
        retained = Path(caught.exception.candidate_path)
        self.assertTrue(retained.is_file())
        self.assertFalse(json.loads(retained.read_text())['packet']['translations'][0]['independent_review']['passes'])
        with self.assertRaises(RuntimeError) as repeated:
            self.run_case('complete')
        self.assertEqual(type(repeated.exception).__name__, 'SemanticQualityHold')
        self.assertEqual(len(self.calls), 3)

    def test_fresh_typed_source_objection_uses_same_selective_gloss_repair_coordinator(self):
        self.fail_kind = 'bhakti_translation_review'; self.fail_type = 'source_review'
        result = self.run_case('fresh')
        self.assertEqual(self.sequence(), [(routes.FLASH_MODEL,'bhakti_word_glosses'),
            (routes.FLASH_MODEL,'bhakti_literal_translation'), (routes.FLASH_MODEL,'bhakti_translation_review'),
            (routes.PRO_MODEL,'bhakti_word_glosses'), (routes.FLASH_MODEL,'bhakti_literal_translation'),
            (routes.FLASH_MODEL,'bhakti_translation_review')])
        self.assertEqual(result[0]['resolved_model'], routes.PRO_MODEL)
        self.assertEqual(self.fresh.plan, self.fresh.original_plan)
        self.assertIn('OWNER ENGLISH', self.c.calls[-1]['prompt'])
        self.assertEqual(self.run_case('fresh'), result)
        self.assertEqual(len(self.calls), 6)

    def test_held_evidence_hashes_exact_saved_bytes_and_rejects_rewritten_file(self):
        self.fail_kind = 'bhakti_translation_review'; self.fail_type = 'unresolved_review'
        with self.assertRaises(RuntimeError) as caught:
            self.run_case('complete')
        self.assertEqual(type(caught.exception).__name__, 'SemanticQualityHold')
        for record in caught.exception.evidence.values():
            self.assertEqual(record['sha256'], hashlib.sha256(Path(record['path']).read_bytes()).hexdigest())
        retained = Path(caught.exception.candidate_path)
        retained.write_bytes(retained.read_bytes() + b' ')
        with self.assertRaisesRegex(RuntimeError, 'held semantic evidence hash mismatch'):
            self.run_case('complete')
        self.assertEqual(len(self.calls), 3)

    def test_protected_fresh_population_change_holds_before_calls_and_retains_private_proposal(self):
        baseline_path = self.c.root/'data'/'editorial_baselines.json'
        baseline = {'version':1,'songs':{'fixture':{'policy':'preserve_english',
            'englishSha256':'a'*64,'plainEnglishByLine':{'q':'OWNER ENGLISH'}}}}
        baseline_path.write_text(json.dumps(baseline))
        baseline_bytes = baseline_path.read_bytes()
        original_plan = copy.deepcopy(self.fresh.plan)
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError, 'owner baseline.*population|locked_baseline_population'):
                self.run_case('fresh')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.fresh.plan, original_plan)
        self.assertEqual(baseline_path.read_bytes(), baseline_bytes)
        proposals = list(self.fresh.route_dir.rglob('source-proposal.json'))
        self.assertEqual(len(proposals), 1)
        self.assertEqual(json.loads(proposals[0].read_text())['plan'], original_plan)
        self.assertEqual(self.fresh.plan['reuse_by_id']['q']['english'], '{0:OWNER ENGLISH}')

    def test_explicit_flash_only_qualification_holds_without_stage_escalation(self):
        self.c.options.semantic_stage_escalation = False
        self.c.options.semantic_repair_rounds = 0
        self.fail_kind = 'bhakti_translation_review'; self.fail_type = 'english_review'
        with self.assertRaises(RuntimeError) as caught:
            self.run_case('complete')
        self.assertEqual(self.sequence(), [(routes.FLASH_MODEL,'bhakti_word_glosses'),
            (routes.FLASH_MODEL,'bhakti_literal_translation'), (routes.FLASH_MODEL,'bhakti_translation_review')])
        self.assertEqual(type(caught.exception).__name__, 'SemanticQualityHold')
        self.assertEqual(caught.exception.issues[0]['kind'], 'english_realization')
        with self.assertRaises(RuntimeError):
            self.run_case('complete')
        self.assertEqual(len(self.calls), 3)

    def test_explicit_flash_only_malformed_reviewer_cannot_dispatch_pro_or_replay(self):
        self.c.options.semantic_stage_escalation = False
        self.fail_kind = 'bhakti_translation_review'
        with self.assertRaises(RuntimeError) as caught:
            self.run_case('complete')
        self.assertEqual(self.sequence(), [(routes.FLASH_MODEL,'bhakti_word_glosses'),
            (routes.FLASH_MODEL,'bhakti_literal_translation'), (routes.FLASH_MODEL,'bhakti_translation_review')])
        self.assertNotEqual(type(caught.exception).__name__, 'SemanticQualityHold',
                            'Malformed reviewer output is not a completed semantic judgment.')
        before = [(p, p.read_bytes()) for p in self.c.packets.rglob('route-state.json')]
        self.assertTrue(before, 'Failed stage attempts must remain durable under the explicit route policy.')
        with self.assertRaises(RuntimeError):
            self.run_case('complete')
        self.assertEqual(len(self.calls), 3)
        for path, data in before:
            self.assertEqual(path.read_bytes(), data)

    def test_gloss_and_writer_failures_escalate_independently_without_cross_stage_feedback(self):
        self.fail_kinds = {'bhakti_word_glosses','bhakti_literal_translation'}
        result = self.run_case('complete')
        self.assertEqual(self.sequence(), [(routes.FLASH_MODEL,'bhakti_word_glosses'),
            (routes.PRO_MODEL,'bhakti_word_glosses'), (routes.FLASH_MODEL,'bhakti_literal_translation'),
            (routes.PRO_MODEL,'bhakti_literal_translation'), (routes.FLASH_MODEL,'bhakti_translation_review')])
        self.assertEqual(result[0]['resolved_model'], routes.PRO_MODEL)
        self.assertEqual(result[1]['resolved_model'], routes.PRO_MODEL)
        self.assertNotIn('glosses: model rows must be an array', self.calls[3]['prompt'])
        self.assertNotIn('translations: model rows must be an array', self.calls[1]['prompt'])
        self.assertNotIn('glosses: model rows must be an array', self.calls[-1]['prompt'])
        self.assert_contexts()

    def test_fresh_materialized_target_change_renews_only_english_and_review(self):
        ranking = None
        original = pipeline.bhakti_lexical_producer.prepare_translation
        def materialize(*args, **kw):
            options, gloss = original(*args, **kw)
            options = copy.copy(options)
            options.semantic_lexical_support = copy.deepcopy(options.semantic_lexical_support)
            options.semantic_lexical_support['targets'][0]['english_discovery'] = {
                'scores':[{'evidence_id':'wordnet:3.1:a:01154749','score':ranking,
                    'status':'ranked' if ranking is not None else 'query_not_cached'}]}
            options.automatic_lexical_identity = pipeline.bhakti_lexical_support.content_digest(options.semantic_lexical_support)
            return options, gloss
        with patch.object(pipeline.bhakti_lexical_producer, 'prepare_translation', side_effect=materialize):
            first = self.run_case('fresh')
            self.assertEqual(len(self.calls), 3)
            ranking = .25
            second = self.run_case('fresh')
            self.assertEqual(self.sequence()[3:], [(routes.FLASH_MODEL,'bhakti_literal_translation'),
                                                   (routes.FLASH_MODEL,'bhakti_translation_review')])
            self.assertEqual(second[0], first[0])
            self.assertNotEqual(second[1]['automatic_evidence_receipt'], first[1]['automatic_evidence_receipt'])
            self.assertIn('"score":0.25', self.c.calls[-1]['prompt'])
            self.assertEqual(self.run_case('fresh'), second)
            self.assertEqual(len(self.calls), 5)
            self.assertEqual(self.fresh.plan, self.fresh.original_plan)

    def legacy_target(self):
        path = Path(__file__).parent/'fixtures'/'legacy_fresh_semantic_caller.py'
        spec = importlib.util.spec_from_file_location('legacy_fresh_semantic_caller', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module.process_new_targets(self.c.song, self.fresh.plan, {'languages':['Hindi']},
            self.c.options, self.fresh.route_dir, time.time()+120)

    def test_historical_combined_acceptance_is_reused_without_relabeling_models(self):
        old = self.legacy_target(); calls = len(self.calls)
        self.assertEqual(calls, 3)
        value = self.run_case('fresh')
        self.assertEqual(value, (old['glosses'], old['translations']))
        self.assertEqual(len(self.calls), calls)
        self.assertEqual(value[0]['resolved_model'], routes.FLASH_MODEL)

    def test_historical_combined_acceptance_changed_dictionary_adopts_only_validated_gloss(self):
        old = self.legacy_target(); calls = len(self.calls)
        self.c.change_english_definition()
        value = self.run_case('fresh')
        self.assertEqual(self.sequence()[calls:], [(routes.FLASH_MODEL,'bhakti_literal_translation'),
                                                  (routes.FLASH_MODEL,'bhakti_translation_review')])
        self.assertEqual(value[0], old['glosses'])
        self.assertEqual(value[0]['resolved_model'], routes.FLASH_MODEL)
        self.assertIn('hardness of a crystal', self.c.calls[-1]['prompt'])
        self.assertEqual(self.run_case('fresh'), value)
        self.assertEqual(len(self.calls), calls+2)

    def test_historical_unknown_attempt_is_not_restarted_under_new_stage_ids(self):
        self.fail_kind = 'bhakti_literal_translation'; self.fail_type = 'unknown'
        with self.assertRaises((routes.UnitUnresolved, RuntimeError)):
            self.legacy_target()
        self.assertEqual(len(self.calls), 2)
        with self.assertRaises((routes.UnitUnresolved, RuntimeError)):
            self.run_case('fresh')
        self.assertEqual(len(self.calls), 2)

    def test_interruption_after_gloss_acceptance_preserves_original_deadline_and_no_regloss(self):
        original = routes.atomic_json
        initial_deadline = time.time()+90
        self.c.options.unit_deadline_at = initial_deadline
        interrupted = []
        def write(path, value):
            original(path, value)
            if (Path(path).name=='route-state.json' and value.get('status')=='accepted'
                    and not interrupted):
                interrupted.append(copy.deepcopy(value))
                raise KeyboardInterrupt('accepted glossary is durable before semantic checkpoint')
        with patch.object(routes, 'atomic_json', side_effect=write):
            with self.assertRaises(KeyboardInterrupt):
                self.run_case('complete')
        self.assertEqual(self.sequence(), [(routes.FLASH_MODEL,'bhakti_word_glosses')])
        original_semantic_deadline = self.c.state()['deadline_at_epoch']
        self.c.options.unit_deadline_at = time.time()+900
        self.c.options.semantic_repair_seconds = 900
        self.run_case('complete')
        self.assertEqual(self.sequence()[1:], [(routes.FLASH_MODEL,'bhakti_literal_translation'),
                                             (routes.FLASH_MODEL,'bhakti_translation_review')])
        self.assertEqual(self.c.state()['deadline_at_epoch'], original_semantic_deadline)
        self.assertLessEqual(max(call['deadline_at'] for call in self.calls), initial_deadline)

    def test_unknown_dispatched_outcome_cannot_reconstruct_gloss_or_spend_pro_on_resume(self):
        self.fail_kind = 'bhakti_literal_translation'; self.fail_type = 'unknown'
        with self.assertRaises((routes.UnitUnresolved, RuntimeError)):
            self.run_case('fresh')
        self.assertEqual(self.sequence(), [(routes.FLASH_MODEL,'bhakti_word_glosses'),
                                           (routes.FLASH_MODEL,'bhakti_literal_translation')])
        before = [(p, p.read_bytes()) for p in self.fresh.route_dir.rglob('route-state.json')]
        self.assertTrue(before)
        with self.assertRaises((routes.UnitUnresolved, RuntimeError)):
            self.run_case('fresh')
        self.assertEqual(len(self.calls), 2)
        for path, data in before:
            self.assertEqual(path.read_bytes(), data)

    def test_expired_outer_deadline_cannot_be_replaced_by_semantic_default(self):
        with self.assertRaises((routes.UnitUnresolved, RuntimeError)):
            import bhakti_library_source_pass as source
            source.process_new_targets(self.c.song, self.fresh.plan, {'languages':['Hindi']},
                self.c.options, self.fresh.route_dir, time.time()-1)
        self.assertEqual(self.calls, [])

if __name__ == '__main__': unittest.main()

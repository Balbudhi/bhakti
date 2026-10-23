"""Review-first actual cache transitions; canned transport only, no paid calls."""
import argparse
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import bhakti_pipeline as pipeline
import bhakti_library_pass as library
import bhakti_model_routes as routes
import test_library_execution as library_fixture
from test_library_execution import review
from test_bhakti_library_pass import reader
import test_semantic_stage_routes as stage_fixture


def writer_rows(packet):
    return [{k:copy.deepcopy(v) for k,v in row.items() if k!='independent_review'}
            for row in packet['packet']['translations']]

class CompleteReviewVersion(unittest.TestCase):
    def setUp(self):
        self.f=stage_fixture.SemanticStageRoutesTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.c=self.f.c
        version=patch.object(pipeline,'REVIEW_TASK_VERSION',0,create=True)
        version.start();self.addCleanup(version.stop)
    def test_accepted_pair_refreshes_only_review_then_resumes_without_calls(self):
        old=self.c.complete();before=len(self.f.calls);old_state=self.c.state()
        # Exact legacy0 state predates the separate content identity field.
        for name in ('semantic-repair-state.json','semantic-acceptance.json'):
            path=self.c.packets/name;value=json.loads(path.read_text())
            value.pop('content_configuration_run_id',None);path.write_text(json.dumps(value))
        pipeline.REVIEW_TASK_VERSION=1
        new=self.c.complete()
        self.assertEqual([r['kind'] for r in self.f.calls[before:]],['bhakti_translation_review'])
        self.assertEqual(new[0]['packet'],old[0]['packet'])
        self.assertEqual(new[0]['resolved_model'],old[0]['resolved_model'])
        self.assertEqual(writer_rows(new[1]),writer_rows(old[1]))
        self.assertNotEqual(self.c.state()['run_id'],old_state['run_id'])
        self.assertEqual(new[1]['review_task_version'],1)
        count=len(self.f.calls);self.assertEqual(self.c.complete(),new);self.assertEqual(len(self.f.calls),count)
    def test_direct_translate_and_routed_review_cannot_return_old_review(self):
        g=pipeline.gloss(self.c.song,self.c.audit,self.c.options)
        old=pipeline.translate(self.c.song,self.c.audit,g,{},self.c.options)
        count=len(self.f.calls);pipeline.REVIEW_TASK_VERSION=1
        new=pipeline.translate(self.c.song,self.c.audit,g,{},self.c.options)
        self.assertEqual([r['kind'] for r in self.f.calls[count:]],['bhakti_translation_review'])
        self.assertEqual(writer_rows(new),writer_rows(old))
        self.assertEqual(new['review_task_version'],1)
        prompt=self.f.calls[-1]['prompt']
        self.assertIn('A correct English sentence cannot cure an unsupported popup or frame claim.',prompt)
        self.assertIn('Do not promote a synonym preference into a required repair.',prompt)
        self.assertIn('supplied evidence contains the matching entry or passage',prompt)
        self.assertIn('English lock does not certify popup glosses or frame claims.',prompt)
        self.assertNotIn('keep passes=true',prompt)
    def test_fresh_source_complete_refresh_preserves_retained_owner_context(self):
        old=self.f.run_case('fresh');count=len(self.f.calls)
        pipeline.REVIEW_TASK_VERSION=1
        new=self.f.run_case('fresh')
        self.assertEqual([r['kind'] for r in self.f.calls[count:]],['bhakti_translation_review'])
        self.assertEqual(writer_rows(new[1]),writer_rows(old[1]))
        self.assertEqual(self.f.fresh.plan,self.f.fresh.original_plan)
        self.assertIn('OWNER ENGLISH',self.f.calls[-1]['prompt'])
        self.assertIn('OWNER GLOSS',self.f.calls[-1]['prompt'])
    def test_legacy_fresh_acceptance_requires_new_review_without_regloss_or_rewriting(self):
        old=self.f.legacy_target();count=len(self.f.calls)
        pipeline.REVIEW_TASK_VERSION=1
        new=self.f.run_case('fresh')
        self.assertEqual([r['kind'] for r in self.f.calls[count:]],['bhakti_translation_review'])
        self.assertEqual(new[0]['packet'],old['glosses']['packet'])
        self.assertEqual(writer_rows(new[1]),writer_rows(old['translations']))
        self.assertEqual(new[1]['review_task_version'],1)
    def test_task_change_cannot_replay_legacy_unknown_attempt(self):
        self.f.fail_kind='bhakti_literal_translation';self.f.fail_type='unknown'
        with self.assertRaises((routes.UnitUnresolved,RuntimeError)):self.f.legacy_target()
        count=len(self.f.calls);pipeline.REVIEW_TASK_VERSION=1
        with self.assertRaises((routes.UnitUnresolved,RuntimeError)):self.f.run_case('fresh')
        self.assertEqual(len(self.f.calls),count)
    def test_tampered_prior_accepted_writer_cannot_seed_new_review(self):
        self.c.complete();path=self.c.packets/'05-translation.json'
        obj=json.loads(path.read_text());obj['packet']['translations'][0]['literal_english']='tampered'
        path.write_text(json.dumps(obj));pipeline.REVIEW_TASK_VERSION=1;count=len(self.f.calls)
        with self.assertRaises((RuntimeError,ValueError)):self.c.complete()
        self.assertEqual(len(self.f.calls),count)
    def test_changed_dictionary_is_not_mistaken_for_review_only_renewal(self):
        self.c.complete();count=len(self.f.calls)
        self.c.change_english_definition();pipeline.REVIEW_TASK_VERSION=1
        self.c.complete()
        self.assertEqual([r['kind'] for r in self.f.calls[count:]],['bhakti_literal_translation','bhakti_translation_review'])
    def test_review_only_seed_is_durable_before_new_state_and_preserves_deadline(self):
        old=self.c.complete();pipeline.REVIEW_TASK_VERSION=1;original=pipeline.semantic_write_json
        fired=False
        def interrupt(path,value):
            nonlocal fired
            original(path,value)
            if Path(path).name=='semantic-repair-state.json' and value.get('status')=='in-progress' and not fired:
                fired=True;raise KeyboardInterrupt('after state claim')
        count=len(self.f.calls)
        with patch.object(pipeline,'semantic_write_json',side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):self.c.complete()
        self.assertTrue(fired);self.assertEqual(len(self.f.calls),count)
        deadline=self.c.state()['deadline_at_epoch']
        new=self.c.complete()
        self.assertEqual([r['kind'] for r in self.f.calls[count:]],['bhakti_translation_review'])
        self.assertEqual(writer_rows(new[1]),writer_rows(old[1]))
        self.assertEqual(self.c.state()['deadline_at_epoch'],deadline)

class LibraryAuditReviewVersion(unittest.TestCase):
    def setUp(self):
        self.f=library_fixture.CurrentContentExecutionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.data=reader();self.calls=[];self.defect=False
        for manager in (patch.object(pipeline,'REVIEW_TASK_VERSION',0,create=True),
            patch.object(pipeline.gemini,'key',return_value='fixture'),
            patch.object(pipeline.gemini,'call',side_effect=self.provider)):
            manager.start();self.addCleanup(manager.stop)
    def provider(self,model,key,prompt,**kw):
        self.calls.append(prompt)
        issues=[]
        if self.defect:
            issues=[{'kind':'gloss_sense','target_line_ids':['one'],
                'references':[{'line_id':'one','domain':'word_glosses','word_indices':[0],'source_quote':'मन'}],
                'explanation':'unsupported qualifier in popup','evidence':'Source noun has no qualifier.',
                'hold_reason':'','needed_evidence':''}]
        return {'packet':{'reviews':[review(issues=issues)]}}
    def test_task_change_cannot_replay_unknown_current_reader_audit(self):
        def unknown(*args, **kwargs):
            self.calls.append('unknown dispatch')
            raise routes.UnitTransportFailure('unknown-outcome', request_id='dispatched-unknown',
                                              worker_terminated=False)
        with patch.object(pipeline.gemini,'call',side_effect=unknown):
            with self.assertRaises((routes.UnitUnresolved,RuntimeError)):self.f.execute(self.data)
        count=len(self.calls);pipeline.REVIEW_TASK_VERSION=1
        with self.assertRaises((routes.UnitUnresolved,RuntimeError)):self.f.execute(self.data)
        self.assertEqual(len(self.calls),count)
    def test_task_change_cannot_abandon_running_reader_audit(self):
        def interrupted(*args, **kwargs):
            self.calls.append('interrupted dispatch')
            raise KeyboardInterrupt('worker outcome not recorded')
        with patch.object(pipeline.gemini,'call',side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):self.f.execute(self.data)
        paths=list((self.f.directory/'routes').rglob('route-state.json'))
        self.assertEqual(len(paths),1)
        self.assertEqual(json.loads(paths[0].read_text())['attempts'][0]['status'],'running')
        count=len(self.calls);pipeline.REVIEW_TASK_VERSION=1
        with self.assertRaises((routes.UnitUnresolved,RuntimeError)):self.f.execute(self.data)
        self.assertEqual(len(self.calls),count)
    def test_frozen_inventory_task_change_holds_without_relabel_or_dispatch(self):
        from test_bhakti_library_pass import SelectivePassTests
        fixture=SelectivePassTests('runTest');fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.add_song('fixture');fixture.commit();inventory=fixture.inventory()
        options=argparse.Namespace(budget_usd=.35,max_calls=2,deadline_seconds=120,
            slugs=['fixture'],model=self.f.options.model,pro_model=self.f.options.pro_model,
            source_reuse_maps={},timeout=600,force=False)
        first=library.execute_inventory(fixture.root,inventory,fixture.state,options)
        self.assertEqual(len(self.calls),1,first)
        run=fixture.state/'run.json';original=run.read_bytes();pipeline.REVIEW_TASK_VERSION=1
        with self.assertRaisesRegex(ValueError,'frozen run'):
            library.execute_inventory(fixture.root,inventory,fixture.state,options)
        self.assertEqual(len(self.calls),1);self.assertEqual(run.read_bytes(),original)
    def test_requested_audit_new_task_gets_new_review_then_reuses(self):
        old=self.f.execute(self.data);pipeline.REVIEW_TASK_VERSION=1
        new=self.f.execute(self.data)
        self.assertEqual(len(self.calls),2)
        self.assertNotEqual(old['attempt_id'],new['attempt_id'])
        self.assertEqual(self.f.execute(self.data),new);self.assertEqual(len(self.calls),2)
    def test_review_task_change_retains_prior_findings_and_checks_their_route(self):
        self.defect=True;old=self.f.execute(self.data);self.defect=False;pipeline.REVIEW_TASK_VERSION=1
        new=self.f.execute(self.data)
        self.assertEqual(len(self.calls),2)
        self.assertTrue(new['finding_snapshot']['findings'],'A new task cannot erase a prior concrete finding by omission.')
        self.assertEqual(len(new['finding_snapshot']['reviews']),2)
        route=Path(old['finding_route_state_path']);candidate=route.parent/'flash/candidate.json'
        obj=json.loads(candidate.read_text());obj['unbound_change']=True;candidate.write_text(json.dumps(obj))
        with self.assertRaises((routes.RunFatal,RuntimeError,ValueError)):self.f.execute(self.data)
        self.assertEqual(len(self.calls),2)

if __name__=='__main__':unittest.main()

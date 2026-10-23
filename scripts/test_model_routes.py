"""Pro route contract tests: real persistence, no provider calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import bhakti_model_routes as routes


class ModelRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.calls=[];self.now=1000.
        p=patch.object(routes.time,'time',side_effect=lambda:self.now);p.start();self.addCleanup(p.stop)
        self.fp='a'*64;self.dependency='b'*64

    def run_unit(self,execute,validate=None,**kw):
        return routes.run_unit(self.root,'song:timing:pair-3',self.fp,execute,
            validate or (lambda candidate:candidate['issues']),deadline_at=kw.pop('deadline_at',2200.),
            dependency_fingerprint=self.dependency,**kw)

    def execute(self,ctx):
        self.calls.append(ctx)
        return {'model':ctx.model,'issues':[],'independent_review':{'passes':True},'text':'exact accepted wording'}

    def state(self):
        paths=list(self.root.rglob('route-state.json'));self.assertEqual(len(paths),1)
        return json.loads(paths[0].read_text())

    def test_attempt_directory_exists_before_stage_execution(self):
        def execute(ctx):
            self.assertTrue(ctx.attempt_dir.is_dir())
            (ctx.attempt_dir/'stage-evidence.json').write_text('{"source": "preserved"}')
            return self.execute(ctx)
        self.run_unit(execute)
        self.assertEqual((self.calls[0].attempt_dir/'stage-evidence.json').read_text(), '{"source": "preserved"}')

    def test_accepted_flash_artifact_is_unchanged_and_reused_after_deadline(self):
        validations=[]
        result=self.run_unit(self.execute,lambda artifact:validations.append(copy.deepcopy(artifact)) or [])
        self.assertEqual(result,validations[0]);self.assertEqual(len(self.calls),1)
        self.assertEqual(self.calls[0].model,routes.FLASH_MODEL)
        self.now=3000
        self.assertEqual(self.run_unit(self.execute),result);self.assertEqual(len(self.calls),1)
        self.assertEqual(self.state()['status'],'accepted')

    def test_quality_failure_once_escalates_pro_and_requires_independent_validation(self):
        validated=[]
        def execute(ctx):
            artifact=self.execute(ctx)
            if ctx.model==routes.FLASH_MODEL:artifact['issues']=[{'kind':'agency_mismatch','line_id':'a','detail':'wrong actor'}]
            return artifact
        result=self.run_unit(execute,lambda artifact:validated.append(artifact['model']) or artifact['issues'])
        self.assertEqual([ctx.model for ctx in self.calls],[routes.FLASH_MODEL,routes.PRO_MODEL])
        self.assertEqual(validated,[routes.FLASH_MODEL,routes.PRO_MODEL]);self.assertEqual(result['model'],routes.PRO_MODEL)
        state=self.state();self.assertEqual(len(state['attempts']),2)
        self.assertEqual(state['attempts'][0]['status'],'quality-failed')
        self.assertTrue((self.calls[0].attempt_dir/'candidate.json').is_file())
        self.assertTrue((self.calls[1].attempt_dir/'candidate.json').is_file())

    def test_pro_failure_remains_unresolved_and_resume_cannot_repeat(self):
        def execute(ctx):
            self.calls.append(ctx);raise routes.QualityFailure([{'kind':'timing_disagreement','detail':'two unequal starts'}])
        with self.assertRaises(routes.UnitUnresolved):self.run_unit(execute)
        self.assertEqual(len(self.calls),2)
        with self.assertRaises(routes.UnitUnresolved):self.run_unit(execute,deadline_at=5000)
        self.assertEqual(len(self.calls),2);self.assertEqual(self.state()['deadline_at'],2200)

    def test_changed_dependency_and_input_create_distinct_unit_identity(self):
        self.run_unit(self.execute);self.dependency='c'*64;self.run_unit(self.execute)
        self.fp='d'*64;self.run_unit(self.execute)
        self.assertEqual(len(self.calls),3)
        self.assertEqual(len(list(self.root.rglob('route-state.json'))),3)

    def test_locked_baseline_and_missing_source_do_not_escalate(self):
        for kind in ('locked_baseline_conflict','missing_source_evidence'):
            with self.subTest(kind=kind):
                self.fp=kind
                def execute(ctx):self.calls.append(ctx);raise routes.QualityFailure([{'kind':kind,'detail':'requires original evidence'}])
                before=len(self.calls)
                with self.assertRaises(routes.UnitUnresolved):self.run_unit(execute)
                self.assertEqual(len(self.calls)-before,1)

    def test_flash_deadline_leaves_pro_allowance_and_resume_never_extends(self):
        def execute(ctx):
            self.calls.append(ctx)
            if ctx.model==routes.FLASH_MODEL:
                self.assertEqual(ctx.deadline_at,1600);self.assertEqual(ctx.call_timeout_seconds,600)
                self.now=1599
                raise routes.QualityFailure([{'kind':'agency_mismatch','detail':'source actor differs'}])
            self.assertEqual(ctx.deadline_at,2200);return {'issues':[]}
        self.run_unit(execute)
        self.assertEqual(self.state()['deadline_at'],2200)
        self.assertEqual(self.calls[0].unit_deadline_at,2200)

    def test_generic_failure_is_not_guessed_as_quality_or_retried(self):
        def execute(ctx):self.calls.append(ctx);raise ValueError('looks like agency uncertainty')
        with self.assertRaises(routes.UnitUnresolved):self.run_unit(execute)
        self.assertEqual(len(self.calls),1)

    def test_unknown_outcome_needs_confirmed_worker_termination(self):
        for stopped in (False,True):
            with self.subTest(stopped=stopped):
                self.fp='unknown-'+str(stopped);before=len(self.calls)
                def execute(ctx):
                    self.calls.append(ctx)
                    if ctx.model==routes.FLASH_MODEL:
                        raise routes.UnitTransportFailure('unknown-outcome',request_id='paid-request',worker_terminated=stopped)
                    return {'issues':[]}
                if stopped:self.run_unit(execute)
                else:
                    with self.assertRaises(routes.UnitUnresolved):self.run_unit(execute)
                self.assertEqual(len(self.calls)-before,2 if stopped else 1)

    def test_runfatal_budget_and_auth_never_trigger_pro(self):
        def execute(ctx):self.calls.append(ctx);raise routes.RunFatal('budget_exhausted')
        with self.assertRaises(routes.RunFatal):self.run_unit(execute)
        self.assertEqual(len(self.calls),1)

    def test_explicit_model_routes_policy_and_fingerprints_are_persisted(self):
        self.run_unit(self.execute,base_model=routes.FLASH_MODEL,pro_model=routes.PRO_MODEL,
                      policy=routes.EscalationPolicy(quality_failure=False))
        state=self.state()
        self.assertEqual(state['dependency_fingerprint'],self.dependency)
        self.assertEqual(state['input_fingerprint'],self.fp)
        self.assertFalse(state['policy']['quality_failure']);self.assertEqual(state['version'],routes.ROUTE_VERSION)
        ctx=self.calls[0]
        self.assertEqual(ctx.transport_context['attempt_id'],ctx.attempt_id)
        self.assertEqual(ctx.transport_context['model'],ctx.model)

    def test_pro_pricing_tier_switch_and_unsupported_model_fail_closed(self):
        self.assertEqual(routes.model_pricing(routes.FLASH_MODEL,250000)['prompt'],.75)
        self.assertEqual(routes.model_pricing(routes.PRO_MODEL,199999),{'prompt':2.,'completion':12.,'tier':'standard'})
        self.assertEqual(routes.model_pricing(routes.PRO_MODEL,200000),{'prompt':4.,'completion':18.,'tier':'long-context'})
        with self.assertRaises(routes.RunFatal):routes.model_pricing('google/unknown-pro',1)

    def test_interrupted_running_attempt_cannot_repeat_execute_on_resume(self):
        def execute(ctx):self.calls.append(ctx);raise KeyboardInterrupt('local process stopped during execution')
        with self.assertRaises(KeyboardInterrupt):self.run_unit(execute)
        self.assertEqual(self.state()['attempts'][0]['status'],'running')
        with self.assertRaises(routes.UnitUnresolved):self.run_unit(self.execute)
        self.assertEqual(len(self.calls),1)

    def test_explicit_pro_base_does_not_repeat_same_model_on_failure(self):
        def execute(ctx):self.calls.append(ctx);raise routes.QualityFailure([{'kind':'agency_mismatch','detail':'wrong actor'}])
        with self.assertRaises(routes.UnitUnresolved):
            self.run_unit(execute,base_model=routes.PRO_MODEL,pro_model=routes.PRO_MODEL)
        self.assertEqual([ctx.model for ctx in self.calls],[routes.PRO_MODEL])

    def test_tampered_accepted_artifact_or_running_state_does_not_dispatch(self):
        self.run_unit(self.execute)
        path=next(self.root.rglob('accepted-result.json'));path.write_text('{"issues":[],"text":"changed"}')
        with self.assertRaises(routes.RunFatal):self.run_unit(self.execute)
        self.assertEqual(len(self.calls),1)


if __name__=='__main__':unittest.main()

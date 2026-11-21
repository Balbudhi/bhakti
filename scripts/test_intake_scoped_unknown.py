"""Real bounded intake restart and HTTP worker evidence; localhost only."""
import copy
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import bhakti_intake_run as intake
import bhakti_model_routes as routes
import process_song_gemini as client
from test_bounded_gemini_transport import BoundedTransportTests


class ScopedUnknownResumeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=BoundedTransportTests('test_success_saves_exact_raw_and_usage_without_credentials')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root.resolve()
        source=self.root/'source.m4a';source.write_bytes(b'local identity fixture')
        self.jobs=[{'slug':'fixture','source':str(source)}]
        self.options=SimpleNamespace(model=client.GEMINI_MODEL,run_dir=self.root/'.transcription/run',
            budget_usd=.01,max_calls=5,deadline_seconds=120)
        self.ledger=self.root/'.transcription/api-ledger.json'
        env=patch.dict(os.environ,{'BHAKTI_API_RUN_LEDGER':str(self.ledger)})
        env.start();self.addCleanup(env.stop)
        self.route_dir=self.root/'routes'

    def execute(self, ctx):
        return client.call(ctx.model,'test-secret-never-persist','fixture',audio=None,
            timeout=3,max_completion_tokens=512,deadline_at=ctx.deadline_at,
            unit_context=ctx.transport_context)

    def create_unknown(self):
        worker=client._BOUNDED_HTTP_WORKER.replace("    path = Path(job['response_path'])", '    sys.exit(7)\n' + "    path = Path(job['response_path'])")
        with intake.bounded_intake_run(self.root,self.jobs,self.options), patch.object(client,'_BOUNDED_HTTP_WORKER',worker):
            with self.assertRaises(routes.UnitUnresolved):
                routes.run_unit(self.route_dir,'first','a'*64,self.execute,lambda value:[],
                    deadline_at=self.options.unit_deadline_at,
                    base_model=routes.FLASH_MODEL,pro_model=routes.FLASH_MODEL)
        self.record=json.loads(self.ledger.read_text())
        self.row=self.record['requests'][0]
        self.state_path=Path(self.row['unit_context']['state_path'])
        self.state=json.loads(self.state_path.read_text())

    def test_restart_retains_unknown_and_allows_different_unit_but_not_replay(self):
        self.create_unknown()
        before=copy.deepcopy(self.record)
        with intake.bounded_intake_run(self.root,self.jobs,self.options):
            with patch.object(client.subprocess,'Popen',side_effect=AssertionError('same attempt dispatched')):
                with self.assertRaises(routes.RunFatal):
                    client.call(client.GEMINI_MODEL,'test-secret-never-persist','fixture',audio=None,
                        timeout=3,max_completion_tokens=512,unit_context=self.row['unit_context'])
            result=routes.run_unit(self.route_dir,'other','b'*64,self.execute,lambda value:[],
                deadline_at=self.options.unit_deadline_at,
                base_model=routes.FLASH_MODEL,pro_model=routes.FLASH_MODEL)
            self.assertTrue(result['packet']['ok'])
        after=json.loads(self.ledger.read_text())
        self.assertEqual(after['requests'][0],before['requests'][0])
        self.assertEqual(after['blocked_attempts'],before['blocked_attempts'])
        self.assertEqual(len(after['requests']),2)
        self.assertEqual(len(self.fixture.requests),2)
        self.assertEqual(after['requests'][0]['status'],'unknown-outcome')
        self.assertNotIn('reported_cost_usd',after['requests'][0])
        for key in ('budget_usd','max_calls','deadline_at','intake_ledger_id'):
            self.assertEqual(after[key],before[key])
        self.assertEqual(self.state_path.read_text(),json.dumps(self.state,ensure_ascii=False,indent=2)+'\n')

    def test_incomplete_or_mismatched_unknown_evidence_holds_before_worker(self):
        self.create_unknown()
        cases=['dispatched','nonterminated','unscoped','missing-block','mismatched-block',
               'missing-route','wrong-fingerprint','wrong-model','wrong-request','route-running',
               'attempt-running','route-nonterminated','partial-charge','globally-blocked']
        for case in cases:
            record=copy.deepcopy(self.record);state=copy.deepcopy(self.state);row=record['requests'][0]
            attempt=state['attempts'][0];context=row['unit_context']
            if case=='dispatched':row['status']='dispatched'
            elif case=='nonterminated':row['worker_terminated']=False
            elif case=='unscoped':row.pop('unit_context')
            elif case=='missing-block':record['blocked_attempts']={}
            elif case=='mismatched-block':record['blocked_attempts'][context['attempt_id']]['request_id']='wrong'
            elif case=='wrong-fingerprint':state['input_fingerprint']='wrong'
            elif case=='wrong-model':attempt['model']='wrong'
            elif case=='wrong-request':attempt['request_id']='wrong'
            elif case=='route-running':state['status']='running'
            elif case=='attempt-running':attempt['status']='running'
            elif case=='route-nonterminated':attempt['worker_terminated']=False
            elif case=='partial-charge':row['reported_cost_usd']=0
            elif case=='globally-blocked':record['blocked']=True
            self.ledger.write_text(json.dumps(record))
            if case=='missing-route':self.state_path.unlink(missing_ok=True)
            else:self.state_path.write_text(json.dumps(state))
            before=self.ledger.read_bytes()
            with self.subTest(case=case),self.assertRaises(ValueError):
                with intake.bounded_intake_run(self.root,self.jobs,self.options):
                    self.fail('invalid evidence entered worker scope')
            self.assertEqual(self.ledger.read_bytes(),before)
        self.assertEqual(len(self.fixture.requests),1)


if __name__=='__main__':unittest.main()

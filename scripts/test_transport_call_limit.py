"""Run-wide call cap: actual worker/HTTP/ledger, no paid provider."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import test_pro_transport as fixtures
import process_song_gemini as client
import bhakti_model_routes as routes


class CallLimitTests(unittest.TestCase):
    setUp = fixtures.ProTransportTests.setUp
    ledger = fixtures.ProTransportTests.ledger
    execute = fixtures.ProTransportTests.execute
    run_route = fixtures.ProTransportTests.run_route
    def call(self):
        return client.call(routes.FLASH_MODEL, 'fixture', 'fixture', audio=None,
                           timeout=3, max_completion_tokens=512)

    def test_present_limit_without_ledger_never_dispatches(self):
        for value in ('1', ''):
            with self.subTest(value=value), patch.dict(os.environ, {'BHAKTI_API_RUN_MAX_CALLS':value}):
                os.environ.pop('BHAKTI_API_RUN_LEDGER',None)
                with self.assertRaises(routes.RunFatal):self.call()
                with self.assertRaises(routes.RunFatal):self.call()
        self.assertEqual(self.requests, [])
        self.assertFalse((self.root/'ledger.json').exists())

    def test_invalid_limits_fail_before_any_reservation_or_dispatch(self):
        for value in ('0', '-1', '1.5', 'true', '', ' 2', '+2'):
            with self.subTest(value=value), patch.dict(os.environ, {'BHAKTI_API_RUN_MAX_CALLS':value}):
                with self.assertRaises(routes.RunFatal):self.call()
        self.assertEqual(self.requests, [])
        self.assertFalse((self.root/'ledger.json').exists())

    def test_persisted_limit_cannot_change_or_disappear_on_resume(self):
        with patch.dict(os.environ, {'BHAKTI_API_RUN_MAX_CALLS':'1'}):self.call()
        self.assertEqual(self.ledger()['max_calls'],1)
        with patch.dict(os.environ, {'BHAKTI_API_RUN_MAX_CALLS':'2'}):
            with self.assertRaises(routes.RunFatal):self.call()
        with patch.dict(os.environ):
            os.environ.pop('BHAKTI_API_RUN_MAX_CALLS',None)
            with self.assertRaises(routes.RunFatal):self.call()
        self.assertEqual(len(self.requests),1)
        self.assertEqual(len(self.ledger()['requests']),1)

    def test_existing_unlimited_run_cannot_be_relabelled(self):
        self.call()
        with patch.dict(os.environ, {'BHAKTI_API_RUN_MAX_CALLS':'2'}):
            with self.assertRaises(routes.RunFatal):self.call()
        self.assertEqual(len(self.requests),1)

    def test_threads_share_cap_and_count_every_reservation(self):
        with patch.dict(os.environ, {'BHAKTI_API_RUN_MAX_CALLS':'2'}):
            def attempt(_):
                try:self.call();return 'accepted'
                except routes.RunFatal:return 'capped'
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
                outcomes=list(pool.map(attempt,range(5)))
        self.assertEqual(outcomes.count('accepted'),2)
        self.assertEqual(outcomes.count('capped'),3)
        self.assertEqual(len(self.requests),2)
        self.assertEqual(len(self.ledger()['requests']),2)

    def test_processes_share_cap_under_actual_file_lock(self):
        source="""import sys
sys.path.insert(0,sys.argv[1])
import process_song_gemini as c
import bhakti_model_routes as r
c.API_URL=sys.argv[2]
try:
 c.call(r.FLASH_MODEL,'fixture','fixture',audio=None,timeout=3,max_completion_tokens=512)
 print('accepted')
except r.RunFatal:
 print('capped')
"""
        environment=dict(os.environ,BHAKTI_API_RUN_MAX_CALLS='2')
        jobs=[subprocess.Popen([sys.executable,'-c',source,str(Path(client.__file__).parent),client.API_URL],
              env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(4)]
        outcomes=[]
        for job in jobs:
            stdout,stderr=job.communicate(timeout=10)
            self.assertEqual(job.returncode,0,stderr);outcomes.append(stdout.strip())
        self.assertEqual(outcomes.count('accepted'),2)
        self.assertEqual(outcomes.count('capped'),2)
        self.assertEqual(len(self.requests),2)
        self.assertEqual(len(self.ledger()['requests']),2)

    def test_unknown_outcome_consumes_call_allowance_before_pro(self):
        self.mode='timeout'
        def execute(ctx):
            return client.call(ctx.model,'fixture','fixture',audio=None,timeout=1.5,
                  deadline_at=ctx.deadline_at,max_completion_tokens=512,unit_context=ctx.transport_context)
        with patch.dict(os.environ, {'BHAKTI_API_RUN_MAX_CALLS':'1'}):
            with self.assertRaises(routes.RunFatal):self.run_route(execute)
        self.assertEqual(len(self.requests),1)
        ledger=self.ledger();self.assertEqual(len(ledger['requests']),1)
        self.assertEqual(ledger['requests'][0]['status'],'unknown-outcome')
        self.assertNotIn('reported_cost_usd',ledger['requests'][0])


if __name__=='__main__':unittest.main()

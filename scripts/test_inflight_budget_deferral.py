"""Exact OpenRouter in-flight 402 handling through the real bounded caller."""
import http.server
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import process_song_gemini as client
import bhakti_model_routes as routes


class InflightDeferralTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.requests=[];self.waits=[];self.always=False
        self.metadata={'reason':'in_flight_budget_exhausted','limit_source':'openrouter_in_flight_budget',
                       'headers':{'Retry-After':'120'}}
        self.budget=1.;self.calls=4;self.seconds=300
        outer=self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                outer.requests.append(payload)
                reject=len(outer.requests)==1 or outer.always
                self.send_response(402 if reject else 200);self.end_headers()
                result=({'error':{'code':402,'metadata':outer.metadata}} if reject else
                    {'model':payload['model'],'choices':[{'message':{'content':'{"ok":true}'}}],
                     'usage':{'cost':.00001}})
                self.wfile.write(json.dumps(result).encode())
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        for p in (patch.object(client,'API_URL',f'http://127.0.0.1:{server.server_port}/'),
                  patch.object(client,'_wait_for_api_start'),
                  patch.object(client,'_API_SLOTS',threading.BoundedSemaphore(1))):
            p.start();self.addCleanup(p.stop)
        self.clock=time.time()

    def wait(self, seconds):
        self.assertTrue(client._API_SLOTS.acquire(blocking=False),'retry wait held API slot')
        client._API_SLOTS.release()
        self.waits.append(seconds);self.clock+=seconds

    def invoke(self):
        env={'BHAKTI_GEMINI_PROVIDER':'openrouter','BHAKTI_API_RUN_LEDGER':str(self.root/'ledger.json'),
             'BHAKTI_API_RUN_BUDGET_USD':str(self.budget),'BHAKTI_API_RUN_MAX_CALLS':str(self.calls)}
        with patch.dict(os.environ,env),patch.object(client.time,'time',side_effect=lambda:self.clock), \
                patch.object(client.time,'sleep',side_effect=self.wait):
            def execute(ctx):
                return client.call(ctx.model,'secret-never-persist','fixture',audio=None,
                    timeout=300,max_completion_tokens=512,deadline_at=ctx.deadline_at,
                    unit_context=ctx.transport_context)
            return routes.run_unit(self.root/'routes','fixture','a'*64,execute,lambda result:[],
                deadline_at=self.clock+self.seconds,
                policy=routes.EscalationPolicy(flash_time_share=.9))

    def ledger(self): return json.loads((self.root/'ledger.json').read_text())

    def test_one_same_model_retry_honors_delay_releases_slot_and_counts_both(self):
        self.assertTrue(self.invoke()['packet']['ok'])
        self.assertEqual(len(self.requests),2)
        self.assertEqual(self.requests[0],self.requests[1])
        self.assertEqual(sum(self.waits),120)
        ledger=self.ledger();first=ledger['requests'][0]
        self.assertEqual(first['status'],'in-flight-budget-deferred')
        self.assertEqual(first['http_status'],402)
        self.assertGreater(first['reservation_usd'],0)
        self.assertNotIn('reported_cost_usd',first)
        self.assertEqual(first['retry_after_seconds'],120)
        self.assertFalse(ledger['blocked'])
        self.assertEqual(len(ledger['requests']),2)
        self.assertTrue(Path(first['response_path']).exists())
        for p in self.root.rglob('*.json'):self.assertNotIn('secret-never-persist',p.read_text())

    def test_repeated_exact_402_holds_without_pro_or_third_request(self):
        self.always=True
        with self.assertRaises(routes.UnitUnresolved):self.invoke()
        self.assertEqual([r['model'] for r in self.requests],[routes.FLASH_MODEL]*2)
        self.assertEqual(sum(self.waits),120)
        self.assertEqual(len(self.ledger()['blocked_attempts']),1)
        self.assertFalse(self.ledger()['blocked'])
        with self.assertRaises(routes.UnitUnresolved):self.invoke()
        self.assertEqual(len(self.requests),2)

    def test_deadline_cannot_accommodate_retry(self):
        self.seconds=100
        with self.assertRaises(routes.UnitUnresolved):self.invoke()
        self.assertEqual(len(self.requests),1);self.assertEqual(self.waits,[])

    def test_call_cap_cannot_accommodate_retry(self):
        self.calls=1
        with self.assertRaises(routes.UnitUnresolved):self.invoke()
        self.assertEqual(len(self.requests),1);self.assertEqual(self.waits,[])

    def test_delay_overshoot_holds_without_escalating_to_pro(self):
        normal_wait=self.wait
        self.wait=lambda seconds:normal_wait(seconds+220)
        with self.assertRaises(routes.UnitUnresolved):self.invoke()
        self.assertEqual(len(self.requests),1)
        self.assertFalse(self.ledger()['blocked'])

    def test_budget_cannot_accommodate_retry(self):
        self.budget=.004
        with self.assertRaises(routes.UnitUnresolved):self.invoke()
        self.assertEqual(len(self.requests),1);self.assertEqual(self.waits,[])

    def test_other_402_is_fatal_without_retry(self):
        self.metadata['reason']='insufficient_credits'
        with self.assertRaises(routes.RunFatal):self.invoke()
        self.assertEqual(len(self.requests),1);self.assertEqual(self.waits,[])
        self.assertTrue(self.ledger()['blocked'])

    def test_wrong_limit_source_is_fatal(self):
        self.metadata['limit_source']='other'
        with self.assertRaises(routes.RunFatal):self.invoke()
        self.assertEqual(len(self.requests),1);self.assertEqual(self.waits,[])

    def test_invalid_retry_after_is_fatal(self):
        self.metadata['headers']['Retry-After']='nan'
        with self.assertRaises(routes.RunFatal):self.invoke()
        self.assertEqual(len(self.requests),1);self.assertEqual(self.waits,[])


if __name__=='__main__':unittest.main()

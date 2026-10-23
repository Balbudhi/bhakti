"""Real local HTTP/worker/ledger checks for explicit Pro and scoped failures."""
import http.server
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import process_song_gemini as client
import bhakti_model_routes as routes


class ProTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.requests=[];self.mode='success';self.audio=False
        outer=self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])));outer.requests.append(payload)
                flash=payload['model']==routes.FLASH_MODEL
                status=503 if outer.mode=='transient' and flash else (401 if outer.mode=='auth' else 200)
                self.send_response(status);self.end_headers()
                if outer.mode=='timeout' and flash:
                    try:
                        for _ in range(200):self.wfile.write(b' ');self.wfile.flush();time.sleep(.03)
                    except (BrokenPipeError,ConnectionResetError):pass
                    return
                content='not json' if outer.mode=='malformed' and flash else '{"ok":true}'
                result={'model':payload['model'],'provider':'local fixture',
                        'choices':[{'message':{'content':content},'finish_reason':'stop'}],
                        'usage':{'cost':.00001}}
                self.wfile.write(json.dumps(result).encode())
        self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        p=patch.dict(os.environ,{'BHAKTI_GEMINI_PROVIDER':'openrouter','BHAKTI_API_RUN_LEDGER':str(self.root/'ledger.json'),
                                'BHAKTI_API_RUN_BUDGET_USD':'1.0'})
        p.start();self.addCleanup(p.stop)
        for p in (patch.object(client,'API_URL',f'http://127.0.0.1:{self.server.server_port}/'),
                  patch.object(client,'_wait_for_api_start')):
            p.start();self.addCleanup(p.stop)

    def ledger(self):return json.loads((self.root/'ledger.json').read_text())

    def execute(self,ctx,prompt='fixture'):
        return client.call(ctx.model,'fixture-secret-never-persist',prompt,audio=None,timeout=ctx.call_timeout_seconds,
            deadline_at=ctx.deadline_at,max_completion_tokens=512,unit_context=ctx.transport_context)

    def run_route(self,execute=None,**kw):
        return routes.run_unit(self.root/'routes','song:semantic','a'*64,execute or self.execute,
            lambda value:[],deadline_at=time.time()+30,**kw)

    def test_pro_explicit_route_has_correct_price_caps_and_persisted_model(self):
        result=self.run_route(base_model=routes.PRO_MODEL,pro_model=routes.PRO_MODEL)
        self.assertTrue(result['packet']['ok'])
        self.assertEqual(self.requests[0]['provider']['max_price'],{'prompt':2.,'completion':12.})
        self.assertEqual(self.ledger()['requests'][0]['model'],routes.PRO_MODEL)
        self.assertEqual(self.ledger()['requests'][0]['pricing_tier'],'standard')
        for path in self.root.rglob('*.json'):
            self.assertNotIn('fixture-secret-never-persist',path.read_text())

    def test_pro_long_context_tier_uses_upper_bound_even_before_actual_usage(self):
        self.run_route(lambda ctx:self.execute(ctx,'a'*200000),base_model=routes.PRO_MODEL,pro_model=routes.PRO_MODEL)
        row=self.ledger()['requests'][0]
        self.assertGreaterEqual(row['input_token_upper_bound'],200000)
        self.assertEqual(row['pricing_tier'],'long-context')
        self.assertEqual(self.requests[0]['provider']['max_price'],{'prompt':4.,'completion':18.})
        expected=math.ceil((row['input_token_upper_bound']*4+512*18)/1e6*1e8)/1e8
        self.assertEqual(row['reservation_usd'],expected)

    def test_transient_failure_blocks_attempt_only_then_one_pro_on_same_ledger(self):
        self.mode='transient';self.run_route()
        ledger=self.ledger();self.assertFalse(ledger['blocked'])
        self.assertEqual([r['model'] for r in ledger['requests']],[routes.FLASH_MODEL,routes.PRO_MODEL])
        self.assertEqual(len(ledger['blocked_attempts']),1)
        self.assertTrue(all(Path(row['response_path']).is_file() for row in ledger['requests']))

    def test_unknown_outcome_retains_full_reservation_and_worker_is_dead_before_pro(self):
        self.mode='timeout'
        def execute(ctx):
            if ctx.model==routes.PRO_MODEL:
                import subprocess
                first=self.ledger()['requests'][0]
                self.assertEqual(first['status'],'unknown-outcome')
                self.assertNotIn('reported_cost_usd',first)
                self.assertTrue(first['worker_terminated'])
                self.assertFalse(subprocess.run(['ps','-p',str(first['worker_pid']),'-o','pid='],capture_output=True,text=True).stdout.strip())
            return client.call(ctx.model,'fixture-secret-never-persist','fixture',audio=None,timeout=1.5 if ctx.model==routes.FLASH_MODEL else 3,
                deadline_at=ctx.deadline_at,max_completion_tokens=512,unit_context=ctx.transport_context)
        self.run_route(execute)
        ledger=self.ledger();self.assertFalse(ledger['blocked']);self.assertEqual(len(ledger['requests']),2)
        self.assertGreater(ledger['requests'][0]['reservation_usd'],0)

    def test_malformed_model_json_is_saved_and_scoped_not_hidden(self):
        self.mode='malformed';self.run_route()
        ledger=self.ledger();self.assertFalse(ledger['blocked'])
        self.assertEqual(len(ledger['requests']),2)
        self.assertEqual(ledger['requests'][0]['status'],'invalid-model-output')
        self.assertIn('not json',Path(ledger['requests'][0]['response_path']).read_text())

    def test_auth_failure_is_runfatal_without_pro_or_unblocking(self):
        self.mode='auth'
        with self.assertRaises(routes.RunFatal):self.run_route()
        self.assertTrue(self.ledger()['blocked']);self.assertEqual(len(self.requests),1)

    def test_budget_failure_before_pro_does_not_discard_failed_flash_reservation(self):
        self.mode='timeout'
        def execute(ctx):
            return client.call(ctx.model,'fixture-secret-never-persist','fixture',audio=None,timeout=1.5,
                deadline_at=ctx.deadline_at,max_completion_tokens=512,unit_context=ctx.transport_context)
        with patch.dict(os.environ,{'BHAKTI_API_RUN_BUDGET_USD':'.007'}):
            with self.assertRaises(routes.RunFatal):self.run_route(execute)
        self.assertEqual(len(self.requests),1)
        self.assertEqual(self.ledger()['requests'][0]['status'],'unknown-outcome')
        self.assertGreater(self.ledger()['requests'][0]['reservation_usd'],0)

    def test_attempt_context_model_mismatch_fails_before_dispatch(self):
        def execute(ctx):
            context={**ctx.transport_context,'model':routes.PRO_MODEL}
            return client.call(ctx.model,'fixture-secret-never-persist','fixture',audio=None,timeout=3,
                max_completion_tokens=512,unit_context=context)
        with self.assertRaises(routes.RunFatal):self.run_route(execute)
        self.assertEqual(self.requests,[])

    def test_native_audio_pro_request_preserves_audio_and_reserves_its_tokens(self):
        import wave
        audio=self.root/'one-second.wav'
        with wave.open(str(audio),'wb') as handle:
            handle.setnchannels(1);handle.setsampwidth(2);handle.setframerate(16000)
            handle.writeframes(b'\x00\x00'*16000)
        def execute(ctx):
            return client.call(ctx.model,'fixture-secret-never-persist','listen',audio=audio,timeout=3,
                deadline_at=ctx.deadline_at,max_completion_tokens=512,unit_context=ctx.transport_context)
        self.run_route(execute,base_model=routes.PRO_MODEL,pro_model=routes.PRO_MODEL)
        self.assertTrue(any(part['type']=='input_audio' for part in self.requests[0]['messages'][0]['content']))
        row=self.ledger()['requests'][0]
        self.assertGreaterEqual(row['input_token_upper_bound'],1024+32)
        evidence=json.loads(Path(row['response_path'].replace('.response.json','.request.json')).read_text())
        audio_part=next(part for part in evidence['messages'][0]['content'] if part['type']=='input_audio')
        self.assertIsInstance(audio_part['input_audio']['data'],dict)
        self.assertIn('base64_sha256',audio_part['input_audio']['data'])

    def test_legacy_no_context_failure_still_globally_blocks(self):
        self.mode='transient'
        with self.assertRaises(RuntimeError):client.call(routes.FLASH_MODEL,'fixture-secret-never-persist','fixture',audio=None,timeout=3,max_completion_tokens=512)
        self.assertTrue(self.ledger()['blocked']);self.assertEqual(len(self.requests),1)


if __name__=='__main__':unittest.main()

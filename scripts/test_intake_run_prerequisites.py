"""Actual CLI/ledger prerequisite tests for review BEFORE implementation.
Expensive song stages are replaced; shared filesystem ledger and worker pool are real.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock
import bhakti_pipeline as p

ENV_KEYS=('BHAKTI_API_RUN_LEDGER','BHAKTI_API_RUN_BUDGET_USD','BHAKTI_API_RUN_MAX_CALLS')


class IntakeRunPrerequisites(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.input=self.root/'input.m4a';self.input.write_bytes(b'source identity fixture; no decoder in these tests')
        self.envpatch=mock.patch.dict(os.environ,{k:v for k,v in os.environ.items() if k not in ENV_KEYS},clear=True)
        self.envpatch.start();self.rootpatch=mock.patch.object(p,'ROOT',self.root);self.rootpatch.start()
        self.calls=[]

    def tearDown(self):
        self.rootpatch.stop();self.envpatch.stop();self.tmp.cleanup()

    def invoke(self, argv=(), worker=None, count=1):
        args=['bhakti_pipeline.py']
        for i in range(count):args += ['--song',f'song-{i}={self.input}']
        args += list(argv)
        worker=worker or self.worker
        with mock.patch('sys.argv',args),mock.patch.object(p,'preflight_blocked_reason',return_value=None), \
             mock.patch.object(p,'run_one',side_effect=worker),contextlib.redirect_stdout(io.StringIO()):
            try:return p.main()
            except (ValueError,RuntimeError,SystemExit):return 1

    def worker(self, job, options):
        ledger=Path(os.environ['BHAKTI_API_RUN_LEDGER'])
        budget=float(os.environ['BHAKTI_API_RUN_BUDGET_USD'])
        context={'slug':job['slug'],'ledger':str(ledger),'budget':budget,
                 'calls':int(os.environ['BHAKTI_API_RUN_MAX_CALLS']),
                 'deadline':options.unit_deadline_at,'boundary_deadline':options.boundary_deadline_at,
                 'timing_deadline':options.timing_deadline_at}
        self.calls.append(context)
        with p.gemini._locked_run_ledger(ledger,budget) as record:
            record['requests'].append({'id':f"fixture-{len(record['requests'])}",'status':'parsed',
                                       'reservation_usd':.02,'reported_cost_usd':.01})
        return {'slug':job['slug'],'status':'review-required','reported_openrouter_cost':.01}

    def test_parse_args_accepts_explicit_whole_run_limits(self):
        with mock.patch('sys.argv',['bhakti_pipeline.py','--song',f'fixture={self.input}',
             '--run-dir',str(self.root/'.transcription'/'private'),'--budget-usd','.75','--max-calls','30','--deadline-seconds','120']):
            options=p.parse_args()
        self.assertEqual(options.run_dir,self.root/'.transcription'/'private')
        self.assertEqual((options.budget_usd,options.max_calls,options.deadline_seconds),(.75,30,120))

    def test_default_run_initializes_one_shared_bounded_ledger_for_seven_workers_and_restores_environment(self):
        barrier=threading.Barrier(7)
        def worker(job,options):
            barrier.wait(timeout=5)
            return self.worker(job,options)
        self.assertEqual(self.invoke(count=7,worker=worker),0)
        self.assertEqual(len(self.calls),7)
        self.assertEqual(len({c['ledger'] for c in self.calls}),1)
        self.assertEqual({c['budget'] for c in self.calls},{1.})
        self.assertEqual({c['calls'] for c in self.calls},{128})
        self.assertEqual(len({c['deadline'] for c in self.calls}),1)
        self.assertTrue(all(c['deadline']==c['boundary_deadline']==c['timing_deadline'] for c in self.calls))
        ledger=Path(self.calls[0]['ledger']);record=json.loads(ledger.read_text())
        self.assertTrue(ledger.is_relative_to(self.root/'.transcription'/'intake-runs'))
        self.assertEqual(len(record['requests']),7)
        self.assertEqual(record['deadline_at'],self.calls[0]['deadline'])
        self.assertTrue(all(k not in os.environ for k in ENV_KEYS))

    def test_resume_keeps_paid_prefix_and_original_deadline_without_new_allowance(self):
        self.assertEqual(self.invoke(),0)
        path=Path(self.calls[-1]['ledger']);first=json.loads(path.read_text());deadline=self.calls[-1]['deadline']
        with mock.patch.object(p.time,'time',return_value=time.time()+20):
            self.assertEqual(self.invoke(),0)
        resumed=json.loads(path.read_text())
        self.assertEqual(resumed['requests'][:len(first['requests'])],first['requests'])
        self.assertEqual(resumed['deadline_at'],deadline)
        self.assertEqual(self.calls[-1]['deadline'],deadline)
        self.assertEqual(len(list((self.root/'.transcription'/'intake-runs').glob('*/api-ledger.json'))),1)

    def test_existing_environment_ledger_limits_and_charges_are_preserved(self):
        ledger=self.root/'.transcription'/'external'/'api-ledger.json';ledger.parent.mkdir(parents=True)
        original={'version':1,'budget_usd':.4,'max_calls':9,'blocked':False,'requests':[
            {'id':'paid-earlier','status':'parsed','reservation_usd':.03,'reported_cost_usd':.02}]}
        ledger.write_text(json.dumps(original))
        configured={'BHAKTI_API_RUN_LEDGER':str(ledger),'BHAKTI_API_RUN_BUDGET_USD':'.4','BHAKTI_API_RUN_MAX_CALLS':'9'}
        with mock.patch.dict(os.environ,configured):
            self.assertEqual(self.invoke(),0)
            self.assertEqual({k:os.environ[k] for k in ENV_KEYS},configured)
        record=json.loads(ledger.read_text())
        self.assertEqual(record['requests'][0],original['requests'][0])
        self.assertEqual((record['budget_usd'],record['max_calls']),(.4,9))
        self.assertEqual(self.calls[-1]['ledger'],str(ledger))

    def test_changed_limits_input_or_expired_run_refuse_before_workers_and_keep_charges(self):
        run_dir=self.root/'.transcription'/'private';argv=['--run-dir',str(run_dir),'--budget-usd','.5','--max-calls','10','--deadline-seconds','120']
        self.assertEqual(self.invoke(argv),0)
        ledger=Path(self.calls[-1]['ledger']);before=ledger.read_bytes();n=len(self.calls)
        changed=list(argv);changed[3]='.6'
        self.assertEqual(self.invoke(changed),1)
        self.assertEqual(len(self.calls),n);self.assertEqual(ledger.read_bytes(),before)
        self.input.write_bytes(b'changed source input')
        self.assertEqual(self.invoke(argv),1)
        self.assertEqual(len(self.calls),n);self.assertEqual(ledger.read_bytes(),before)
        self.input.write_bytes(b'source identity fixture; no decoder in these tests')
        with mock.patch.object(p.time,'time',return_value=self.calls[-1]['deadline']+1):
            self.assertEqual(self.invoke(argv),1)
        self.assertEqual(len(self.calls),n);self.assertEqual(ledger.read_bytes(),before)

    def test_unsettled_existing_request_is_not_replayed_or_reset(self):
        ledger=self.root/'.transcription'/'external.json'
        record={'version':1,'budget_usd':.5,'max_calls':10,'blocked':False,'requests':[
            {'id':'unknown','status':'dispatched','reservation_usd':.1}]}
        ledger.parent.mkdir(parents=True,exist_ok=True)
        ledger.write_text(json.dumps(record));before=ledger.read_bytes()
        with mock.patch.dict(os.environ,{'BHAKTI_API_RUN_LEDGER':str(ledger),
             'BHAKTI_API_RUN_BUDGET_USD':'.5','BHAKTI_API_RUN_MAX_CALLS':'10'}):
            self.assertEqual(self.invoke(),1)
        self.assertEqual(self.calls,[]);self.assertEqual(ledger.read_bytes(),before)

    def test_generate_only_does_not_initialize_run_or_access_credentials(self):
        args=['bhakti_pipeline.py','--song','fixture=unused','--generate-only','--budget-usd','-1']
        with mock.patch('sys.argv',args),mock.patch.object(p.gemini,'key',side_effect=AssertionError('credential access')), \
             mock.patch.object(p.gemini,'call',side_effect=AssertionError('provider call')), \
             mock.patch.object(p,'hydrate_pipeline_artifacts'),mock.patch.object(p,'generate'), \
             mock.patch.object(p,'write_catalogue'),mock.patch.object(p,'read_packet',return_value={'packet':{}}), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(p.main(),0)
        self.assertFalse((self.root/'.transcription'/'intake-runs').exists())
        self.assertTrue(all(k not in os.environ for k in ENV_KEYS))

    def test_bounded_economy_text_is_rejected_before_spending_instead_of_silently_charging_full_price(self):
        self.assertEqual(self.invoke(['--economy']),1)
        self.assertEqual(self.calls,[])

    def test_persisted_deadline_blocks_actual_transport_even_without_caller_deadline(self):
        ledger=self.root/'.transcription'/'expired-ledger.json'
        record={'version':1,'budget_usd':1.,'max_calls':4,'deadline_at':time.time()-1,'requests':[],'blocked':False}
        ledger.parent.mkdir(parents=True,exist_ok=True)
        ledger.write_text(json.dumps(record));before=ledger.read_bytes()
        with mock.patch.dict(os.environ,{'BHAKTI_API_RUN_LEDGER':str(ledger),'BHAKTI_API_RUN_BUDGET_USD':'1',
             'BHAKTI_API_RUN_MAX_CALLS':'4','BHAKTI_GEMINI_PROVIDER':'openrouter'}), \
             mock.patch.object(p.gemini,'_wait_for_api_start'), \
             mock.patch.object(p.gemini.subprocess,'Popen',side_effect=AssertionError('must not dispatch')) as spawn:
            with self.assertRaises(RuntimeError) as failure:
                p.gemini.call(p.MODEL,'test-not-a-secret','fixture',audio=None,timeout=5,max_completion_tokens=512)
            spawn.assert_not_called()
            self.assertIn('deadline',str(failure.exception).lower())
        self.assertEqual(ledger.read_bytes(),before)

    def test_plain_cli_reaches_real_routed_boundary_transport_with_one_ledger(self):
        # Only the HTTP worker is replaced. FFmpeg, routed attempt records,
        # transport reservation/parse, detector, apply and main are actual.
        import re
        from test_boundary_application import create_audio
        song=self.root/'songs'/'song-0';song.mkdir(parents=True);create_audio(song)
        self.input=song/'audio.m4a'
        real_popen=p.gemini.subprocess.Popen
        dispatched=[]
        class HttpWorker:
            returncode=0
            pid=123456
            def communicate(self,input=None,timeout=None):
                job=json.loads(input);dispatched.append(job)
                payload=job['payload'];name=payload['response_format']['json_schema']['name']
                edge='start' if 'start' in name else 'end'
                prompt=payload['messages'][0]['content'][0]['text']
                endpoint=float(re.search(r'Keep endpoint relative to this clip: ([0-9.]+)',prompt).group(1))
                packet={'edge':edge,'decision':'keep','boundary':endpoint,'outside_type':'music',
                        'relationship':'attached_to_work','confidence':'high','reason':'Fixture observation',
                        'retained_evidence':'Continuous attached performance.','excluded_evidence':''}
                Path(job['response_path']).write_text(json.dumps({'model':payload['model'],
                    'choices':[{'message':{'content':json.dumps(packet)}}],'usage':{'cost':.001}}))
                return b'{"http_status":200}',b''
            def poll(self):return 0
            def kill(self):pass
        def popen(command,*args,**kwargs):
            if len(command)>2 and command[1]=='-c' and command[2]==p.gemini._BOUNDED_HTTP_WORKER:
                return HttpWorker()
            return real_popen(command,*args,**kwargs)
        args=['bhakti_pipeline.py','--song',f'song-0={self.input}']
        with mock.patch('sys.argv',args),mock.patch.object(p,'preflight_blocked_reason',return_value=None), \
             mock.patch.object(p,'intake',return_value=(song,{'source_file':self.input.name})), \
             mock.patch.object(p.gemini,'key',return_value='test-not-a-secret'), \
             mock.patch.object(p.gemini,'_wait_for_api_start'), \
             mock.patch.object(p.gemini.subprocess,'Popen',side_effect=popen), \
             mock.patch.object(p,'transcript',return_value={'packet':{}}), \
             mock.patch.object(p,'audit_transcript',return_value={'packet':{}}), \
             mock.patch.object(p,'apply_verified_text_corrections',return_value=False), \
             mock.patch.object(p,'align',return_value={}), \
             mock.patch.object(p,'complete_semantics',return_value=({},{})), \
             mock.patch.object(p,'publication_errors',return_value=[]),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(p.main(),0)
        self.assertEqual(len(dispatched),2)
        ledgers=list((self.root/'.transcription'/'intake-runs').glob('*/api-ledger.json'))
        self.assertEqual(len(ledgers),1)
        ledger=json.loads(ledgers[0].read_text())
        self.assertEqual([r['status'] for r in ledger['requests']],['parsed','parsed'])
        self.assertAlmostEqual(sum(r['reported_cost_usd'] for r in ledger['requests']),.002)
        self.assertTrue(all(r['unit_context']['deadline_at']<=ledger['deadline_at'] for r in ledger['requests']))
        self.assertEqual(p.read_packet(song/'.transcription'/'trim-review.json')['status'],'reviewed')

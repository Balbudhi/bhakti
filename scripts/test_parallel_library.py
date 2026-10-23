"""Coordinator contracts; transport case uses real subprocess/local HTTP/ledger."""
import copy
import subprocess
import http.server
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import bhakti_library_pass as library
import bhakti_model_routes as routes


class ParallelLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.root = self.base / 'repo'; self.root.mkdir()
        self.state = self.base / 'state'; self.state.mkdir()
        self.rows = [dict(slug=s, fingerprints={'all': s + '-input'}) for s in ('alpha','beta','gamma')]
        self.inventory = {'catalogueRevision':'fixed', 'songs':self.rows}
        self.options = SimpleNamespace(slugs=None, budget_usd=1., max_calls=20,
            deadline_seconds=60., timeout=5., workers=2,
            model=routes.FLASH_MODEL, pro_model=routes.PRO_MODEL,
            source_reuse_maps={}, editorial_adjudications={})
        self.env = patch.dict(os.environ)
        self.env.start(); self.addCleanup(self.env.stop)
        for key in ('BHAKTI_API_RUN_LEDGER','BHAKTI_API_RUN_BUDGET_USD','BHAKTI_API_RUN_MAX_CALLS'):
            os.environ.pop(key, None)

    def run_inventory(self):
        return library.execute_inventory(self.root,self.inventory,self.state,self.options)

    def held(self, slug):
        return {'status':'protected', 'publicationEligible':False, 'slug':slug}

    def test_ready_jobs_overlap_and_only_coordinator_writes_run(self):
        self.inventory['songs'] = self.rows[:2]
        barrier=threading.Barrier(2); coordinator=threading.get_ident(); writers=[]; seen=[]
        original=library.pipeline.semantic_write_json
        def save(path,value):
            if Path(path).name == 'run.json': writers.append(threading.get_ident())
            return original(path,value)
        def job(root,row,state,options,deadline):
            seen.append((row['slug'],threading.get_ident(),id(options)))
            barrier.wait(timeout=1)
            self.assertEqual(os.environ['BHAKTI_API_RUN_LEDGER'],str(self.state/'api-ledger.json'))
            return self.held(row['slug'])
        with patch.object(library,'execute_song',side_effect=job), patch.object(library.pipeline,'semantic_write_json',side_effect=save):
            result=self.run_inventory()
        self.assertEqual(result['status'],'complete')
        self.assertEqual(len(seen),2); self.assertEqual(len({r[1] for r in seen}),2)
        self.assertEqual(len({r[2] for r in seen}),2, 'workers share mutable options')
        self.assertTrue(writers); self.assertEqual(set(writers),{coordinator})
        self.assertNotIn('BHAKTI_API_RUN_LEDGER',os.environ)

    def test_quality_hold_does_not_block_successful_peer_or_next_song(self):
        entered=threading.Event(); calls=[]
        def job(root,row,state,options,deadline):
            calls.append(row['slug'])
            if row['slug']=='alpha':
                self.assertTrue(entered.wait(1),'peer never began while first was held')
                raise routes.UnitUnresolved('alpha:review','quality failure',[],state/'route.json')
            entered.set(); return self.held(row['slug'])
        with patch.object(library,'execute_song',side_effect=job): result=self.run_inventory()
        self.assertEqual(result['status'],'unresolved'); self.assertEqual(result['remaining'],[])
        self.assertEqual(set(calls),{'alpha','beta','gamma'})
        self.assertEqual(result['songs']['alpha']['status'],'unresolved')
        self.assertEqual(result['songs']['beta']['status'],'protected')

    def test_fatal_stops_replenishment_but_drains_active_and_preserves_queue(self):
        barrier=threading.Barrier(2); calls=[]
        def job(root,row,state,options,deadline):
            calls.append(row['slug']); barrier.wait(timeout=1)
            if row['slug']=='alpha': raise routes.RunFatal('confirmed ledger stop')
            time.sleep(.03)
            self.assertIn('BHAKTI_API_RUN_LEDGER',os.environ)
            return self.held(row['slug'])
        with patch.object(library,'execute_song',side_effect=job): result=self.run_inventory()
        self.assertEqual(set(calls),{'alpha','beta'})
        self.assertEqual(result['status'],'bounded-stop')
        self.assertEqual(result['remaining'],['alpha','gamma'])
        self.assertEqual(set(result['songs']),{'beta'})
        self.assertNotIn('BHAKTI_API_RUN_LEDGER',os.environ)

    def test_deadline_stops_new_jobs_and_retains_completed_peers(self):
        clock=[100.]; barrier=threading.Barrier(2); calls=[]
        def job(root,row,state,options,deadline):
            calls.append(row['slug']); barrier.wait(timeout=1)
            clock[0]=161.; return self.held(row['slug'])
        with patch.object(library,'time',SimpleNamespace(time=lambda:clock[0])), patch.object(library,'execute_song',side_effect=job):
            result=self.run_inventory()
        self.assertEqual(set(calls),{'alpha','beta'}); self.assertEqual(result['remaining'],['gamma'])
        self.assertEqual(result['status'],'bounded-stop'); self.assertEqual(len(result['songs']),2)

    def test_duplicate_inventory_slug_rejected_before_any_work(self):
        self.inventory['songs']=[self.rows[0],copy.deepcopy(self.rows[0])]
        with patch.object(library,'execute_song',side_effect=AssertionError('duplicate dispatched')) as job:
            with self.assertRaisesRegex(ValueError,'duplicate|unique'):self.run_inventory()
        job.assert_not_called()

    def test_invalid_worker_counts_fail_before_any_work(self):
        for value in (0,-1,True,1.5,'2'):
            with self.subTest(workers=value):
                self.options.workers=value
                with patch.object(library,'execute_song',side_effect=AssertionError('invalid workers dispatched')) as job:
                    with self.assertRaisesRegex(ValueError,'workers'):self.run_inventory()
                job.assert_not_called()

    def test_interruption_drains_peer_and_resume_never_replays_uncertain_route(self):
        self.inventory['songs']=self.rows[:2]; barrier=threading.Barrier(2); dispatched=[]
        def job(root,row,state,options,deadline):
            if row['slug']=='beta':
                barrier.wait(timeout=1); time.sleep(.03); return self.held('beta')
            def execute(ctx):
                dispatched.append(ctx.attempt_id); barrier.wait(timeout=1)
                raise KeyboardInterrupt('simulate interrupted dispatched stage')
            return routes.run_unit(state/'routes','alpha:review','input',execute,lambda _:[],deadline_at=deadline)
        with patch.object(library,'execute_song',side_effect=job):
            with self.assertRaises(KeyboardInterrupt): self.run_inventory()
        saved=json.loads((self.state/'run.json').read_text())
        self.assertEqual(saved['status'],'interrupted'); self.assertEqual(saved['remaining'],['alpha'])
        self.assertEqual(saved['songs']['beta']['status'],'protected')
        self.options.workers=1 # Scheduling is not frozen evidence identity.
        def resume(root,row,state,options,deadline):
            self.assertEqual(row['slug'],'alpha')
            return routes.run_unit(state/'routes','alpha:review','input',
                lambda ctx:self.fail('interrupted request redispatched'),lambda _:[],deadline_at=deadline)
        with patch.object(library,'execute_song',side_effect=resume): result=self.run_inventory()
        self.assertEqual(len(dispatched),1)
        self.assertEqual(result['songs']['alpha']['status'],'unresolved')
        self.assertIn('reconciliation',str(result['songs']['alpha']))
        self.assertNotIn('BHAKTI_API_RUN_LEDGER',os.environ)

    def test_second_owner_rejected_without_replacing_active_environment(self):
        self.inventory['songs']=self.rows[:1]; entered=threading.Event(); release=threading.Event(); errors=[]
        def job(*args): entered.set(); release.wait(2); return self.held('alpha')
        def first():
            try:self.run_inventory()
            except BaseException as exc:errors.append(exc)
        with patch.object(library,'execute_song',side_effect=job):
            thread=threading.Thread(target=first); thread.start()
            try:
                self.assertTrue(entered.wait(1))
                with self.assertRaisesRegex(ValueError,'active|owner|execution'):self.run_inventory()
                self.assertEqual(os.environ['BHAKTI_API_RUN_LEDGER'],str(self.state/'api-ledger.json'))
            finally:release.set(); thread.join(3)
        self.assertFalse(thread.is_alive()); self.assertEqual(errors,[])

    def test_actual_shared_transport_call_cap_with_parallel_workers(self):
        self.options.workers=3; self.options.max_calls=2
        requests=[]; outer=self; active=[0]; maximum=[0]; lock=threading.Lock()
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                with lock:
                    requests.append(body); active[0]+=1; maximum[0]=max(maximum[0],active[0])
                time.sleep(.05)
                result={'model':body['model'],'provider':'local fixture',
                    'choices':[{'message':{'content':'{"ok":true}'},'finish_reason':'stop'}],
                    'usage':{'cost':.00001}}
                self.send_response(200);self.end_headers();self.wfile.write(json.dumps(result).encode())
                with lock:active[0]-=1
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        server.daemon_threads=True;threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        barrier=threading.Barrier(3)
        def job(root,row,state,options,deadline):
            barrier.wait(timeout=1)
            def execute(ctx):
                return library.pipeline.gemini.call(ctx.model,'fixture-secret',row['slug'],audio=None,
                    timeout=3,deadline_at=ctx.deadline_at,max_completion_tokens=512,unit_context=ctx.transport_context)
            routes.run_unit(state/'routes',row['slug']+':review',row['fingerprints']['all'],
                execute,lambda packet:[] if packet['packet']['ok'] else [{'kind':'bad','detail':'bad'}],deadline_at=deadline)
            return self.held(row['slug'])
        client=library.pipeline.gemini
        with patch.object(library,'execute_song',side_effect=job), patch.object(client,'API_URL',f'http://127.0.0.1:{server.server_port}/'), patch.object(client,'_wait_for_api_start'):
            result=self.run_inventory()
        self.assertTrue((self.state/'api-ledger.json').is_file(), 'no parallel request reached the real transport')
        ledger=json.loads((self.state/'api-ledger.json').read_text())
        self.assertEqual(len(requests),2);self.assertEqual(len(ledger['requests']),2)
        self.assertEqual(maximum[0],2,'real requests did not overlap')
        self.assertEqual(result['status'],'bounded-stop'); self.assertEqual(len(result['remaining']),1)
        self.assertEqual(len(result['songs']),2)
        self.assertLessEqual(result['ledger']['accounted_usd'],self.options.budget_usd)
        self.assertTrue(all(row['status']=='parsed' for row in ledger['requests']))
        self.assertEqual(client.API_MAX_CONCURRENCY,3)

    def test_coordinator_interrupt_drains_started_jobs_then_resume_runs_only_queue(self):
        both=threading.Barrier(3); release=threading.Event(); seen=[]
        def job(root,row,state,options,deadline):
            seen.append(row['slug']); both.wait(timeout=1);release.wait(1)
            return self.held(row['slug'])
        original_wait=library.concurrent.futures.wait
        first=[True]
        def interrupt_once(*args,**kwargs):
            if first[0]:
                first[0]=False;both.wait(timeout=1);release.set();raise KeyboardInterrupt('coordinator')
            return original_wait(*args,**kwargs)
        with patch.object(library,'execute_song',side_effect=job), patch.object(library.concurrent.futures,'wait',side_effect=interrupt_once):
            with self.assertRaises(KeyboardInterrupt):self.run_inventory()
        saved=json.loads((self.state/'run.json').read_text())
        self.assertEqual(saved['status'],'interrupted');self.assertEqual(saved['remaining'],['gamma'])
        self.assertEqual(set(saved['songs']),{'alpha','beta'})
        deadline=saved['deadline_at']
        self.options.workers=1
        with patch.object(library,'execute_song',side_effect=lambda root,row,*_:self.held(row['slug'])) as resumed:
            result=self.run_inventory()
        self.assertEqual([call.args[1]['slug'] for call in resumed.call_args_list],['gamma'])
        self.assertEqual(result['deadline_at'],deadline);self.assertEqual(result['status'],'complete')
        self.assertNotIn('BHAKTI_API_RUN_LEDGER',os.environ)

    def test_cli_default_seven_and_explicit_worker_setting(self):
        for extra, expected in (([],7),(['--workers','3'],3)):
            with self.subTest(arguments=extra):
                def execute(root,inventory,state,options):
                    self.assertEqual(options.workers,expected)
                    return {'status':'complete','remaining':[],'ledger':{}}
                with patch.object(library,'build_inventory',return_value={'counts':{},'songs':[], 'catalogueRevision':'fixed'}), patch.object(library,'execute_inventory',side_effect=execute):
                    self.assertEqual(library.main(['--root',str(self.root),'--state-dir',str(self.state),'--execute','--budget-usd','1','--max-calls','2',*extra]),0)

    def test_other_process_state_owner_rejected_before_worker(self):
        source = "import fcntl,sys; f=open(sys.argv[1],'a'); fcntl.flock(f,fcntl.LOCK_EX); print('ready',flush=True); sys.stdin.read()"
        proc=subprocess.Popen([sys.executable,'-c',source,str(self.state/'.execution.lock')],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        try:
            self.assertEqual(proc.stdout.readline().strip(),'ready')
            with patch.object(library,'execute_song',side_effect=AssertionError('state has another owner')) as job:
                with self.assertRaisesRegex(ValueError,'active|owner|execution'):self.run_inventory()
            job.assert_not_called()
        finally:
            proc.communicate('');self.assertEqual(proc.returncode,0)

    def test_late_tampered_acceptance_preflight_blocks_earlier_new_job(self):
        self.inventory['songs']=self.rows[:2]
        # Persist an ordinary held result, then deliberately replace beta's
        # recorded state with an accepted marker missing its required evidence.
        with patch.object(library,'execute_song',side_effect=lambda root,row,*_:self.held(row['slug'])):
            self.run_inventory()
        path=self.state/'run.json';run=json.loads(path.read_text())
        del run['songs']['alpha'];run['remaining']=['alpha']
        run['songs']['beta']={'status':'accepted','publicationEligible':True}
        path.write_text(json.dumps(run))
        with patch.object(library,'execute_song',side_effect=AssertionError('new job before resume validation')) as job:
            with self.assertRaisesRegex(ValueError,'finding evidence'):self.run_inventory()
        job.assert_not_called()


class RealParallelStageTests(unittest.TestCase):
    # Use the existing committed-reader fixtures, but exercise the actual
    # caller→stage→router→client→worker chain against local HTTP.
    from test_bhakti_library_pass import SelectivePassTests as _Fixture
    setUp = _Fixture.setUp
    git = _Fixture.git
    add_song = _Fixture.add_song
    commit = _Fixture.commit

    def test_two_real_source_reviews_overlap_accept_and_resume_without_dispatch(self):
        from test_library_execution import review
        self.add_song('alpha'); self.add_song('beta'); self.commit()
        originals={slug:(self.root/'songs'/slug/'data.js').read_bytes() for slug in ('alpha','beta')}
        requests=[]; barrier=threading.Barrier(2); failures=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_POST(self):
                try:
                    payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    requests.append(payload)
                    barrier.wait(timeout=2)
                    text='\n'.join(part['text'] for message in payload['messages'] for part in message['content'] if part['type']=='text')
                    evidence=json.JSONDecoder().raw_decode(text.split('EVIDENCE:\n',1)[1].lstrip())[0]
                    packet={'reviews':[review(item['source']['id']) for item in evidence]}
                    result={'model':payload['model'],'provider':'local fixture',
                        'choices':[{'message':{'content':json.dumps(packet)},'finish_reason':'stop'}], 'usage':{'cost':.00001}}
                    self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(result).encode())
                except BaseException as exc:
                    failures.append(repr(exc)); self.send_error(500)
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler); server.daemon_threads=True
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        client=library.pipeline.gemini
        command=['--root',str(self.root),'--state-dir',str(self.state),'--execute','--all',
                 '--workers','2','--budget-usd','1','--max-calls','2','--deadline-seconds','60']
        with patch.dict(os.environ), patch.object(client,'API_URL',f'http://127.0.0.1:{server.server_port}/'), patch.object(client,'key',return_value='local-fixture'), patch.object(client,'_wait_for_api_start'):
            for key in ('BHAKTI_API_RUN_LEDGER','BHAKTI_API_RUN_BUDGET_USD','BHAKTI_API_RUN_MAX_CALLS'):
                os.environ.pop(key,None)
            library.main(command); library.main(command)
        self.assertEqual(failures,[]);self.assertEqual(len(requests),2)
        run=json.loads((self.state/'run.json').read_text())
        self.assertEqual(run['status'],'complete');self.assertEqual(run['remaining'],[])
        self.assertTrue(all(row['status']=='accepted' for row in run['songs'].values()))
        self.assertEqual(originals,{slug:(self.root/'songs'/slug/'data.js').read_bytes() for slug in originals})


if __name__=='__main__':unittest.main()

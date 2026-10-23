"""Explicit source continuation never resets a terminal route or frozen budget."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import bhakti_library_pass as library
import test_bhakti_library_pass as fixtures


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


class ReconciliationTests(unittest.TestCase):
    git = fixtures.SelectivePassTests.git
    add_song = fixtures.SelectivePassTests.add_song
    commit = fixtures.SelectivePassTests.commit
    inventory = fixtures.SelectivePassTests.inventory
    def setUp(self):
        fixtures.SelectivePassTests.setUp(self)
        self.add_song('patta');self.add_song('rehna');self.commit()
        self.inv=self.inventory()
        for row in self.inv['songs']:row['plannedStages']=['source-merge','current-content-review']
        self.options=SimpleNamespace(slugs=None,budget_usd=3,max_calls=12,deadline_seconds=3600,
            model='google/gemini-3.7-flash',pro_model='google/gemini-3.1-pro-preview',
            source_reuse_maps={},editorial_adjudications={})
        self.old_results={s:{'status':'unresolved','publicationEligible':False,
            'source':{'status':'unresolved','issues':[{'kind':'source_unit_unresolved','detail':s+' failed'}]}}
            for s in ('patta','rehna')}
        with patch.object(library,'execute_song',side_effect=lambda root,row,*args:self.old_results[row['slug']]):
            library.execute_inventory(self.root,self.inv,self.state,self.options)
        self.original_run=(self.state/'run.json').read_bytes()
        self.route=self.state/'routes/unit-fingerprint/route-state.json'
        self.candidate=self.route.parent/'flash/candidate.json'
        write(self.route,{'unit_id':'patta:new-source-semantics','status':'unresolved',
                         'attempts':[{'attempt_id':'flash','status':'quality-failed'},
                                     {'attempt_id':'pro','status':'quality-failed'}]})
        write(self.candidate,{'saved':'complete primary candidate; semantic verifier owned separately'})
        self.decision=self.base/'decision.json'
        write(self.decision,{'version':1,'decision_kind':'retain_existing_primary',
            'unit_id':'patta:new-source-semantics','route_state_path':str(self.route),
            'route_state_sha256':library.file_hash(self.route),'candidate_path':str(self.candidate),
            'candidate_file_sha256':library.file_hash(self.candidate)})
        write(self.state/'api-ledger.json',{'version':1,'budget_usd':3,'max_calls':12,
            'requests':[{'id':str(i),'reported_cost_usd':.1} for i in range(7)],'blocked':False})
        self.freeze_ledger()
        self.original_evidence={p:p.read_bytes() for p in (self.route,self.candidate,self.state/'api-ledger.json')}

    def freeze_ledger(self):
        record=json.loads(self.decision.read_text())
        record['run_ledger_sha256']=library.file_hash(self.state/'api-ledger.json')
        write(self.decision,record)
        run=json.loads((self.state/'run.json').read_text())
        run['ledger']=library.ledger_summary(self.state/'api-ledger.json')
        write(self.state/'run.json',run)
        self.original_run=(self.state/'run.json').read_bytes()

    def invoke(self,explicit=True):
        self.options.editorial_adjudications={'patta:new-source-semantics':str(self.decision)} if explicit else {}
        return library.execute_inventory(self.root,self.inv,self.state,self.options)

    def test_no_explicit_decision_never_reopens_terminal_song(self):
        with patch.object(library,'execute_song') as execute:self.invoke(False)
        execute.assert_not_called()

    def test_explicit_continuation_preserves_old_results_sibling_attempts_budget_and_deadline(self):
        continued={'status':'unresolved','publicationEligible':False,'issues':['later gate unresolved']}
        with patch.object(library,'execute_song',return_value=continued) as execute:
            result=self.invoke()
        self.assertEqual(execute.call_count,1);self.assertEqual(execute.call_args.args[1]['slug'],'patta')
        self.assertEqual(execute.call_args.args[3].editorial_adjudications,self.options.editorial_adjudications)
        old=json.loads(self.original_run)
        self.assertEqual(result['identity'],old['identity']);self.assertEqual(result['deadline_at'],old['deadline_at'])
        self.assertEqual(result['songs']['rehna'],self.old_results['rehna'])
        self.assertEqual(result['songs']['patta'],continued)
        self.assertEqual(self.original_evidence,{p:p.read_bytes() for p in self.original_evidence})
        self.assertEqual(result['reconciliations'][0]['previousResult'],self.old_results['patta'])
        self.assertEqual(result['reconciliations'][0]['phase'],'authorized')
        self.assertEqual(result['reconciliations'][1]['phase'],'completed')
        self.assertEqual(Path(result['reconciliations'][0]['originalRunPath']).read_bytes(),self.original_run)

    def test_completed_decision_cannot_retry_unresolved_result_again(self):
        with patch.object(library,'execute_song',return_value=self.old_results['patta']) as execute:
            first=self.invoke();second=self.invoke()
        self.assertEqual(execute.call_count,1);self.assertEqual(first['reconciliations'],second['reconciliations'])

    def test_changed_decision_or_candidate_rejects_before_dispatch(self):
        with patch.object(library,'execute_song',return_value=self.old_results['patta']):self.invoke()
        for path in (self.decision,self.candidate):
            old=path.read_bytes();path.write_bytes(old+b' ')
            with self.subTest(path=path.name),patch.object(library,'execute_song') as execute:
                with self.assertRaises(ValueError):self.invoke()
                execute.assert_not_called()
            path.write_bytes(old)

    def test_wrong_unit_or_outside_route_cannot_reopen(self):
        original=json.loads(self.decision.read_text())
        for updates in ({'unit_id':'rehna:new-source-semantics'},
                        {'route_state_path':str(self.base/'outside-route.json')}):
            write(self.decision,{**original,**updates})
            with self.subTest(updates=updates),patch.object(library,'execute_song') as execute:
                with self.assertRaises(ValueError):self.invoke()
                execute.assert_not_called()
        write(self.decision,original)

    def test_original_call_cap_blocks_continuation_without_erasing_unresolved(self):
        write(self.state/'api-ledger.json',{'version':1,'budget_usd':3,'max_calls':12,'requests':[{'reported_cost_usd':.01} for _ in range(12)],'blocked':False})
        self.freeze_ledger()
        with patch.object(library,'execute_song') as execute:result=self.invoke()
        execute.assert_not_called();self.assertEqual(result['songs'],self.old_results)
        self.assertEqual(result['deadline_at'],json.loads(self.original_run)['deadline_at'])
        self.assertEqual(result['status'],'bounded-stop')

    def test_original_expired_deadline_cannot_be_extended_by_continuation(self):
        run=json.loads(self.original_run);run['deadline_at']=0;write(self.state/'run.json',run)
        self.options.deadline_seconds=100000
        with patch.object(library,'execute_song') as execute:result=self.invoke()
        execute.assert_not_called();self.assertEqual(result['songs'],self.old_results)
        self.assertEqual(result['deadline_at'],0);self.assertEqual(result['status'],'bounded-stop')

    def test_accepted_or_protected_target_cannot_be_reopened(self):
        for status in ('accepted','protected'):
            run=json.loads(self.original_run);run['songs']['patta']['status']=status
            write(self.state/'run.json',run)
            with self.subTest(status=status),patch.object(library,'execute_song') as execute:
                with self.assertRaises(ValueError):self.invoke()
                execute.assert_not_called()

    def test_semantic_only_unresolved_song_is_not_reopened_by_source_receipt(self):
        row=next(r for r in self.inv['songs'] if r['slug']=='patta')
        row['plannedStages']=['current-content-review']
        with patch.object(library,'execute_song') as execute:
            with self.assertRaises(ValueError):self.invoke()
        execute.assert_not_called()

    def test_dollar_cap_does_not_dispatch(self):
        write(self.state/'api-ledger.json',{'version':1,'budget_usd':3,'max_calls':12,
              'requests':[{'reservation_usd':3}],'blocked':False})
        self.freeze_ledger()
        with patch.object(library,'execute_song') as execute:result=self.invoke()
        execute.assert_not_called();self.assertEqual(result['songs'],self.old_results)
        self.assertEqual(result['status'],'bounded-stop')

    def test_blocked_ledger_does_not_dispatch(self):
        ledger=json.loads((self.state/'api-ledger.json').read_text());ledger['blocked']=True
        write(self.state/'api-ledger.json',ledger);self.freeze_ledger()
        with patch.object(library,'execute_song') as execute:result=self.invoke()
        execute.assert_not_called();self.assertEqual(result['status'],'bounded-stop')

    def test_missing_truncated_or_substituted_original_ledger_rejects(self):
        path=self.state/'api-ledger.json';raw=path.read_bytes();old=json.loads(raw)
        variants=[None,{**old,'requests':[]},
                  {**old,'requests':[{**row,'id':'substituted'} for row in old['requests']]}]
        for ledger in variants:
            if ledger is None:path.unlink()
            else:write(path,ledger)
            with self.subTest(ledger=ledger),patch.object(library,'execute_song') as execute:
                with self.assertRaisesRegex(ValueError,'ledger'):self.invoke()
                execute.assert_not_called()
            path.write_bytes(raw)

    def test_original_ledger_archive_is_bound_to_reviewed_file_hash(self):
        with patch.object(library,'execute_song',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):self.invoke()
        run=json.loads((self.state/'run.json').read_text())
        event=run['reconciliations'][0]
        archive=self.state/'reconciliations'/event['id']/'original-api-ledger.json'
        original=json.loads(archive.read_text());original['requests']=[];write(archive,original)
        with patch.object(library,'execute_song') as execute:
            with self.assertRaisesRegex(ValueError,'ledger archive'):self.invoke()
        execute.assert_not_called()

    def test_pending_resume_retains_later_acknowledged_spending_after_fatal_stop(self):
        import bhakti_model_routes as routes
        path=self.state/'api-ledger.json';initial=json.loads(path.read_text())
        eighth=copy.deepcopy(initial);eighth['requests'].append({'id':'eighth-paid','reported_cost_usd':.2})
        def paid_then_stop(*args):
            write(path,eighth)
            raise routes.RunFatal('stop after paid eighth request')
        with patch.object(library,'execute_song',side_effect=paid_then_stop):stopped=self.invoke()
        self.assertEqual(stopped['status'],'bounded-stop')
        self.assertEqual(stopped['ledger']['calls'],8)
        # Same-count/cost substitution must also fail, not just aggregate rollback.
        substituted=copy.deepcopy(eighth);substituted['requests'][-1]['id']='different-request'
        for changed in (initial,substituted):
            write(path,changed)
            with self.subTest(ledger=changed),patch.object(library,'execute_song',side_effect=AssertionError('rollback dispatched')) as execute:
                with self.assertRaisesRegex(ValueError,'ledger'):self.invoke()
                execute.assert_not_called()
        # Legacy summaries without the new exact-prefix checkpoint still forbid cost/count rollback.
        saved=(self.state/'run.json').read_bytes();legacy=json.loads(saved)
        legacy.pop('ledgerCheckpoint',None);write(self.state/'run.json',legacy);write(path,initial)
        with patch.object(library,'execute_song') as execute:
            with self.assertRaisesRegex(ValueError,'ledger'):self.invoke()
            execute.assert_not_called()
        (self.state/'run.json').write_bytes(saved)
        ninth=copy.deepcopy(eighth);ninth['requests'].append({'id':'legitimate-ninth','reported_cost_usd':.1})
        write(path,ninth)
        with patch.object(library,'execute_song',return_value=self.old_results['patta']) as execute:resumed=self.invoke()
        self.assertEqual(execute.call_count,1)
        self.assertEqual(resumed['ledger']['calls'],9)
        self.assertEqual(json.loads(path.read_text()),ninth)
        self.assertEqual(resumed['deadline_at'],json.loads(self.original_run)['deadline_at'])

    def test_pending_resume_rejects_changed_prefix_but_allows_appended_requests(self):
        with patch.object(library,'execute_song',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):self.invoke()
        path=self.state/'api-ledger.json';old=json.loads(path.read_text())
        changed=copy.deepcopy(old);changed['requests'][0]['id']='substituted'
        write(path,changed)
        with patch.object(library,'execute_song') as execute:
            with self.assertRaisesRegex(ValueError,'ledger prefix'):self.invoke()
            execute.assert_not_called()
        appended=copy.deepcopy(old);appended['requests'].append({'id':'legitimate-next','reported_cost_usd':.1})
        write(path,appended)
        with patch.object(library,'execute_song',return_value=self.old_results['patta']) as execute:self.invoke()
        self.assertEqual(execute.call_count,1)
        self.assertEqual(json.loads(path.read_text()),appended)

    def test_accepted_source_checkpoint_cannot_reopen_later_text_failure(self):
        write(self.state/'songs/patta/source-checkpoint.json',{'result':{'status':'accepted'}})
        with patch.object(library,'execute_song') as execute:
            with self.assertRaisesRegex(ValueError,'completed source stage'):self.invoke()
        execute.assert_not_called()

    def test_pending_continuation_cannot_extend_persisted_deadline(self):
        with patch.object(library,'execute_song',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):self.invoke()
        run=json.loads((self.state/'run.json').read_text());run['deadline_at']+=3600
        write(self.state/'run.json',run)
        with patch.object(library,'execute_song') as execute:
            with self.assertRaisesRegex(ValueError,'frozen identity changed'):self.invoke()
        execute.assert_not_called()

    def test_cli_reads_explicit_unit_map_and_forwards_it_without_key_access(self):
        map_path=self.base/'decisions.json'
        write(map_path,{'patta:new-source-semantics':str(self.decision)})
        args=['--root',str(self.root),'--state-dir',str(self.state),'--execute','--all',
              '--budget-usd','3','--max-calls','12','--deadline-seconds','3600',
              '--editorial-adjudications',str(map_path)]
        with patch.object(library,'build_inventory',return_value=self.inv), \
             patch.object(library,'execute_song',return_value=self.old_results['patta']) as execute, \
             patch.object(library.pipeline.gemini,'key',side_effect=AssertionError('runner read credential')):
            self.assertEqual(library.main(args),0)
        self.assertEqual(execute.call_count,1)
        self.assertEqual(execute.call_args.args[3].editorial_adjudications,
                         {'patta:new-source-semantics':str(self.decision)})

    def test_interrupted_authorization_resumes_once_without_duplicate_history(self):
        with patch.object(library,'execute_song',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):self.invoke()
        pending=json.loads((self.state/'run.json').read_text())
        self.assertEqual([e['phase'] for e in pending['reconciliations']],['authorized'])
        with patch.object(library,'execute_song',return_value=self.old_results['patta']) as execute:result=self.invoke()
        self.assertEqual(execute.call_count,1)
        self.assertEqual([e['phase'] for e in result['reconciliations']],['authorized','completed'])

if __name__=='__main__':unittest.main()

"""Design tests for the existing benchmark's small replacement API.

These exercise orchestration and persistence only, never semantic correctness.
Prepared before implementation. Run with private candidate module preceding repo.
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import benchmark_translation_prompt as benchmark

class TranslationBenchmarkDesignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        self.case = {'id':'owner-example','slug':'owner-example','mode':'generation',
                     'target_ids':['a'],'owner_reference':True,'excerpt_start':0,'excerpt_end':2}
        self.reader = {'SONG_META':{'languages':['Punjabi']},
            'SONG_LINES':{'a':{'source':'ਮੇਰਾ ਮਨ','roman':'merā mana',
                'sourceLanguage':'pa','sourceWords':[{'text':'ਮੇਰਾ','wordIndices':[0]},
                {'text':'ਮਨ','wordIndices':[1]}],
                'words':[{'roman':'merā','gloss':'my'},{'roman':'mana','gloss':'mind'}],
                'english':'{0:OWNER_SECRET }{1:REFERENCE}'},
                'b':{'source':'ਹਰੀ','roman':'harī','sourceLanguage':'pa',
                'sourceWords':[{'text':'ਹਰੀ','wordIndices':[0]}],
                'words':[{'roman':'harī','gloss':'Lord'}], 'english':'{0:NEIGHBOR_SECRET}'}},
            'SONG_SEQUENCE':[{'ref':'a','repeats':1},{'ref':'b','repeats':1}],
            'SONG_TIMINGS':[0,2]}
        self.options = SimpleNamespace(model='fixture',timeout=30,force=False)
        self.gloss_packet={'packet':{'glosses':[{'id':'a','word_glosses':[
            {'roman':'merā','gloss':'my'},{'roman':'mana','gloss':'mind'}]}]}}
        self.translation_packet={'packet':{'translations':[{'id':'a','literal_english':'My mind',
            'segments':[{'text':'My ','word_indices':[0]},{'text':'mind','word_indices':[1]}],
            'independent_review':{'passes':True}}, {'id':'b','literal_english':'Lord', 'segments':[{'text':'Lord','word_indices':[0]}], 'independent_review':{'passes':True}}]}}

    def generation(self, failure=False):
        with patch.object(benchmark.pipeline,'gloss',return_value=self.gloss_packet) as gloss, \
             patch.object(benchmark.pipeline,'translate',side_effect=RuntimeError('truncated') if failure else None,
                          return_value=self.translation_packet) as translate:
            result=benchmark.run_generation_case(self.case,self.reader,self.out,self.options)
        return result,gloss.call_args,translate.call_args

    def test_generation_uses_real_separate_stages_language_and_source_context(self):
        _,gloss,translation=self.generation()
        audited=gloss.args[1]; opts=gloss.args[2]
        self.assertEqual(audited['packet']['metadata']['languages'],['Punjabi'])
        self.assertEqual([r['id'] for r in audited['packet']['verified_lines']],['a','b'])
        self.assertEqual({r['id'] for r in opts.semantic_full_source},{'a','b'})
        self.assertEqual(opts.semantic_performance_order,self.reader['SONG_SEQUENCE'])
        self.assertEqual(translation.args[3]['languages'],['Punjabi'])
        self.assertEqual(translation.args[2],self.gloss_packet)

    def test_owner_comparison_is_independent_and_original_not_mutated(self):
        before=copy.deepcopy(self.reader)
        _,gloss,translation=self.generation()
        self.assertNotIn('providedTranslation',translation.args[3])
        for call in (gloss,translation):
            payload=json.dumps([call.args[1],vars(call.args[-1])],default=str)
            self.assertNotIn('OWNER_SECRET',payload)
            self.assertNotIn('NEIGHBOR_SECRET',payload)
        self.assertEqual(self.reader,before)

    def test_private_case_directory_is_stable_and_force_is_false(self):
        _,first,_=self.generation();_,second,_=self.generation()
        self.assertEqual(first.args[0],second.args[0])
        self.assertTrue(first.args[0].is_relative_to(self.out))
        self.assertFalse(first.args[2].force)
        self.assertTrue(first.args[0].exists())

    def test_completed_gloss_artifact_survives_translation_failure(self):
        try:self.generation(failure=True)
        except RuntimeError:pass
        files=list(self.out.rglob('*.json'))
        self.assertTrue(any(json.loads(p.read_text())==self.gloss_packet for p in files))

    def test_model_approval_is_not_editorial_success(self):
        result=benchmark.comparison_record(self.case,self.reader,self.gloss_packet,self.translation_packet)
        self.assertEqual(result['semantic_status'],'not-reviewed')
        self.assertNotIn('passed',result)
        self.assertEqual(result['lines'][0]['original_english'],'OWNER_SECRET REFERENCE')
        self.assertEqual(result['lines'][0]['proposed_english'],'My mind')

    def test_flagging_bad_output_does_not_turn_it_into_success(self):
        bad=copy.deepcopy(self.translation_packet)
        bad['packet']['translations'][0]['literal_english']='Invented imagery'
        bad['packet']['translations'][0]['independent_review']['passes']=False
        result=benchmark.comparison_record(self.case,self.reader,self.gloss_packet,bad)
        self.assertEqual(result['semantic_status'],'not-reviewed')
        self.assertEqual(result['lines'][0]['proposed_english'],'Invented imagery')
        self.assertFalse(result['lines'][0]['independent_review']['passes'])

    def test_comparison_retains_index_maps_for_same_english_different_mapping(self):
        a=benchmark.comparison_record(self.case,self.reader,self.gloss_packet,self.translation_packet)
        bad=copy.deepcopy(self.translation_packet)
        bad['packet']['translations'][0]['segments'][0]['word_indices']=[1]
        b=benchmark.comparison_record(self.case,self.reader,self.gloss_packet,bad)
        self.assertEqual(a['lines'][0]['proposed_english'],b['lines'][0]['proposed_english'])
        self.assertNotEqual(a['lines'][0]['proposed_segments'],b['lines'][0]['proposed_segments'])


    def test_malformed_or_missing_generation_targets_are_rejected(self):
        for rows in ([], [self.translation_packet['packet']['translations'][1]],
                     [self.translation_packet['packet']['translations'][0]] * 2):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                benchmark.comparison_record(self.case,self.reader,self.gloss_packet,{'packet':{'translations':rows}})

    def test_preparation_never_replaces_snapshot_on_changed_reader(self):
        root=self.out/'repo';song=root/'songs'/'fixture';song.mkdir(parents=True)
        path=song/'data.js';raw='window.SONG_META={}; window.SONG_LINES={a:{english:"first"}};'
        path.write_text(raw)
        cases=[{'id':'x','slug':'fixture','origin':'working','target_ids':['a'],'mode':'diagnostic'}]
        output=self.out/'run'
        first=benchmark.prepare_benchmark(root,output,cases=cases)
        frozen=(output/'corpus/x.reader.json').read_bytes()
        self.assertEqual(benchmark.prepare_benchmark(root,output,cases=cases),first)
        path.write_text(raw.replace('first','changed'))
        with self.assertRaisesRegex(ValueError,'changed'):
            benchmark.prepare_benchmark(root,output,cases=cases)
        self.assertEqual((output/'corpus/x.reader.json').read_bytes(),frozen)
        self.assertTrue((output/'source-changes.json').exists())

    def test_actual_production_prompts_cannot_see_reference_english(self):
        import bhakti_translation_policy as policy
        prompts=[]
        def section(prompt,marker):
            return json.JSONDecoder().raw_decode(prompt.split(marker+'\n',1)[1].lstrip())[0]
        def provider(model,key,prompt,**kwargs):
            prompts.append(prompt); name=kwargs['schema_name']
            if name=='bhakti_word_glosses':
                lines=section(prompt,'TARGET LYRICS (return these IDs only):'); rows=[]
                for line in lines:
                    tokens=policy.token_candidates([line],['Punjabi'])[line['id']]
                    rows.append({'id':line['id'],'word_glosses':[{'roman':t['roman'],'gloss':'meaning','concept_key':'','preserve_in_english':False} for t in tokens],
                        'semantic_frame':{f:'' for f in benchmark.pipeline.SEMANTIC_FRAME_FIELDS},'grammar_note':'','uncertainty':'',
                        'sense_decisions':[{'word_index':t['word_index'],'roman':t['roman'],'evidence_status':'contextual_inference','chosen':[], 'rejected':[], 'contextual_reason':'fixture context','grammatical_role':'fixture role'} for t in tokens]})
                return {'packet':{'glosses':rows}}
            if name=='bhakti_literal_translation':
                lines=section(prompt,'TARGET audited source lines (return these IDs only):')
                return {'packet':{'translations':[{'id':line['id'],'literal_english':'Draft '+line['id'],
                    'segments':[{'text':'Draft '+line['id'],'word_indices':list(range(len(policy.word_tokens(line))))}],
                    'material_alternatives':[],'human_review_recommended':False,'choice_note':'','uncertainty':'',
                    'fidelity':{'agency_and_image_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[],'notes':''}} for line in lines], 'comparison':[]}}
            if name=='bhakti_translation_review':
                ids=section(prompt,'OUTPUT TARGET IDS (return exactly these, once each):')
                return {'packet':{'reviews':[{'id':i,'passes':True,'agency_preserved':True,'imagery_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[],'human_review_recommended':False,'material_choice':'','reason':'fixture only','issues':[]} for i in ids]}}
            raise AssertionError(name)
        with patch.object(benchmark.pipeline.gemini,'key',return_value='fake-no-key'),patch.object(benchmark.pipeline.gemini,'call',side_effect=provider):
            benchmark.run_generation_case(self.case,self.reader,self.out,self.options)
        self.assertEqual(len(prompts),3)
        for prompt in prompts:
            self.assertNotIn('OWNER_SECRET',prompt);self.assertNotIn('NEIGHBOR_SECRET',prompt)
        self.assertIn('Punjabi',prompts[0]);self.assertIn('ਮੇਰਾ ਮਨ',prompts[0]);self.assertIn('ਹਰੀ',prompts[0])


    def test_cli_prepare_does_not_dispatch_and_execute_requires_explicit_limits(self):
        root=self.out/'repo';song=root/'songs'/'owner-example';song.mkdir(parents=True)
        (song/'data.js').write_text(''.join('window.'+k+'='+json.dumps(v)+';' for k,v in self.reader.items()))
        case={**self.case,'origin':'working','owner_reference':False}
        args=['--root',str(root),'--output-dir',str(self.out/'private'),'--cases',case['id']]
        with patch.object(benchmark,'CASES',[case]),patch.object(benchmark,'run_generation_case') as run:
            self.assertEqual(benchmark.main(args),0);run.assert_not_called()
            with self.assertRaises(SystemExit):benchmark.main(args+['--execute'])
            run.assert_not_called()

    def test_cli_bounds_and_original_deadline_persist_completed_case_is_not_repeated(self):
        import os
        root=self.out/'repo';song=root/'songs'/'owner-example';song.mkdir(parents=True)
        (song/'data.js').write_text(''.join('window.'+k+'='+json.dumps(v)+';' for k,v in self.reader.items()))
        case={**self.case,'origin':'working','owner_reference':False}
        output=self.out/'private';args=['--root',str(root),'--output-dir',str(output),'--cases',case['id'],
            '--execute','--budget-usd','1','--max-calls','3','--deadline-seconds','120']
        def run(case,reader,path,options):
            self.assertEqual(os.environ['BHAKTI_API_RUN_MAX_CALLS'],'3')
            self.assertEqual(os.environ['BHAKTI_API_RUN_BUDGET_USD'],'1.0')
            self.assertEqual(Path(os.environ['BHAKTI_API_RUN_LEDGER']),output.resolve()/'api-ledger.json')
            self.assertFalse(options.force)
            self.fake_completed_outputs(path,case)
        with patch.dict(os.environ,{'BHAKTI_GEMINI_PROVIDER':'openrouter'}),patch.object(benchmark,'CASES',[case]),patch.object(benchmark,'run_generation_case',side_effect=run) as runner:
            self.assertEqual(benchmark.main(args),0)
            saved=json.loads((output/'run.json').read_text())
            self.assertEqual(benchmark.main(args),0);self.assertEqual(runner.call_count,1)
            self.assertEqual(json.loads((output/'run.json').read_text())['deadline_at'],saved['deadline_at'])
            bad=args[:];bad[bad.index('--budget-usd')+1]='2'
            with self.assertRaisesRegex(ValueError,'configuration changed'):benchmark.main(bad)


    def fake_completed_outputs(self, output, case):
        folder=output/'cases'/case['id'];folder.mkdir(parents=True,exist_ok=True)
        for name in ('source-input.json','gloss-result.json','translation-result.json'):
            (folder/name).write_text('{}')
        (folder/'comparison.json').write_text(json.dumps({'case_id':case['id'],'semantic_status':'not-reviewed'}))
        (folder/'comparison.md').write_text('Editorial review pending.')

    def cli_fixture(self):
        root=self.out/'repo';song=root/'songs'/'owner-example';song.mkdir(parents=True)
        (song/'data.js').write_text(''.join('window.'+k+'='+json.dumps(v)+';' for k,v in self.reader.items()))
        case={**self.case,'origin':'working','owner_reference':False}
        output=(self.out/'private').resolve()
        args=['--root',str(root),'--output-dir',str(output),'--cases',case['id'],
              '--execute','--budget-usd','1','--max-calls','3','--deadline-seconds','120']
        return case,output,args

    def test_unresolved_resume_is_nonzero_and_never_dispatches(self):
        import os
        case,output,args=self.cli_fixture()
        with patch.dict(os.environ,{'BHAKTI_GEMINI_PROVIDER':'openrouter'}),patch.object(benchmark,'CASES',[case]),patch.object(benchmark,'run_generation_case',side_effect=RuntimeError('invalid output')) as run:
            try: first_status=benchmark.main(args)
            except RuntimeError: first_status=1
            self.assertEqual(first_status,1)
            saved=(output/'run.json').read_bytes()
            self.assertEqual(benchmark.main(args),1);self.assertEqual(run.call_count,1)
            self.assertEqual((output/'run.json').read_bytes(),saved)

    def test_completed_case_missing_or_changed_artifacts_never_counts_complete(self):
        import os
        case,output,args=self.cli_fixture()
        with patch.dict(os.environ,{'BHAKTI_GEMINI_PROVIDER':'openrouter'}),patch.object(benchmark,'CASES',[case]),patch.object(benchmark,'run_generation_case',side_effect=lambda c,r,p,o:self.fake_completed_outputs(p,c)) as run:
            self.assertEqual(benchmark.main(args),0)
            target=output/'cases'/case['id']/'comparison.json';original=target.read_bytes()
            for mutation in ('changed','missing'):
                if mutation=='changed':target.write_text('{}')
                else:target.unlink()
                with self.assertRaisesRegex(ValueError,'artifact'):benchmark.main(args)
                self.assertEqual(run.call_count,1)
                target.write_bytes(original)

    def test_no_artifact_success_marker_cannot_be_created(self):
        import os
        case,output,args=self.cli_fixture()
        with patch.dict(os.environ,{'BHAKTI_GEMINI_PROVIDER':'openrouter'}),patch.object(benchmark,'CASES',[case]),patch.object(benchmark,'run_generation_case',return_value={}):
            self.assertEqual(benchmark.main(args),1)
            self.assertEqual(json.loads((output/'run.json').read_text())['outcomes'][case['id']]['status'],'unresolved')

    def test_dependency_change_holds_existing_run_without_dispatch(self):
        import os
        case,output,args=self.cli_fixture()
        with patch.dict(os.environ,{'BHAKTI_GEMINI_PROVIDER':'openrouter'}),patch.object(benchmark,'CASES',[case]),patch.object(benchmark,'run_generation_case',side_effect=lambda c,r,p,o:self.fake_completed_outputs(p,c)) as run,patch.object(benchmark,'dependency_identity',return_value={'review_contract':'one'}) as identity:
            self.assertEqual(benchmark.main(args),0)
            identity.return_value={'review_contract':'two'}
            with self.assertRaisesRegex(ValueError,'configuration changed'):benchmark.main(args)
            self.assertEqual(run.call_count,1)

    def test_concurrent_run_lock_prevents_preparation_and_dispatch(self):
        case,output,args=self.cli_fixture()
        with benchmark.run_lock(output),patch.object(benchmark,'CASES',[case]),patch.object(benchmark,'run_generation_case') as run:
            with self.assertRaisesRegex(ValueError,'already active'):benchmark.main(args)
            run.assert_not_called();self.assertFalse((output/'manifest.json').exists())

    def test_interruption_after_reservation_preserves_running_marker_and_never_redispatches(self):
        import os
        case,output,args=self.cli_fixture()
        def crash(c,r,p,o):
            (output/'api-ledger.json').write_text(json.dumps({'requests':[{'status':'dispatched','reservation_usd':0.25}]}))
            raise KeyboardInterrupt('simulated interruption before response/cache')
        with patch.dict(os.environ,{'BHAKTI_GEMINI_PROVIDER':'openrouter'}),patch.object(benchmark,'CASES',[case]),patch.object(benchmark,'run_generation_case',side_effect=crash) as run:
            with self.assertRaises(KeyboardInterrupt):benchmark.main(args)
            ledger=(output/'api-ledger.json').read_bytes()
            self.assertEqual(json.loads((output/'run.json').read_text())['outcomes'][case['id']]['status'],'running')
            self.assertEqual(benchmark.main(args),1);self.assertEqual(run.call_count,1)
            self.assertEqual((output/'api-ledger.json').read_bytes(),ledger)


    def test_dependency_identity_observes_actual_pipeline_source_bytes(self):
        path=self.out/'pipeline.py';path.write_text('version one')
        with patch.object(benchmark.pipeline,'__file__',str(path)):
            first=benchmark.dependency_identity()
            path.write_text('version two')
            self.assertNotEqual(first,benchmark.dependency_identity())


    def payment_corruption_case(self, relative, replacement):
        import os
        case,output,args=self.cli_fixture()
        second={**case,'id':'second'};args.insert(args.index('--execute'),'second')
        real_write=benchmark.write
        def stop_after_first(path,value):
            real_write(path,value)
            if Path(path).name=='run.json' and value.get('outcomes',{}).get(case['id'],{}).get('status')=='completed-awaiting-editorial-review' and 'second' not in value['outcomes']:
                raise KeyboardInterrupt('interrupted between cases, no in-flight request')
        def paid_fixture(c,r,p,o):
            self.fake_completed_outputs(p,c)
            (p/'api-ledger.json').write_text(json.dumps({'requests':[{'id':'first-request','status':'complete','reported_cost_usd':0.1}]}))
            raw=p/'api-ledger-responses';raw.mkdir(exist_ok=True)
            (raw/'first.response.json').write_text('{"provider":"offline-fixture"}')
        with patch.dict(os.environ,{'BHAKTI_GEMINI_PROVIDER':'openrouter'}),patch.object(benchmark,'CASES',[case,second]),patch.object(benchmark,'run_generation_case',side_effect=paid_fixture) as run:
            with patch.object(benchmark,'write',side_effect=stop_after_first),self.assertRaises(KeyboardInterrupt):benchmark.main(args)
            self.assertEqual(run.call_count,1)
            target=output/relative
            if replacement is None:target.unlink()
            else:target.write_text(replacement)
            with self.assertRaisesRegex(ValueError,'payment evidence'):benchmark.main(args)
            self.assertEqual(run.call_count,1)

    def test_missing_ledger_cannot_reset_allowance_before_pending_case(self):
        self.payment_corruption_case('api-ledger.json',None)

    def test_replaced_ledger_cannot_reset_allowance_before_pending_case(self):
        self.payment_corruption_case('api-ledger.json','{"requests":[]}')

    def test_deleted_raw_response_blocks_resume_before_pending_case(self):
        self.payment_corruption_case('api-ledger-responses/first.response.json',None)

    def test_changed_raw_response_blocks_resume_before_pending_case(self):
        self.payment_corruption_case('api-ledger-responses/first.response.json','{}')


    def test_legitimate_second_case_appends_payment_history_and_resumes_without_calls(self):
        import os
        case,output,args=self.cli_fixture();second={**case,'id':'second'}
        args.insert(args.index('--execute'),'second')
        def paid_fixture(c,r,p,o):
            self.fake_completed_outputs(p,c)
            ledger=p/'api-ledger.json';history=json.loads(ledger.read_text()) if ledger.exists() else {'requests':[]}
            history['requests'].append({'id':c['id'],'status':'complete','reported_cost_usd':0.1})
            ledger.write_text(json.dumps(history))
            raw=p/'api-ledger-responses';raw.mkdir(exist_ok=True)
            (raw/(c['id']+'.response.json')).write_text('{"provider":"offline-fixture"}')
        with patch.dict(os.environ,{'BHAKTI_GEMINI_PROVIDER':'openrouter'}),patch.object(benchmark,'CASES',[case,second]),patch.object(benchmark,'run_generation_case',side_effect=paid_fixture) as run:
            self.assertEqual(benchmark.main(args),0)
            self.assertEqual(len(json.loads((output/'api-ledger.json').read_text())['requests']),2)
            self.assertEqual(benchmark.main(args),0);self.assertEqual(run.call_count,2)

if __name__=='__main__': unittest.main()

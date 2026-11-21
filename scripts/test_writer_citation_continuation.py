"""Real semantic parent/routes/acceptor; canned remote answers only, never linguistic proof."""
import copy
import hashlib
import json
import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import bhakti_pipeline as bp
import bhakti_review_continuation as continuation
import bhakti_model_routes as routes
from bhakti_intake_run import bounded_intake_run
import test_semantic_stage_routes as fixtures


def ref(path):
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return ref(path)

class ProjectionTests(unittest.TestCase):
    def test_exact_containing_span_preserves_selected_indices_and_all_other_fields(self):
        line={'id':'v','source_text':'ओ मैया, हम सब उतारें तेरी आरती',
              'roman':'o maiyā, hama saba utārẽ terī āratī'}
        token_map={'v':{**line,'tokens':list(zip(line['source_text'].split(),line['roman'].split()))}}
        row={'id':'v','literal_english':'with','fidelity':{'notes':'unchanged'},'word_support':[
            {'unit':0,'bases':['grammar'],'reason':'conjunctive expression','references':[
                {'line_id':'v','domain':'word_glosses','word_indices':[4,6],'source_quote':'utārẽ terī āratī'}]}]}
        output,changes=continuation.project_writer_citations([line],[row],token_map)
        expected=copy.deepcopy(row);expected['word_support'][0]['references'][0]['source_quote']='उतारें तेरी आरती'
        self.assertEqual(output,[expected]);self.assertEqual(len(changes),1)
        for mutate in ('quote','indices','ambiguous','map'):
            test=copy.deepcopy(row);source=copy.deepcopy(line);mapping=copy.deepcopy(token_map)
            if mutate=='quote':test['word_support'][0]['references'][0]['source_quote']='utāre terī āratī'
            if mutate=='indices':test['word_support'][0]['references'][0]['word_indices']=[3,6]
            if mutate=='ambiguous':
                source['roman']='x x x';source['source_text']='क ख ग';mapping={'v':{**source,'tokens':[['क','x'],['ख','x'],['ग','x']]}}
                test['word_support'][0]['references'][0].update(word_indices=[1],source_quote='x x')
            if mutate=='map':mapping['v']['tokens'][4]=['तेरी','utārẽ']
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):
                continuation.project_writer_citations([source],[test],mapping)

class WriterContinuationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.SemanticStageRoutesTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.c=self.fixture.c;self.c.options.semantic_repair_rounds=0
        self.transport=bp.gemini.call.side_effect
        self.work=self.c.root/'writer-continuation';self.work.mkdir()
        baseline=self.work/'english.json';save(baseline,{'v':'Adamantine'})
        self.job={'slug':'fixture','source':'https://www.youtube.com/watch?v=7Phj6-g7c2k','providedTranslation':str(baseline)}
        self.complete=lambda:bp.complete_semantics(self.c.song,self.c.audit,self.job,self.c.options)
        self.requests=[];self.rawrefs=[]
        def failed_writer(model,key,prompt,**kw):
            result=self.transport(model,key,prompt,**kw)
            if kw['schema_name'] in {'bhakti_literal_translation','bhakti_translation_batch'}:
                result=copy.deepcopy(result)
                if self._testMethodName=='test_nonselected_writer_semantic_concern_cannot_be_hidden' and model==routes.PRO_MODEL:
                    result['packet']['translations'][0]['human_review_recommended']=True
                    result['packet']['translations'][0]['choice_note']='A source meaning requires separate review.'
                for row in result['packet']['translations']:
                    for support in row['word_support']:
                        for citation in support['references']:citation['source_quote']='vajra'
                path=self.work/f'raw-writer-{len(self.requests)}.json'
                self.rawrefs.append(save(path,{'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result['packet'],ensure_ascii=False)}}]}))
                self.requests.append({'id':f'fixture-{len(self.requests)}','status':'parsed','model':model,
                    'reservation_usd':0.01,'reported_cost_usd':0.001,'response_path':str(path),
                    'unit_context':copy.deepcopy(kw['unit_context'])})
            return result
        with patch.object(bp.gemini,'call',side_effect=failed_writer):
            with self.assertRaises(RuntimeError):self.complete()
        self.parent=self.c.packets/'semantic-repair-state.json';self.parent_before=self.parent.read_bytes()
        parent=json.loads(self.parent_before);self.assertEqual(parent['status'],'blocked')
        self.rd=self.c.packets/'semantic-repair'/parent['run_id']/'round-0'
        self.route=next(p for p in self.rd.rglob('route-state.json') if json.loads(p.read_text())['unit_id'].endswith(':semantic-writer'))
        state=json.loads(self.route.read_text());self.assertEqual([a['status'] for a in state['attempts']],['quality-failed','quality-failed'])
        self.candidate=self.route.parent/'flash/songs/round-0/.transcription/pipeline/translation-candidate.json'
        candidate=json.loads(self.candidate.read_text());projected=copy.deepcopy(candidate['packet']['translations'])
        for row in projected:
            for support in row['word_support']:
                for citation in support['references']:citation['source_quote']='वज्र'
        mapping={'v':{'source_text':'वज्र','roman':'vajra','tokens':[['वज्र','vajra']]}}
        projection=save(self.work/'projection.json',{'version':1,'kind':'assistant-derived-writer-citation-projection',
            'source_sha256':bp.bhakti_semantic_repair.digest(self.c.audit),'token_map':mapping,'translations':projected})
        independent=save(self.work/'independent.json',{'status':'accepted','projection':projection,'scope':'citation-only, not semantic acceptance'})
        self.old_ledger=save(self.work/'prior-ledger.json',{'budget_usd':1,'max_calls':6,'deadline_at':parent['deadline_at_epoch'],
            'blocked':False,'requests':self.requests})
        self.declaration={'version':1,'kind':'writer-citation','parent_state':save(self.work/'prior-parent.json',parent),
            'audited_source':save(self.work/'audited.json',self.c.audit),
            'audited_source_sha256':bp.bhakti_semantic_repair.digest(self.c.audit),
            'source_evidence_sha256':bp.bhakti_semantic_repair.digest(bp.bhakti_semantic_repair.source_evidence(bp,self.c.song,self.c.audit)),
            'writer_route':ref(self.route),'writer_candidate':ref(self.candidate),'selected_attempt_id':state['attempts'][0]['attempt_id'],
            'gloss':ref(self.rd/'gloss-ready.json'),'prior_ledger':self.old_ledger,'responses':self.rawrefs,
            'projection':projection,'independent_review':independent}
        self.historical={p:p.read_bytes() for p in self.rd.rglob('*') if p.is_file()}
        for item in [self.old_ledger,*self.rawrefs,self.declaration['parent_state']]:
            self.historical[Path(item['path'])]=Path(item['path']).read_bytes()
        self.c.options.run_dir=str(self.c.root/'.transcription/new-review-run')
        self.c.options.budget_usd=1;self.c.options.max_calls=3;self.c.options.deadline_seconds=300
        self.new_calls=[]

    def invoke(self,declaration=None,*,defect=False,unknown=False):
        declaration=declaration or self.declaration
        self.c.options.semantic_review_continuation=save(self.work/('declaration-'+bp.bhakti_semantic_repair.digest(declaration)+'.json'),declaration)
        jobs=[{**self.job,'_continuation':self.c.options.semantic_review_continuation}]
        def reviewer(model,key,prompt,**kw):
            self.assertEqual(kw['schema_name'],'bhakti_translation_review','No fresh writer/gloss may dispatch')
            self.new_calls.append(copy.deepcopy(kw))
            if unknown:
                raise routes.UnitTransportFailure('unknown-outcome',request_id='charged-unknown-review',worker_terminated=False)
            result=self.transport(model,key,prompt,**kw)
            if defect:
                row=result['packet']['reviews'][0]
                row.update(passes=False,human_review_recommended=False,issues=[{
                    'kind':'english_realization','target_line_ids':['v'],'references':[{'line_id':'v','domain':'word_glosses','word_indices':[0],'source_quote':'वज्र'}],
                    'explanation':'Retained actual reviewer defect','evidence':'Source warrants physical hardness.'}])
                row['component_judgments']['english']={'status':'defect','reason':'Retained actual reviewer defect'}
                row['word_judgments'][0]['status']='defect'
            return result
        with patch.dict(os.environ,{'BHAKTI_API_RUN_LEDGER':str(Path(self.c.options.run_dir)/'api-ledger.json'),'BHAKTI_API_RUN_BUDGET_USD':'1'}),patch.object(bp.gemini,'call',side_effect=reviewer):
            with bounded_intake_run(self.c.root,jobs,self.c.options):return self.complete()

    def assert_originals(self):
        for p,raw in self.historical.items():self.assertEqual(p.read_bytes(),raw,str(p))

    def test_actual_review_acceptance_and_replay_keep_failed_writer_history(self):
        gloss,result=self.invoke();self.assertEqual(len(self.new_calls),1)
        self.assertEqual(result['packet']['translations'][0]['literal_english'],'Adamantine')
        self.assertEqual(json.loads(self.route.read_text())['status'],'unresolved')
        self.assertEqual(result['writer_citation_projection']['kind'],'assistant-derived-writer-citation-projection')
        bp.bhakti_semantic_repair.require_acceptance(bp,self.c.packets,gloss,result,audited=self.c.audit)
        accepted=self.parent.read_bytes();self.assertEqual(self.invoke(),(gloss,result));self.assertEqual(len(self.new_calls),1)
        self.assertEqual(self.parent.read_bytes(),accepted);self.assert_originals()
        del self.c.options.semantic_review_continuation
        with patch.object(bp.gemini,'call',side_effect=AssertionError('No normal accepted replay calls')):
            self.assertEqual(self.complete(),(gloss,result))

    def test_wrong_candidate_unknown_history_and_changed_inputs_fail_before_review(self):
        for kind in ('candidate','unknown','english','indices','fidelity','source'):
            d=copy.deepcopy(self.declaration)
            if kind=='candidate':d['writer_candidate']=d['gloss']
            elif kind=='unknown':
                ledger=json.loads(Path(d['prior_ledger']['path']).read_text());ledger['requests'][0]['status']='unknown'
                d['prior_ledger']=save(self.work/'unknown-ledger.json',ledger)
            elif kind=='source':d['source_evidence_sha256']='0'*64
            else:
                projection=json.loads(Path(d['projection']['path']).read_text());row=projection['translations'][0]
                if kind=='english':row['literal_english']='Changed'
                if kind=='indices':row['word_support'][0]['references'][0]['word_indices']=[5]
                if kind=='fidelity':row['fidelity']['notes']='Changed'
                d['projection']=save(self.work/f'{kind}-projection.json',projection)
                d['independent_review']=save(self.work/f'{kind}-review.json',{'status':'accepted','projection':d['projection']})
            # Separate temporary outer run per invalid-input check; no provider call or old run mutation.
            olddir=self.c.options.run_dir;self.c.options.run_dir=str(self.c.root/f'.transcription/invalid-{kind}')
            try:
                with self.subTest(kind=kind),self.assertRaises((ValueError,RuntimeError)):self.invoke(d)
            finally:self.c.options.run_dir=olddir
            self.assertEqual(self.new_calls,[]);self.assertEqual(self.parent.read_bytes(),self.parent_before);self.assert_originals()

    def test_refreshed_hashes_do_not_forge_batch_route_correlation_or_current_parent(self):
        for kind in ('raw-content','pro-raw-content','context','omitted-response','live-parent'):
            d=copy.deepcopy(self.declaration)
            restore=None
            if kind in ('raw-content','pro-raw-content'):
                chosen=0 if kind=='raw-content' else 1
                raw=json.loads(Path(d['responses'][chosen]['path']).read_text())
                packet=json.loads(raw['choices'][0]['message']['content'])
                packet['translations'][0]['fidelity']['notes']='not the actual candidate'
                raw['choices'][0]['message']['content']=json.dumps(packet)
                new=save(self.work/f'{kind}-forged-response.json',raw);d['responses'][chosen]=new
                ledger=json.loads(Path(d['prior_ledger']['path']).read_text());ledger['requests'][chosen]['response_path']=new['path']
                d['prior_ledger']=save(self.work/'forged-ledger.json',ledger)
            elif kind=='context':
                ledger=json.loads(Path(d['prior_ledger']['path']).read_text());ledger['requests'][0]['unit_context']['attempt_id']='different'
                d['prior_ledger']=save(self.work/'context-ledger.json',ledger)
            elif kind=='omitted-response':d['responses']=d['responses'][1:]
            else:
                restore=self.parent.read_bytes();parent=json.loads(restore);parent['reason']='unrelated live work';save(self.parent,parent)
            self.c.options.run_dir=str(self.c.root/f'.transcription/history-negative-{kind}')
            try:
                with self.subTest(kind=kind),self.assertRaises((ValueError,RuntimeError)):self.invoke(d)
                self.assertEqual(self.new_calls,[])
                if restore:self.assertNotEqual(self.parent.read_bytes(),restore)
            finally:
                if restore:self.parent.write_bytes(restore)
            self.assert_originals()

    def test_jointly_forged_leaf_raw_projection_cannot_override_route_candidate(self):
        d=copy.deepcopy(self.declaration);original=self.candidate.read_bytes()
        leaf=json.loads(original);leaf['packet']['translations'][0]['fidelity']['notes']='forged revised fidelity'
        d['writer_candidate']=save(self.candidate,leaf)
        raw=json.loads(Path(d['responses'][0]['path']).read_text());packet=json.loads(raw['choices'][0]['message']['content'])
        packet['translations'][0]['fidelity']['notes']='forged revised fidelity'
        raw['choices'][0]['message']['content']=json.dumps(packet)
        new=save(self.work/'joint-forged-raw.json',raw);d['responses'][0]=new
        ledger=json.loads(Path(d['prior_ledger']['path']).read_text());ledger['requests'][0]['response_path']=new['path']
        d['prior_ledger']=save(self.work/'joint-forged-ledger.json',ledger)
        projection=json.loads(Path(d['projection']['path']).read_text());projection['translations'][0]['fidelity']['notes']='forged revised fidelity'
        d['projection']=save(self.work/'joint-forged-projection.json',projection)
        d['independent_review']=save(self.work/'joint-forged-review.json',{'status':'accepted','projection':d['projection']})
        try:
            with self.assertRaisesRegex(ValueError,'authenticated failed attempt diagnostics'):self.invoke(d)
            self.assertEqual(self.new_calls,[]);self.assertEqual(self.parent.read_bytes(),self.parent_before)
        finally:self.candidate.write_bytes(original)
        self.assert_originals()

    def test_nonselected_writer_semantic_concern_cannot_be_hidden(self):
        with self.assertRaisesRegex(ValueError,'semantic concerns'):self.invoke()
        self.assertEqual(self.new_calls,[]);self.assertEqual(self.parent.read_bytes(),self.parent_before);self.assert_originals()

    def test_real_independent_semantic_failure_stays_held(self):
        with self.assertRaises((ValueError,RuntimeError)):self.invoke(defect=True)
        self.assertEqual(len(self.new_calls),1);self.assertFalse((self.c.packets/'semantic-acceptance.json').exists())
        before=len(self.new_calls)
        with self.assertRaises((ValueError,RuntimeError)):self.invoke(defect=True)
        self.assertEqual(len(self.new_calls),before);self.assert_originals()

    def test_unknown_review_cannot_redispatch_or_renew_deadline(self):
        with self.assertRaises((ValueError,RuntimeError)):self.invoke(unknown=True)
        self.assertEqual(len(self.new_calls),1)
        state=self.parent.read_bytes();run=(Path(self.c.options.run_dir)/'run.json').read_bytes()
        with self.assertRaises((ValueError,RuntimeError)):self.invoke()
        self.assertEqual(len(self.new_calls),1);self.assertEqual(self.parent.read_bytes(),state)
        self.assertEqual((Path(self.c.options.run_dir)/'run.json').read_bytes(),run);self.assert_originals()

    def test_final_write_interruption_reuses_review_and_tampered_closure_fails(self):
        original=bp.semantic_write_json
        def interrupted(path,value):
            if Path(path)==self.c.packets/'05-translation.json':raise OSError('interrupted final write')
            return original(path,value)
        with patch.object(bp,'semantic_write_json',side_effect=interrupted):
            with self.assertRaises(OSError):self.invoke()
        with self.assertRaises(RuntimeError):bp.bhakti_semantic_repair.require_acceptance(bp,self.c.packets,audited=self.c.audit)
        gloss,result=self.invoke();self.assertEqual(len(self.new_calls),1);self.assert_originals()
        projection=Path(self.declaration['projection']['path']);raw=projection.read_bytes();projection.write_bytes(raw+b' ')
        try:
            with self.assertRaises((ValueError,RuntimeError)):bp.bhakti_semantic_repair.require_acceptance(bp,self.c.packets,gloss,result,audited=self.c.audit)
        finally:projection.write_bytes(raw)

if __name__=='__main__':unittest.main()

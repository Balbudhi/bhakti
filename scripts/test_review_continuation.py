"""Temporary real parent/routes; canned provider establishes failure, never acoustic proof."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import bhakti_pipeline as bp
import bhakti_model_routes as routes
import test_semantic_stage_routes as fixtures


def ref(path):
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return ref(path)

class ParentContinuationTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.SemanticStageRoutesTests();self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.c=self.case.c;self.c.options.semantic_stage_escalation=False
        self.review_requests=[];self.rawrefs=[];self.transport=bp.gemini.call.side_effect
        semantic_defect=self._testMethodName=='test_original_semantic_defect_is_not_cleared_by_projection'
        def provider(model,key,prompt,**kw):
            result=self.transport(model,key,prompt,**kw)
            if kw['schema_name']=='bhakti_translation_review':
                if not self.review_requests:
                    path=self.c.root/'truncated-review.response.json'
                    self.rawrefs.append(save(path,{'choices':[{'finish_reason':'length','message':{'content':'{"reviews":['}}]}))
                    self.review_requests.append({'id':'fixture-truncated-review','status':'invalid-model-output',
                        'unit_context':copy.deepcopy(kw['unit_context']),'response_path':str(path),
                        'reported_cost_usd':0.002,'reservation_usd':0.003})
                    raise routes.UnitTransportFailure('invalid-model-output',request_id='fixture-truncated-review',worker_terminated=True)
                result=copy.deepcopy(result)
                if semantic_defect:
                    row=result['packet']['reviews'][0]
                    issue={'kind':'english_realization','target_line_ids':['v'],
                        'references':[{'line_id':'v','domain':'word_glosses','word_indices':[0],'source_quote':'वज्र'}],
                        'explanation':'Actual retained reviewer objection.', 'evidence':'Physical sense must remain.'}
                    row.update(passes=False,human_review_recommended=False,issues=[issue])
                    row['component_judgments']['english']={'status':'defect','reason':'Actual retained reviewer objection.'}
                    row['word_judgments'][0]['status']='defect'
                for row in result['packet']['reviews']:
                    for judgment in row['word_judgments']:
                        for citation in judgment['references']:
                            citation['source_quote']='vajra'
                raw={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result['packet'],ensure_ascii=False)}}]}
                path=self.c.root/'retained-review.response.json';rawref=save(path,raw)
                self.review_requests.append({'id':'fixture-parsed-review','status':'parsed',
                    'unit_context':copy.deepcopy(kw['unit_context']),'response_path':str(path),
                    'reported_cost_usd':0.001,'reservation_usd':0.002})
                self.rawref=rawref;self.rawrefs.append(rawref)
            return result
        original_routed=bp.bhakti_semantic_repair.routed_translation
        captured={}
        def capture(*args,**kw):
            captured['args']=args;captured['kw']=kw
            return original_routed(*args,**kw)
        with patch.object(bp.gemini,'call',side_effect=provider), patch.object(bp.bhakti_semantic_repair,'routed_translation',side_effect=capture):
            with self.assertRaises(RuntimeError): self.c.complete()
            args=list(captured['args']);args[-1]=copy.copy(args[-1]);args[-1].text_reasoning_effort={'review':'low'}
            with self.assertRaises(RuntimeError):original_routed(*args,**captured['kw'])
        self.parent=self.c.packets/'semantic-repair-state.json'
        self.parent_before=self.parent.read_bytes()
        parent=json.loads(self.parent_before);self.assertEqual(parent['status'],'blocked')
        self.rd=self.c.packets/'semantic-repair'/parent['run_id']/'round-0'
        states=list(self.rd.rglob('route-state.json'))
        self.writer=next(p for p in states if json.loads(p.read_text())['unit_id'].endswith(':semantic-writer'))
        self.review=Path(self.review_requests[-1]['unit_context']['state_path'])
        self.truncated=Path(self.review_requests[0]['unit_context']['state_path'])
        self.assertEqual(routes.read_unit_cache(self.writer)['state']['status'],'accepted')
        self.assertEqual(routes.read_unit_cache(self.review)['state']['status'],'unresolved')
        self.work=self.c.root/'continuation-inputs';self.work.mkdir()
        raw_reviews=json.loads(json.loads(Path(self.rawref['path']).read_text())['choices'][0]['message']['content'])['reviews']
        projected=copy.deepcopy(raw_reviews)
        for row in projected:
            for judgment in row['word_judgments']:
                for citation in judgment['references']: citation['source_quote']='वज्र'
        mapping={'v':{'source_text':'वज्र','roman':'vajra','tokens':[['वज्र','vajra']]}}
        projection=save(self.work/'projection.json',{'version':1,'kind':'assistant-derived-citation-projection',
            'source_sha256':bp.bhakti_semantic_repair.digest(self.c.audit),
            'token_map':mapping,'reviews':projected})
        independent=save(self.work/'independent-review.json',{'status':'accepted','projection':projection,
            'scope':'exact source mapping and citation-only derivative, not new provider judgments'})
        ledger=save(self.work/'settled-ledger.json',{'requests':self.review_requests,'blocked':False})
        self.declaration={'version':1,'parent_state':save(self.work/'prior-parent.json',parent),
            'audited_source_sha256':bp.bhakti_semantic_repair.digest(self.c.audit),
            'source_evidence_sha256':bp.bhakti_semantic_repair.digest(bp.bhakti_semantic_repair.source_evidence(bp,self.c.song,self.c.audit)),
            'writer_route':ref(self.writer),'gloss':ref(self.rd/'gloss-ready.json'),
            'failed_reviews':[{'route':ref(Path(request['unit_context']['state_path'])),'ledger':ledger,'responses':[rawref],'review_controls':({} if request['status']=='invalid-model-output' else {'text_reasoning_effort':{'review':'low'}})} for request,rawref in zip(self.review_requests,self.rawrefs)],
            'projection':projection,'independent_review':independent}
        self.historical={p:p.read_bytes() for p in self.rd.rglob('*') if p.is_file()}
        for item in self.rawrefs:self.historical[Path(item['path'])]=Path(item['path']).read_bytes()
        self.historical[Path(ledger['path'])]=Path(ledger['path']).read_bytes()

    def invoke(self,declaration=None):
        value=declaration or self.declaration
        path=self.work/('declaration-'+bp.bhakti_semantic_repair.digest(value)+'.json')
        self.c.options.semantic_review_continuation=save(path,value)
        with patch.object(bp.gemini,'call',side_effect=AssertionError('continuation must never call provider')):
            return self.c.complete()

    def assert_historical_unchanged(self):
        for path,raw in self.historical.items(): self.assertEqual(path.read_bytes(),raw,str(path))

    def test_real_parent_acceptance_reuses_writer_and_is_idempotent(self):
        gloss,translation=self.invoke()
        self.assertEqual(translation['packet']['translations'][0]['literal_english'],'Adamantine')
        self.assertEqual(gloss['packet'],json.loads((self.rd/'gloss-ready.json').read_text())['packet'])
        bp.bhakti_semantic_repair.require_acceptance(bp,self.c.packets,gloss,translation,audited=self.c.audit)
        accepted=self.parent.read_bytes()
        self.assertEqual(json.loads(accepted)['status'],'accepted')
        self.assertNotEqual(json.loads(accepted)['run_id'],json.loads(self.parent_before)['run_id'])
        self.assert_historical_unchanged()
        self.assertEqual(self.invoke(),(gloss,translation));self.assertEqual(self.parent.read_bytes(),accepted)
        self.assert_historical_unchanged()
        del self.c.options.semantic_review_continuation
        with patch.object(bp.gemini,'call',side_effect=AssertionError('accepted normal resume cannot call provider')):
            self.assertEqual(self.c.complete(),(gloss,translation))
        self.assert_historical_unchanged()

    def test_interrupted_final_write_is_fail_closed_and_resumes_exact_declaration(self):
        original=bp.semantic_write_json
        def interrupted(path,value):
            if Path(path)==self.c.packets/'05-translation.json':
                raise OSError('test interrupted before final translation write')
            return original(path,value)
        with patch.object(bp,'semantic_write_json',side_effect=interrupted):
            with self.assertRaises(OSError): self.invoke()
        with self.assertRaises(RuntimeError):
            bp.bhakti_semantic_repair.require_acceptance(bp,self.c.packets,audited=self.c.audit)
        self.assert_historical_unchanged()
        gloss,translation=self.invoke()
        bp.bhakti_semantic_repair.require_acceptance(bp,self.c.packets,gloss,translation,audited=self.c.audit)
        self.assert_historical_unchanged()

    def test_bad_replay_cannot_overwrite_accepted_pointer(self):
        self.invoke();accepted=self.parent.read_bytes()
        declaration=copy.deepcopy(self.declaration)
        declaration['source_evidence_sha256']='0'*64
        with self.assertRaises((ValueError,RuntimeError)): self.invoke(declaration)
        self.assertEqual(self.parent.read_bytes(),accepted)
        bp.bhakti_semantic_repair.require_acceptance(bp,self.c.packets,audited=self.c.audit)
        self.assert_historical_unchanged()

    def test_unknown_ledger_and_hash_drift_do_not_advance_parent(self):
        for kind in ('unknown','raw','writer','parent','source','gloss','projection-review','wrong-context'):
            declaration=copy.deepcopy(self.declaration)
            if kind=='unknown':
                value=json.loads(Path(declaration['failed_reviews'][0]['ledger']['path']).read_text())
                value['requests'][0]['status']='unknown'
                declaration['failed_reviews'][0]['ledger']=save(self.work/'unknown-ledger.json',value)
            elif kind=='wrong-context':
                value=json.loads(Path(declaration['failed_reviews'][1]['ledger']['path']).read_text())
                value['requests'][1]['unit_context']['input_fingerprint']='f'*64
                newref=save(self.work/'wrong-context-ledger.json',value)
                for item in declaration['failed_reviews']:item['ledger']=newref
            elif kind=='raw': declaration['failed_reviews'][0]['responses'][0]['sha256']='0'*64
            elif kind=='source': declaration['source_evidence_sha256']='0'*64
            else:
                key={'writer':'writer_route','parent':'parent_state','gloss':'gloss','projection-review':'independent_review'}[kind]
                declaration[key]['sha256']='0'*64
            reason={'unknown':'unsettled','wrong-context':'unit context','source':'source identity'}.get(kind,'hash mismatch')
            with self.subTest(kind=kind),self.assertRaisesRegex((ValueError,RuntimeError),reason): self.invoke(declaration)
            self.assertEqual(self.parent.read_bytes(),self.parent_before)
            self.assertFalse((self.c.packets/'semantic-acceptance.json').exists())
            self.assert_historical_unchanged()

    def test_original_semantic_defect_is_not_cleared_by_projection(self):
        original=json.loads(json.loads(Path(self.rawref['path']).read_text())['choices'][0]['message']['content'])['reviews'][0]
        self.assertFalse(original['passes']);self.assertTrue(original['issues'])
        self.assertEqual(bp.bhakti_semantic_repair.issue_errors(self.c.audit['packet']['verified_lines'],json.loads((self.rd/'gloss-ready.json').read_text())['packet']['glosses'],original['issues']),[])
        with self.assertRaisesRegex((ValueError,RuntimeError),'semantic acceptance hold'):self.invoke()
        self.assertEqual(self.parent.read_bytes(),self.parent_before)
        self.assertFalse((self.c.packets/'semantic-acceptance.json').exists())
        self.assert_historical_unchanged()

    def test_accepted_writer_result_digest_drift_rejected_before_parent_write(self):
        accepted=self.writer.parent/'accepted-result.json'
        original=accepted.read_bytes()
        changed=json.loads(original)
        changed['packet']['translations'][0]['literal_english']='Changed owner English'
        accepted.write_text(json.dumps(changed))
        try:
            with self.assertRaises((ValueError,RuntimeError)): self.invoke()
            self.assertEqual(self.parent.read_bytes(),self.parent_before)
        finally:
            accepted.write_bytes(original)
        self.assert_historical_unchanged()

    def test_citation_derivative_cannot_clear_semantic_judgment(self):
        declaration=copy.deepcopy(self.declaration)
        projection=json.loads(Path(declaration['projection']['path']).read_text())
        projection['reviews'][0]['component_judgments']['frame']['reason']='different meaning'
        declaration['projection']=save(self.work/'changed-projection.json',projection)
        declaration['independent_review']=save(self.work/'changed-independent-review.json',{
            'status':'accepted','projection':declaration['projection']})
        with self.assertRaises((ValueError,RuntimeError)):self.invoke(declaration)
        self.assertEqual(self.parent.read_bytes(),self.parent_before)
        self.assert_historical_unchanged()

if __name__=='__main__':unittest.main()

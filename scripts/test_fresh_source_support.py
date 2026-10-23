"""Actual fresh-target route/stages/storage; provider fixtures prove delivery only."""
import copy,json,time,unittest
from pathlib import Path
from unittest.mock import patch
import bhakti_pipeline as pipeline
import bhakti_library_source_pass as source
import bhakti_lexical_support as support
import bhakti_model_routes as routes
import test_lexical_support as fixtures

class FreshSourceSupportTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ActualCallerTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        f=self.f;f.options.model=pipeline.MODEL;f.options.pro_model=routes.PRO_MODEL
        # A second supported retained line forces full-plan validation while
        # the actual gloss/translation/review responses must target only p.
        q={**copy.deepcopy(f.lines[0]),'id':'q'}
        target={**copy.deepcopy(f.packet['targets'][0]),'id':'choice-q','line_id':'q'}
        f.packet['targets'].append(target)
        f.options.lexical_support_packets={f.song.name:copy.deepcopy(f.packet)}
        del f.options.semantic_lexical_support
        self.plan={'lines':[q,*copy.deepcopy(f.lines)],'new_target_ids':['p'],
            'performance_order':[{'line_id':'q','occurrence':1},{'line_id':'p','occurrence':1}],
            'reuse_by_id':{'q':{'source':'पति','roman':'pati','sourceLanguage':'sa',
               'english':'{0:OWNER TEXT}','words':[{'roman':'pati','gloss':'OWNER GLOSS'}],
               'sourceWords':[{'text':'पति','wordIndices':[0]}]}}}
        original=f.provider
        def response(*args,**kwargs):
            # The helper produces witnessed decisions when its direct option
            # exists; the real caller receives only the per-slug option.
            f.options.semantic_lexical_support=f.packet
            try:return original(*args,**kwargs)
            finally:del f.options.semantic_lexical_support
        patcher=patch.object(pipeline.gemini,'call',side_effect=response);patcher.start();self.addCleanup(patcher.stop)
    def run_target(self):
        f=self.f
        return source.process_new_targets(f.song,self.plan,{'languages':['Sanskrit']},f.options,f.root/'routes',time.time()+120)
    def test_full_plan_support_reaches_actual_gloss_translation_review_and_zero_call_resume(self):
        first=self.run_target();count=len(self.f.calls);self.assertEqual(count,3)
        second=self.run_target();self.assertEqual(first,second);self.assertEqual(len(self.f.calls),count)
        for kind,prompt,schema in self.f.calls:
            self.assertIn('TARGETED LEXICAL SUPPORT:',prompt)
            payload=json.JSONDecoder().raw_decode(prompt.split('TARGETED LEXICAL SUPPORT:\n',1)[1])[0]
            self.assertEqual([t['line_id'] for t in payload['targets']],['p'])
            self.assertIn('without protest',prompt);self.assertIn('पातेर्डतिः',prompt)
        self.assertEqual(self.plan['reuse_by_id']['q']['english'],'{0:OWNER TEXT}')
    def test_changed_evidence_invalidates_outer_route_while_same_relocated_content_reuses(self):
        self.run_target();count=len(self.f.calls)
        relocated=self.f.root/'relocated';relocated.mkdir()
        _,lines,_=fixtures.fixture(relocated)
        packet=support.build_support(relocated/'manifest.json',lines,['Sanskrit'])
        packet['targets'].append({**copy.deepcopy(packet['targets'][0]),'id':'choice-q','line_id':'q'})
        self.f.options.lexical_support_packets[self.f.song.name]=packet
        self.run_target();self.assertEqual(len(self.f.calls),count)
        packet['evidence'][0]['limitations'].append('Additional explicit limitation.')
        self.run_target();self.assertGreater(len(self.f.calls),count)
    def test_stale_full_plan_source_binding_holds_before_any_provider_call(self):
        packet=self.f.options.lexical_support_packets[self.f.song.name]
        packet['targets'][1]['surfaces']=['unrelated']
        with self.assertRaises(ValueError):self.run_target()
        self.assertEqual(self.f.calls,[])
    def test_cached_route_without_required_wording_decision_is_rejected_without_dispatch(self):
        self.run_target()
        state_path=next((self.f.root/'routes').rglob('route-state.json'))
        state=json.loads(state_path.read_text());result_path=state_path.parent/'accepted-result.json'
        value=json.loads(result_path.read_text());value['translations']['packet']['translations'][0].pop('wording_decisions')
        # Model an integrity-bound result accepted under the former weak gate.
        result_path.write_text(json.dumps(value));state['accepted_sha256']=routes._digest(value)
        state_path.write_text(json.dumps(state))
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('cached invalidity is a hold, no repay')):
            with self.assertRaises((ValueError,routes.QualityFailure)):
                self.run_target()

if __name__=='__main__':unittest.main()

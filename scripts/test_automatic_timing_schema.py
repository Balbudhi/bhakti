"""Actual automatic caller/router with offline measurements, not acoustic proof."""
import argparse, copy, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
import bhakti_pipeline as p
import bhakti_model_routes as routes

class AutomaticTimingSchemaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.song=Path(self.tmp.name);self.audio=self.song/'source.m4a';self.audio.write_bytes(b'offline audio identity')
        self.occ=[{'occurrence_id':f'occ-{i:03d}','ref':f'line-{i:03d}','source_text':'राम','roman':'rāma','repeats':1,'section':'verse'} for i in range(85)]
        self.opts=argparse.Namespace(model=routes.PRO_MODEL,pro_model=routes.PRO_MODEL,timeout=60,force=False,timing_deadline_at=time.time()+300)
    def answer(self, structured=True):
        rows=[]
        for i,row in enumerate(p.expanded_timing_targets(self.occ)):
            start=.5+i*5
            value={'minutes':int(start//60),'seconds':start%60} if structured else start
            rows.append({'timing_id':row['timing_id'],'start':value,'uncertainty':'','onset_at_clip_start':False})
        return {'packet':{'starts':rows}}
    def invoke(self):return p.align_long_segments(self.song,self.audio,{},self.occ,[],600.,self.opts)
    def test_new_bounded_auto_region_uses_existing_v4_and_resumes_without_calls(self):
        with patch.object(p.subprocess,'run'),patch.object(p.gemini,'key',return_value='offline'),patch.object(p.gemini,'call',side_effect=[self.answer(),self.answer()]) as call:
            result=self.invoke();self.assertEqual(self.invoke(),result)
        self.assertEqual(call.call_count,2);sequence,reports,errors=result
        self.assertEqual(errors,[]);self.assertEqual(len(sequence),85)
        self.assertEqual([row['start'] for row in sequence],[.5+i*5 for i in range(85)])
        self.assertEqual(reports[0]['region']['prompt_version'],4)
        for request in call.call_args_list:
            array=request.kwargs['response_schema']['properties']['starts']
            self.assertNotIn('minItems',array);self.assertNotIn('maxItems',array)
            self.assertEqual(array['items']['properties']['start'],{'type':'object','properties':{'minutes':{'type':'integer'},'seconds':{'type':'number'}},'required':['minutes','seconds'],'additionalProperties':False})
            self.assertIn('separate integer minutes and fractional seconds',request.args[2])
    def test_old_failed_v1_route_bytes_are_not_changed_by_new_auto_region(self):
        region=p.plan_joint_timing_regions(self.occ,[],{},600.,[])['regions'][0];original=copy.deepcopy(region)
        with patch.object(p.subprocess,'run'),patch.object(p.gemini,'key',return_value='offline'),patch.object(p.gemini,'call',side_effect=[routes.RunFatal('HTTP400 schema states'),self.answer(),self.answer()]) as call:
            with self.assertRaises(routes.RunFatal):p.run_joint_timing_unit(self.song,self.audio,region,600.,self.opts,{})
            state=next(self.song.rglob('route-state.json'));old={path:path.read_bytes() for path in state.parent.rglob('*.json')}
            self.assertEqual(len(self.invoke()[0]),85)
        self.assertEqual(region,original);self.assertEqual(call.call_count,3)
        for path,raw in old.items():self.assertEqual(path.read_bytes(),raw)
        self.assertEqual(len(list(self.song.rglob('route-state.json'))),2)
    def test_auto_v4_local_validator_rejects_missing_target_and_invalid_seconds(self):
        for kind in ('missing','seconds'):
            with tempfile.TemporaryDirectory() as tmp:
                self.song=Path(tmp);bad=self.answer()
                if kind=='missing':bad['packet']['starts'].pop()
                else:bad['packet']['starts'][25]['start']['seconds']=61
                with self.subTest(kind=kind),patch.object(p.subprocess,'run'),patch.object(p.gemini,'key',return_value='offline'),patch.object(p.gemini,'call',side_effect=[self.answer(),bad]) as call:
                    with self.assertRaises(routes.UnitUnresolved):self.invoke()
                    with self.assertRaises(routes.UnitUnresolved):self.invoke()
                    self.assertEqual(call.call_count,2)
    def test_legacy_unbounded_auto_caller_keeps_numeric_request(self):
        del self.opts.timing_deadline_at
        with patch.object(p.subprocess,'run'),patch.object(p.gemini,'key',return_value='offline'),patch.object(p.gemini,'call',side_effect=[self.answer(False),self.answer(False)]) as call:
            result=self.invoke()
        self.assertEqual(len(result[0]),85);self.assertNotIn('prompt_version',result[1][0]['region'])
        self.assertEqual(call.call_args_list[0].kwargs['response_schema']['properties']['starts']['minItems'],85)

if __name__=='__main__':unittest.main()

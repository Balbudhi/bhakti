import argparse,copy,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import bhakti_pipeline as p
import bhakti_model_routes as routes
SCOPE=json.loads((Path(__file__).parent/'fixtures/inhi-timing-scope.json').read_text())

class TimingSchemaV3Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.audio=self.root/'audio.m4a';self.audio.write_bytes(b'no-audio-fixture-transport-test')
  self.region=copy.deepcopy(SCOPE['region']);self.opts=argparse.Namespace(model=routes.PRO_MODEL,pro_model=routes.PRO_MODEL,timeout=180,timing_deadline_at=time.time()+600,force=False)
  self.targets=p.region_timing_targets(self.region);self.assertEqual(len(self.targets),95)
 def invoke(self):return p.run_joint_timing_unit(self.root,self.audio,self.region,SCOPE['duration'],self.opts,SCOPE['source_identity'])
 def answer(self):return {'packet':{'starts':[{'timing_id':row['timing_id'],'start':0.5+index*3,'uncertainty':'','onset_at_clip_start':False} for index,row in enumerate(self.targets)]}}
 def mocks(self,replies):return patch.object(p.subprocess,'run'),patch.object(p.gemini,'key',return_value='offline'),patch.object(p.gemini,'call',side_effect=replies)
 def test_v2_actual_large_schema_stays_unchanged(self):
  a,b,c=self.mocks([self.answer(),self.answer()])
  with a,b,c as call:r=self.invoke()
  self.assertEqual(len(r['expanded_starts']),95)
  for req in call.call_args_list:
   schema=req.kwargs['response_schema']['properties']['starts']
   self.assertEqual((schema['minItems'],schema['maxItems']),(95,95))
   self.assertEqual(schema['items']['properties']['start'],{'type':'number','minimum':0,'maximum':425.761})
 def test_v3_only_removes_wire_bounds_preserves_full_prompt_and_free_cache(self):
  a,b,c=self.mocks([self.answer() for _ in range(4)])
  with a,b,c as call:
   old=self.invoke();self.region['prompt_version']=3;new=self.invoke();self.assertEqual(self.invoke(),new)
  self.assertEqual(call.call_count,4);self.assertNotEqual(old['input_fingerprint'],new['input_fingerprint'])
  self.assertEqual(len(new['expanded_starts']),95);self.assertEqual(new['expanded_starts'][-1]['start'],282.5)
  for prior,now in zip(call.call_args_list[:2],call.call_args_list[2:]):
   self.assertEqual(prior.args[2],now.args[2]);self.assertIn('EXCERPT CLOCK: 0.000–425.761 seconds.',now.args[2])
   expected=copy.deepcopy(prior.kwargs['response_schema']);array=expected['properties']['starts'];array.pop('minItems');array.pop('maxItems');array['items']['properties']['start']={'type':'number'}
   self.assertEqual(now.kwargs['response_schema'],expected)
   self.assertEqual(now.kwargs['max_completion_tokens'],8192);self.assertEqual(now.kwargs['reasoning_effort'],'low')
 def test_v3_keeps_local_population_bounds_uncertainty_and_order_checks(self):
  for index,kind in enumerate(('missing','duplicate','reordered','outside','uncertain','nonfinite')):
   self.region.update(prompt_version=3,index=index)
   bad=self.answer();rows=bad['packet']['starts']
   if kind=='missing':rows.pop()
   elif kind=='duplicate':rows[1]['timing_id']=rows[0]['timing_id']
   elif kind=='reordered':rows[0],rows[1]=rows[1],rows[0]
   elif kind=='outside':rows[-1]['start']=425.761
   elif kind=='uncertain':rows[0]['uncertainty']='masked first syllable'
   else:rows[0]['start']=float('nan')
   a,b,c=self.mocks([self.answer(),bad])
   # Non-JSON NaN is rejected by immutable artifact persistence, before quality routing.
   held_error=routes.RunFatal if kind=='nonfinite' else routes.UnitUnresolved
   with self.subTest(kind=kind),a,b,c as call:
    with self.assertRaises(held_error):self.invoke()
    with self.assertRaises(held_error):self.invoke()
    self.assertEqual(call.call_count,2)
 def test_explicit_v3_does_not_reset_failed_v2_route(self):
  failure=routes.UnitTransportFailure('invalid-response',worker_terminated=True,detail='HTTP400 INVALID_ARGUMENT')
  a,b,c=self.mocks([failure,self.answer(),self.answer()])
  with a,b,c as call:
   with self.assertRaises(routes.UnitUnresolved):self.invoke()
   old_path=next(self.root.rglob('route-state.json'));old_bytes=old_path.read_bytes()
   self.region['prompt_version']=3;r=self.invoke();self.assertEqual(len(r['expanded_starts']),95)
   self.assertEqual(old_path.read_bytes(),old_bytes)
   self.region['prompt_version']=2
   with self.assertRaises(routes.UnitUnresolved):self.invoke()
   self.assertEqual(old_path.read_bytes(),old_bytes);self.assertEqual(call.call_count,3)
 def test_invalid_version_still_precedes_audio_identity(self):
  self.region['prompt_version']=4
  with patch.object(p,'timing_input_identity',side_effect=AssertionError('read audio')):
   with self.assertRaises(ValueError):self.invoke()

if __name__=='__main__':unittest.main()

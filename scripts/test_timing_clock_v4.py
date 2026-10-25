"""Explicit clock arithmetic and real route/revalidation; no acoustic qualification."""
import argparse,copy,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import bhakti_pipeline as p
import bhakti_model_routes as routes
FIXTURE=json.loads((Path(__file__).parent/'fixtures/satgur-timing.json').read_text())
class ClockV4Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.audio=self.root/'audio.m4a';self.audio.write_bytes(b'offline-clock-fixture')
  self.occ=copy.deepcopy([r for r in FIXTURE['timing']['ordered_occurrences'] if r['repeats']==1][:3])
  self.region={'index':0,'clip_start':60.,'clip_end':700.,'target_occurrences':self.occ,'preceding_context':None,'following_context':None,
               'prompt_version':4,'max_completion_tokens':8192,'reasoning_effort':'low','clip_audio_bitrate_kbps':128}
  self.opts=argparse.Namespace(model=routes.PRO_MODEL,pro_model=routes.PRO_MODEL,timeout=180,timing_deadline_at=time.time()+600,force=False)
 def packet(self,starts):
  return {'starts':[{'timing_id':x['timing_id'],'start':s,'uncertainty':'','onset_at_clip_start':False}
        for x,s in zip(p.region_timing_targets(self.region),starts)]}
 def responses(self):
  return [{'packet':self.packet([{'minutes':0,'seconds':s},{'minutes':1,'seconds':s},{'minutes':10,'seconds':last}])}
          for s,last in [(4.49,27.5),(14.49,37.5)]]
 def invoke(self):return p.run_joint_timing_unit(self.root,self.audio,self.region,800.,self.opts,{})
 def test_actual_route_clock_schema_offsets_and_free_resume(self):
  replies=self.responses();before=copy.deepcopy(replies)
  with patch.object(p.subprocess,'run'),patch.object(p.gemini,'key',return_value='offline'),patch.object(p.gemini,'call',side_effect=replies) as call:
   result=self.invoke();self.assertEqual(self.invoke(),result)
  self.assertEqual(call.call_count,2);self.assertEqual(replies,before)
  self.assertEqual([x['start'] for x in result['expanded_starts']],[64.49,124.49,687.5])
  for req,duration in zip(call.call_args_list,('10:40.000','10:50.000')):
   self.assertIn('EXCERPT CLOCK: 0:00.000–'+duration,req.args[2])
   schema=req.kwargs['response_schema']['properties']['starts']
   self.assertNotIn('minItems',schema);self.assertNotIn('maxItems',schema)
   self.assertEqual(schema['items']['properties']['start'],{'type':'object','properties':{'minutes':{'type':'integer'},'seconds':{'type':'number'}},'required':['minutes','seconds'],'additionalProperties':False})
  self.assertEqual(result['passes'][0]['response']['packet']['starts'][2]['start'],{'minutes':10,'seconds':27.5})
 def test_version_identity_changes_without_reinterpreting_old_numeric_answers(self):
  self.region['prompt_version']=3
  old=[{'packet':self.packet([4.49,64.49,627.5])},{'packet':self.packet([14.49,74.49,637.5])}]
  with patch.object(p.subprocess,'run'),patch.object(p.gemini,'key',return_value='offline'),patch.object(p.gemini,'call',side_effect=old+self.responses()) as call:
   first=self.invoke();path=next(self.root.rglob('accepted-result.json'));saved=path.read_bytes()
   self.region['prompt_version']=4;second=self.invoke();self.assertEqual(self.invoke(),second)
  self.assertEqual(call.call_count,4);self.assertNotEqual(first['input_fingerprint'],second['input_fingerprint']);self.assertEqual(path.read_bytes(),saved)
  for version in (1,2,3):
   r={**self.region,'prompt_version':version};q=self.packet([104.49,201.99,609.99])
   self.assertEqual(p.validate_joint_timing_pass(r,q,800.)['starts'][0]['start'],164.49)
   self.assertTrue(p.validate_joint_timing_pass(r,self.responses()[0]['packet'],800.)['validation_errors'])
 def test_real_failure_shape_not_repaired_only_new_explicit_clock_converts(self):
  r={**self.region,'clip_start':0.,'clip_end':642.781,'prompt_version':3}
  old=self.packet([106.5,123.5,1027.5]);self.assertTrue(p.validate_joint_timing_pass(r,old,642.781)['validation_errors'])
  r['prompt_version']=4
  new=self.packet([{'minutes':1,'seconds':6.5},{'minutes':1,'seconds':23.5},{'minutes':10,'seconds':27.5}])
  self.assertEqual([x['start'] for x in p.validate_joint_timing_pass(r,new,642.781)['starts']],[66.5,83.5,627.5])
  self.assertTrue(p.validate_joint_timing_pass(r,old,642.781)['validation_errors'])
 def test_invalid_components_population_and_clip_bounds_hold(self):
  invalid=[104.49,None,{'minutes':1},{'minutes':1,'seconds':4,'start':64},
   {'minutes':True,'seconds':4},{'minutes':1.,'seconds':4},{'minutes':-1,'seconds':4},
   {'minutes':0,'seconds':True},{'minutes':0,'seconds':'4'},{'minutes':0,'seconds':-1},
   {'minutes':1,'seconds':60},{'minutes':1,'seconds':93.12},{'minutes':0,'seconds':float('nan')},
   {'minutes':0,'seconds':float('inf')},{'minutes':11,'seconds':0}]
  for value in invalid:
   q=copy.deepcopy(self.responses()[0]['packet']);q['starts'][0]['start']=value
   with self.subTest(value=value):self.assertTrue(p.validate_joint_timing_pass(self.region,q,800.)['validation_errors'])
  for kind in ('missing','duplicate','order','uncertain'):
   q=copy.deepcopy(self.responses()[0]['packet']);rows=q['starts']
   if kind=='missing':rows.pop()
   elif kind=='duplicate':rows[1]['timing_id']=rows[0]['timing_id']
   elif kind=='order':rows[0],rows[1]=rows[1],rows[0]
   else:rows[0]['uncertainty']='masked consonant'
   with self.subTest(kind=kind):self.assertTrue(p.validate_joint_timing_pass(self.region,q,800.)['validation_errors'])
 def test_zero_clock_needs_explicit_complete_onset(self):
  q=self.responses()[0]['packet'];q['starts'][0]['start']={'minutes':0,'seconds':0}
  self.assertTrue(p.validate_joint_timing_pass(self.region,q,800.)['validation_errors'])
  q['starts'][0]['onset_at_clip_start']=True
  self.assertEqual(p.validate_joint_timing_pass(self.region,q,800.)['starts'][0]['start'],60.)
 def test_same_parser_revalidates_full_partial_and_final_evidence(self):
  report={'region':self.region,'input_fingerprint':'fixture','passes':[
   {'region':p.independent_joint_region(self.region,i),'response':r} for i,r in enumerate(self.responses())]}
  original=copy.deepcopy(report)
  full=p.joint_pair_evidence(report,expected_region=self.region,expected_fingerprint='fixture',duration=800.)
  self.assertEqual([x['start'] for x in full['agreed']],[64.49,124.49,687.5]);self.assertEqual(report,original)
  report['passes'][1]['response']['packet']['starts'][1]['start']['seconds']=93.12
  with self.assertRaises(ValueError):p.joint_pair_evidence(report,expected_region=self.region,expected_fingerprint='fixture',duration=800.)
  partial=p.joint_pair_evidence(report,expected_region=self.region,expected_fingerprint='fixture',duration=800.,allow_partial_rows=True)
  self.assertEqual(partial['held_timing_ids'],[p.region_timing_targets(self.region)[1]['timing_id']])
  self.assertEqual(len(partial['agreed']),2)
  with self.assertRaises(ValueError):p.assemble_joint_pair_evidence(self.occ,partial['agreed'],800.)
 def test_unknown_version_fails_direct_retained_packet_validation(self):
  for version in (True,None,0,5,'4',4.0):
   r={**self.region,'prompt_version':version}
   with self.subTest(version=version):
    self.assertTrue(p.validate_joint_timing_pass(r,self.packet([4.49,64.49,627.5]),800.)['validation_errors'])

if __name__=='__main__':unittest.main()

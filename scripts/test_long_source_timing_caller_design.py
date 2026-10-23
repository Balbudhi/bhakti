"""Real long timing caller/FFmpeg/router with synthetic provider responses only."""
import argparse,copy,json,re,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import audit_bhakti_contract as contract
import bhakti_pipeline as pipeline
import bhakti_library_source_pass as source
import bhakti_model_routes as routes
from test_generic_source_caller import make_audio,js,write_json
from test_source_timing_ownership_design import long_fixture

class LongSourceTimingCallerDesignTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.song=self.root/'long-song';self.song.mkdir()
  self.audio=self.song/'audio.m4a';make_audio(self.audio,1200)
  self.calls=[];self.wrong_repeat=False;self.uncertain_second=False
  self.addCleanup(patch.stopall)
  patch.object(pipeline.gemini,'key',return_value='fixture-not-a-key').start()
  patch.object(pipeline.gemini,'call',side_effect=self.provider).start()
 def setup_source(self,repeat=False):
  reader,delta,_=long_fixture(split_repeat=repeat)
  delta['before_identity']['audio_sha256']=source.file_hash(self.audio)
  archive=self.song/'.transcription/source-pass-original';archive.mkdir(parents=True)
  js(archive/'data.js',reader);reader=contract.load_data(archive/'data.js')
  routes.run_unit(self.root/'source-route','fixture-source','a'*64,lambda ctx:{'source':'fixture'},lambda value:[],
    deadline_at=time.time()+300,base_model=pipeline.MODEL,pro_model=routes.PRO_MODEL)
  state=next((self.root/'source-route').rglob('route-state.json'))
  receipt={'version':1,'status':'accepted-source','original_reader_digest':source.digest(reader),
    'before_identity':delta['before_identity'],'delta':delta,'delta_digest':source.digest(delta),
    'approved_source_order_digest':source.digest(delta['rebuilt']),
    'evidence_files':{str(p):source.file_hash(p) for p in (state,state.parent/'accepted-result.json')}}
  path=self.root/'accepted-source-delta.json';write_json(path,receipt)
  self.options=argparse.Namespace(model=pipeline.MODEL,pro_model=routes.PRO_MODEL,force=False,
    timeout=60,timing_deadline_at=time.time()+300,timing_source_adoption={
      'path':str(path),'sha256':source.file_hash(path),
      'original_reader':{'path':str(archive/'data.js'),'sha256':source.file_hash(archive/'data.js')},'prior_timing':None})
  self.audited={'packet':delta['rebuilt']}
  self.target=self.song/'.transcription/pipeline/03-timing.json';write_json(self.target,{'original':'unchanged'})
  self.old_bytes=self.target.read_bytes()
  self.points=({'occ-000-r01':2.,'occ-001-r01':402.,'occ-001-r02':802.,'occ-002-r01':1002.,'occ-003-r01':1102.}
      if repeat else {'occ-000-r01':2.,'occ-001-r01':402.,'occ-002-r01':802.,'occ-003-r01':1102.})
 def provider(self,model,key,prompt,**kwargs):
  self.assertEqual(kwargs['schema_name'],'bhakti_joint_starts')
  targets=json.JSONDecoder().raw_decode(prompt.split('EXACT ORDERED TIMING TARGETS: ',1)[1])[0]
  bounds=re.search(r'SOURCE CLIP: ([0-9.]+)–([0-9.]+)',prompt);left,right=map(float,bounds.groups())
  self.assertLessEqual(right-left,900.)
  self.assertLessEqual(pipeline.gemini.duration_seconds(kwargs['audio']),900.1)
  ids=[row['timing_id'] for row in targets];self.calls.append((model,ids,left,right))
  second='occ-003-r01' in ids;starts=[]
  for row in targets:
   point=self.points[row['timing_id']]
   if self.wrong_repeat and row['timing_id']=='occ-001-r02' and model==self.options.model:
    point=402.;self.assertLess(left,point);self.assertLess(point,right)
   starts.append({'timing_id':row['timing_id'],'start':point-left,'onset_at_clip_start':point==left,
     'uncertainty':'masked onset' if second and self.uncertain_second else ''})
  return {'packet':{'starts':starts},'resolved_model':model}
 def invoke(self):return pipeline.align(self.song,self.audited,self.audio,self.options)
 def test_actual_requests_stay_bounded_and_owned_targets_appear_once_per_independent_pass(self):
  self.setup_source();result=self.invoke()
  self.assertEqual([ids for _,ids,_,_ in self.calls],
    [['occ-000-r01','occ-001-r01','occ-002-r01']]*2+[['occ-003-r01']]*2)
  self.assertEqual([row['start'] for row in result['sequence']],[2.,402.,802.,1102.])
  count=len(self.calls);self.assertEqual(self.invoke(),result);self.assertEqual(len(self.calls),count)
 def test_cross_unit_repeat_keeps_global_identity_and_one_public_display_block(self):
  self.setup_source(repeat=True);result=self.invoke()
  self.assertEqual([ids for _,ids,_,_ in self.calls],
    [['occ-000-r01','occ-001-r01']]*2+[['occ-001-r02','occ-002-r01','occ-003-r01']]*2)
  self.assertEqual([row['repeats'] for row in result['sequence']],[1,2,1,1])
  self.assertEqual([(row['start'],row['end']) for row in result['sequence']],[(2.,402.),(402.,1002.),(1002.,1102.),(1102.,1200.)])
 def test_wrong_second_repeat_escalates_only_second_unit_using_first_accepted_repeat_anchor(self):
  self.setup_source(repeat=True);self.wrong_repeat=True;result=self.invoke()
  self.assertEqual(len(self.calls),6)
  self.assertEqual([model for model,_,_,_ in self.calls],[self.options.model]*4+[self.options.pro_model]*2)
  self.assertEqual([ids for _,ids,_,_ in self.calls][2:],[['occ-001-r02','occ-002-r01','occ-003-r01']]*4)
  self.assertEqual([row['start'] for row in result['sequence']],[2.,402.,1002.,1102.])
 def test_interrupted_long_caller_reuses_first_unit_and_only_measures_remaining_owner(self):
  self.setup_source();real=pipeline.run_joint_timing_unit
  def interrupted(song,audio,region,*args,**kwargs):
   if region['source_unit_id']=='segment-1':raise KeyboardInterrupt('between accepted units')
   return real(song,audio,region,*args,**kwargs)
  with patch.object(pipeline,'run_joint_timing_unit',side_effect=interrupted):
   with self.assertRaises(KeyboardInterrupt):self.invoke()
  self.assertEqual(len(self.calls),2);self.assertEqual(self.target.read_bytes(),self.old_bytes)
  result=self.invoke();self.assertEqual(len(self.calls),4)
  self.assertEqual([row['start'] for row in result['sequence']],[2.,402.,802.,1102.])
 def test_second_unit_uncertain_holds_without_repaying_completed_first_unit(self):
  self.setup_source();self.uncertain_second=True
  with self.assertRaises(routes.UnitUnresolved):self.invoke()
  self.assertEqual(len(self.calls),6);self.assertEqual(self.target.read_bytes(),self.old_bytes)
  with patch.object(pipeline.gemini,'call',side_effect=AssertionError('terminal held unit must not repay')):
   with self.assertRaises(routes.UnitUnresolved):self.invoke()
  self.assertEqual(self.target.read_bytes(),self.old_bytes)

if __name__=='__main__':unittest.main()

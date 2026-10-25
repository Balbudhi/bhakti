"""Model excerpt bitrate routing only; listener audio and validation stay unchanged."""
import argparse,copy,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import bhakti_pipeline as p
import bhakti_model_routes as routes
FIXTURE=json.loads((Path(p.__file__).parent/'fixtures/satgur-timing.json').read_text())
class ClipAudioRateTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.audio=self.root/'audio.m4a';self.audio.write_bytes(b'unchanged-canonical-audio')
  self.occ=copy.deepcopy([x for x in FIXTURE['timing']['ordered_occurrences'] if x['repeats']==1][:3])
  self.region={'index':0,'clip_start':105.,'clip_end':189.,'target_occurrences':self.occ,
               'preceding_context':None,'following_context':None,'prompt_version':3,'max_completion_tokens':8192,'reasoning_effort':'low'}
  self.options=argparse.Namespace(model=routes.PRO_MODEL,pro_model=routes.PRO_MODEL,timeout=180,timing_deadline_at=time.time()+600,force=False)
 def invoke(self):return p.run_joint_timing_unit(self.root,self.audio,self.region,400.,self.options,{})
 def replies(self):
  return [{'packet':{'starts':[{'timing_id':x['timing_id'],'start':s,'uncertainty':'','onset_at_clip_start':False}
    for x,s in zip(p.region_timing_targets(self.region),starts)]}} for starts in ([25.6,32.8,40.1],[35.6,42.8,50.1])]
 def test_default_remains192_both_passes(self):
  with patch.object(p.subprocess,'run') as ff,patch.object(p.gemini,'key',return_value='offline'),patch.object(p.gemini,'call',side_effect=self.replies()) as call:
   result=self.invoke()
  self.assertEqual(call.call_count,2)
  self.assertEqual([c.args[0][c.args[0].index('-b:a')+1] for c in ff.call_args_list],['192k','192k'])
  self.assertEqual([r['start'] for r in result['expanded_starts']],[130.6,137.8,145.1])
 def test_explicit128_is_bound_to_both_clips_and_cache_without_changing_original(self):
  original=self.audio.read_bytes()
  with patch.object(p.subprocess,'run') as ff,patch.object(p.gemini,'key',return_value='offline'),patch.object(p.gemini,'call',side_effect=self.replies()+self.replies()) as call:
   old=self.invoke();old_path=next(self.root.rglob('accepted-result.json'));old_bytes=old_path.read_bytes()
   self.region['clip_audio_bitrate_kbps']=128;new=self.invoke();self.assertEqual(self.invoke(),new)
  self.assertEqual(call.call_count,4);self.assertNotEqual(old['input_fingerprint'],new['input_fingerprint'])
  self.assertEqual([c.args[0][c.args[0].index('-b:a')+1] for c in ff.call_args_list],['192k','192k','128k','128k'])
  self.assertEqual([c.args[0][c.args[0].index('-ss')+1] for c in ff.call_args_list[-2:]],['105.000','95.000'])
  self.assertEqual(old_path.read_bytes(),old_bytes);self.assertEqual(self.audio.read_bytes(),original)
  self.assertEqual(old['expanded_starts'],new['expanded_starts'])
 def test_invalid_rate_rejected_before_audio_identity_or_route(self):
  for rate in (True,False,None,0,64,127,129,256,128.0,'128',[],{}):
   self.region['clip_audio_bitrate_kbps']=rate
   with self.subTest(rate=rate),patch.object(p,'timing_input_identity',side_effect=AssertionError('read audio')):
    with self.assertRaises(ValueError):self.invoke()
  self.assertFalse(list(self.root.rglob('route-state.json')))
if __name__=='__main__':unittest.main()

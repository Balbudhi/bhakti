"""Actual cache behavior with private imported snapshots; no paid/provider calls."""
import ast,copy,importlib.util,json,os,pathlib,sys,unittest
from unittest.mock import patch
BASE=pathlib.Path(__file__).resolve().parents[1]
MAIN=pathlib.Path(os.environ.get('BHAKTI_TEST_PIPELINE_ROOT',BASE if (BASE/'data').is_dir() else pathlib.Path.cwd()))
sys.path.insert(0,str(MAIN/'scripts'))
import test_generic_source_caller as fixture

def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

class AudioContractTests(unittest.TestCase):
 def setUp(self):
  self.f=fixture.CallerTests('test_missing_02_03_reaches_actual_audio_auditor_before_old_reads');self.f.setUp();self.addCleanup(self.f.doCleanups)
  self.pipeline_source=(BASE/'scripts/bhakti_pipeline.py').read_text();self.adapter_source=(BASE/'scripts/bhakti_library_source_pass.py').read_text()
  self.pipeline_path=self.f.base/'bhakti_pipeline.py';self.adapter_path=self.f.base/'source_adapter.py'
  self.dispatches=[];provider=self.f.provider
  def capture(model,key,prompt,**kwargs):self.dispatches.append({'model':model,'prompt':prompt,'kwargs':copy.deepcopy(kwargs)});return provider(model,key,prompt,**kwargs)
  self.f.call.side_effect=capture
 def modules(self,pipeline_source=None,adapter_source=None):
  self.pipeline_path.write_text(pipeline_source or self.pipeline_source);self.adapter_path.write_text(adapter_source or self.adapter_source)
  p=load('bhakti_pipeline',self.pipeline_path);p.ROOT=MAIN;a=load('source_audio_contract_adapter',self.adapter_path);return p,a
 def invoke(self,p,a):
  with patch.dict(sys.modules,{'bhakti_pipeline':p}),patch.object(fixture,'adapter',a):
   return self.f.observed(self.f.invoke())
 def test_english_prompt_only_change_reuses_audio_and_original_receipt(self):
  p,a=self.modules();first=self.invoke(p,a);path=pathlib.Path(first['receipt_path']);raw=path.read_bytes();self.invoke(p,a);self.assertEqual(len(self.dispatches),1)
  before='A rare but attested word is acceptable when it is precise and remains understandable in context.';after=before.replace('remains','stays');self.assertEqual(self.pipeline_source.count(before),1)
  changed=self.pipeline_source.replace(before,after)
  funcs=lambda text:{n.name:ast.dump(n,include_attributes=False) for n in ast.parse(text).body if isinstance(n,ast.FunctionDef)}
  old,new=funcs(self.pipeline_source),funcs(changed);self.assertEqual([k for k in old if old[k]!=new[k]],['translate'])
  p,a=self.modules(pipeline_source=changed);second=self.invoke(p,a);self.assertEqual(len(self.dispatches),1);self.assertEqual(second['input_fingerprint'],first['input_fingerprint']);self.assertEqual(second['unit_results'][0]['route_state_path'],first['unit_results'][0]['route_state_path']);self.assertEqual(path.read_bytes(),raw)
 def test_semantic_adapter_only_change_reuses_audio(self):
  p,a=self.modules();first=self.invoke(p,a);needle='Fresh text is a routed, independently reviewed subset, never old English.';self.assertEqual(self.adapter_source.count(needle),1)
  p,a=self.modules(adapter_source=self.adapter_source.replace(needle,needle+' Semantic-only documentation edit.'));second=self.invoke(p,a)
  self.assertEqual(len(self.dispatches),1);self.assertEqual(second['input_fingerprint'],first['input_fingerprint'])
 def test_actual_audio_prompt_change_invalidates_request(self):
  p,a=self.modules();first=self.invoke(p,a);needle='Do not translate or estimate timestamps.';self.assertGreaterEqual(self.pipeline_source.count(needle),1)
  p,a=self.modules(pipeline_source=self.pipeline_source.replace(needle,'Do not translate; do not estimate timestamps.'));second=self.invoke(p,a)
  self.assertEqual(len(self.dispatches),2);self.assertNotEqual(first['input_fingerprint'],second['input_fingerprint']);self.assertNotEqual(self.dispatches[0]['prompt'],self.dispatches[1]['prompt'])
 def test_schema_change_invalidates_and_actual_dispatch_uses_changed_schema(self):
  p,a=self.modules();first=self.invoke(p,a);schema=p.segment_transcript_schema
  def changed_schema():return {**schema(),'description':'Source audio schema revision fixture'}
  with patch.object(p,'segment_transcript_schema',side_effect=changed_schema):second=self.invoke(p,a)
  self.assertEqual(len(self.dispatches),2);self.assertNotEqual(first['input_fingerprint'],second['input_fingerprint']);self.assertEqual(self.dispatches[-1]['kwargs']['response_schema']['description'],'Source audio schema revision fixture')
 def test_generation_and_codec_contract_are_consumed_by_real_dispatch(self):
  p,a=self.modules();first=self.invoke(p,a);request=p.audio_audit_request_contract;clip=p.audio_audit_clip_contract
  def changed_request(*args,**kwargs):
   value=request(*args,**kwargs);value['reasoning_effort']='medium';value['max_completion_tokens']=16000;return value
  def changed_clip():return {**clip(),'bitrate':'128k'}
  commands=[];real=p.subprocess.run
  def capture(cmd,*args,**kwargs):commands.append(cmd);return real(cmd,*args,**kwargs)
  with patch.object(p,'audio_audit_request_contract',side_effect=changed_request),patch.object(p,'audio_audit_clip_contract',side_effect=changed_clip),patch.object(p.subprocess,'run',side_effect=capture):second=self.invoke(p,a)
  self.assertEqual(len(self.dispatches),2);self.assertNotEqual(first['input_fingerprint'],second['input_fingerprint']);self.assertEqual(self.dispatches[-1]['kwargs']['reasoning_effort'],'medium');self.assertEqual(self.dispatches[-1]['kwargs']['max_completion_tokens'],16000)
  encoded=[cmd for cmd in commands if pathlib.Path(cmd[0]).name=='ffmpeg' and '-b:a' in cmd];self.assertTrue(encoded);self.assertTrue(all(cmd[cmd.index('-b:a')+1]=='128k' for cmd in encoded))
 def test_observation_contract_change_has_new_receipt_and_unit_identity(self):
  p,a=self.modules();first=self.invoke(p,a)
  with patch.object(a,'SOURCE_OBSERVATION_VERSION',a.SOURCE_OBSERVATION_VERSION+1):second=self.invoke(p,a)
  self.assertEqual(len(self.dispatches),2);self.assertNotEqual(first['input_fingerprint'],second['input_fingerprint'])
 def test_routing_contract_change_invalidates_saved_plan(self):
  p,a=self.modules();first=self.invoke(p,a)
  with patch.object(a,'SOURCE_ROUTING_VERSION',a.SOURCE_ROUTING_VERSION+1):second=self.invoke(p,a)
  self.assertNotEqual(first['input_fingerprint'],second['input_fingerprint']);self.assertNotEqual(first['receipt_path'],second['receipt_path'])
 def test_model_route_change_invalidates(self):
  p,a=self.modules();first=self.invoke(p,a);self.f.options.model=self.f.options.pro_model;second=self.invoke(p,a)
  self.assertEqual(len(self.dispatches),2);self.assertNotEqual(first['input_fingerprint'],second['input_fingerprint']);self.assertEqual(self.dispatches[-1]['model'],self.f.options.pro_model)
 def test_native_audio_change_invalidates_with_same_source(self):
  import shutil
  p,a=self.modules();first=self.invoke(p,a);fixture.make_audio(self.f.song/'audio.m4a',5);shutil.copy2(self.f.song/'audio.m4a',self.f.workspace/'songs'/self.f.slug/'audio.m4a');second=self.invoke(p,a)
  self.assertEqual(len(self.dispatches),2);self.assertNotEqual(first['input_fingerprint'],second['input_fingerprint'])

if __name__=='__main__':unittest.main()

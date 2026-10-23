"""Legacy migration qualification: compact v1 producer + real router/HTTP worker/storage.
No external service: a local HTTP fixture echoes the source transcript.
Fixture identities and request contract reproduce the supported historical version.
"""
import copy,http.server,json,os,pathlib,subprocess,sys,threading,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(os.environ.get('BHAKTI_TEST_PIPELINE_ROOT',pathlib.Path(__file__).resolve().parents[1]))/'scripts'))
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
import bhakti_model_routes
import bhakti_source_cache_compat
import fixture_legacy_audio_cache as old_fixture
import test_source_audio_contract as fixture
import process_song_gemini as client
import bhakti_model_routes as routes
REAL_CALL=client.call

class LegacyMigrationTests(unittest.TestCase):
 def setUp(self):
  self.case=fixture.AudioContractTests('test_english_prompt_only_change_reuses_audio_and_original_receipt');self.case.setUp();self.addCleanup(self.case.doCleanups)
  self.http_requests=[];outer=self
  class Handler(http.server.BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));outer.http_requests.append(body)
    prompt=next(p['text'] for p in body['messages'][0]['content'] if p['type']=='text')
    draft=json.JSONDecoder().raw_decode(prompt.split('FIRST TRANSCRIPT:\n',1)[1].lstrip())[0]
    if getattr(outer,'uncertain',False):draft['uncertainties']=['fixture unresolved hearing']
    result={'model':body['model'],'provider':'local fixture','choices':[{'message':{'content':json.dumps(draft)},'finish_reason':'stop'}],'usage':{'cost':.00001}}
    self.send_response(200);self.end_headers();self.wfile.write(json.dumps(result).encode())
  self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
  threading.Thread(target=self.server.serve_forever,daemon=True).start();self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
  self.ledger=self.case.f.base/'ledger.json'
  for p in [patch.dict(os.environ,{'BHAKTI_GEMINI_PROVIDER':'openrouter','BHAKTI_API_RUN_LEDGER':str(self.ledger),'BHAKTI_API_RUN_BUDGET_USD':'5'}),patch.object(client,'API_URL',f'http://127.0.0.1:{self.server.server_port}/'),patch.object(client,'_wait_for_api_start')]:p.start();self.addCleanup(p.stop)
  self.case.f.call.side_effect=REAL_CALL
 def legacy(self):
  p,a=self.case.modules()
  with patch.dict(sys.modules,{'bhakti_pipeline':p}):result=old_fixture.produce(self.case.f,p,a)
  self.assertEqual(len(self.http_requests),1)
  return result
 def current(self):
  p,a=self.case.modules()
  with patch.dict(sys.modules,{'bhakti_pipeline':p}),patch.object(fixture.fixture,'adapter',a):return self.case.f.invoke()
 def request_file(self):return next(self.ledger.parent.glob('ledger-responses/*.request.json'))
 def test_exact_legacy_request_is_reused_without_http_or_history_rewrite(self):
  old=self.legacy();saved={p:p.read_bytes() for p in self.case.f.route.rglob('*.json')}
  new=self.current();self.case.f.observed(new);self.assertEqual(len(self.http_requests),1)
  self.assertEqual(new['evidence']['audio_review']['unit_results'][0]['result'],old['unit_results'][0]['result'])
  self.assertTrue(all(p.read_bytes()==data for p,data in saved.items()))
 def test_missing_legacy_request_proof_holds_without_repaying(self):
  self.legacy();self.request_file().unlink();result=self.current()
  self.assertEqual(len(self.http_requests),1);self.assertFalse(result['publicationEligible'])
  self.assertIn('legacy',json.dumps(result).lower())
 def test_tampered_legacy_prompt_proof_holds_without_repaying(self):
  self.legacy();p=self.request_file();r=json.loads(p.read_text());next(x for x in r['messages'][0]['content'] if x['type']=='text')['text']='unproved different request';p.write_text(json.dumps(r))
  result=self.current();self.assertEqual(len(self.http_requests),1);self.assertFalse(result['publicationEligible']);self.assertIn('legacy',json.dumps(result).lower())
 def test_missing_aggregate_receipt_still_reuses_integrity_bound_legacy_unit(self):
  old=self.legacy();pathlib.Path(old['receipt_path']).unlink();result=self.current();self.case.f.observed(result);self.assertEqual(len(self.http_requests),1)
 def test_legacy_candidate_tamper_is_never_treated_as_permission_to_repay(self):
  self.legacy();p=next(self.case.f.route.rglob('candidate.json'));r=json.loads(p.read_text());r['segment_audits'][0]['audit']['packet']['lines'][0]['roman']='invented';p.write_text(json.dumps(r))
  try:result=self.current()
  except routes.RunFatal:pass
  else:self.assertFalse(result['publicationEligible']);self.assertIn('legacy',json.dumps(result).lower())
  self.assertEqual(len(self.http_requests),1)
 def test_genuine_model_change_dispatches_new_request(self):
  self.legacy();self.case.f.options.model=self.case.f.options.pro_model;self.case.f.observed(self.current());self.assertEqual(len(self.http_requests),2);self.assertEqual(self.http_requests[-1]['model'],self.case.f.options.pro_model)
 def test_unresolved_legacy_history_cannot_restart_flash_pro_allowance(self):
  self.uncertain=True;p,a=self.case.modules()
  with patch.dict(sys.modules,{'bhakti_pipeline':p}):old=old_fixture.produce(self.case.f,p,a)
  self.assertEqual(old['status'],'unresolved');self.assertEqual(len(self.http_requests),2)
  self.uncertain=False;result=self.current();self.assertEqual(len(self.http_requests),2)
  self.assertIn('legacy',json.dumps(result).lower());self.assertFalse(result['publicationEligible'])
 def test_interrupted_running_legacy_request_is_held_without_new_dispatch(self):
  def interrupted(*args,**kwargs):
   REAL_CALL(*args,**kwargs)
   raise KeyboardInterrupt('fixture interruption after paid response')
  self.case.f.call.side_effect=interrupted;p,a=self.case.modules()
  with patch.dict(sys.modules,{'bhakti_pipeline':p}),self.assertRaises(KeyboardInterrupt):old_fixture.produce(self.case.f,p,a)
  self.assertEqual(len(self.http_requests),1);self.case.f.call.side_effect=REAL_CALL
  result=self.current();self.assertEqual(len(self.http_requests),1);self.assertIn('legacy',json.dumps(result).lower())
 def test_genuine_audio_change_dispatches_new_request(self):
  import shutil
  self.legacy();fixture.fixture.make_audio(self.case.f.song/'audio.m4a',5)
  shutil.copy2(self.case.f.song/'audio.m4a',self.case.f.workspace/'songs'/self.case.f.slug/'audio.m4a')
  self.case.f.observed(self.current());self.assertEqual(len(self.http_requests),2)
 def test_genuine_prompt_change_dispatches_only_after_legacy_proof(self):
  self.legacy();self.case.pipeline_source=self.case.pipeline_source.replace('Do not translate or estimate timestamps.','Do not translate; do not estimate timestamps.')
  self.case.f.observed(self.current());self.assertEqual(len(self.http_requests),2)
 def test_genuine_codec_change_dispatches_new_request(self):
  self.legacy();p,a=self.case.modules();clip=p.audio_audit_clip_contract
  with patch.dict(sys.modules,{'bhakti_pipeline':p}),patch.object(fixture.fixture,'adapter',a),patch.object(p,'audio_audit_clip_contract',side_effect=lambda:{**clip(),'bitrate':'128k'}):result=self.case.f.invoke()
  self.case.f.observed(result);self.assertEqual(len(self.http_requests),2)
 def test_interrupted_new_receipt_reuses_legacy_on_resume(self):
  self.legacy();p,a=self.case.modules();write=a.atomic_json
  def interrupt(path,value):
   if pathlib.Path(path).name.endswith('-source-observed.json'):raise OSError('fixture receipt interruption')
   return write(path,value)
  with patch.dict(sys.modules,{'bhakti_pipeline':p}),patch.object(fixture.fixture,'adapter',a),patch.object(a,'atomic_json',side_effect=interrupt):result=self.case.f.invoke()
  self.assertFalse(result['publicationEligible']);self.assertEqual(len(self.http_requests),1)
  self.case.f.observed(self.current());self.assertEqual(len(self.http_requests),1)
 def test_genuine_schema_change_dispatches_new_request(self):
  self.legacy();p,a=self.case.modules();schema=p.segment_transcript_schema
  with patch.dict(sys.modules,{'bhakti_pipeline':p}),patch.object(fixture.fixture,'adapter',a),patch.object(p,'segment_transcript_schema',side_effect=lambda:{**schema(),'description':'changed source schema'}):result=self.case.f.invoke()
  self.case.f.observed(result);self.assertEqual(len(self.http_requests),2)
 def test_missing_legacy_ledger_holds_without_dispatch(self):
  self.legacy();self.ledger.unlink()
  result=self.current();self.assertEqual(len(self.http_requests),1);self.assertIn('legacy',json.dumps(result).lower())
 def test_tampered_encoded_audio_evidence_holds_without_dispatch(self):
  self.legacy();p=self.request_file();r=json.loads(p.read_text())
  next(x for x in r['messages'][0]['content'] if x['type']=='input_audio')['input_audio']['data']['base64_sha256']='0'*64
  p.write_text(json.dumps(r));result=self.current();self.assertEqual(len(self.http_requests),1);self.assertIn('legacy',json.dumps(result).lower())
 def assert_migration_holds_without_new_http(self):
  before=len(self.http_requests)
  try:result=self.current()
  except routes.RunFatal:pass
  else:
   self.assertFalse(result['publicationEligible'])
   self.assertNotEqual(result.get('evidence',{}).get('audio_review',{}).get('status'),'observed')
   self.assertIn('legacy',json.dumps(result.get('issues',[])).lower())
  self.assertEqual(len(self.http_requests),before)
 def test_receipt_referenced_state_missing_unit_id_holds_before_dispatch(self):
  self.legacy();p=next(self.case.f.route.glob('*/route-state.json'))
  state=json.loads(p.read_text());del state['unit_id'];p.write_text(json.dumps(state))
  self.assert_migration_holds_without_new_http()
 def test_receipt_referenced_valid_wrong_unit_holds_before_dispatch(self):
  old=self.legacy();p=next(self.case.f.route.glob('*/route-state.json'))
  state=json.loads(p.read_text());state['unit_id']='other-song:source-observation:whole-recording'
  target=routes.unit_state_path(self.case.f.route,state['unit_id'],state['input_fingerprint'],
   dependency_fingerprint=state['dependency_fingerprint'],base_model=state['base_model'],pro_model=state['pro_model'],
   policy=routes.EscalationPolicy(**state['policy']))
  p.parent.rename(target.parent);target.write_text(json.dumps(state))
  self.assertEqual(routes.read_unit_cache(target)['state']['unit_id'],state['unit_id'])
  receipt=pathlib.Path(old['receipt_path']);record=json.loads(receipt.read_text())
  record['result']['unit_results'][0]['route_state_path']=str(target.resolve())
  record['result_digest']=bhakti_source_cache_compat.digest(record['result']);receipt.write_text(json.dumps(record))
  self.assert_migration_holds_without_new_http()
 def test_ledger_surviving_lost_receipt_and_state_holds_before_dispatch(self):
  old=self.legacy();pathlib.Path(old['receipt_path']).unlink()
  next(self.case.f.route.glob('*/route-state.json')).unlink()
  self.assert_migration_holds_without_new_http()
 def test_unexpected_legacy_generation_field_prevents_compatibility(self):
  self.legacy();p=self.request_file();record=json.loads(p.read_text())
  record['top_p']=0.01;p.write_text(json.dumps(record))
  self.assert_migration_holds_without_new_http()

if __name__=='__main__':unittest.main()

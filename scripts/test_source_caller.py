"""Real private generation; only model/timing boundaries replaced in fixtures."""
import argparse,copy,importlib.util,json,os,pathlib,shutil,sys,tempfile,time,unittest
from unittest.mock import patch
HERE=pathlib.Path(__file__).resolve().parents[1]
DEPENDENCY=pathlib.Path(os.environ.get('BHAKTI_TEST_PIPELINE_ROOT', HERE))
sys.path.insert(0,str(DEPENDENCY/'scripts'))
spec=importlib.util.spec_from_file_location('source_adapter_caller',HERE/'scripts/bhakti_library_source_pass.py'); adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
import bhakti_pipeline as pipeline
import audit_bhakti_contract as contract
import bhakti_translation_policy as policy

def write_json(p,value):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,ensure_ascii=False))
def write_reader(p,value):p.parent.mkdir(parents=True,exist_ok=True);p.write_text('\n'.join('window.'+k+' = '+json.dumps(v,ensure_ascii=False)+';' for k,v in value.items()))
def fresh(plan):
 lines=[x for x in plan['lines'] if x['id'] in plan['new_target_ids']];glosses=[];translations=[]
 for line in lines:
  lid=line['id'];tokens=policy.word_tokens(line)
  decisions=[{'word_index':i,'roman':t,'evidence_status':'contextual_inference','chosen':[],'rejected':[],'contextual_reason':'The source describes bodily coolness.','grammatical_role':'adjective'} for i,t in enumerate(tokens)]
  glosses.append({'id':lid,'word_glosses':[{'roman':t,'gloss':'cool','concept_key':'','preserve_in_english':False} for t in tokens], 'semantic_frame':{k:'Describes coolness' for k in pipeline.SEMANTIC_FRAME_FIELDS},'grammar_note':'Adjective.','uncertainty':'','sense_decisions':decisions})
  translations.append({'id':lid,'literal_english':'Cool','segments':[{'text':'Cool','word_indices':list(range(len(tokens)))}],'uncertainty':'','human_review_recommended':False,'fidelity':{'agency_and_image_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[]},'independent_review':{'id':lid,'passes':True,'agency_preserved':True,'imagery_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[],'human_review_recommended':False}})
 return {'glosses':{'packet':{'glosses':glosses}},'translations':{'packet':{'translations':translations}}}

class CallerTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);base=pathlib.Path(self.tmp.name);self.root=base/'root';self.workspace=base/'workspace';self.route=base/'route';self.slug='source-fixture'
  self.reader={'SONG_META':{'title':'Original','languages':['Hindi'],'audioSources':[{'src':'audio.webm','type':'audio/webm'}],'arbitraryOwnerField':'keep','credit':'Singer','writer':'','singer':'Singer','composer':'','subjectTags':[],'timingStatus':'start-only-reviewed','translationStatus':'gloss-derived literal','sourceStatus':'reviewed'},'SONG_LINES':{'old':{'source':'मन','sourceLanguage':'hi','sourceWords':[{'text':'मन','wordIndices':[0]}],'roman':'man','english':'{0:Mind}','words':[{'roman':'man','gloss':'mind'}],'grammarNote':'Original note'}},'SONG_SEQUENCE':[{'ref':'old','section':'verse','repeats':1}],'SONG_TIMINGS':[{'start':0,'end':1}]}
  self.audit={'packet':{'metadata':{'languages':['Hindi']},'verified_lines':[{'id':'raw-old','source_text':'मन','roman':'man','kind':'verse'},{'id':'raw-new','source_text':'शीतल','roman':'śītal','kind':'verse'}],'performance_order':[{'line_id':'raw-old','occurrence':1},{'line_id':'raw-new','occurrence':1}],'uncertainties':[]}}
  self.timing={'sequence':[{'ref':'old','section':'verse','repeats':1,'start':0,'end':1},{'ref':'source-new-raw-new','section':'verse','repeats':1,'start':1,'end':2}], 'validation_errors':[]}
  song=self.root/'songs'/self.slug;write_reader(song/'data.js',self.reader);(song/'index.html').write_text('<html>Original</html>');(song/'audio.webm').write_bytes(b'fixture only')
  write_json(song/'.transcription/pipeline/02-transcript-audit.json',self.audit);write_json(song/'.transcription/pipeline/03-timing.json',{'sequence':[]});write_json(self.root/'data/editorial_baselines.json',{'version':1,'songs':{}})
  shutil.copytree(self.root,self.workspace)
  self.options=argparse.Namespace(model=pipeline.MODEL,pro_model='test/pro',timeout=30)
  self.target_calls=[]
  def targets(song_dir,plan,metadata,options,route_dir,deadline_at):self.target_calls.append(copy.deepcopy(plan['new_target_ids']));return fresh(plan)
  self.target=patch.object(adapter,'process_new_targets',side_effect=targets,create=True).start();self.addCleanup(patch.stopall)
  self.align=patch.object(pipeline,'align',return_value=self.timing).start()
 def run_candidate(self):return adapter.run_source_candidate(root=self.root,slug=self.slug,reader=self.reader,workspace=self.workspace,route_dir=self.route,options=self.options,deadline_at=time.time()+60)
 def test_real_generation_preserves_every_old_field_and_valid_new_maps(self):
  original=(self.root/'songs'/self.slug/'data.js').read_bytes();result=self.run_candidate();self.assertEqual(result['status'],'accepted',result)
  after=result['reader'];self.assertEqual(after['SONG_META'],self.reader['SONG_META']);self.assertEqual(after['SONG_LINES']['old'],self.reader['SONG_LINES']['old']);self.assertEqual(self.target_calls,[['source-new-raw-new']]);self.assertEqual((self.root/'songs'/self.slug/'data.js').read_bytes(),original)
  row=after['SONG_LINES']['source-new-raw-new'];self.assertEqual(row['english'],'{0:Cool}');self.assertEqual(pipeline.source_word_map.validate_source_words(row['source'],row['words'],row['sourceWords']),[])
  self.assertEqual(contract.load_data(self.workspace/'songs'/self.slug/'data.js'),after)
  self.assertEqual(contract.audit_song(self.workspace/'songs'/self.slug)['status'],'ready')
 def test_resume_does_not_call_any_stage(self):
  first=self.run_candidate();self.assertEqual(first['status'],'accepted',first);self.target.side_effect=AssertionError('target rerun');self.align.side_effect=AssertionError('timing rerun');self.assertEqual(self.run_candidate(),first)
 def test_checkpoint_refuses_workspace_reader_and_html_drift(self):
  self.assertEqual(self.run_candidate()['status'],'accepted')
  (self.workspace/'songs'/self.slug/'index.html').write_text('<html>stale</html>')
  self.target.side_effect=AssertionError('must not rerun models');self.align.side_effect=AssertionError('must not rerun timing')
  self.assertEqual(self.run_candidate()['status'],'unresolved')
 def test_checkpoint_refuses_changed_candidate_data_without_rerun(self):
  result=self.run_candidate();self.assertEqual(result['status'],'accepted');changed=copy.deepcopy(result['reader']);changed['SONG_LINES']['old']['english']='{0:Invented}'
  write_reader(self.workspace/'songs'/self.slug/'data.js',changed);self.target.side_effect=AssertionError('must not rerun models');self.align.side_effect=AssertionError('must not rerun timing')
  self.assertEqual(self.run_candidate()['status'],'unresolved')
 def test_audio_change_invalidates_source_checkpoint(self):
  self.assertEqual(self.run_candidate()['status'],'accepted');(self.root/'songs'/self.slug/'audio.webm').write_bytes(b'changed');result=self.run_candidate();self.assertNotEqual(result['status'],'accepted')
 def test_failed_independent_review_never_becomes_eligible(self):
  def failed(song_dir,plan,*args):value=fresh(plan);value['translations']['packet']['translations'][0]['independent_review']['passes']=False;return value
  self.target.side_effect=failed;result=self.run_candidate();self.assertEqual(result['status'],'unresolved');self.assertFalse(result['publicationEligible']);self.align.assert_not_called()
 def test_corrupt_existing_source_map_blocks_before_stages(self):
  self.reader['SONG_LINES']['old']['sourceWords'][0]['wordIndices']=[7];write_reader(self.root/'songs'/self.slug/'data.js',self.reader);result=self.run_candidate();self.assertEqual(result['status'],'unresolved');self.target.assert_not_called();self.align.assert_not_called()
 def test_copied_registry_cannot_replace_authoritative_baseline(self):
  write_json(self.workspace/'data/editorial_baselines.json',{'version':1,'songs':{},'altered':True});self.assertEqual(self.run_candidate()['status'],'unresolved');self.target.assert_not_called()
 def test_locked_baseline_population_holds_before_calls(self):
  reg={'version':1,'songs':{self.slug:{'policy':'preserve_english','englishSha256':'a'*64,'plainEnglishByLine':{'old':'Mind'}}}}
  for root in [self.root,self.workspace]:write_json(root/'data/editorial_baselines.json',reg)
  self.assertEqual(self.run_candidate()['status'],'unresolved');self.target.assert_not_called()
 def test_actual_patta_align_retains_original_segments_and_remapped59_order(self):
  fixtures=pathlib.Path(__file__).parent/'fixtures/source_pass';raw=(fixtures/'patta-data.js').read_bytes();self.reader=contract.load_data(fixtures/'patta-data.js');original=json.loads((fixtures/'patta-original-audit.json').read_text())
  for root in [self.root,self.workspace]:
   (root/'songs'/self.slug/'data.js').write_bytes(raw);shutil.copy2(fixtures/'patta-original-audit.json',root/'songs'/self.slug/'.transcription/pipeline/02-transcript-audit.json')
  self.options.source_reuse_maps={self.slug:str(fixtures/'patta-map.json')}
  self.target.side_effect=lambda *args: {'glosses':{'packet':{'glosses':[]}},'translations':{'packet':{'translations':[]}}}
  self.align.side_effect=RuntimeError('intentional stop at real alignment boundary')
  with patch.object(adapter,'fresh_target_errors',return_value=[]):result=self.run_candidate()
  self.assertEqual(result['status'],'unresolved');self.assertIn('intentional stop',result['issues'][0]['detail']);actual=self.align.call_args.args[1]
  self.assertEqual(actual['segment_audits'],original['segment_audits']);self.assertEqual(len(actual['packet']['performance_order']),59)
  plan=result['evidence']['plan'];self.assertEqual(actual['packet']['performance_order'],plan['performance_order']);self.assertEqual(len(plan['new_target_ids']),5);self.assertEqual(set(plan['reuse_by_id']),set(self.reader['SONG_LINES']))
 def test_unknown_audit_uncertainty_holds(self):
  self.audit['packet']['uncertainties']=['unresolved source'];write_json(self.root/'songs'/self.slug/'.transcription/pipeline/02-transcript-audit.json',self.audit);self.assertEqual(self.run_candidate()['status'],'unresolved');self.target.assert_not_called()
 def test_invalid_audio_cannot_be_cleared_by_cached_source(self):
  self.options.source_requested_stages=['audio-review'];self.options.source_confirmed_issues=['hearing unclear']
  result=self.run_candidate();self.assertEqual(result['status'],'unresolved');self.assertEqual(result['issues'][0]['kind'],'source_stage_hold');self.assertIn('ffprobe',result['issues'][0]['detail']);self.target.assert_not_called();self.align.assert_not_called()
 def test_timing_only_calls_no_semantics_and_preserves_source(self):
  self.audit['packet']['verified_lines']=self.audit['packet']['verified_lines'][:1];self.audit['packet']['performance_order']=self.audit['packet']['performance_order'][:1]
  # Timing-only uses exact original IDs; any source remapping would invalidate cached evidence.
  self.audit['packet']['verified_lines'][0]['id']='old';self.audit['packet']['performance_order'][0]['line_id']='old'
  for root in [self.root,self.workspace]:write_json(root/'songs'/self.slug/'.transcription/pipeline/02-transcript-audit.json',self.audit)
  self.timing['sequence']=self.timing['sequence'][:1];self.timing['sequence'][0]['start']=.1
  for root in [self.root,self.workspace]:write_json(root/'songs'/self.slug/'.transcription/pipeline/03-timing.json',{'uncertain_occurrence_ids':['occ-000']})
  result=self.run_candidate();self.assertEqual(result['status'],'accepted',result);self.target.assert_not_called();self.assertFalse(result['source_changed']);self.assertEqual(result['reader']['SONG_LINES'],self.reader['SONG_LINES']);opts=self.align.call_args.args[3];self.assertEqual(opts.timing_repair_occurrence_ids,['occ-000']);self.assertIn('audio_sha256',opts.timing_legacy_evidence_identity)


class TargetRouteTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.directory=pathlib.Path(self.tmp.name);self.options=argparse.Namespace(model='google/gemini-3.7-flash',pro_model='google/gemini-3.1-pro-preview',timeout=20,force=False)
  self.plan={'lines':[{'id':'old','source_text':'मन','roman':'man','kind':'verse'},{'id':'new','source_text':'शीतल','roman':'śītal','kind':'verse'}],'performance_order':[{'line_id':'old'},{'line_id':'new'}],'new_target_ids':['new']};self.metadata={'languages':['Hindi']};self.value=fresh(self.plan);self.calls=[]
  old={'source':'मन','roman':'man','sourceLanguage':'hi','sourceWords':[{'text':'मन','wordIndices':[0]}],
       'english':'{0:Mind}','words':[{'roman':'man','gloss':'mind'}],'grammarNote':'Preserved noun.'}
  self.plan['reuse_by_id']={'old':old}
  self.context_evidence=[{'source':copy.deepcopy(self.plan['lines'][0]),
    'gloss':{'id':'old','word_glosses':copy.deepcopy(old['words']),'grammar_note':'Preserved noun.'},
    'draft':{'id':'old','literal_english':'Mind','segments':[{'text':'Mind','word_indices':[0]}]}}]
 def gloss(self,song,audited,options):
  self.calls.append(('gloss',options.model,audited,options));return copy.deepcopy(self.value['glosses'])
 def translate(self,song,audited,glosses,job,options,*,candidate_only):
  self.calls.append(('translate',options.model,audited,options));self.assertTrue(candidate_only);value=copy.deepcopy(self.value['translations'])
  if options.model=='google/gemini-3.7-flash':value['packet']['translations'][0]['independent_review']['passes']=False
  return value
 def run_targets(self):return adapter.process_new_targets(self.directory/'songs/test-source',self.plan,self.metadata,self.options,self.directory/'routes',time.time()+60)
 def test_real_router_escalates_failed_review_once_and_retains_full_context(self):
  with patch.object(pipeline,'gloss',side_effect=self.gloss),patch.object(pipeline,'translate',side_effect=self.translate):result=self.run_targets()
  self.assertTrue(result['translations']['packet']['translations'][0]['independent_review']['passes'])
  self.assertEqual([(x[0],x[1]) for x in self.calls],[('gloss','google/gemini-3.7-flash'),('translate','google/gemini-3.7-flash'),('gloss','google/gemini-3.1-pro-preview'),('translate','google/gemini-3.1-pro-preview')])
  for _,_,audited,options in self.calls:
   self.assertEqual([line['id'] for line in audited['packet']['verified_lines']],['new']);self.assertEqual(options.semantic_full_source,self.plan['lines']);self.assertEqual(options.semantic_performance_order,self.plan['performance_order']);self.assertEqual(options.semantic_context_evidence,self.context_evidence);self.assertTrue(options.unit_context);self.assertGreater(options.unit_deadline_at,time.time())
 def test_accepted_target_route_resumes_without_model_calls(self):
  with patch.object(pipeline,'gloss',side_effect=self.gloss),patch.object(pipeline,'translate',side_effect=self.translate):first=self.run_targets()
  with patch.object(pipeline,'gloss',side_effect=AssertionError('cached target rerun')),patch.object(pipeline,'translate',side_effect=AssertionError('cached target rerun')):self.assertEqual(self.run_targets(),first)
 def test_fatal_auth_is_not_semantic_hold_or_escalation(self):
  import bhakti_model_routes as routes
  with patch.object(pipeline,'gloss',side_effect=routes.RunFatal('credentials rejected')) as stage, self.assertRaises(routes.RunFatal):self.run_targets()
  self.assertEqual(stage.call_count,1)

class EditorialSourceConsumerTests(unittest.TestCase):
 """Explicit receipt consumes real verifier; no router state is reopened."""
 def setUp(self):
  TargetRouteTests.setUp(self)
  helper_path=os.environ.get('BHAKTI_TEST_EDITORIAL_ROOT')
  if helper_path:sys.path.insert(0,str(pathlib.Path(helper_path)))
  self.unit_id='test-source:new-source-semantics';self.route=self.directory/'routes';self.record=self.directory/'decision.json'
  self.evidence={'targets':[self.plan['lines'][1]],'source':self.plan['lines'],'order':self.plan['performance_order'],'languages':self.metadata['languages'],'reading_context':self.context_evidence,'policy':pipeline.translation_policy_payload()}
  self.input_id=adapter.digest(self.evidence);self.dependency=adapter.digest(self.evidence['policy'])
  self.candidate=copy.deepcopy(self.value);row=self.candidate['translations']['packet']['translations'][0]
  row['human_review_recommended']=True;row['material_alternatives']=['Be cool'];row['independent_review'].update(human_review_recommended=True,material_choice='Adjectival state versus direct imperative',issues=[])
  self.state_path=self.directory/'old-unit/route-state.json';self.candidate_path=self.directory/'old-unit/flash/candidate.json'
  state={'unit_id':self.unit_id,'input_fingerprint':self.input_id,'dependency_fingerprint':self.dependency,'status':'unresolved','attempts':[{'attempt_id':'saved-flash','status':'quality-failed'}]}
  write_json(self.state_path,state);write_json(self.candidate_path,self.candidate)
  self.effective=copy.deepcopy(self.candidate);effective_row=self.effective['translations']['packet']['translations'][0];effective_row['human_review_recommended']=False;effective_row['independent_review']['human_review_recommended']=False
  import hashlib
  sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
  record={'version':1,'decision_kind':'retain_existing_primary','reviewer':'fixture editor','rationale':'Fixture chooses the existing descriptive adjective; no real content judgment claimed.', 'source_references':[{'line_id':'new','source_quote':'शीतल'}], 'unit_id':self.unit_id,'input_fingerprint':self.input_id,'dependency_fingerprint':self.dependency,'source_digest':adapter.digest(self.evidence),'policy_digest':self.dependency,'line_id':'new','attempt_id':'saved-flash','candidate_path':str(self.candidate_path),'candidate_file_sha256':sha(self.candidate_path),'candidate_digest':adapter.digest(self.candidate),'route_state_path':str(self.state_path),'route_state_sha256':sha(self.state_path),'original_row_digest':adapter.digest(row),'selected_literal_english':'Cool','expected_flags':{'translation_human_review_recommended':True,'independent_human_review_recommended':True},'expected_result_digest':adapter.digest(self.effective)}
  write_json(self.record,record);self.options.editorial_adjudications={self.unit_id:str(self.record)}
 run_targets=TargetRouteTests.run_targets
 def test_explicit_verified_receipt_uses_original_candidate_with_zero_dispatch(self):
  import bhakti_model_routes as routes
  original_state=self.state_path.read_bytes();original_candidate=self.candidate_path.read_bytes()
  with patch.object(routes,'run_unit',side_effect=AssertionError('must not reopen router')),patch.object(pipeline,'gloss',side_effect=AssertionError('no gloss call')),patch.object(pipeline,'translate',side_effect=AssertionError('no translation call')):
   result=self.run_targets();again=self.run_targets()
  self.assertEqual(result['glosses'],self.effective['glosses']);self.assertEqual(result['translations'],self.effective['translations']);self.assertEqual(result,again);self.assertEqual(len(result['editorial_receipt']['effective_changes']),2);self.assertEqual(self.state_path.read_bytes(),original_state);self.assertEqual(self.candidate_path.read_bytes(),original_candidate)
 def test_stale_receipt_does_not_fall_back_to_paid_router(self):
  import bhakti_model_routes as routes
  record=json.loads(self.record.read_text());record['source_digest']='0'*64;write_json(self.record,record)
  with patch.object(routes,'run_unit',side_effect=AssertionError('invalid receipt cannot dispatch')),self.assertRaises(ValueError):self.run_targets()
 def test_real_fresh_gloss_validator_still_blocks_editorial_override(self):
  import bhakti_model_routes as routes
  import hashlib
  self.candidate['glosses']['packet']['glosses'][0]['semantic_frame']={}
  write_json(self.candidate_path,self.candidate);effective=copy.deepcopy(self.candidate);row=effective['translations']['packet']['translations'][0];row['human_review_recommended']=False;row['independent_review']['human_review_recommended']=False
  record=json.loads(self.record.read_text());record.update(candidate_file_sha256=hashlib.sha256(self.candidate_path.read_bytes()).hexdigest(),candidate_digest=adapter.digest(self.candidate),expected_result_digest=adapter.digest(effective));write_json(self.record,record)
  with patch.object(routes,'run_unit',side_effect=AssertionError('invalid receipt cannot dispatch')),self.assertRaises(ValueError):self.run_targets()


if __name__=='__main__':unittest.main()

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
 def test_unsupported_audio_flags_are_not_cleared_by_cached_source(self):
  self.options.source_requested_stages=['audio-review'];self.options.source_confirmed_issues=['hearing unclear']
  result=self.run_candidate();self.assertEqual(result['status'],'unresolved');self.assertEqual(result['issues'][0]['kind'],'unsupported_audio_source_review');self.target.assert_not_called();self.align.assert_not_called()
 def test_timing_only_calls_no_semantics_and_preserves_source(self):
  self.audit['packet']['verified_lines']=self.audit['packet']['verified_lines'][:1];self.audit['packet']['performance_order']=self.audit['packet']['performance_order'][:1]
  # Timing-only uses exact original IDs; any source remapping would invalidate cached evidence.
  self.audit['packet']['verified_lines'][0]['id']='old';self.audit['packet']['performance_order'][0]['line_id']='old'
  for root in [self.root,self.workspace]:write_json(root/'songs'/self.slug/'.transcription/pipeline/02-transcript-audit.json',self.audit)
  self.timing['sequence']=self.timing['sequence'][:1];self.timing['sequence'][0]['start']=.1
  for root in [self.root,self.workspace]:write_json(root/'songs'/self.slug/'.transcription/pipeline/03-timing.json',{'uncertain_occurrence_ids':['occ-000']})
  result=self.run_candidate();self.assertEqual(result['status'],'accepted',result);self.target.assert_not_called();self.assertFalse(result['source_changed']);self.assertEqual(result['reader']['SONG_LINES'],self.reader['SONG_LINES']);opts=self.align.call_args.args[3];self.assertEqual(opts.timing_repair_occurrence_ids,['occ-000']);self.assertIn('audio_sha256',opts.timing_legacy_evidence_identity)
if __name__=='__main__':unittest.main()

class TargetRouteTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.directory=pathlib.Path(self.tmp.name);self.options=argparse.Namespace(model='google/gemini-3.7-flash',pro_model='google/gemini-3.1-pro-preview',timeout=20,force=False)
  self.plan={'lines':[{'id':'old','source_text':'मन','roman':'man','kind':'verse'},{'id':'new','source_text':'शीतल','roman':'śītal','kind':'verse'}],'performance_order':[{'line_id':'old'},{'line_id':'new'}],'new_target_ids':['new']};self.metadata={'languages':['Hindi']};self.value=fresh(self.plan);self.calls=[]
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
   self.assertEqual([line['id'] for line in audited['packet']['verified_lines']],['new']);self.assertEqual(options.semantic_full_source,self.plan['lines']);self.assertEqual(options.semantic_performance_order,self.plan['performance_order']);self.assertTrue(options.unit_context);self.assertGreater(options.unit_deadline_at,time.time())
 def test_accepted_target_route_resumes_without_model_calls(self):
  with patch.object(pipeline,'gloss',side_effect=self.gloss),patch.object(pipeline,'translate',side_effect=self.translate):first=self.run_targets()
  with patch.object(pipeline,'gloss',side_effect=AssertionError('cached target rerun')),patch.object(pipeline,'translate',side_effect=AssertionError('cached target rerun')):self.assertEqual(self.run_targets(),first)
 def test_fatal_auth_is_not_semantic_hold_or_escalation(self):
  import bhakti_model_routes as routes
  with patch.object(pipeline,'gloss',side_effect=routes.RunFatal('credentials rejected')) as stage, self.assertRaises(routes.RunFatal):self.run_targets()
  self.assertEqual(stage.call_count,1)

"""Caller/partition contracts: real files, router and FFmpeg; only provider faked.

Silent fixture audio cannot establish lyric truth. Returned fixture words test
preservation, routing and refusal to publish observations, not hearing quality.
"""
import argparse,copy,importlib.util,json,os,pathlib,shutil,subprocess,sys,tempfile,time,unittest,wave
from unittest.mock import patch
BASE=pathlib.Path(__file__).resolve().parents[1]
MAIN=pathlib.Path(os.environ.get('BHAKTI_TEST_PIPELINE_ROOT',BASE if (BASE/'scripts/bhakti_pipeline.py').is_file() else pathlib.Path.cwd()))
sys.path.insert(0,str(MAIN/'scripts'))
spec=importlib.util.spec_from_file_location('generic_caller',BASE/'scripts/bhakti_library_source_pass.py')
adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
import bhakti_pipeline as pipeline
import bhakti_model_routes as routes

def js(path,data):
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text('\n'.join('window.'+k+' = '+json.dumps(v,ensure_ascii=False)+';' for k,v in data.items()))
def write_json(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False))
def make_audio(path,seconds):
 wav=path.with_suffix('.wav')
 with wave.open(str(wav),'wb') as out:
  out.setnchannels(1);out.setsampwidth(2);out.setframerate(8000)
  for _ in range(int(seconds)):out.writeframes(b'\0\0'*8000)
 subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(wav),'-c:a','aac',str(path)],check=True)
 wav.unlink()
def reader_for(duration):
 d={'SONG_META':{'title':'Source fixture','languages':['Hindi'],'audio':'audio.m4a'},'SONG_LINES':{},'SONG_SEQUENCE':[],'SONG_TIMINGS':[]}
 for i,(native,roman) in enumerate([('मन','man'),('तन','tan'),('राम','rāma')]):
  lid=f'line-{i}';d['SONG_LINES'][lid]={'source':native,'roman':roman,'sourceLanguage':'hi','english':'{0:OWNER ENGLISH}','words':[{'roman':roman,'gloss':'PRIVATE GLOSS'}],'sourceWords':[{'text':native,'wordIndices':[0]}],'grammarNote':'unchanged'}
  d['SONG_SEQUENCE'].append({'ref':lid,'section':'verse','repeats':2 if i==1 else 1})
  d['SONG_TIMINGS'].append({'start':duration*i/3,'end':duration*(i+1)/3})
 return d

class CallerTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=pathlib.Path(self.tmp.name)
  self.root=self.base/'public';self.workspace=self.base/'private';self.route=self.base/'routes';self.slug='source-review-fixture'
  self.song=self.root/'songs'/self.slug;self.song.mkdir(parents=True);make_audio(self.song/'audio.m4a',4)
  self.duration=pipeline.gemini.duration_seconds(self.song/'audio.m4a');self.reader=reader_for(self.duration)
  js(self.song/'data.js',self.reader);(self.song/'index.html').write_text('original html')
  write_json(self.root/'data/editorial_baselines.json',{'version':1,'songs':{}})
  shutil.copytree(self.root,self.workspace)
  self.options=argparse.Namespace(model=routes.FLASH_MODEL,pro_model=routes.PRO_MODEL,timeout=30,force=False,source_witness_audit=False,source_requested_stages=['audio-review'],source_review_flags={'audio':True},source_coverage_requested=False)
  self.deadline=time.time()+180;self.calls=[];self.extra=False
  self.addCleanup(patch.stopall)
  patch.object(pipeline.gemini,'key',return_value='not-a-real-key').start()
  self.call=patch.object(pipeline.gemini,'call',side_effect=self.provider).start()
  self.align=patch.object(pipeline,'align',side_effect=AssertionError('observation cannot retime')).start()
  self.gloss=patch.object(pipeline,'gloss',side_effect=AssertionError('observation cannot translate')).start()
  self.generate=patch.object(pipeline,'generate',side_effect=AssertionError('observation cannot publish')).start()
 def provider(self,model,key,prompt,**kw):
  self.assertEqual(kw['schema_name'],'bhakti_segment_audit');self.assertNotIn('OWNER ENGLISH',prompt);self.assertNotIn('PRIVATE GLOSS',prompt)
  self.assertEqual(kw['unit_context']['model'],model);self.assertLessEqual(kw['unit_context']['deadline_at'],self.deadline)
  draft=json.JSONDecoder().raw_decode(prompt.split('FIRST TRANSCRIPT:\n',1)[1].lstrip())[0]
  self.calls.append({'model':model,'draft':copy.deepcopy(draft),'prompt':prompt})
  if self.extra:
   draft['lines'].append({'id':'heard-extra','source_text':'नाम','roman':'nāma','language':'Hindi','kind':'verse','partial':'none','notes':'extra heard source'})
   draft['performance_order'].insert(1,{'line_id':'heard-extra','occurrence':1})
  draft['uncertainties']=[]
  return {'packet':draft,'resolved_model':model}
 def invoke(self):
  # This fixture qualifies the observation stage and its original admission
  # guards. Automatic adoption is separately exercised by the full caller tests.
  def observation_only(**arguments):
   target=arguments['workspace']/'songs'/arguments['slug']
   original=arguments['root']/'songs'/arguments['slug']
   return adapter.observe_source_candidate(reader=arguments['reader'],song_dir=target,
    original_song=original,audio=target/pipeline.preferred_listener_audio(original).name,
    route_dir=arguments['route_dir'],options=arguments['options'],deadline_at=arguments['deadline_at'])
  with patch.object(adapter,'run_observed_source_candidate',side_effect=observation_only):
   return adapter.run_source_candidate(root=self.root,slug=self.slug,reader=self.reader,workspace=self.workspace,route_dir=self.route,options=self.options,deadline_at=self.deadline)
 def observed(self,result):
  self.assertEqual(result['status'],'unresolved',result);self.assertFalse(result['publicationEligible']);self.assertFalse(result['source_changed']);self.assertEqual(result['reader'],self.reader)
  self.assertIn('audio_review',result['evidence'],result);obs=result['evidence']['audio_review'];self.assertEqual(obs['status'],'observed');self.assertTrue(pathlib.Path(obs['receipt_path']).is_file())
  self.assertIn('source-adjudication',obs['remaining_obligations']);self.assertIn('timing',obs['remaining_obligations'])
  self.assertFalse((self.route/(self.slug+'-source-accepted.json')).exists());return obs
 def test_missing_02_03_reaches_actual_audio_auditor_before_old_reads(self):
  before=(self.song/'data.js').read_bytes();result=self.invoke();self.observed(result)
  self.assertEqual(len(self.calls),1);self.assertEqual((self.song/'data.js').read_bytes(),before)
  self.assertEqual((self.workspace/'songs'/self.slug/'data.js').read_bytes(),before)
  self.assertEqual(len(self.calls[0]['draft']['performance_order']),4)
 def test_explicit_audio_stage_is_not_suppressed_by_false_flag(self):
  for stage,extra in [('audio-review',{}),('focused-audio-review',{'occurrence_ids':['occ-001']})]:
   with self.subTest(stage=stage):
    self.options.source_requested_stages=[stage];self.options.source_review_flags={'audio':False,**extra};before=len(self.calls)
    obs=self.observed(self.invoke());self.assertEqual(len(self.calls),before+1);self.assertTrue(obs['units'])
    if extra:self.assertEqual(obs['units'][0]['target_occurrence_ids'],['occ-001'])
 def test_coverage_only_request_routes_without_audio_flag(self):
  self.options.source_requested_stages=[];self.options.source_review_flags={};self.options.source_coverage_requested=True
  self.observed(self.invoke());self.assertEqual(len(self.calls),1)
 def test_focused_selection_keeps_exact_occurrence_not_whole_target(self):
  self.options.source_requested_stages=['focused-audio-review'];self.options.source_review_flags={'audio':True,'occurrence_ids':['occ-001']}
  obs=self.observed(self.invoke());self.assertEqual(obs['units'][0]['target_occurrence_ids'],['occ-001'])
  self.assertEqual(len(obs['units'][0]['expanded_draft']['performance_order']),4)
 def test_added_hearing_is_preserved_as_observation_never_direct_mutation(self):
  self.extra=True;obs=self.observed(self.invoke());self.assertIn('heard-extra',json.dumps(obs));self.assertNotIn('heard-extra',self.reader['SONG_LINES'])
 def test_resume_reuses_routes_without_provider_or_audio_conversion(self):
  first=self.invoke();self.observed(first);self.call.side_effect=AssertionError('duplicate paid call');real=subprocess.run
  def guarded(cmd,*a,**k):
   if pathlib.Path(cmd[0]).name=='ffmpeg':raise AssertionError('duplicate conversion')
   return real(cmd,*a,**k)
  with patch.object(subprocess,'run',side_effect=guarded):self.assertEqual(self.invoke(),first)
 def test_deleted_receipt_reconstructed_from_durable_unit_cache(self):
  first=self.invoke();obs=self.observed(first);pathlib.Path(obs['receipt_path']).unlink();self.call.side_effect=AssertionError('lost receipt must not repay')
  self.observed(self.invoke());self.assertEqual(len(self.calls),1)
 def test_interruption_after_unit_acceptance_before_receipt_resumes_without_calls(self):
  original=adapter.atomic_json
  def interrupt(path,value):
   if pathlib.Path(path).name.endswith('-source-observed.json'):raise OSError('fixture interrupted receipt write')
   return original(path,value)
  with patch.object(adapter,'atomic_json',side_effect=interrupt):result=self.invoke()
  self.assertFalse(result['publicationEligible']);self.assertEqual(len(self.calls),1)
  self.call.side_effect=AssertionError('resume must reuse accepted audio unit')
  self.observed(self.invoke());self.assertEqual(len(self.calls),1)
 def test_long_actual_caller_reviews_every_core_without_reading_02_03(self):
  make_audio(self.song/'audio.m4a',1200);self.duration=pipeline.gemini.duration_seconds(self.song/'audio.m4a')
  self.reader=reader_for(self.duration);self.reader['SONG_SEQUENCE']=[];self.reader['SONG_TIMINGS']=[]
  for i in range(12):
   self.reader['SONG_SEQUENCE'].append({'ref':f'line-{i%3}','section':'verse','repeats':2 if i==5 else 1})
   self.reader['SONG_TIMINGS'].append({'start':self.duration*i/12,'end':self.duration*(i+1)/12})
  js(self.song/'data.js',self.reader);shutil.copy2(self.song/'audio.m4a',self.workspace/'songs'/self.slug/'audio.m4a');js(self.workspace/'songs'/self.slug/'data.js',self.reader)
  obs=self.observed(self.invoke());self.assertGreater(len(self.calls),1)
  self.assertEqual([x for u in obs['units'] for x in u['target_occurrence_ids']],[f'occ-{i:03d}' for i in range(12)])
  self.assertEqual(obs['units'][0]['core_start'],0);self.assertAlmostEqual(obs['units'][-1]['core_end'],self.duration)
  self.assertTrue(all(u['clip_end']-u['clip_start']<=900 for u in obs['units']))
 def test_receipt_content_tamper_holds_without_fresh_call(self):
  obs=self.observed(self.invoke());p=pathlib.Path(obs['receipt_path']);value=json.loads(p.read_text());value['result']['units'][0]['core_end']=.5;write_json(p,value)
  self.call.side_effect=AssertionError('tamper cannot authorize rerun');result=self.invoke();self.assertFalse(result['publicationEligible']);self.assertTrue(any('identity' in str(x) or 'digest' in str(x) or 'tamper' in str(x) for x in result['issues']))
 def test_saved_receipt_missing_route_never_replays_paid_unit(self):
  self.observed(self.invoke());state=next(self.route.rglob('route-state.json'));state.unlink()
  self.call.side_effect=AssertionError('missing durable route cannot reset paid attempts')
  result=self.invoke();self.assertFalse(result['publicationEligible']);self.assertTrue(any('route' in str(x) for x in result['issues']))
 def test_completed_raw_candidate_tamper_rejected_even_with_receipt(self):
  self.observed(self.invoke());candidate=next(self.route.rglob('candidate.json'));value=json.loads(candidate.read_text());value['segment_audits'][0]['audit']['packet']['lines'][0]['roman']='invented';write_json(candidate,value)
  self.call.side_effect=AssertionError('tamper must not repay')
  with self.assertRaises(routes.RunFatal):self.invoke()
 def test_explicit_source_hypothesis_and_prior_hearing_reach_actual_audit(self):
  prior=self.base/'prior.json';raw={'lines':[{'id':'heard','source_text':'नाम','roman':'nāma','language':'Hindi','kind':'verse','partial':'none','notes':''}],'performance_order':[{'line_id':'heard','occurrence':1}],'uncertainties':[]};write_json(prior,raw)
  self.options.source_review_flags={'audio':True,'occurrence_ids':['occ-001'],'disagreements':[{'id':'gap-one','occurrence_ids':['occ-001'],'reason':'Possible missing sung source','alternatives':[{'source_text':'नाम','roman':'nāma'}],'evidence':[{'path':str(prior),'sha256':adapter.file_hash(prior)}]}]}
  self.options.source_requested_stages=['focused-audio-review'];obs=self.observed(self.invoke())
  self.assertIn('gap-one',self.calls[0]['prompt']);self.assertIn(adapter.file_hash(prior),self.calls[0]['prompt']);self.assertEqual(obs['units'][0]['hypotheses'][0]['id'],'gap-one')
  prior.write_text('{}');self.call.side_effect=AssertionError('stale original evidence must not dispatch');result=self.invoke();self.assertFalse(result['publicationEligible']);self.assertTrue(any('evidence' in str(x) for x in result['issues']))
 def test_whole_audio_review_preserves_and_validates_prior_hearing(self):
  prior=self.base/'prior.json';raw={'lines':[{'id':'heard','source_text':'नाम','roman':'nāma','language':'Hindi','kind':'verse','partial':'none','notes':''}],'performance_order':[{'line_id':'heard','occurrence':1}],'uncertainties':[]};write_json(prior,raw)
  self.options.source_review_flags={'audio':True,'disagreements':[{'id':'gap-one','occurrence_ids':['occ-001'],'reason':'Possible missing sung source','alternatives':[{'source_text':'नाम','roman':'nāma'}],'evidence':[{'path':str(prior),'sha256':adapter.file_hash(prior)}]}]}
  self.options.source_requested_stages=['audio-review'];obs=self.observed(self.invoke())
  self.assertIn('gap-one',self.calls[0]['prompt']);self.assertIn(adapter.file_hash(prior),self.calls[0]['prompt']);self.assertEqual(obs['units'][0]['hypotheses'][0]['id'],'gap-one')
  prior.write_text('{}');self.call.side_effect=AssertionError('stale original evidence must not dispatch');result=self.invoke();self.assertFalse(result['publicationEligible']);self.assertTrue(any('evidence' in str(x) for x in result['issues']))
 def test_changed_trim_requires_new_observation_identity(self):
  first=self.observed(self.invoke());
  for root in (self.root,self.workspace):write_json(root/'songs'/self.slug/'.transcription/trim-applied.json',{'start_seconds':1})
  second=self.observed(self.invoke());self.assertEqual(len(self.calls),2);self.assertNotEqual(first['input_fingerprint'],second['input_fingerprint'])
 def test_owner_english_can_be_observed_but_never_sent_or_changed(self):
  reg={'version':1,'songs':{self.slug:{'policy':'preserve_english','englishSha256':'a'*64,'plainEnglishByLine':{lid:'OWNER ENGLISH' for lid in self.reader['SONG_LINES']}}}}
  for root in (self.root,self.workspace):write_json(root/'data/editorial_baselines.json',reg)
  self.observed(self.invoke());self.assertEqual(len(self.calls),1)
 def test_owner_registry_drift_and_invalid_flag_hold_before_provider(self):
  write_json(self.workspace/'data/editorial_baselines.json',{'version':1,'songs':{},'extra':1});self.assertFalse(self.invoke()['publicationEligible']);self.assertEqual(self.calls,[])
  shutil.copy2(self.root/'data/editorial_baselines.json',self.workspace/'data/editorial_baselines.json');self.options.source_review_flags={'audio':True,'occurrence_ids':['occ-999']}
  self.assertFalse(self.invoke()['publicationEligible']);self.assertEqual(self.calls,[])
  for flags in ([],False,None):
   self.options.source_review_flags=flags
   with self.subTest(flags=flags):
    self.assertFalse(self.invoke()['publicationEligible']);self.assertEqual(self.calls,[])

class PartitionTests(unittest.TestCase):
 def setUp(self):
  self.reader=reader_for(1200.);self.reader['SONG_TIMINGS']=[{'start':0.,'end':400.},{'start':400.,'end':800.},{'start':800.,'end':1200.}]
  self.evidence={'identity':{'audio_sha256':'a'*64,'trim_sha256':None,'reader_source_sha256':adapter.reader_source_identity(self.reader)},'duration_seconds':1200.,'coverage_requested':True,'timing_required':True,'routing_intervals':self.reader['SONG_TIMINGS'],'disagreements':[]}
  self.plan=adapter.plan_audio_review(self.reader,source_evidence=self.evidence,flags={},duration_seconds=1200.)
  self.segments=[{'index':i,'core_start':i*400.,'core_end':(i+1)*400.,'clip_start':max(0,i*400.-15),'clip_end':min(1200,(i+1)*400.+15)} for i in range(3)]
 def partition(self):return adapter.partition_source_plan(self.reader,self.plan,self.evidence,segments=self.segments)
 def test_core_coverage_exact_targets_once_repeats_and_neighbor_context_retained(self):
  units=self.partition();self.assertEqual([u['core_start'] for u in units],[0.,400.,800.]);self.assertEqual([u['core_end'] for u in units],[400.,800.,1200.])
  self.assertEqual([x for u in units for x in u['target_occurrence_ids']],['occ-000','occ-001','occ-002'])
  for u in units:
   self.assertLessEqual(u['clip_end']-u['clip_start'],900)
   for target in u['target_occurrence_ids']:
    rows=[e for e in u['expanded_draft']['performance_order'] if e['display_occurrence_id']==target]
    self.assertEqual(len(rows),2 if target=='occ-001' else 1)
    i=int(target[4:]);self.assertLessEqual(u['clip_start'],self.reader['SONG_TIMINGS'][i]['start']);self.assertGreaterEqual(u['clip_end'],self.reader['SONG_TIMINGS'][i]['end'])
  self.assertTrue(set(units[0]['context_occurrence_indices'])&set(units[1]['context_occurrence_indices']))
 def test_malformed_gap_overlap_nan_or_missing_end_reject_before_dispatch(self):
  original=copy.deepcopy(self.segments)
  for mode in ('gap','core-overlap','nan','missing-end'):
   self.segments=copy.deepcopy(original)
   if mode=='gap':self.segments[1]['core_start']+=1
   if mode=='core-overlap':self.segments[1]['core_start']-=1
   if mode=='nan':self.segments[1]['clip_end']=float('nan')
   if mode=='missing-end':self.segments[-1]['core_end']-=1
   with self.subTest(mode=mode),self.assertRaises(ValueError):self.partition()
 def test_invalid_public_intervals_or_oversize_repeat_group_need_transcription_not_guess(self):
  for intervals in ([],[{'start':0,'end':1000},{'start':1000,'end':1100},{'start':1100,'end':1200}]):
   self.reader['SONG_TIMINGS']=intervals;self.evidence['routing_intervals']=intervals
   with self.assertRaisesRegex(ValueError,'transcription|routing|900|bound'):self.partition()
 def test_empty_core_is_explicit_dependency_not_silently_discarded(self):
  self.reader['SONG_TIMINGS']=[{'start':0,'end':200},{'start':800,'end':1000},{'start':1000,'end':1200}];self.evidence['routing_intervals']=self.reader['SONG_TIMINGS']
  with self.assertRaisesRegex(ValueError,'transcription|draft|empty'):self.partition()
 def test_actual_ffmpeg_adaptive_segments_partition_every_long_occurrence(self):
  with tempfile.TemporaryDirectory() as td:
   audio=pathlib.Path(td)/'audio.m4a';make_audio(audio,1200);duration=pipeline.gemini.duration_seconds(audio)
   self.reader=reader_for(duration);self.reader['SONG_SEQUENCE']=[];self.reader['SONG_TIMINGS']=[]
   for i in range(12):self.reader['SONG_SEQUENCE'].append({'ref':f'line-{i%3}','section':'verse','repeats':2 if i==5 else 1});self.reader['SONG_TIMINGS'].append({'start':duration*i/12,'end':duration*(i+1)/12})
   self.evidence.update(duration_seconds=duration,routing_intervals=self.reader['SONG_TIMINGS']);self.evidence['identity']['reader_source_sha256']=adapter.reader_source_identity(self.reader)
   self.plan=adapter.plan_audio_review(self.reader,source_evidence=self.evidence,flags={},duration_seconds=duration);self.segments=pipeline.adaptive_audio_segments(audio)
   units=self.partition();self.assertEqual([x for u in units for x in u['target_occurrence_ids']],[f'occ-{i:03d}' for i in range(12)])
   self.assertEqual(units[0]['core_start'],0);self.assertAlmostEqual(units[-1]['core_end'],duration)

if __name__=='__main__':unittest.main()

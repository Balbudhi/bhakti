"""First observation slice; real pipeline/router/FFmpeg, provider boundary only.

The WAV is silent. Stubbed words establish scope/storage contracts, never audio truth.
"""
import argparse, copy, hashlib, importlib.util, json, pathlib, subprocess, sys, tempfile, time, unittest, wave
from unittest.mock import patch
HERE=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE/'scripts'))
spec=importlib.util.spec_from_file_location('observation_adapter',HERE/'scripts/bhakti_library_source_pass.py')
adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
import bhakti_pipeline as pipeline
import bhakti_model_routes as routes

class ObservationFixture(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name)
  self.song=self.root/'songs'/'source-observation-fixture';self.song.mkdir(parents=True)
  wav=self.root/'fixture.wav'
  with wave.open(str(wav),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(b'\0\0'*32000)
  self.audio=self.song/'audio.m4a'
  subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-i',str(wav),'-c:a','aac',str(self.audio)],check=True)
  self.duration=pipeline.gemini.duration_seconds(self.audio)
  self.reader={'SONG_META':{'languages':['Hindi']},'SONG_LINES':{},'SONG_SEQUENCE':[],'SONG_TIMINGS':[]}
  for i,(native,roman) in enumerate([('मन','man'),('तन','tan'),('राम','rāma')]):
   lid=f'old-{i}';self.reader['SONG_LINES'][lid]={'source':native,'roman':roman,'english':'DO NOT SEND OWNER ENGLISH','words':[{'roman':roman,'gloss':'DO NOT SEND GLOSS'}],'sourceWords':[{'text':native,'wordIndices':[0]}]}
   self.reader['SONG_SEQUENCE'].append({'ref':lid,'repeats':1,'section':'verse'})
   self.reader['SONG_TIMINGS'].append({'start':i*1.3,'end':(i+1)*1.3 if i<2 else self.duration})
  self.identity={'audio_sha256':adapter.file_hash(self.audio),'trim_sha256':None}
  self.deadline=time.time()+90
  self.options=argparse.Namespace(model=routes.FLASH_MODEL,pro_model=routes.PRO_MODEL,timeout=15,force=False,source_witness_audit=False)
  self.units=[]
  for i in range(3):
   interval=self.reader['SONG_TIMINGS'][i]
   self.units.append({'id':f'unit-{i}','kind':'focused-source','segment_index':i,
    'clip_start':interval['start'],'clip_end':interval['end'],'core_start':interval['start'],'core_end':interval['end'],
    'target_occurrence_ids':[f'occ-{i:03d}'],'core_occurrence_indices':[i],'context_occurrence_indices':[i],
    'expanded_draft':adapter.source_draft(self.reader,[i]),'hypotheses':[],'prior_evidence':[]})
  self.calls=[];self.fail_middle=False;self.partial=None;self.rename=False
  self.key_patch=patch.object(pipeline.gemini,'key',return_value='fixture-not-a-real-key');self.key_patch.start();self.addCleanup(self.key_patch.stop)
  self.call_patch=patch.object(pipeline.gemini,'call',side_effect=self.provider);self.call=self.call_patch.start();self.addCleanup(self.call_patch.stop)
 def provider(self,model,key,prompt,**kwargs):
  self.assertEqual(kwargs['schema_name'],'bhakti_segment_audit')
  self.assertNotIn('DO NOT SEND',prompt)
  ctx=kwargs.get('unit_context');self.assertIsInstance(ctx,dict);self.assertEqual(ctx['model'],model)
  self.assertLessEqual(ctx['deadline_at'],self.deadline);self.assertGreater(ctx['deadline_at'],time.time())
  first=json.JSONDecoder().raw_decode(prompt.split('FIRST TRANSCRIPT:\n',1)[1].lstrip())[0]
  lines=first['lines'];start=float(prompt.split('absolute source seconds ')[1].split('–')[0]);end=float(prompt.split('absolute source seconds ')[1].split('–')[1].split(';')[0])
  self.assertAlmostEqual(pipeline.gemini.duration_seconds(pathlib.Path(kwargs['audio'])),end-start,delta=.15)
  self.calls.append({'model':model,'first':copy.deepcopy(first),'bounds':(start,end),'context':copy.deepcopy(ctx)})
  packet=copy.deepcopy(first);packet['uncertainties']=[]
  for row in packet['lines']:
   row.setdefault('language','Hindi');row.setdefault('partial','none');row.setdefault('notes','')
  if self.fail_middle and len(lines)==1 and lines[0]['source_text']=='तन' and model==routes.FLASH_MODEL:packet['uncertainties']=['core word unclear']
  if self.partial:
   for row in packet['lines']:
    if row['source_text']==self.partial[0]:row['partial']=self.partial[1]
  if self.rename:
   renames={r['id']:'provider-'+str(i) for i,r in enumerate(packet['lines'])}
   for row in packet['lines']:row['id']=renames[row['id']]
   for event in packet['performance_order']:event['line_id']=renames[event['line_id']]
  return {'packet':packet,'resolved_model':model}
 def evidence_fixture(self):
  return {'identity':{**self.identity,'reader_source_sha256':adapter.reader_source_identity(self.reader)},'audio_path':str(self.audio),'duration_seconds':self.duration,'coverage_requested':True,'timing_required':True,'historical_audio_binding':'unbound','artifacts':{'02-transcript-audit.json':None,'03-timing.json':None},'disagreements':[],'routing_intervals':copy.deepcopy(self.reader['SONG_TIMINGS'])}
 def collect(self):return adapter.collect_source_evidence(self.song,self.reader,flags={},coverage_requested=True)
 def invoke(self):return adapter.review_audio_units(song_dir=self.song,units=self.units,audio=self.audio,source_identity=self.identity,options=self.options,route_dir=self.root/'routes',deadline_at=self.deadline)
 def whole_context(self):
  self.units=[{**copy.deepcopy(self.units[1]),'clip_start':0.,'clip_end':self.duration,
    'core_start':1.3,'core_end':2.6,'context_occurrence_indices':[0,1,2],
    'expanded_draft':adapter.source_draft(self.reader)}]

class EvidenceAndMaterialization(ObservationFixture):
 def test_missing_old02_and03_are_absent_not_certification_or_exception(self):
  e=self.collect();self.assertEqual(e['audio_path'],str(self.audio));self.assertEqual(e['identity']['audio_sha256'],adapter.file_hash(self.audio))
  self.assertEqual(e['identity']['reader_source_sha256'],adapter.reader_source_identity(self.reader));self.assertIsNone(e['artifacts']['02-transcript-audit.json']);self.assertIsNone(e['artifacts']['03-timing.json'])
  self.assertEqual(e['historical_audio_binding'],'unbound');self.assertFalse(e.get('coverage_receipt'));self.assertTrue(e['timing_required']);self.assertEqual(self.call.call_count,0)
 def test_old_artifacts_without_audio_binding_are_kept_as_unbound_evidence(self):
  folder=self.song/'.transcription/pipeline';folder.mkdir(parents=True)
  old=b'{"packet":{"uncertainties":[]},"resolved_model":"historical"}\n';path=folder/'02-transcript-audit.json';path.write_bytes(old)
  e=self.collect();self.assertEqual(e['artifacts'][path.name]['sha256'],hashlib.sha256(old).hexdigest());self.assertEqual(path.read_bytes(),old)
  self.assertEqual(e['historical_audio_binding'],'unbound');self.assertFalse(e.get('coverage_receipt'))
 def test_trim_raw_bytes_and_current_audio_bound_without_relabeling_old_response(self):
  folder=self.song/'.transcription';folder.mkdir();path=folder/'trim-applied.json';path.write_text('{"start_seconds": 1.25}\n')
  first=self.collect();self.assertEqual(first['identity']['trim_sha256'],adapter.file_hash(path));path.write_text('{"start_seconds": 1.5}\n');second=self.collect()
  self.assertNotEqual(first['identity']['trim_sha256'],second['identity']['trim_sha256']);self.assertEqual(second['historical_audio_binding'],'unbound')
 def test_missing_recording_fails_without_provider(self):
  self.audio.unlink()
  with self.assertRaises((ValueError,RuntimeError,FileNotFoundError)):self.collect()
  self.assertEqual(self.call.call_count,0)
 def test_short_whole_plan_materializes_exact_core_and_expanded_repeats(self):
  self.reader['SONG_SEQUENCE'][1]['repeats']=2;e=self.evidence_fixture()
  plan=adapter.plan_audio_review(self.reader,source_evidence=e,flags={},duration_seconds=self.duration)
  units=adapter.materialize_source_units(plan,e,duration_seconds=self.duration);self.assertEqual(len(units),1)
  u=units[0];self.assertEqual((u['clip_start'],u['core_start']),(0.,0.));self.assertEqual((u['clip_end'],u['core_end']),(self.duration,self.duration));self.assertEqual(u['segment_index'],0)
  self.assertEqual([r['line_id'] for r in u['expanded_draft']['performance_order']],['old-0','old-1','old-1','old-2']);self.assertNotIn('DO NOT SEND',json.dumps(units))
 def test_focused_materialization_keeps_bounds_and_target_context_distinction(self):
  e=self.evidence_fixture();plan=adapter.plan_audio_review(self.reader,source_evidence=e,flags={'audio':True,'occurrence_ids':['occ-001']},duration_seconds=self.duration)
  units=adapter.materialize_source_units(plan,e,duration_seconds=self.duration);self.assertEqual(len(units),1);u=units[0]
  self.assertEqual(u['target_occurrence_ids'],['occ-001']);self.assertEqual(u['context_occurrence_indices'],[0,1,2]);self.assertEqual((u['clip_start'],u['clip_end']),(0.,self.duration));self.assertEqual((u['core_start'],u['core_end']),(1.3,2.6))
 def test_long_whole_plan_requires_partition_before_any_dispatch(self):
  e=self.evidence_fixture();e['duration_seconds']=901.
  plan=adapter.plan_audio_review(self.reader,source_evidence=e,flags={},duration_seconds=901.)
  with self.assertRaisesRegex(ValueError,'partition'):
   adapter.materialize_source_units(plan,e,duration_seconds=901.)
  self.assertEqual(self.call.call_count,0)
 def test_stale_plan_identity_refused_before_materialization(self):
  e=self.evidence_fixture();plan=adapter.plan_audio_review(self.reader,source_evidence=e,flags={},duration_seconds=self.duration);e['identity']['audio_sha256']='f'*64
  with self.assertRaises(ValueError):adapter.materialize_source_units(plan,e,duration_seconds=self.duration)

class RoutedObservations(ObservationFixture):
 def test_real_auditor_attachment_context_and_raw_result_preserved(self):
  self.rename=True;before=copy.deepcopy(self.reader);result=self.invoke();self.assertEqual(result['status'],'observed');self.assertEqual(result['issues'],[]);self.assertEqual(len(self.calls),3)
  self.assertEqual(self.reader,before);self.assertNotIn('publicationEligible',result);self.assertNotIn('coverage_receipt',result)
  for unit in result['unit_results']:
   saved=unit['result'];self.assertEqual(len(saved['segment_audits']),1);packet=saved['segment_audits'][0]['audit']['packet'];self.assertTrue(packet['lines'][0]['id'].startswith('provider-'))
  self.assertTrue(list((self.root/'routes').rglob('route-state.json')))
 def test_one_quality_failure_escalates_only_that_segment(self):
  self.fail_middle=True;result=self.invoke();self.assertEqual(result['status'],'observed')
  self.assertEqual([(c['first']['lines'][0]['source_text'],c['model']) for c in self.calls],[('मन',routes.FLASH_MODEL),('तन',routes.FLASH_MODEL),('तन',routes.PRO_MODEL),('राम',routes.FLASH_MODEL)])
 def test_resume_never_reconverts_or_repays_but_may_ffprobe(self):
  first=self.invoke();run=subprocess.run
  def no_conversion(argv,*args,**kwargs):
   if pathlib.Path(argv[0]).name=='ffmpeg':raise AssertionError('accepted unit converted again')
   return run(argv,*args,**kwargs)
  self.call.side_effect=AssertionError('accepted unit paid again')
  with patch.object(subprocess,'run',side_effect=no_conversion):self.assertEqual(self.invoke(),first)
 def test_changed_one_unit_reroutes_only_its_inputs(self):
  self.invoke();self.calls=[];self.units[1]['hypotheses']=[{'id':'new-reading','alternatives':['तन','धन']}]
  result=self.invoke();self.assertEqual(result['status'],'observed');self.assertEqual([c['first']['lines'][0]['source_text'] for c in self.calls],['तन'])
 def test_core_partial_held_after_both_models_while_siblings_retained(self):
  self.partial=('तन','leading');r=self.invoke();self.assertEqual(r['status'],'unresolved');self.assertTrue(r['issues']);self.assertEqual([x['unit']['id'] for x in r['unit_results']],['unit-0','unit-2'])
  self.assertEqual(sum(c['first']['lines'][0]['source_text']=='तन' for c in self.calls),2)
 def test_context_only_edge_partial_allowed_despite_provider_id_renumber(self):
  self.whole_context();self.partial=('मन','leading');self.rename=True;r=self.invoke();self.assertEqual(r['status'],'observed');self.assertEqual(len(self.calls),1)
  self.assertEqual(r['unit_results'][0]['result']['segment_audits'][0]['audit']['packet']['lines'][0]['partial'],'leading')
 def test_same_lexical_identity_in_target_and_neighbor_cannot_exempt_partial(self):
  self.reader['SONG_LINES']['old-1']['source']='मन';self.reader['SONG_LINES']['old-1']['roman']='man';self.whole_context();self.partial=('मन','leading')
  r=self.invoke();self.assertEqual(r['status'],'unresolved');self.assertTrue(r['issues'])
 def test_stale_audio_hash_rejected_before_any_provider(self):
  self.identity['audio_sha256']='0'*64
  with self.assertRaises(ValueError):self.invoke()
  self.assertEqual(self.call.call_count,0)
 def test_invalid_later_unit_bounds_validate_before_first_dispatch(self):
  for field,value in [('clip_end',self.duration+1),('core_start',-1),('core_end',float('nan'))]:
   with self.subTest(field=field):
    units=copy.deepcopy(self.units);self.units[2][field]=value
    with self.assertRaises(ValueError):self.invoke()
    self.assertEqual(self.call.call_count,0);self.units=units
 def test_stale_prior_evidence_file_rejected_before_provider(self):
  path=self.root/'paid.json';path.write_text('{"old":true}')
  self.units[2]['prior_evidence']=[{'path':str(path),'sha256':'0'*64}]
  with self.assertRaises(ValueError):self.invoke()
  self.assertEqual(self.call.call_count,0)
 def test_duplicate_unit_or_unknown_target_fails_before_provider(self):
  for mutation in ['duplicate','target']:
   with self.subTest(mutation=mutation):
    units=copy.deepcopy(self.units)
    if mutation=='duplicate':self.units[2]['id']=self.units[0]['id']
    else:self.units[2]['target_occurrence_ids']=['occ-999']
    with self.assertRaises(ValueError):self.invoke()
    self.assertEqual(self.call.call_count,0);self.units=units
 def test_expired_absolute_deadline_dispatches_nothing(self):
  self.deadline=time.time()-1
  with self.assertRaises((routes.RunFatal,routes.UnitUnresolved,ValueError)):self.invoke()
  self.assertEqual(self.call.call_count,0)
 def test_malformed_uncertainties_escalates_as_quality_before_legacy_merge(self):
  self.units=self.units[:1]
  def response(model,key,prompt,**kwargs):
   result=self.provider(model,key,prompt,**kwargs)
   if model==routes.FLASH_MODEL:result['packet']['uncertainties']=None
   return result
  self.call.side_effect=response;r=self.invoke();self.assertEqual(r['status'],'observed')
  self.assertEqual([c['model'] for c in self.calls],[routes.FLASH_MODEL,routes.PRO_MODEL])
 def test_blank_instrumental_raw_observation_is_not_lost_in_lexical_merge(self):
  self.units=self.units[:1]
  def response(model,key,prompt,**kwargs):
   result=self.provider(model,key,prompt,**kwargs)
   result['packet']['lines'].append({'id':'instrumental-end','source_text':'','roman':'','kind':'instrumental','language':'','partial':'none','notes':''})
   result['packet']['performance_order'].append({'line_id':'instrumental-end','occurrence':1})
   return result
  self.call.side_effect=response;r=self.invoke();self.assertEqual(r['status'],'observed');self.assertEqual(len(self.calls),1)
  raw=r['unit_results'][0]['result']['segment_audits'][0]['audit']['packet'];self.assertEqual(raw['lines'][-1]['source_text'],'');self.assertEqual(raw['performance_order'][-1]['line_id'],'instrumental-end')
  self.assertTrue(r['unit_results'][0]['result']['observation_only'])
 def test_empty_registered_witness_fails_before_route_or_acquisition(self):
  path=pipeline.source_witness.cache_path(self.song);path.parent.mkdir(parents=True)
  record={'retriever':'srigranth-gurmukhi-pages','title':'fixture'}
  valid={'schema_version':1,'work':self.song.name,'witness':record,'lines':[{'text':'मन में राम','page':1}]}
  invalid=[{}, {**valid,'work':'other-song'}, {**valid,'witness':{'title':'wrong'}}, {**valid,'lines':[]}, {**valid,'lines':[{'text':''}]}, {**valid,'lines':[False]}]
  for cache in invalid:
   with self.subTest(cache=cache):
    path.write_text(json.dumps(cache))
    with patch.object(pipeline.source_witness,'record_for_slug',return_value=record),patch.object(pipeline.source_witness,'acquire',side_effect=AssertionError('unbound fetch forbidden')) as acquire:
     with self.assertRaises(ValueError):self.invoke()
     self.assertEqual(acquire.call_count,0);self.assertEqual(self.call.call_count,0);self.assertFalse((self.root/'routes').exists())
 def test_valid_registered_witness_is_frozen_and_never_acquired_in_attempt(self):
  self.units=self.units[:1];self.units[0]['expanded_draft']['lines'][0].update(source_text='मन में राम',roman='man meṁ rāma')
  path=pipeline.source_witness.cache_path(self.song);path.parent.mkdir(parents=True)
  record={'retriever':'srigranth-gurmukhi-pages','title':'fixture'}
  path.write_text(json.dumps({'schema_version':1,'work':self.song.name,'witness':record,'lines':[{'text':'मन में राम','page':1}]}))
  prompts=[]
  def response(model,key,prompt,**kwargs):prompts.append(prompt);return self.provider(model,key,prompt,**kwargs)
  self.call.side_effect=response
  with patch.object(pipeline.source_witness,'record_for_slug',return_value=record),patch.object(pipeline.source_witness,'acquire',side_effect=AssertionError('snapshot must bypass acquire')) as acquire:
   r=self.invoke();self.assertEqual(r['status'],'observed');self.assertEqual(acquire.call_count,0)
  self.assertIn('IDENTIFIED TEXTUAL WITNESS',prompts[0]);self.assertIn('मन में राम',prompts[0].split('IDENTIFIED TEXTUAL WITNESS',1)[1])
 def test_omission_hypotheses_and_prior_paid_source_reach_real_prompt(self):
  self.units=self.units[:1];path=self.root/'prior-source.json'
  prior={'packet':{'lines':[{'id':'prior-1','source_text':'आरत की आरति','roman':'ārata kī ārati','kind':'verse','partial':'none','notes':'previous complete hearing','english':'DO NOT SEND PRIOR ENGLISH'}], 'performance_order':[{'line_id':'prior-1','occurrence':1}], 'uncertainties':[]}}
  path.write_text(json.dumps(prior));before=path.read_bytes()
  self.units[0]['prior_evidence']=[{'path':str(path),'sha256':adapter.file_hash(path)}]
  self.units[0]['hypotheses']=[{'id':'omission','reason':'saved response includes an omitted phrase','alternatives':[{'source_text':'आरत की आरति','roman':'ārata kī ārati','english':'DO NOT SEND ALTERNATIVE ENGLISH'},{'source_text':'','kind':'absent'}]}]
  prompts=[]
  def response(model,key,prompt,**kwargs):prompts.append(prompt);return self.provider(model,key,prompt,**kwargs)
  self.call.side_effect=response;r=self.invoke();self.assertEqual(r['status'],'observed');self.assertEqual(path.read_bytes(),before)
  self.assertIn('SOURCE OBSERVATION CONTEXT',prompts[0]);self.assertIn('आरत की आरति',prompts[0]);self.assertIn('previous complete hearing',prompts[0]);self.assertNotIn('DO NOT SEND',prompts[0])
 def test_default_auditor_still_merges_and_acquires_its_witness(self):
  unit=self.units[0];local=copy.copy(self.options);local.unit_context={'model':local.model,'deadline_at':self.deadline};local.unit_deadline_at=self.deadline
  raw={'packet':{'segments':[{'segment':{'index':0,**{k:unit[k] for k in ('clip_start','clip_end','core_start','core_end')}},'transcript':adapter._observation_draft(unit['expanded_draft'])}]}}
  with patch.object(pipeline.source_witness,'acquire',return_value=None) as acquire:
   result=pipeline.audit_long_transcript(self.song,raw,self.audio,local);self.assertEqual(acquire.call_count,1)
  self.assertNotIn('observation_only',result);self.assertEqual(result['packet']['verified_lines'][0]['source_text'],'मन');self.assertEqual(len(result['packet']['performance_order']),1)
 def test_auth_failure_does_not_escalate_or_try_other_units(self):
  self.call.side_effect=routes.RunFatal('fixture credentials rejected')
  with self.assertRaises(routes.RunFatal):self.invoke()
  self.assertEqual(self.call.call_count,1)

if __name__=='__main__':unittest.main()

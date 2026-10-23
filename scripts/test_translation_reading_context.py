"""Context delivery tests, not assertions of model grammatical competence."""
import argparse,copy,json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
FIXTURES=pathlib.Path(__file__).resolve().parent/'fixtures'/'translation_reading_context'
sys.path.insert(0,str(ROOT/'scripts'))
import bhakti_pipeline as pipeline
import bhakti_library_pass as library
REAL_POLICY = pipeline.translation_policy_payload

class ReadingContextTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.song=pathlib.Path(self.tmp.name)
  self.lines=[{'id':f'line-{i}','source_text':f'source{i}','roman':f'word{i}','kind':'verse'} for i in range(30)]
  self.glosses=[{'id':r['id'],'word_glosses':[{'roman':r['roman'],'gloss':f'meaning {i}'}],'grammar_note':f'grammar {i}','semantic_frame':{'cross_line_relation':''}} for i,r in enumerate(self.lines)]
  self.drafts=[{'id':r['id'],'literal_english':f'Current English {i}.','segments':[{'text':f'Current English {i}.','word_indices':[0]}]} for i,r in enumerate(self.lines)]
  self.order=[{'line_id':r['id'],'occurrence':1} for r in self.lines];self.calls=[]
  self.options=argparse.Namespace(model='fixture-model',timeout=1,force=False,semantic_performance_order=self.order)
  for mocked in [patch.object(pipeline.gemini,'key',return_value='fixture-only'),patch.object(pipeline.gemini,'call',side_effect=self.provider),patch.object(pipeline.bhakti_translation_policy,'guidance',return_value='fixture policy'),patch.object(pipeline,'translation_policy_payload',return_value={})]:
   mocked.start();self.addCleanup(mocked.stop)
 def provider(self,model,key,prompt,**kwargs):
  targets=json.JSONDecoder().raw_decode(prompt.split('OUTPUT TARGET IDS (return exactly these, once each):\n')[1].lstrip())[0]
  self.calls.append((targets,prompt));return {'packet':{'reviews':[{'id':i,'passes':True} for i in targets]}}
 def run_review(self):return pipeline.independently_review_translations(self.song,self.lines,self.glosses,self.drafts,'(none supplied)',self.options)
 def context(self,prompt):
  marker='ENGLISH READING CONTEXT (context only; target obligations unchanged):\n';self.assertIn(marker,prompt)
  return json.JSONDecoder().raw_decode(prompt.split(marker,1)[1].lstrip())[0]
 def build(self,targets):return pipeline.translation_reading_context(self.lines,self.glosses,self.drafts,targets,performance_order=self.order)
 def test_actual_kolaru_final_stanza_crosses_parent_boundary_with_current_english(self):
  fixture=json.loads((FIXTURES/'kolaru-final-stanza.json').read_text())
  for phase in ('before','after'):
   with self.subTest(phase=phase):
    self.options.force=True;self.calls=[]
    reader={'SONG_LINES':fixture[phase],'SONG_META':{},'SONG_SEQUENCE':[{'ref':i,'section':'verse','repeats':1} for i in fixture['ids']]}
    lines,glosses,drafts=library.reader_evidence(reader)
    self.lines=self.lines[:18]+lines+self.lines[22:];self.glosses=self.glosses[:18]+glosses+self.glosses[22:];self.drafts=self.drafts[:18]+drafts+self.drafts[22:]
    self.order=[{'line_id':r['id'],'occurrence':1} for r in self.lines];self.options.semantic_performance_order=self.order
    self.run_review();targets,prompt=next(c for c in self.calls if 'v11-l3' in c[0]);ctx=self.context(prompt);by={r['source']['id']:r for r in ctx['context_rows']}
    self.assertIn('v11-l1',by);self.assertIn('v11-l2',by)
    self.assertEqual(by['v11-l1']['draft']['literal_english'],drafts[0]['literal_english']);self.assertEqual(by['v11-l2']['gloss'],glosses[1]);self.assertNotIn('v11-l1',targets)
    self.assertIn('Read the draft English continuously',prompt);self.assertIn('Do not require each',prompt)
 def test_actual_kolaru_causal_opening_before_and_after_visible_as_complete_stanza(self):
  fixture=json.loads((FIXTURES/'kolaru-first-stanza.json').read_text())
  self.assertNotEqual(fixture['before']['v1-l1']['english'],fixture['after']['v1-l1']['english'])
  for phase in ('before','after'):
   with self.subTest(phase=phase):
    reader={'SONG_LINES':fixture[phase],'SONG_META':{},'SONG_SEQUENCE':[{'ref':i,'section':'verse','repeats':1} for i in fixture['ids']]}
    self.lines,self.glosses,self.drafts=library.reader_evidence(reader);self.order=[{'line_id':i,'occurrence':1} for i in fixture['ids']]
    ctx=self.build(['v1-l2']);by={r['source']['id']:r for r in ctx['context_rows']}
    self.assertEqual(set(by),{'v1-l1','v1-l3','v1-l4'})
    for i in (0,2,3):self.assertEqual(by[fixture['ids'][i]]['draft'],self.drafts[i])
    self.assertEqual([r['line_id'] for r in ctx['reading_windows'][0]['occurrences']],fixture['ids'])
 def test_exact_relation_line_id_boundaries_do_not_confuse_line2_and_line25(self):
  self.glosses[0]['semantic_frame']['cross_line_relation']='Subject specified in line-25.'
  ctx=self.build(['line-0']);by={r['source']['id'] for r in ctx['context_rows']};self.assertIn('line-25',by)
  # line-2 is a normal neighbor here; its unrelated distant relation must not be followed.
  self.glosses[2]['semantic_frame']['cross_line_relation']='line-29 supplies a different verse.'
  ctx=self.build(['line-0']);by={r['source']['id'] for r in ctx['context_rows']};self.assertNotIn('line-29',by)
 def test_unknown_order_or_invalid_repeats_fail_before_any_provider(self):
  for order in [[{'ref':'missing','repeats':1}],*[ [{'ref':'line-0','repeats':n}] for n in (0,-1,True,1.5,'2')]]:
   with self.subTest(order=order):
    self.options.semantic_performance_order=order
    with self.assertRaises((ValueError,RuntimeError)):self.run_review()
    self.assertEqual(self.calls,[])
 def test_missing_referenced_draft_fails_before_any_provider(self):
  self.glosses[0]['semantic_frame']['cross_line_relation']='Subject is line-25.';self.drafts=[r for r in self.drafts if r['id']!='line-25']
  with self.assertRaises((ValueError,RuntimeError,KeyError)):self.run_review()
  self.assertEqual(self.calls,[])
 def test_context_overflow_does_not_silently_truncate_or_dispatch(self):
  for i in range(30,130):
   self.lines.append({'id':f'line-{i}','source_text':f'source{i}','roman':f'word{i}','kind':'verse'});self.glosses.append({'id':f'line-{i}','word_glosses':[]});self.drafts.append({'id':f'line-{i}','literal_english':f'English{i}'})
  self.glosses[0]['semantic_frame']['cross_line_relation']=' '.join(f'line-{i}' for i in range(20,130))
  self.order=[{'line_id':r['id'],'occurrence':1} for r in self.lines];self.options.semantic_performance_order=self.order
  with self.assertRaisesRegex((ValueError,RuntimeError),'context|limit|scope'):self.run_review()
  self.assertEqual(self.calls,[])
 def test_normal_translate_forwards_actual_order_without_semantic_deadline_option(self):
  self.lines=self.lines[:2];self.glosses=self.glosses[:2];del self.options.semantic_performance_order
  actual=[{'line_id':'line-1','occurrence':1},{'line_id':'line-0','occurrence':1}]
  provider=self.provider
  def response(model,key,prompt,**kwargs):
   if kwargs['schema_name']=='bhakti_translation_review':return provider(model,key,prompt,**kwargs)
   return {'packet':{'translations':[{'id':r['id'],'literal_english':'Meaning.','segments':[{'text':'Meaning.','word_indices':[0]}],'human_review_recommended':False,'material_alternatives':[],'uncertainty':'','choice_note':'','fidelity':{'agency_and_image_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[],'notes':''}} for r in self.lines],'comparison':[]}}
  with patch.object(pipeline.gemini,'call',side_effect=response),patch.object(pipeline.bhakti_translation_policy,'sense_decision_errors',return_value=[]):
   pipeline.translate(self.song,{'packet':{'verified_lines':self.lines,'performance_order':actual}}, {'packet':{'glosses':self.glosses}}, {'slug':'context-fixture','languages':[]}, self.options,candidate_only=True)
  self.assertEqual(len(self.calls),1);reading=self.context(self.calls[0][1]);forwarded=[{k:event[k] for k in ('line_id','occurrence')} for window in reading['reading_windows'] for event in window['occurrences']];self.assertEqual(forwarded,actual)
 def test_late_only_context_failure_preflights_before_earlier_valid_batches_dispatch(self):
  for i in range(30,130):
   self.lines.append({'id':f'line-{i}','source_text':f'source{i}','roman':f'word{i}','kind':'verse'});self.glosses.append({'id':f'line-{i}','word_glosses':[]});self.drafts.append({'id':f'line-{i}','literal_english':f'English{i}'})
  self.order=[{'line_id':r['id'],'occurrence':1} for r in self.lines];self.options.semantic_performance_order=self.order
  self.glosses[25]['semantic_frame']['cross_line_relation']=' '.join(f'line-{i}' for i in range(40,130))
  # First ten targets have no dependency on line25; their context is valid.
  early=self.build([f'line-{i}' for i in range(10)]);self.assertEqual(early['scope_issues'],[])
  with self.assertRaises((ValueError,RuntimeError)):self.run_review()
  self.assertEqual(self.calls,[])
 def test_target_only_repair_uses_full_current_context_but_keeps_new_target_draft(self):
  full=[{'source':copy.deepcopy(s),'gloss':copy.deepcopy(g),'draft':copy.deepcopy(d)} for s,g,d in zip(self.lines,self.glosses,self.drafts)]
  self.lines=[self.lines[20]];self.glosses=[self.glosses[20]];self.drafts=[self.drafts[20]]
  self.drafts[0]['literal_english']='New corrected target.';self.drafts[0]['segments'][0]['text']='New corrected target.'
  self.options.semantic_full_source=[r['source'] for r in full];self.options.semantic_context_evidence=full
  self.run_review();self.assertEqual(len(self.calls),1);targets,prompt=self.calls[0];self.assertEqual(targets,['line-20'])
  context=self.context(prompt);by={r['source']['id']:r for r in context['context_rows']};self.assertEqual(by['line-19']['draft'],full[19]['draft']);self.assertEqual(by['line-21']['gloss'],full[21]['gloss'])
  target=json.JSONDecoder().raw_decode(prompt.split('EVIDENCE:\n',1)[1].lstrip())[0];self.assertEqual(target[0]['draft']['literal_english'],'New corrected target.')
 def test_target_at_end_of_four_line_utterance_gets_all_three_predecessors(self):
  ctx=self.build(['line-3']);self.assertTrue({'line-0','line-1','line-2'}.issubset({r['source']['id'] for r in ctx['context_rows']}))
 def test_actual_performance_neighbors_and_return_contexts_not_definition_neighbors(self):
  self.order=[{'ref':'line-25','repeats':1},{'ref':'line-4','repeats':2},{'ref':'line-26','repeats':1},{'ref':'line-20','repeats':1},{'ref':'line-4','repeats':1},{'ref':'line-21','repeats':1}]
  ctx=self.build(['line-4']);ids={r['source']['id'] for r in ctx['context_rows']};self.assertTrue({'line-25','line-26','line-20','line-21'}.issubset(ids));self.assertNotIn('line-3',ids)
  occurrences=[o for w in ctx['reading_windows'] for o in w['occurrences']];self.assertEqual(sum(o['line_id']=='line-4' for o in occurrences),3)
 def test_changed_neighbor_english_invalidates_boundary_parent_and_child(self):
  self.run_review();self.calls=[];self.run_review();self.assertEqual(self.calls,[])
  self.drafts[19]['literal_english']='Corrected preceding subject.';self.drafts[19]['segments'][0]['text']='Corrected preceding subject.';self.run_review()
  ids={c[0][0] for c in self.calls};self.assertIn('line-10',ids);self.assertIn('line-20',ids);self.assertNotIn('line-0',ids)
  ctx=self.context(next(c[1] for c in self.calls if c[0][0]=='line-20'));row=next(r for r in ctx['context_rows'] if r['source']['id']=='line-19');self.assertEqual(row['draft']['literal_english'],'Corrected preceding subject.')
 def test_changed_neighbor_gloss_invalidates_review_without_english_change(self):
  self.run_review();self.calls=[];self.glosses[19]['word_glosses'][0]['gloss']='corrected subject sense';self.run_review();self.assertIn('line-20',{c[0][0] for c in self.calls})
 def test_explicit_cross_line_reference_brings_distant_draft_and_gloss(self):
  self.glosses[0]['semantic_frame']['cross_line_relation']='The grammatical subject continues from line-25.'
  ctx=self.build(['line-0']);row=next(r for r in ctx['context_rows'] if r['source']['id']=='line-25');self.assertEqual(row['draft'],self.drafts[25]);self.assertEqual(row['gloss'],self.glosses[25])
 def test_long_song_uses_bounded_neighbor_context_not_full_english_catalog(self):
  for i in range(30,600):
   self.lines.append({'id':f'line-{i}','source_text':f'source{i}','roman':f'word{i}','kind':'verse'});self.glosses.append({'id':f'line-{i}','word_glosses':[]});self.drafts.append({'id':f'line-{i}','literal_english':f'English{i}'})
  self.order=[{'line_id':r['id'],'occurrence':1} for r in self.lines];ctx=self.build([f'line-{i}' for i in range(200,210)])
  ids={r['source']['id'] for r in ctx['context_rows']};self.assertEqual(ids,{f'line-{i}' for i in [197,198,199,210,211,212]});self.assertNotIn('English599',json.dumps(ctx))

 def test_short_missing_performance_order_is_labeled_not_audited(self):
  self.lines=self.lines[:2];self.glosses=self.glosses[:2];self.drafts=self.drafts[:2];self.order=[]
  ctx=self.build(['line-0']);self.assertEqual(ctx['order_basis'],'definition-order-unverified')
  self.assertEqual([r['source']['id'] for r in ctx['context_rows']],['line-1'])
 def test_returned_reading_context_row_is_projected_out_not_new_target(self):
  self.options.semantic_full_source=copy.deepcopy(self.lines)
  original=self.provider
  def extra(*args,**kwargs):
   result=original(*args,**kwargs)
   if self.calls[-1][0]==['line-20']:
    result['packet']['reviews'].append({'id':'line-19','passes':True,
     'agency_preserved':True,'imagery_preserved':True,'all_meaning_accounted_for':True,
     'human_review_recommended':False,'unsupported_additions':[],'issues':[],
     'material_choice':'','reason':'Context is supported.'})
   return result
  full=[{'source':s,'gloss':g,'draft':d} for s,g,d in zip(self.lines,self.glosses,self.drafts)]
  self.options.semantic_context_evidence=full
  self.lines=self.lines[20:21];self.glosses=self.glosses[20:21];self.drafts=self.drafts[20:21]
  with patch.object(pipeline.gemini,'call',side_effect=extra):reviews,packets=self.run_review()
  self.assertEqual([r['id'] for r in reviews],['line-20'])
  self.assertEqual(self.context(self.calls[0][1])['targets'],['line-20'])
 def test_actual_library_repair_forwards_current_neighbor_rows_to_shared_translate(self):
  import bhakti_model_routes as routes
  fixture=json.loads((FIXTURES/'kolaru-first-stanza.json').read_text())
  reader={'SONG_LINES':fixture['after'],'SONG_META':{'languages':['Tamil']},'SONG_SEQUENCE':[{'ref':i,'section':'verse','repeats':1} for i in fixture['ids']]}
  saved=copy.deepcopy(reader);sources,glosses,drafts=library.reader_evidence(reader)
  context=argparse.Namespace(model='fixture-model',attempt_dir=self.song,attempt_id='fixture',call_timeout_seconds=1,transport_context={},deadline_at=9999999999)
  expected=[{'source':s,'gloss':g,'draft':d} for s,g,d in zip(sources,glosses,drafts)]
  class ReachedTranslate(Exception):pass
  def translate(song,audited,packet,job,options,**kwargs):
   self.assertEqual(options.semantic_context_evidence,expected)
   self.assertEqual([r['id'] for r in audited['packet']['verified_lines']],['v1-l2'])
   self.assertEqual(options.semantic_performance_order,reader['SONG_SEQUENCE'])
   raise ReachedTranslate()
  def execute_route(directory,unit,identity,execute,validate,**kwargs):return execute(context)
  pre={'issues':[{'kind':'english_grammar','target_line_ids':['v1-l2'],'references':[]}]}
  with patch.object(library,'current_review_errors',return_value=[]),patch.object(routes,'run_unit',side_effect=execute_route),patch.object(pipeline,'gloss',return_value={'packet':{'glosses':[copy.deepcopy(glosses[1])]}}),patch.object(pipeline,'translate',side_effect=translate):
   with self.assertRaises(ReachedTranslate):
    library.repair_current_reader(reader,slug='fixture',pre_review=pre,workspace=self.song,route_dir=self.song/'routes',options=argparse.Namespace(timeout=1,model='fixture-model',pro_model='fixture-pro'),dependency_fingerprint='fixture',deadline_at=9999999999)
  self.assertEqual(reader,saved)

 def source_plan(self):
  fixture=json.loads((FIXTURES/'kolaru-first-stanza.json').read_text())
  rows=fixture['after'];ids=fixture['ids']
  lines=[{'id':i,'source_text':rows[i]['source'],'roman':rows[i]['roman'],'kind':'verse',
          'sourceWords':copy.deepcopy(rows[i]['sourceWords'])} for i in ids]
  return {'lines':lines,'performance_order':[{'line_id':i,'occurrence':1} for i in ids],
          'new_target_ids':[ids[1]],'reuse_by_id':{i:copy.deepcopy(rows[i]) for i in ids if i!=ids[1]}}
 def test_new_source_target_forwards_preserved_old_context_before_text_stage(self):
  import bhakti_library_source_pass as source
  import bhakti_model_routes as routes
  plan=self.source_plan();saved=copy.deepcopy(plan)
  context=argparse.Namespace(model='fixture-model',attempt_dir=self.song,attempt_id='fixture',call_timeout_seconds=1,transport_context={},deadline_at=9999999999)
  class ReachedGloss(Exception):pass
  def gloss(song,audited,options):
   rows={r['source']['id']:r for r in options.semantic_context_evidence}
   self.assertEqual(set(rows),set(plan['reuse_by_id']))
   for i,old in plan['reuse_by_id'].items():
    self.assertEqual(rows[i]['draft']['literal_english'],library.editorial_baselines.plain_english(old['english']))
    self.assertEqual(rows[i]['gloss']['word_glosses'],old['words'])
   self.assertEqual([r['id'] for r in audited['packet']['verified_lines']],plan['new_target_ids'])
   raise ReachedGloss()
  def route(directory,unit,identity,execute,validate,**kwargs):return execute(context)
  with patch.object(routes,'run_unit',side_effect=route),patch.object(pipeline,'gloss',side_effect=gloss):
   with self.assertRaises(ReachedGloss):source.process_new_targets(self.song,plan,{'languages':['Tamil']},argparse.Namespace(timeout=1,model='fixture-model',pro_model='fixture-pro'),self.song/'routes',9999999999)
  self.assertEqual(plan,saved)
 def test_new_source_missing_known_neighbor_english_holds_before_gloss_or_translation(self):
  import bhakti_library_source_pass as source
  plan=self.source_plan();del plan['reuse_by_id']['v1-l1']['english']
  import bhakti_model_routes as routes
  context=argparse.Namespace(model='fixture-model',attempt_dir=self.song,attempt_id='fixture',call_timeout_seconds=1,transport_context={},deadline_at=9999999999)
  def route(directory,unit,identity,execute,validate,**kwargs):return execute(context)
  with patch.object(routes,'run_unit',side_effect=route),patch.object(pipeline,'gloss',side_effect=AssertionError('paid gloss reached')) as gloss,patch.object(pipeline,'translate',side_effect=AssertionError('paid translation reached')) as translate:
   with self.assertRaises((ValueError,RuntimeError,KeyError)):
    source.process_new_targets(self.song,plan,{'languages':['Tamil']},argparse.Namespace(timeout=1,model='fixture-model',pro_model='fixture-pro'),self.song/'routes',9999999999)
  gloss.assert_not_called();translate.assert_not_called()

 def test_cached_translation_cannot_bypass_changed_neighbor_english_or_new_context_contract(self):
  full=[{'source':copy.deepcopy(s),'gloss':copy.deepcopy(g),'draft':copy.deepcopy(d)} for s,g,d in zip(self.lines,self.glosses,self.drafts)]
  self.lines=self.lines[20:21];self.glosses=self.glosses[20:21];self.drafts=self.drafts[20:21]
  self.options.semantic_context_evidence=full
  self.options.semantic_full_source=[r['source'] for r in full]
  audited={'packet':{'verified_lines':self.lines,'performance_order':self.order}}
  glosses={'packet':{'glosses':self.glosses}};job={'slug':'context-fixture','languages':[]}
  provider=self.provider;dispatch=[]
  def response(model,key,prompt,**kwargs):
   dispatch.append(kwargs['schema_name'])
   if kwargs['schema_name']=='bhakti_translation_review':return provider(model,key,prompt,**kwargs)
   return {'packet':{'translations':copy.deepcopy(self.drafts),'comparison':[]}}
  cache=self.song/'.transcription/pipeline/05-translation.json'
  with patch.object(pipeline.gemini,'call',side_effect=response),patch.object(pipeline.bhakti_translation_policy,'sense_decision_errors',return_value=[]),patch.object(pipeline,'fresh_translation_contract_errors',return_value=[]):
   result=pipeline.translate(self.song,audited,glosses,job,self.options,candidate_only=True)
   pipeline.write_json(cache,result);self.calls=[]
   pipeline.translate(self.song,audited,glosses,job,self.options,candidate_only=True);self.assertEqual(self.calls,[])
   full[19]['draft']['literal_english']='Changed neighboring subject.';full[19]['draft']['segments'][0]['text']='Changed neighboring subject.'
   result=pipeline.translate(self.song,audited,glosses,job,self.options,candidate_only=True)
   self.assertEqual(len(self.calls),1)
   # Recreate the precise former source-only cache identity, not a corrupt file.
   old=pipeline.text_stage_fingerprint('translation',self.options.model,{'lines':self.lines,'glosses':self.glosses,'provided_translation':'(none supplied)','languages':[]},pipeline.semantic_stage_policy(self.options))
   result['fingerprint']=old;pipeline.write_json(cache,result)
   pipeline.write_json(cache.parent/'translation-candidate.json',result)
   self.calls=[];dispatch=[]
   pipeline.translate(self.song,audited,glosses,job,self.options,candidate_only=True)
   self.assertTrue(any(name!='bhakti_translation_review' for name in dispatch))

 def test_pre_context_accepted_route_and_journal_are_held_without_erasure(self):
  import time
  import bhakti_model_routes as routes
  fixture=json.loads((FIXTURES/'kolaru-first-stanza.json').read_text())
  reader={'SONG_LINES':fixture['after'],'SONG_META':{'languages':['Tamil']},'SONG_SEQUENCE':[{'ref':i,'section':'verse','repeats':1} for i in fixture['ids']]}
  lines,glosses,drafts=library.reader_evidence(reader);reader_digest=library.prepare.json_digest(reader)
  options=argparse.Namespace(model=routes.FLASH_MODEL,pro_model=routes.PRO_MODEL,timeout=1,force=False)
  old_policy=REAL_POLICY();old_policy.pop('reading_context_contract',None)
  old_identity=library.prepare.json_digest({'version':library.VERSION,'reader':reader,'policy':old_policy,'baseline':None,'purpose':'identify-current-defects'})
  dependency='existing-source-dependency';workspace=self.song/'workspace';route_dir=self.song/'routes'
  journal=workspace/'.transcription/review-findings'/(library.prepare.json_digest({'reader':reader_digest,'dependency':dependency})+'.json')
  context=dict(lines=lines,glosses=glosses,reader_digest=reader_digest,dependency_fingerprint=dependency)
  def old_execute(attempt):
   reviews=[{'id':r['id'],'passes':True,'agency_preserved':True,'imagery_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[],'human_review_recommended':False,'material_choice':'','reason':'Historical source-only review fixture.','issues':[]} for r in lines]
   artifact={'reviewPurpose':'identify-current-defects','reader_digest':reader_digest,'dependency_fingerprint':dependency,'attempt_id':attempt.attempt_id,'reviews':reviews,'issues':[],'reviewPackets':[],'source_lines':lines,'gloss_rows':glosses}
   library.finding_store.record_review(journal,artifact,**context)
   return artifact
  routes.run_unit(route_dir,'fixture:current-source-review',old_identity,old_execute,
   lambda value:library.current_review_errors(value,lines,glosses,reader_digest,dependency),
   deadline_at=time.time()+30,dependency_fingerprint=dependency)
  saved={str(p):p.read_bytes() for p in self.song.rglob('*.json')}
  with patch.object(pipeline,'translation_policy_payload',side_effect=REAL_POLICY),patch.object(pipeline.gemini,'call',side_effect=AssertionError('migration must not dispatch')):
   with self.assertRaisesRegex(routes.RunFatal,'journal.*route history'):
    library.audit_current_reader(reader,slug='fixture',workspace=workspace,route_dir=route_dir,options=options,dependency_fingerprint=dependency,deadline_at=time.time()+30)
  self.assertEqual(saved,{str(p):p.read_bytes() for p in self.song.rglob('*.json')})
  # The library's enclosing accepted-song/run identity also observes the marker.
  old=library.fingerprints(reader,[],{},None,old_policy,None)
  new=library.fingerprints(reader,[],{},None,REAL_POLICY(),None)
  self.assertNotEqual(old['all'],new['all'])
  for key in ('audio','text','timing'):self.assertEqual(old[key],new[key])
  # Actual outer runner must reject its old accepted-input identity before work.
  state=self.song/'old-library-run';state.mkdir()
  run={'identity':{'catalogueRevision':'fixture-revision','budget_usd':1,'max_calls':2,
       'model':options.model,'pro_model':options.pro_model,'source_reuse_maps':{},'inputs':{'fixture':old['all']}},
       'status':'complete','songs':{'fixture':{'status':'accepted'}},'remaining':[]}
  pipeline.write_json(state/'run.json',run);run_bytes=(state/'run.json').read_bytes()
  opts=argparse.Namespace(**vars(options),budget_usd=1,max_calls=2,deadline_seconds=30,slugs=[])
  with patch.object(pipeline.gemini,'call',side_effect=AssertionError('old run must not dispatch')):
   with self.assertRaisesRegex(ValueError,'frozen run inputs'):
    library.execute_inventory(self.song,{'catalogueRevision':'fixture-revision','songs':[{'slug':'fixture','fingerprints':new}]},state,opts)
  self.assertEqual((state/'run.json').read_bytes(),run_bytes)
  # Fresh explicit state really reaches the new bounded English-context request.
  calls=[]
  def current_provider(model,key,prompt,**kwargs):
   calls.append(prompt);ids=json.JSONDecoder().raw_decode(prompt.split('OUTPUT TARGET IDS (return exactly these, once each):\n')[1].lstrip())[0]
   return {'packet':{'reviews':[{'id':i,'passes':True,'agency_preserved':True,'imagery_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[],'human_review_recommended':False,'material_choice':'','reason':'Fresh context delivery fixture.','issues':[]} for i in ids]}}
  with patch.object(pipeline,'translation_policy_payload',side_effect=REAL_POLICY),patch.object(pipeline.gemini,'call',side_effect=current_provider):
   result=library.audit_current_reader(reader,slug='fixture',workspace=self.song/'fresh-workspace',route_dir=self.song/'fresh-routes',options=options,dependency_fingerprint=dependency,deadline_at=time.time()+30)
  self.assertEqual(len(calls),1);self.context(calls[0]);self.assertEqual(len(result['reviews']),4)
  self.assertTrue(all(pathlib.Path(path).read_bytes()==value for path,value in saved.items()))

if __name__=='__main__':unittest.main()

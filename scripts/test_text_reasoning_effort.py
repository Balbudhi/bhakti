"""Actual semantic orchestration; canned outputs do not certify lower-effort quality."""
import copy,json,unittest
from unittest.mock import patch
import bhakti_pipeline as p
import bhakti_model_routes as routes
import bhakti_semantic_repair as semantic
import test_fresh_automatic_support as fixture

class TextReasoningTests(unittest.TestCase):
 def setUp(self):
  self.f=fixture.FreshAutomaticSupportTests();self.f.setUp();self.addCleanup(self.f.doCleanups);self.c=self.f.case
  self.c.options.semantic_stage_escalation=False;self.calls=[];self.unknown=False
  def transport(model,key,prompt,**kw):
   self.calls.append({'schema':kw['schema_name'],'effort':kw['reasoning_effort'],'prompt':prompt,'deadline':kw.get('deadline_at'),'cap':kw['max_completion_tokens']})
   if self.unknown and kw['schema_name']=='bhakti_literal_translation':
    raise routes.UnitTransportFailure('unknown-outcome',request_id='retained-unknown',worker_terminated=False)
   value=self.c.transport(model,key,prompt,**kw);value['resolved_model']=model;return value
  q=patch.object(p.gemini,'call',side_effect=transport);q.start();self.addCleanup(q.stop)
 def sequence(self):return [(c['schema'],c['effort']) for c in self.calls]
 def test_omitted_and_explicit_high_preserve_existing_acceptance_and_policy(self):
  policy=p.semantic_stage_policy(self.c.options);first=self.c.complete();state=self.c.state()
  self.assertEqual([c['effort'] for c in self.calls],['high']*3)
  self.c.options.text_reasoning_effort={'gloss':'high','writer':'high','review':'high'}
  self.assertEqual(p.semantic_stage_policy(self.c.options),policy)
  self.assertEqual(self.c.complete(),first);self.assertEqual(self.c.state(),state);self.assertEqual(len(self.calls),3)
 def test_actual_three_stage_dispatch_and_cache(self):
  self.c.options.text_reasoning_effort={'gloss':'low','writer':'low','review':'medium'}
  original=copy.deepcopy(self.c.audit);result=self.c.complete()
  self.assertEqual(self.sequence(),[('bhakti_word_glosses','low'),('bhakti_literal_translation','low'),('bhakti_translation_review','medium')])
  self.assertEqual(self.c.complete(),result);self.assertEqual(len(self.calls),3);self.assertEqual(self.c.audit,original)
  self.assertIn('having the hardness of a diamond',self.calls[-1]['prompt'])
 def test_writer_only_change_reuses_authenticated_gloss_not_old_writer(self):
  first=self.c.complete();old_gloss=copy.deepcopy(first[0]);old_run=self.c.state()['run_id'];self.calls.clear()
  self.c.options.text_reasoning_effort={'writer':'low'};second=self.c.complete()
  self.assertEqual(self.sequence(),[('bhakti_literal_translation','low'),('bhakti_translation_review','high')])
  self.assertEqual(second[0]["packet"],old_gloss["packet"]);self.assertEqual(second[0]["producer_fingerprint"],old_gloss["producer_fingerprint"]);self.assertNotEqual(self.c.state()['run_id'],old_run)
  self.assertEqual(self.c.complete(),second);self.assertEqual(len(self.calls),2)
 def test_review_only_change_preserves_writer_and_refreshes_only_review(self):
  first=self.c.complete();before=semantic.writer_rows(first[1]['packet']['translations']);self.calls.clear()
  self.c.options.text_reasoning_effort={'review':'medium'};second=self.c.complete()
  self.assertEqual(self.sequence(),[('bhakti_translation_review','medium')])
  self.assertEqual(second[0]["packet"],first[0]["packet"]);self.assertEqual(second[0]["producer_fingerprint"],first[0]["producer_fingerprint"]);self.assertEqual(semantic.writer_rows(second[1]['packet']['translations']),before)
  self.assertEqual(self.c.complete(),second);self.assertEqual(len(self.calls),1)
 def test_fresh_target_effort_keeps_owner_context_exact(self):
  self.c.options.text_reasoning_effort={'gloss':'low','writer':'low','review':'medium'}
  original=copy.deepcopy(self.f.plan);result=self.f.run_target()
  self.assertEqual([c['effort'] for c in self.calls],['low','low','medium'])
  self.assertEqual(self.f.plan,original);self.assertIn('OWNER ENGLISH',self.calls[-1]['prompt'])
  self.assertEqual(self.f.run_target(),result);self.assertEqual(len(self.calls),3)
 def test_unknown_writer_cannot_be_replayed_by_changing_effort(self):
  self.unknown=True
  with self.assertRaises(RuntimeError):self.c.complete()
  before={str(x):x.read_bytes() for x in self.c.packets.rglob('route-state.json')};old_state=self.c.state();n=len(self.calls)
  self.c.options.text_reasoning_effort={'writer':'low'}
  with self.assertRaises(RuntimeError):self.c.complete()
  self.assertEqual(len(self.calls),n);self.assertEqual(self.c.state(),old_state)
  for path,data in before.items():
   from pathlib import Path
   self.assertEqual(Path(path).read_bytes(),data)
 def test_invalid_configuration_precedes_lookup_or_dispatch(self):
  for value in ('low',True,[],{'audio':'low'},{'writer':'minimal'},{'gloss':None},{'review':True}):
   self.c.options.text_reasoning_effort=value
   with self.subTest(value=value),patch.object(p.bhakti_lexical_producer,'prepare_gloss_source',side_effect=AssertionError('lookup reached')):
    with self.assertRaisesRegex(ValueError,'text_reasoning_effort'):self.c.complete()
  self.assertEqual(self.calls,[])

 def test_direct_cached_writer_renews_review_effort_only(self):
  gloss=p.gloss(self.c.song,self.c.audit,self.c.options)
  first=p.translate(self.c.song,self.c.audit,gloss,{'slug':'fixture'},self.c.options)
  before=semantic.writer_rows(first['packet']['translations']);self.calls.clear()
  self.c.options.text_reasoning_effort={'review':'medium'}
  second=p.translate(self.c.song,self.c.audit,gloss,{'slug':'fixture'},self.c.options)
  self.assertEqual(self.sequence(),[('bhakti_translation_review','medium')])
  self.assertEqual(semantic.writer_rows(second['packet']['translations']),before)
  self.assertEqual(p.translate(self.c.song,self.c.audit,gloss,{'slug':'fixture'},self.c.options),second)
  self.assertEqual(len(self.calls),1)

 def test_default_caps_preserve_identity_and_accepted_cache(self):
  policy=p.semantic_stage_policy(self.c.options);first=self.c.complete();state=self.c.state()
  self.c.options.text_completion_caps={'gloss':65536,'writer':65536,'review':32768}
  self.assertEqual(p.semantic_stage_policy(self.c.options),policy)
  self.assertEqual(self.c.complete(),first);self.assertEqual(self.c.state(),state);self.assertEqual(len(self.calls),3)
 def test_explicit_caps_reach_actual_calls_and_free_resume(self):
  self.c.options.text_completion_caps={'gloss':32768,'writer':16384,'review':16384}
  first=self.c.complete();self.assertEqual([x['cap'] for x in self.calls],[32768,16384,16384])
  self.assertEqual(self.c.complete(),first);self.assertEqual(len(self.calls),3)
 def test_review_cap_only_renews_one_review(self):
  first=self.c.complete();before=semantic.writer_rows(first[1]['packet']['translations']);self.calls.clear()
  self.c.options.text_completion_caps={'review':16384};second=self.c.complete()
  self.assertEqual(self.sequence(),[('bhakti_translation_review','high')]);self.assertEqual(self.calls[0]['cap'],16384)
  self.assertEqual(semantic.writer_rows(second[1]['packet']['translations']),before)
  self.assertEqual(self.c.complete(),second);self.assertEqual(len(self.calls),1)
 def test_unknown_writer_cap_change_preserves_history(self):
  self.c.options.text_completion_caps={'writer':16384};self.unknown=True
  with self.assertRaises(RuntimeError):self.c.complete()
  before={path:path.read_bytes() for path in self.c.packets.rglob('route-state.json')}
  state=self.c.state();n=len(self.calls)
  self.c.options.text_completion_caps={}
  with self.assertRaises(RuntimeError):self.c.complete()
  self.assertEqual(len(self.calls),n);self.assertEqual(self.c.state(),state)
  for path,data in before.items():self.assertEqual(path.read_bytes(),data)
 def test_invalid_caps_precede_lookup_on_all_direct_entries(self):
  for value in ('low',True,[],{'audio':100},{'writer':0},{'gloss':65537},{'review':True},{'writer':1.5}):
   self.c.options.text_completion_caps=value
   with self.subTest(value=value):
    for call in (lambda:self.c.complete(),lambda:p.gloss(self.c.song,{},self.c.options),
                 lambda:p.translate(self.c.song,{}, {},{},self.c.options),
                 lambda:p.review_translation(self.c.song,{}, {},{},self.c.options,{}),
                 lambda:p.independently_review_translations(self.c.song,[],[],[],'',self.c.options)):
     with self.assertRaisesRegex(ValueError,'text_completion_caps'):call()
  self.assertEqual(self.calls,[])

class LongTextReasoningTests(unittest.TestCase):
 def test_all_batched_dispatch_sites_use_stage_effort(self):
  import test_automatic_semantic_repair as simple
  c=simple.AutomaticRepairTests();c.setUp();self.addCleanup(c.doCleanups)
  c.lines=[{**copy.deepcopy(c.lines[0]),'id':f'line-{i:03}'} for i in range(41)]
  c.audit['packet']['verified_lines']=c.lines
  original_rows=c.rows;c.rows=lambda lines,repaired=False:original_rows(lines,True)
  c.options.text_reasoning_effort={'gloss':'low','writer':'low','review':'medium'}
  c.options.text_completion_caps={'gloss':32768,'writer':16384,'review':16384}
  calls=[]
  def provider(model,key,prompt,**kw):
   calls.append((kw['schema_name'],kw['reasoning_effort'],kw['max_completion_tokens']));return c.provider(model,key,prompt,**kw)
  with patch.object(p.gemini,'call',side_effect=provider):gloss,translated=c.complete()
  self.assertEqual(len(translated['packet']['translations']),41)
  self.assertEqual({name for name,_,_ in calls},{'bhakti_word_gloss_batch','bhakti_translation_batch','bhakti_translation_review'})
  for name,effort,cap in calls:
   self.assertEqual(effort,'medium' if name=='bhakti_translation_review' else 'low')
   self.assertEqual(cap,32768 if name=='bhakti_word_gloss_batch' else 16384)

class HistoricalUnknownControls(unittest.TestCase):
 def test_new_controls_cannot_hide_old_outer_unknown(self):
  import test_source_before_gloss as historical
  for name,value in [('text_reasoning_effort',{'writer':'low'}),('text_completion_caps',{'writer':16384})]:
   with self.subTest(name=name):
    case=historical.HistoricalSourceGate('test_native_bootstrap_cannot_hide_prior_unknown_historical_route')
    case.setUp()
    try:
     setattr(case.case.options,name,value)
     case.test_native_bootstrap_cannot_hide_prior_unknown_historical_route()
    finally:case.doCleanups()

if __name__=='__main__':unittest.main()

"""Prompt scope/coverage tests; fake responses do not establish language quality."""
import argparse,copy,json,os,pathlib,tempfile,unittest
from unittest.mock import patch
import bhakti_pipeline as pipeline
import bhakti_library_pass as library
import prepare_library_review as prepare

ROOT=pathlib.Path(os.environ.get('BHAKTI_TEST_ROOT',pathlib.Path(__file__).resolve().parents[1]))

class BoundedReviewPayloadTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.song=pathlib.Path(self.tmp.name)
  self.lines=[{'id':f'line-{i}','source_text':f'NATIVE_UNIQUE_{i}','roman':f'word{i}','kind':'verse','sourceLanguage':'hi',
   'sourceWords':[{'text':f'NATIVE_UNIQUE_{i}','wordIndices':[0]}],'lexical_tokens':[f'word{i}'],
   'performed_context':[{'before':[{'id':f'line-{j}','source_text':f'NATIVE_UNIQUE_{j}','roman':f'word{j}'} for j in range(max(0,i-2),i)],'after':[]}]} for i in range(600)]
  self.glosses=[{'id':r['id'],'word_glosses':[{'roman':r['roman'],'gloss':f'meaning{i}'}], 'grammar_note':f'grammar{i}',
    'semantic_frame':{'cross_line_relation':''}} for i,r in enumerate(self.lines)]
  self.drafts=[{'id':r['id'],'literal_english':f'Current English {i}.','segments':[{'text':f'Current English {i}.','word_indices':[0]}]} for i,r in enumerate(self.lines)]
  self.order=[{'ref':r['id'],'section':'verse','repeats':1} for r in self.lines]
  self.options=argparse.Namespace(model='fixture',timeout=1,force=False,semantic_performance_order=self.order,semantic_full_source=self.lines)
  self.calls=[];self.inject=None
  for p in (patch.object(pipeline.gemini,'key',return_value='NO-KEY'),patch.object(pipeline.gemini,'call',side_effect=self.provider),
            patch.object(pipeline,'translation_policy_payload',return_value={}),
            patch.object(pipeline.bhakti_translation_policy,'guidance',return_value='fixture guidance')):
   mock=p.start();self.addCleanup(p.stop)
   if p.attribute=='guidance':self.guidance=mock
 def provider(self,model,key,prompt,**kwargs):
  targets=self.json_section(prompt,'OUTPUT TARGET IDS (return exactly these, once each):')
  self.calls.append((targets,prompt));rows=[self.clean_review(i) for i in targets]
  if self.inject and targets[0]=='line-0':rows.append(self.clean_review(self.inject))
  return {'packet':{'reviews':rows}}
 def clean_review(self,line_id):
  return {'id':line_id,'passes':True,'agency_preserved':True,'imagery_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[],'human_review_recommended':False,'material_choice':'','reason':'fixture only','issues':[]}
 def json_section(self,prompt,label):return json.JSONDecoder().raw_decode(prompt.split(label+'\n',1)[1].lstrip())[0]
 def full(self):return [{'source':s,'gloss':g,'draft':d} for s,g,d in zip(self.lines,self.glosses,self.drafts)]
 def review(self,ids=None):
  lines=self.lines;glosses=self.glosses;drafts=self.drafts
  if ids is not None:
   self.options.semantic_context_evidence=self.full()
   lines=[r for r in lines if r['id'] in ids];glosses=[r for r in glosses if r['id'] in ids];drafts=[r for r in drafts if r['id'] in ids]
  return pipeline.independently_review_translations(self.song,lines,glosses,drafts,'(none supplied)',self.options,languages=['Hindi'])
 def sections(self,prompt):
  return (self.json_section(prompt,'EVIDENCE:'),self.json_section(prompt,'ENGLISH READING CONTEXT (context only; target obligations unchanged):'))
 def test_six_hundred_row_review_supplies_only_actual_windows_without_rich_copies(self):
  self.review(['line-300']);self.assertEqual(len(self.calls),1);targets,prompt=self.calls[0];evidence,reading=self.sections(prompt)
  actual=[r['source']['id'] for r in evidence+reading['context_rows']]
  self.assertEqual(set(actual),{f'line-{i}' for i in range(297,304)});self.assertEqual(len(actual),len(set(actual)))
  self.assertNotIn('NATIVE_UNIQUE_100',prompt);self.assertNotIn('performed_context',prompt)
  self.assertNotIn('FULL SOURCE CONTEXT',prompt);self.assertNotIn('NEARBY SOURCE CONTEXT',prompt)
  self.assertNotIn('AUDITED PERFORMANCE ORDER:',prompt);self.assertLess(len(prompt),30000)
  self.assertEqual(targets,['line-300'])
 def test_target_compound_indices_and_all_analysis_fields_preserved_verbatim(self):
  self.lines[300].update(source_text='कविपति',roman='kavi-pati',sourceWords=[{'text':'कविपति','wordIndices':[0,1]}],lexical_tokens=['kavi','pati'],lexicalRegister='classical')
  self.glosses[300]['word_glosses']=[{'roman':'kavi','gloss':'poet'},{'roman':'pati','gloss':'lord'}]
  self.drafts[300].update(literal_english='lord of poets',segments=[{'text':'lord of poets','word_indices':[0,1]}])
  before=copy.deepcopy((self.lines,self.glosses,self.drafts,self.order))
  self.review(['line-300']);evidence,reading=self.sections(self.calls[0][1])
  expected={k:v for k,v in self.lines[300].items() if k!='performed_context'}
  self.assertEqual(evidence[0]['source'],expected);self.assertEqual(evidence[0]['gloss'],self.glosses[300]);self.assertEqual(evidence[0]['draft'],self.drafts[300])
  self.assertEqual(before,(self.lines,self.glosses,self.drafts,self.order))
  for row in reading['context_rows']:
   original=copy.deepcopy(next(r for r in self.full() if r['source']['id']==row['source']['id']));original['source'].pop('performed_context')
   self.assertEqual(row,original)
 def test_repeated_target_keeps_separate_real_windows_and_occurrence_numbers(self):
  self.order.insert(500,{'ref':'line-10','section':'refrain','repeats':2});self.review(['line-10'])
  evidence,reading=self.sections(self.calls[0][1]);self.assertEqual(len(reading['reading_windows']),2)
  occurrences=[e for w in reading['reading_windows'] for e in w['occurrences'] if e['line_id']=='line-10']
  self.assertEqual([r['occurrence'] for r in occurrences],[1,2,3]);self.assertEqual([r['repeat_index'] for r in occurrences],[0,0,1])
  defined=[r['source']['id'] for r in evidence+reading['context_rows']];self.assertEqual(defined.count('line-10'),1)
  self.assertNotIn('NATIVE_UNIQUE_250',self.calls[0][1])
 def test_distant_named_relation_keeps_source_english_gloss_and_separate_window(self):
  self.glosses[10]['semantic_frame']['cross_line_relation']='Subject and predicate continue in line-500.'
  self.review(['line-10']);evidence,reading=self.sections(self.calls[0][1]);rows={r['source']['id']:r for r in reading['context_rows']}
  self.assertEqual(rows['line-500']['draft'],self.drafts[500]);self.assertEqual(rows['line-500']['gloss'],self.glosses[500])
  self.assertEqual(rows['line-500']['source']['source_text'],self.lines[500]['source_text'])
  self.assertEqual(len(reading['reading_windows']),2);self.assertNotIn('NATIVE_UNIQUE_250',self.calls[0][1]);self.assertTrue(reading['relation_notes'])
 def test_lexical_guidance_still_receives_original_correct_context_not_flattened_windows(self):
  self.order.insert(500,{'ref':'line-10','repeats':1});self.review(['line-10'])
  args=self.guidance.call_args
  self.assertEqual(args.args[0],[self.lines[10]])
  self.assertEqual(args.kwargs['context_lines'],self.lines);self.assertEqual(args.kwargs['performance_order'],self.order)
  self.assertIn('performed_context',args.args[0][0])
 def test_returned_known_but_unsupplied_song_id_is_rejected(self):
  self.inject='line-400'
  with self.assertRaises((ValueError,RuntimeError)):self.review(['line-0'])
  self.assertEqual(len(self.calls),1)
 def test_returned_actually_supplied_context_id_remains_valid_context(self):
  self.inject='line-3';reviews,packets=self.review(['line-0'])
  self.assertEqual([r['id'] for r in reviews],['line-0']);self.assertEqual(len(self.calls),1)
 def test_payload_projection_rejects_duplicate_or_unbound_window_definition(self):
  reading=pipeline.translation_reading_context(self.lines,self.glosses,self.drafts,['line-10'],performance_order=self.order)
  evidence=[self.full()[10]]
  for bad in ('duplicate','unknown','missing'):
   value=copy.deepcopy(reading)
   if bad=='duplicate':value['context_rows'].append(copy.deepcopy(value['context_rows'][0]))
   elif bad=='unknown':value['reading_windows'][0]['occurrences'].append({'line_id':'missing','occurrence':1,'repeat_index':0})
   else:value['context_rows'].pop()
   with self.subTest(bad=bad),self.assertRaises(ValueError):pipeline.translation_review_payload(evidence,value)
 def test_actual_sundar_full_reader_payload_is_bounded_and_has_every_target_map(self):
  reader=prepare.load_javascript((ROOT/'songs/sampurna-sundarakanda/data.js').read_bytes())
  self.lines,self.glosses,self.drafts=library.reader_evidence(reader);self.order=copy.deepcopy(reader['SONG_SEQUENCE'])
  self.options.semantic_full_source=self.lines;self.options.semantic_performance_order=self.order
  self.review();self.assertEqual(sum(len(ids) for ids,_ in self.calls),len(self.lines))
  self.assertEqual(len(self.calls),(len(self.lines)+9)//10)
  originals={r['id']:r for r in self.lines}
  for ids,prompt in self.calls:
   evidence,reading=self.sections(prompt);allrows=evidence+reading['context_rows']
   self.assertLess(len(allrows),len(self.lines)//2);self.assertNotIn('performed_context',prompt)
   self.assertEqual(len(allrows),len({r['source']['id'] for r in allrows}))
   self.assertLess(len(prompt),150000)
   for row in allrows:self.assertEqual(row['source'],{k:v for k,v in originals[row['source']['id']].items() if k!='performed_context'})
 def test_review_payload_contract_versions_only_review_fingerprint_and_reuses_exact_cache(self):
  fingerprints=[];original=pipeline.text_stage_fingerprint
  def record(stage,model,inputs,policy):
   if stage=='translation-review':fingerprints.append(copy.deepcopy(policy))
   return original(stage,model,inputs,policy)
  with patch.object(pipeline,'text_stage_fingerprint',side_effect=record):self.review(['line-10'])
  self.assertTrue(fingerprints);self.assertTrue(all(p.get('review_payload_contract')==1 for p in fingerprints))
  self.calls=[];self.review(['line-10']);self.assertEqual(self.calls,[])
  self.drafts[9]['literal_english']='Changed actual neighbor English';self.review(['line-10']);self.assertEqual(len(self.calls),1)

if __name__=='__main__':unittest.main()

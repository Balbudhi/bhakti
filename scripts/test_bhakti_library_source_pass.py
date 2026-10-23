import copy,hashlib,json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import bhakti_library_source_pass as source_pass
FIX=pathlib.Path(__file__).parent/'fixtures/source_pass'
def reader_file(path):
 text=path.read_text();decoder=json.JSONDecoder()
 return {name:decoder.raw_decode(text.split('window.'+name+' =',1)[1].lstrip())[0] for name in ('SONG_META','SONG_LINES','SONG_SEQUENCE','SONG_TIMINGS')}
def patta():return reader_file(FIX/'patta-data.js'),json.loads((FIX/'patta-rebuilt.json').read_text()),json.loads((FIX/'patta-map.json').read_text())
def candidate_for(before,plan):
 after=copy.deepcopy(before)
 for line in plan['lines']:
  if line['id'] in before['SONG_LINES']:continue
  tokens=[x for x in line['roman'].split() if any(c.isalnum() for c in x)]
  after['SONG_LINES'][line['id']]={'source':line['source_text'],'roman':line['roman'],'sourceLanguage':'hi','sourceWords':[], 'words':[{'roman':t,'gloss':'candidate'} for t in tokens],'english':'candidate','grammarNote':''}
 sequence=[];kinds={line['id']:line.get('kind','verse') for line in plan['lines']}
 for row in plan['performance_order']:
  if sequence and sequence[-1]['ref']==row['line_id']:sequence[-1]['repeats']+=1
  else:sequence.append({'ref':row['line_id'],'section':kinds[row['line_id']],'repeats':1})
 after['SONG_SEQUENCE']=sequence;after['SONG_TIMINGS']=[{'start':float(i),'end':float(i+1)} for i in range(len(sequence))]
 timing={'sequence':[{'occurrence_id':f'occ-{i:03d}',**s,**t} for i,(s,t) in enumerate(zip(sequence,after['SONG_TIMINGS']))]}
 return after,timing
class SourcePlanTests(unittest.TestCase):
 def test_actual_patta_reuses_all29_and_has_only5_new_targets(self):
  old,rebuilt,mapping=patta();snapshot=copy.deepcopy(old);plan=source_pass.plan_source(old,rebuilt,reviewed_map=mapping)
  self.assertEqual(len(plan['new_target_ids']),5);self.assertEqual(set(plan['reuse_by_id']),set(old['SONG_LINES']));self.assertEqual(len(plan['performance_order']),59)
  self.assertEqual(len(plan['lines']),34);self.assertEqual(old,snapshot)
  for lid,line in old['SONG_LINES'].items():self.assertEqual(plan['reuse_by_id'][lid],line)
  self.assertEqual(plan['raw_to_final']['line-000'],plan['raw_to_final']['line-036'])
  self.assertNotEqual(plan['raw_to_final']['line-008'],'line-008')
 def test_aliases_preserve_original_iast_and_words(self):
  old,rebuilt,mapping=patta();plan=source_pass.plan_source(old,rebuilt,reviewed_map=mapping)
  by={x['id']:x for x in plan['lines']}
  self.assertEqual(by['line-000']['roman'],old['SONG_LINES']['line-000']['roman'])
  self.assertEqual(plan['raw_to_final']['line-009'],plan['raw_to_final']['line-011'])
 def test_stale_public_baseline_line_rejected(self):
  old,rebuilt,mapping=patta();old['SONG_LINES']['line-000']['english']='changed'
  with self.assertRaises(ValueError):source_pass.plan_source(old,rebuilt,reviewed_map=mapping)
 def test_stale_audited_source_rejected(self):
  old,rebuilt,mapping=patta();rebuilt['verified_lines'][0]['source_text']='अन्य पाठ'
  with self.assertRaises(ValueError):source_pass.plan_source(old,rebuilt,reviewed_map=mapping)
 def test_unknown_or_duplicated_raw_mapping_rejected(self):
  old,rebuilt,mapping=patta()
  for mutation in ('duplicate','unknown'):
   m=copy.deepcopy(mapping)
   if mutation=='duplicate':m['mapping'].append(copy.deepcopy(m['mapping'][0]))
   else:m['mapping'][0]['new_line_id']='not-a-real-id'
   with self.subTest(mutation=mutation),self.assertRaises(ValueError):source_pass.plan_source(old,rebuilt,reviewed_map=m)
 def test_without_review_ambiguous_same_native_is_not_guessed(self):
  old,rebuilt,_=patta();old['SONG_LINES']['ambiguous']=copy.deepcopy(old['SONG_LINES']['line-000'])
  with self.assertRaises(ValueError):source_pass.plan_source(old,rebuilt)
 def test_unknown_old_source_cannot_be_silently_dropped(self):
  old,rebuilt,mapping=patta();mapping['mapping']=[x for x in mapping['mapping'] if x['old_line_id']!='line-028']
  with self.assertRaises(ValueError):source_pass.plan_source(old,rebuilt,reviewed_map=mapping)
 def test_native_vowel_difference_does_not_share_identity(self):
  line={'source':'मन','roman':'man','english':'{0:mind}','words':[{'roman':'man','gloss':'mind'}]}
  old={'SONG_META':{},'SONG_LINES':{'old':line},'SONG_SEQUENCE':[{'ref':'old','repeats':1}],'SONG_TIMINGS':[{'start':0,'end':1}]}
  rebuilt={'verified_lines':[{'id':'a','source_text':'मन','roman':'man'},{'id':'b','source_text':'मान','roman':'mān'}],'performance_order':[{'line_id':'a'},{'line_id':'b'}],'uncertainties':[]}
  plan=source_pass.plan_source(old,rebuilt);self.assertEqual(plan['raw_to_final']['a'],'old');self.assertNotEqual(plan['raw_to_final']['b'],'old');self.assertEqual(len(plan['new_target_ids']),1)
class PreservationTests(unittest.TestCase):
 def setUp(self):
  self.before,rebuilt,mapping=patta();self.plan=source_pass.plan_source(self.before,rebuilt,reviewed_map=mapping);self.after,self.timing=candidate_for(self.before,self.plan)
 def test_valid_source_addition_keeps_all_old_rows(self):source_pass.assert_source_candidate(self.before,self.after,self.plan,self.timing)
 def test_changed_old_english_and_gloss_rejected(self):
  for field in ('english','words','source','roman','grammarNote','sourceWords','sourceLanguage'):
   after=copy.deepcopy(self.after);after['SONG_LINES']['line-000'][field]='changed'
   with self.subTest(field=field),self.assertRaises(ValueError):source_pass.assert_source_candidate(self.before,after,self.plan,self.timing)
 def test_metadata_mutation_rejected(self):
  self.after['SONG_META']['title']='changed'
  with self.assertRaises(ValueError):source_pass.assert_source_candidate(self.before,self.after,self.plan,self.timing)
 def test_order_and_repeat_changes_rejected(self):
  for field in ('ref','repeats'):
   after=copy.deepcopy(self.after);after['SONG_SEQUENCE'][0][field]='bad' if field=='ref' else 99
   with self.subTest(field=field),self.assertRaises(ValueError):source_pass.assert_source_candidate(self.before,after,self.plan,self.timing)
 def test_new_source_mutation_rejected(self):
  self.after['SONG_LINES'][self.plan['new_target_ids'][0]]['source']='invented'
  with self.assertRaises(ValueError):source_pass.assert_source_candidate(self.before,self.after,self.plan,self.timing)
 def test_unapproved_timing_mutation_rejected(self):
  self.after['SONG_TIMINGS'][0]['start']=.2
  with self.assertRaises(ValueError):source_pass.assert_source_candidate(self.before,self.after,self.plan,self.timing)
class CheckpointTests(unittest.TestCase):
 def test_accepted_checkpoint_requires_matching_input_and_result_digest(self):
  with tempfile.TemporaryDirectory() as td:
   path=pathlib.Path(td)/'accepted.json';result={'status':'accepted','reader':{'a':1},'source_changed':True,'publicationEligible':True,'evidence':{},'issues':[]}
   source_pass.save_checkpoint(path,'original-input',result)
   self.assertEqual(source_pass.load_checkpoint(path,'original-input'),result);self.assertIsNone(source_pass.load_checkpoint(path,'changed-input'))
   value=json.loads(path.read_text());value['result']['reader']['a']=2;path.write_text(json.dumps(value))
   with self.assertRaises(ValueError):source_pass.load_checkpoint(path,'original-input')
 def test_unresolved_result_never_becomes_accepted_checkpoint(self):
  with tempfile.TemporaryDirectory() as td:
   with self.assertRaises(ValueError):source_pass.save_checkpoint(pathlib.Path(td)/'accepted.json','x',{'status':'unresolved','publicationEligible':False})
if __name__=='__main__':unittest.main()

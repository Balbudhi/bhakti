"""Actual saved decisions; gate behavior, not certification of their semantics."""
import copy,json,unittest
from pathlib import Path
import bhakti_lexical_support as support
import bhakti_pipeline as pipeline

class LexicalRealization(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.data=json.loads((Path(__file__).parent/'fixtures/lexical-realization/main-three-decisions.json').read_text())
 def case(self,index):
  row=copy.deepcopy(self.data['translations'][index]);ids={d['target_id'] for d in row['wording_decisions']}
  packet=copy.deepcopy(self.data['packet']);packet['targets']=[t for t in packet['targets'] if t['id'] in ids]
  gloss=[copy.deepcopy(g) for g in self.data['gloss_rows'] if g['id']==row['id']]
  return packet,gloss,row
 def errors(self,case):packet,gloss,row=case;return support.support_decision_errors(packet,gloss,[row])
 def test_actual_unspaced_segments_match_renderer_and_mapping(self):
  for index in (0,1):
   with self.subTest(index=index):
    packet,gloss,row=self.case(index)
    self.assertEqual(pipeline.segment_english([{**p,'word_indices':[]} for p in row['segments']],''),row['literal_english'])
    self.assertEqual(self.errors((packet,gloss,row)),[])
 def test_literal_mismatch_and_wrong_source_mapping_still_hold(self):
  for mutation in ('literal','mapping'):
   with self.subTest(mutation=mutation):
    case=self.case(0);row=case[2]
    if mutation=='literal':row['literal_english']+=' unsupported'
    else:row['segments'][-1]['word_indices']=[0]
    self.assertTrue(any('expression/source' in e for e in self.errors(case)))
 def test_renderer_punctuation_and_explicit_spaces(self):
  for segments,text,expression,indices in [
   ([{'text':'well-','word_indices':[0]},{'text':' loved','word_indices':[1]}],'well-loved','well-loved',[0,1]),
   ([{'text':'in ','word_indices':[0]},{'text':'stillness,','word_indices':[1]}],'in stillness,','in stillness',[0,1])]:
   self.assertTrue(support.expression_matches_segments({'segments':segments,'literal_english':text},expression,indices))
 def test_actual_cherishes_is_same_selected_attested_verb(self):self.assertEqual(self.errors(self.case(2)),[])
 def test_exact_selected_base_still_accepted(self):
  case=self.case(2);row=case[2];row['literal_english']=row['literal_english'].replace('cherishes','cherish')
  row['segments'][1]['text']='cherish ';row['wording_decisions'][0]['expression']='cherish'
  self.assertEqual(self.errors(case),[])
 def test_unrelated_synonym_or_unimplemented_tense_not_inferred(self):
  for expression in ('treasures','cherished','cherishing','cherishez'):
   with self.subTest(expression=expression):
    case=self.case(2);row=case[2];row['literal_english']=row['literal_english'].replace('cherishes',expression)
    row['segments'][1]['text']=expression+' ';row['wording_decisions'][0]['expression']=expression
    self.assertTrue(self.errors(case))
 def test_inflection_does_not_accept_noun_or_unattested_base(self):
  for change in ('noun','lemma','reference'):
   with self.subTest(change=change):
    case=self.case(2);packet,_,row=case;decision=row['wording_decisions'][0]
    evidence=next(e for e in packet['evidence'] if e['id']==decision['english_evidence_ids'][0])
    if change=='noun':evidence['pos']='n'
    elif change=='lemma':evidence['lemmas']=['treasure']
    else:decision['english_evidence_ids']=['unrelated-sense']
    self.assertTrue(self.errors(case))

 def test_written_ch_is_not_assumed_sibilant(self):
  # Structural perturbation: even a declared verb/base is insufficient for this rule.
  case=self.case(2);packet,_,row=case;decision=row['wording_decisions'][0]
  candidate=next(c for c in packet['targets'][0]['english_candidates'] if c['id']==decision['chosen_candidate_id'])
  candidate['expression']='stomach'
  for evidence in packet['evidence']:
   if evidence['id'] in decision['english_evidence_ids']:evidence['lemmas']=['stomach']
  decision['expression']='stomaches';row['literal_english']=row['literal_english'].replace('cherishes','stomaches')
  row['segments'][1]['text']='stomaches '
  self.assertTrue(self.errors(case))

if __name__=='__main__':unittest.main()

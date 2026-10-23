import argparse,copy,json,os,pathlib,sys,tempfile,unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import bhakti_pipeline as pipeline
import bhakti_translation_policy as policy
import bhakti_lexical_retrieval as retrieval
FIXTURE=pathlib.Path(__file__).parent/'fixtures/gloss-lexical-candidates.json'

class CapturedPrompt(BaseException):pass

def block(prompt,marker):return json.JSONDecoder().raw_decode(prompt.split(marker,1)[1].lstrip())[0]
def expand(packet):
 def walk(value):
  if isinstance(value,dict):
   if set(value)=={'$text'}:return packet['text_blocks'][value['$text']]
   return {k:walk(v) for k,v in value.items()}
  if isinstance(value,list):return [walk(v) for v in value]
  return value
 return walk(packet)

class GlossPromptDictionaryCostTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.song=pathlib.Path(self.tmp.name);self.calls=[]
  self.lines=[{'id':'line-0','source_text':'मन बानी करे मन','roman':'Man bānī kare Man','kind':'verse','sourceLanguage':'hi','sourceWords':[{'text':t,'wordIndices':[i]} for i,t in enumerate(['मन','बानी','करे','मन'])]}]
  self.lexicon=json.loads(FIXTURE.read_text())
  for p in [patch.dict(os.environ,{'BHAKTI_LEXICON_PATH':str(FIXTURE)},clear=True),patch.object(pipeline.gemini,'key',return_value='not-a-key'),patch.object(pipeline.gemini,'call',side_effect=self.capture)]:p.start();self.addCleanup(p.stop)
 def capture(self,model,key,prompt,**kwargs):self.calls.append((prompt,kwargs));raise CapturedPrompt()
 def run_gloss(self):
  options=argparse.Namespace(model='google/gemini-3.7-flash',force=False,timeout=1)
  with self.assertRaises(CapturedPrompt):pipeline.gloss(self.song,{'packet':{'verified_lines':self.lines,'metadata':{'languages':['Hindi']}}},options)
 def check_request(self,prompt,kwargs):
  self.assertNotIn('TOKEN CANDIDATES (complete surface bindings',prompt)
  self.assertIn('candidate_entry_ids',prompt)
  self.assertIn('Copy word_index and roman from tokens in COMPACT LEXICAL EVIDENCE',prompt)
  packet=expand(block(prompt,'COMPACT LEXICAL EVIDENCE (unselected):\n'))
  target=block(prompt,'TARGET LYRICS (return these IDs only):\n')
  expected=policy.token_candidates(target,['Hindi'])
  entries={e['entry_id']:e for words in expected.values() for w in words for e in w['candidates']}
  self.assertEqual({e['entry_id']:e for e in packet['entries']},entries)
  for lid,words in expected.items():
   actual=packet['tokens'][lid];self.assertEqual(len(actual),len(words))
   for a,w in zip(actual,words):
    self.assertEqual(a,{**{k:v for k,v in w.items() if k!='candidates'},'candidate_entry_ids':[e['entry_id'] for e in w['candidates']]})
  schema=kwargs['response_schema']['properties']['glosses']['items']['properties']
  self.assertEqual(schema['sense_decisions'],policy.sense_decision_schema())
  self.assertTrue(any(w.get('lemma_evidence') for words in expected.values() for w in words))
  self.assertTrue(any(len(w['candidates'])>1 for words in expected.values() for w in words))
 def test_single_gloss_request_supplies_all_dictionary_evidence_once(self):
  self.run_gloss();self.assertEqual(len(self.calls),1);self.check_request(*self.calls[0])
 def test_actual_batched_gloss_requests_use_same_reference_only_contract(self):
  self.lines=[{**copy.deepcopy(self.lines[0]),'id':f'line-{i}'} for i in range(41)]
  self.run_gloss();self.assertEqual(len(self.calls),2)
  for call in self.calls:self.check_request(*call)
 def test_gloss_does_not_rebuild_full_token_candidates_after_guidance(self):
  with patch.object(policy,'token_candidates',side_effect=AssertionError('duplicate raw candidates requested')):self.run_gloss()
  self.assertEqual(len(self.calls),1)

if __name__=='__main__':unittest.main()

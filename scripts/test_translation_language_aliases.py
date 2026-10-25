"""Actual writer entrypoint: equivalent metadata labels, not inferred languages."""
import argparse,copy,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import bhakti_pipeline as p
from test_sense_decisions import decisions_for, __file__ as fixture_path
from test_word_accountability_fixtures import account_response

class TranslationLanguageAliases(unittest.TestCase):
 def setUp(self):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.song=Path(temp.name)/'song'
  self.options=argparse.Namespace(model='google/gemini-3.7-flash',force=False,timeout=30)
  self.line={'id':'home','source_text':'ਘਰ','roman':'ghar','kind':'verse'}
  self.audit={'packet':{'verified_lines':[self.line],'metadata':{'languages':['pa']}}}
  self.gloss={'packet':{'glosses':[{'id':'home','word_glosses':[{'roman':'ghar','gloss':'home','concept_key':'','preserve_in_english':False}],
   'semantic_frame':{key:'' for key in p.SEMANTIC_FRAME_FIELDS},'grammar_note':'','uncertainty':'',
   'sense_decisions':decisions_for([self.line],['Punjabi'])['home']}]},'sense_languages':['Punjabi']}
  self.calls=[]
  def provider(model,key,prompt,**kwargs):
   self.calls.append(kwargs['schema_name'])
   row={'id':'home','literal_english':'Home.','segments':[{'text':'Home.','word_indices':[0]}],
    'material_alternatives':[],'human_review_recommended':False,'choice_note':'','uncertainty':'',
    'fidelity':{'agency_and_image_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[],'notes':''}}
   return account_response({'packet':{'translations':[row]}},prompt,kwargs['schema_name'])
  for item in (patch.object(p,'ROOT',Path(fixture_path).resolve().parents[1]),
               patch.object(p.gemini,'key',return_value='offline'),patch.object(p.gemini,'call',side_effect=provider),
               patch.dict(os.environ,{'BHAKTI_AUTO_LEXICAL':'0'})):
   item.start();self.addCleanup(item.stop)
 def run_writer(self,language='Punjabi'):
  return p.translate(self.song,self.audit,self.gloss,{'languages':[language]},self.options,candidate_only=True,defer_review=True)
 def test_code_and_name_reach_actual_writer(self):
  original=copy.deepcopy((self.audit,self.gloss));result=self.run_writer()
  self.assertEqual(self.calls,['bhakti_literal_translation']);self.assertEqual(result['packet']['translations'][0]['literal_english'],'Home.')
  self.assertEqual((self.audit,self.gloss),original)
 def test_reverse_code_name_and_gloss_alias(self):
  self.audit['packet']['metadata']['languages']=['Punjabi'];self.gloss['sense_languages']=['pan']
  result=self.run_writer('pa');self.assertEqual(self.calls,['bhakti_literal_translation'])
  self.assertEqual(result['packet']['translations'][0]['literal_english'],'Home.')
 def test_different_source_or_gloss_language_stays_blocked(self):
  for field in ('source','gloss'):
   with self.subTest(field=field):
    self.audit['packet']['metadata']['languages']=['Hindi' if field=='source' else 'pa']
    self.gloss['sense_languages']=['Hindi' if field=='gloss' else 'Punjabi']
    with self.assertRaisesRegex(RuntimeError,'translation language conflicts'):self.run_writer()
  self.assertEqual(self.calls,[])
 def test_unknown_languages_do_not_collapse_to_empty_code(self):
  self.audit['packet']['metadata']['languages']=['Unknown one'];self.gloss['sense_languages']=['Unknown two']
  with self.assertRaisesRegex(RuntimeError,'translation language conflicts'):self.run_writer('Unknown two')
  self.assertEqual(self.calls,[])

if __name__=='__main__':unittest.main()

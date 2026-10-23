"""Actual recent reader regression; selection-only, no dictionary/model claims."""
import copy
import json
from pathlib import Path
import unittest
import bhakti_lexical_retrieval as retrieval

CASES = json.loads((Path(__file__).parent / 'fixtures/recent-language-lines.json').read_text())

class LanguageFallbackTests(unittest.TestCase):
 def test_actual_tamil_and_telugu_blank_line_labels_use_single_explicit_metadata(self):
  for slug,code in [('koodarai-vellum-seer-govinda','ta'),('jo-achyutananda','te')]:
   case=CASES[slug];self.assertEqual(case['line']['sourceLanguage'],'')
   with self.subTest(slug=slug):self.assertEqual(retrieval.line_language(case['line'],case['languages']),code)
 def test_missing_null_empty_and_whitespace_are_unspecified_not_unknown(self):
  for line in [{},{'sourceLanguage':None},{'sourceLanguage':''},{'sourceLanguage':' \t '}]:
   with self.subTest(line=line):self.assertEqual(retrieval.line_language(line,['Tamil']),'ta')
 def test_nonempty_unknown_and_invalid_types_do_not_borrow_metadata(self):
  for value in ['unknown','xx','Devanagari',False,0,[],{}]:
   with self.subTest(value=value):self.assertEqual(retrieval.line_language({'sourceLanguage':value},['Tamil']),'')
 def test_unspecified_line_stays_unresolved_for_mixed_unknown_or_absent_metadata(self):
  for languages in [[],None,['Tamil','Telugu'],['Tamil','unknown'],['unknown'],['Tamil',None],'Tamil',{'Tamil':'x'},1,('Tamil',)]:
   for value in ['',None]:
    with self.subTest(languages=languages,value=value):self.assertEqual(retrieval.line_language({'sourceLanguage':value},languages),'')
 def test_known_explicit_line_language_remains_authoritative(self):
  self.assertEqual(retrieval.line_language({'sourceLanguage':'pa'},['Hindi']),'pa');self.assertEqual(retrieval.line_language({'sourceLanguage':'Tamil'},['Tamil','Telugu']),'ta');self.assertEqual(retrieval.line_language({},['Tamil','ta']),'ta')
 def test_real_reader_token_and_embedding_context_use_same_language_without_mutation(self):
  case=CASES['koodarai-vellum-seer-govinda'];line={'id':case['id'],**copy.deepcopy(case['line'])};before=copy.deepcopy(line)
  def entry(code):return {'entry_id':'fixture.'+code+'.sir','language':code,'register':'poetic','source_spellings':['சீர்'],'roman_search_aliases':['sīr'],'dictionary':{'work':'mechanical language fixture only','url':'https://example.test/fixture'},'senses':[{'sense_id':'fixture.'+code+'.sir:entry','short_english':'fixture sense'}]}
  lexicon={'entries':[entry('ta'),entry('te')]};rows=retrieval.token_candidates([line],case['languages'],lexicon)[line['id']]
  self.assertEqual([r['entry_id'] for r in rows[2]['candidates']],['fixture.ta.sir'])
  self.assertEqual(json.loads(retrieval.query_context(line,'sīr',case['languages']))['language'],'ta');self.assertEqual(line,before)
  line['sourceLanguage']='unknown';self.assertEqual(retrieval.token_candidates([line],case['languages'],lexicon)[line['id']][2]['candidates'],[])
if __name__=='__main__':unittest.main()

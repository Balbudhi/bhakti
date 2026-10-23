import hashlib,json,pathlib,sys,unittest,copy,tempfile,re
ROOT=pathlib.Path(__file__).parent/'fixtures/dictionary_corpus'
from dictionary_corpus import parse_platts_html,query_forms,merge_entries,import_csl_json,load_cached_witness,acquire_queries
ACQ={r['query']:r for r in json.loads((ROOT/'acquisition.json').read_text())}
def parsed(q):
 r=ACQ[q];raw=(ROOT/r['path']).read_bytes()
 return parse_platts_html(raw.decode(),query=q,url=r['url'],witness_sha256=hashlib.sha256(raw).hexdigest())
class PlattsTests(unittest.TestCase):
 def test_actual_unclosed_entry_and_whole_context(self):
  r=parsed('ढलना')[0]
  self.assertEqual(r['dictionary']['print_page'],572)
  self.assertEqual(r['language'],'hi');self.assertIn('ढलना',r['source_spellings']);self.assertIn('ḍhalnā',r['roman_search_aliases'])
  self.assertIn('to decline, sink, fade',r['dictionary']['whole_entry_text']);self.assertIn('ḍhal-jānā',r['dictionary']['whole_entry_text'])
  self.assertEqual(r['senses'][0]['granularity'],'entry_context');self.assertIn('to decline, sink, fade',r['senses'][0]['short_english'])
 def test_etymology_is_context_not_alias(self):
  r=parsed('मन')[0];self.assertNotIn('मणो',r['source_spellings']);self.assertNotIn('मनस्',r['source_spellings']);self.assertIn('मणो',r['dictionary']['whole_entry_text'])
 def test_homographs_kept_distinct(self):
  rs=parsed('मन');self.assertGreaterEqual(len(rs),2);self.assertEqual(len(rs),len({r['entry_id'] for r in rs}));self.assertTrue(any('weight' in r['dictionary']['whole_entry_text'] for r in rs))
 def test_ids_stable_between_fetch_witness_versions(self):
  q='मन';r=ACQ[q];h=(ROOT/r['path']).read_text();a=parse_platts_html(h,query=q,url=r['url'],witness_sha256='a'*64);b=parse_platts_html(h+'\n',query=q,url=r['url'],witness_sha256='b'*64)
  self.assertEqual([x['entry_id'] for x in a],[x['entry_id'] for x in b]);self.assertNotEqual(a[0]['dictionary']['witness_sha256'],b[0]['dictionary']['witness_sha256'])
 def test_roman_only_headword_not_fabricated_native(self):
  r=parsed('wīrāna')[0];self.assertEqual(r['source_spellings'],[]);self.assertIn('wīrāna',r['roman_search_aliases']);self.assertNotIn('वीराना',r['source_spellings'])
 def test_canonical_nukta_query_alias_preserves_diacritic(self):
  self.assertIn('पुड़िया',query_forms('पुड़िया'));self.assertNotIn('पुडिया',query_forms('पुड़िया'));self.assertEqual(query_forms('मन'),['मन'])
  r=parsed('पुड़िया')[0];self.assertIn('पुड़िया',r['source_spellings']);self.assertIn('पुड़िया',r['source_spellings'])
 def test_explicit_miss_not_transport_error(self):
  self.assertEqual(parsed('असंगतअशब्दकखग'),[])
  with self.assertRaises(ValueError):parse_platts_html('<html>Service unavailable</html>',query='x',url='https://dsal.uchicago.edu',witness_sha256='a'*64)
 def test_missing_citation_rejected(self):
  q='ढलना';r=ACQ[q];h=(ROOT/r['path']).read_text().replace('page=572','bad=572')
  with self.assertRaises(ValueError):parse_platts_html(h,query=q,url=r['url'],witness_sha256='a'*64)
 def test_each_entry_requires_its_own_page_witness(self):
  r=ACQ['मन'];h=(ROOT/r['path']).read_text();matches=list(re.finditer('page=1069',h));self.assertGreaterEqual(len(matches),2)
  m=matches[1];broken=h[:m.start()]+'bad=1069'+h[m.end():]
  with self.assertRaises(ValueError):parse_platts_html(broken,query='मन',url=r['url'],witness_sha256='a'*64)
 def test_merge_deduplicates_same_entry_and_rejects_conflicting_body(self):
  a=parsed('ढलना');self.assertEqual(len(merge_entries(a+a)),1);b=copy.deepcopy(a);b[0]['dictionary']['whole_entry_text']='invented'
  with self.assertRaises(ValueError):merge_entries(a+b)
 def test_cache_hash_guard(self):
  r=ACQ['ढलना'];self.assertEqual(load_cached_witness(ROOT,r),(ROOT/r['path']).read_bytes())
  with self.assertRaises(ValueError):load_cached_witness(ROOT,{**r,'sha256':'0'*64})
class AcquisitionTests(unittest.TestCase):
 def test_valid_cache_reused_without_network(self):
  r=ACQ['ढलना']
  with tempfile.TemporaryDirectory() as tmp:
   root=pathlib.Path(tmp);(root/'witnesses').mkdir();(root/r['path']).write_bytes((ROOT/r['path']).read_bytes());(root/'acquisition.json').write_text(json.dumps([r],ensure_ascii=False))
   def forbidden(*args,**kwargs):raise AssertionError('cache reuse must not access network')
   self.assertEqual(acquire_queries(root,['ढलना'],opener=forbidden),[r])
 def test_corrupt_cache_fails_before_network(self):
  r=ACQ['ढलना']
  with tempfile.TemporaryDirectory() as tmp:
   root=pathlib.Path(tmp);(root/'witnesses').mkdir();(root/r['path']).write_bytes(b'corrupt');(root/'acquisition.json').write_text(json.dumps([r],ensure_ascii=False))
   def forbidden(*args,**kwargs):raise AssertionError('corrupt cache must not silently refresh')
   with self.assertRaises(ValueError):acquire_queries(root,['ढलना'],opener=forbidden)
 def test_wrong_query_mode_cache_cannot_be_reused(self):
  r=copy.deepcopy(ACQ['ढलना']);r['url']=r['url'].replace('matchtype=exact','matchtype=containing')
  with tempfile.TemporaryDirectory() as tmp:
   root=pathlib.Path(tmp);(root/'witnesses').mkdir();(root/r['path']).write_bytes((ROOT/r['path']).read_bytes());(root/'acquisition.json').write_text(json.dumps([r],ensure_ascii=False))
   def forbidden(*args,**kwargs):raise AssertionError('wrong-mode cache must not silently refresh')
   with self.assertRaises(ValueError):acquire_queries(root,['ढलना'],opener=forbidden)
 def test_network_error_remains_error_not_empty_entry(self):
  with tempfile.TemporaryDirectory() as tmp:
   def failed(*args,**kwargs):raise TimeoutError('offline')
   rows=acquire_queries(pathlib.Path(tmp),['ढलना'],opener=failed)
   self.assertEqual(len(rows),1);self.assertIn('offline',rows[0]['error']);self.assertNotIn('sha256',rows[0]);self.assertEqual(rows[0]['status'],'fetch_error')
class CSLTests(unittest.TestCase):
 def fixture(self):return {'name':'mw','source':'https://raw.githubusercontent.com/sanskrit-lexicon/csl-json/main/ashtadhyayi.com/mw.json','data':{'words':{'अ':'1,2','अकार':'3'},'text':{'1':['1. अ the first letter of the alphabet ','1,1','1'],'2':[' the first short vowel inherent in consonants. ','1,1','1.1'],'3':['अ—कार m. the letter or sound अ. ','1,1','2']}}}
 def test_source_fragments_keep_parent_context_and_loci(self):
  rs=import_csl_json(self.fixture(),dictionary_code='mw',edition='1899',witness_sha256='a'*64);self.assertEqual(len(rs),2)
  a=next(x for x in rs if x['source_spellings']==['अ']);self.assertEqual(a['language'],'sa');self.assertEqual(a['roman_search_aliases'],[]);self.assertIn('first short vowel',a['dictionary']['whole_entry_text']);self.assertEqual(len(a['senses']),2);self.assertEqual(a['senses'][1]['source_fragment_id'],'1.1');self.assertTrue(all(s['granularity']=='source_fragment' for s in a['senses']))
 def test_missing_join_and_duplicate_l_fail(self):
  x=self.fixture();x['data']['words']['अ']='999'
  with self.assertRaises(ValueError):import_csl_json(x,dictionary_code='mw',edition='1899',witness_sha256='a'*64)
  x=self.fixture();x['data']['text']['2'][2]='1'
  with self.assertRaises(ValueError):import_csl_json(x,dictionary_code='mw',edition='1899',witness_sha256='a'*64)
 def test_real_empty_source_fragment_requires_explicit_gap_report(self):
  x=self.fixture();x['data']['text']['3922']=['','16,1','3294'];x['data']['words']['अतिसृज्य']='3922'
  with self.assertRaises(ValueError):import_csl_json(x,dictionary_code='mw',edition='1899',witness_sha256='a'*64)
  gaps=[];rs=import_csl_json(x,dictionary_code='mw',edition='1899',witness_sha256='a'*64,rejected_records=gaps)
  self.assertEqual(len(rs),2);self.assertEqual(len(gaps),1);self.assertEqual(gaps[0]['source_fragment_id'],'3294');self.assertEqual(gaps[0]['source_row_id'],'3922');self.assertEqual(gaps[0]['print_locus'],'16,1');self.assertEqual(gaps[0]['witness_sha256'],'a'*64)
  self.assertFalse(any('अतिसृज्य' in r['source_spellings'] for r in rs))
 def test_filter_does_not_invent_or_cross_language(self):
  rs=import_csl_json(self.fixture(),dictionary_code='mw',edition='1899',witness_sha256='a'*64,forms={'अकार'});self.assertEqual(len(rs),1);self.assertEqual(rs[0]['source_spellings'],['अकार']);self.assertEqual(rs[0]['language'],'sa')
if __name__=='__main__':unittest.main()

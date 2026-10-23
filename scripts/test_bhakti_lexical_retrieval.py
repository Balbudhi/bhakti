"""Synthetic vectors prove mechanics only; no semantic/API-quality claim."""
import copy,json,math,tempfile,time,unittest,threading,concurrent.futures,os
from pathlib import Path
from unittest.mock import patch
import bhakti_lexical_retrieval as retrieval
import bhakti_embedding_client as client
import bhakti_translation_policy as policy
import retranslate_bhakti as retranslate

def fixture():
 return {'entries':[{'entry_id':'hi.man','language':'hi','register':'classical','lemma':'man','source_spellings':['मन'],'roman_search_aliases':['man'],
  'dictionary':{'work':'Fixture dictionary','url':'https://example.invalid/man','print_page':1,'entry_locator':'man','whole_entry_text':'mind; weight','witness_sha256':'a'*64},
  'senses':[{'sense_id':'mind','short_english':'mind','dictionary_anchor':'mind','context_hints':[],'prohibitions':[]},{'sense_id':'weight','short_english':'weight','dictionary_anchor':'weight','context_hints':[],'prohibitions':[]}]}]}

def vec(axis):
 values=[0.0]*768;values[axis]=2.0;return values

class SyntheticEncoder:
 def __init__(self):self.calls=[]
 def embed(self,texts):
  self.calls.append(list(texts));return [vec(1 if 'weighing' in t or '"sense_id":"weight"' in t else 0) for t in texts]

class RetrievalTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)/'index.sqlite';self.lex=fixture()
 def test_language_register_diacritics_and_whole_tokens_gate_before_ranking(self):
  line={'id':'x','roman':'man mān manas','source_text':'मन मान मनस'}
  rows=retrieval.token_candidates([line],['Hindi'],self.lex)['x']
  self.assertEqual([len(x['candidates']) for x in rows],[1,0,0])
  self.assertEqual(len(retrieval.token_candidates([{**line,'sourceLanguage':'pa'}],['Hindi'],self.lex)['x'][0]['candidates']),0)
  self.assertEqual(len(retrieval.token_candidates([line],['Hindi','Punjabi'],self.lex)['x'][0]['candidates']),0)
  self.assertEqual(len(retrieval.token_candidates([{**line,'lexicalRegister':'modern'}],['Hindi'],self.lex)['x'][0]['candidates']),0)
 def test_only_explicit_reviewed_lemma_link_adds_inflected_surface(self):
  e=self.lex['entries'][0];e['lemma_links']=[{'source_form':'मनां','roman_form':'manāṃ','language':'hi','reason':'Reviewed fixture inflection','evidence':'fixture:1'}]
  rows=retrieval.token_candidates([{'id':'x','roman':'manāṃ manaṃ','source_text':'मनां मनं'}],['Hindi'],self.lex)['x']
  self.assertEqual([len(x['candidates']) for x in rows],[1,0]);self.assertEqual(rows[0]['lemma_evidence'][0]['roman_form'],'manāṃ')
  e['lemma_links'][0]['language']='pa'
  with self.assertRaises(ValueError):retrieval.token_candidates([{'id':'x','roman':'manāṃ'}],['Hindi'],self.lex)
 def test_native_lookup_does_not_invent_a_roman_token_binding(self):
  self.assertEqual(len(retrieval.exact_entries('मन','hi',self.lex)),1)
  self.assertEqual(retrieval.token_candidates([{'id':'x','source_text':'मन','roman':'unknown'}],['Hindi'],self.lex)['x'][0]['candidates'],[])
 def test_sqlite_persistence_context_ranking_all_alternatives_and_citation(self):
  idx=retrieval.LexicalIndex(self.path);idx.build(self.lex);enc=SyntheticEncoder();idx.embed_documents(enc,self.lex['entries'])
  result=idx.rank(self.lex['entries'],'weighing grain',enc)
  self.assertEqual([r['sense_id'] for r in result],['weight','mind']);self.assertEqual(len(result),2)
  self.assertEqual(result[0]['dictionary'],self.lex['entries'][0]['dictionary']);self.assertNotIn('chosen',result[0])
  calls=len(enc.calls);reopened=retrieval.LexicalIndex(self.path);self.assertEqual(reopened.rank(self.lex['entries'],'weighing grain'),result)
  self.assertEqual(len(enc.calls),calls)
  self.assertTrue(all(row['status']=='query_not_cached' for row in reopened.rank(self.lex['entries'],'a different context')))
  other=reopened.rank(self.lex['entries'],'mind contemplates',enc);self.assertEqual(other[0]['sense_id'],'mind')
 def test_entry_context_change_invalidates_document_and_space_cannot_mix(self):
  idx=retrieval.LexicalIndex(self.path);idx.build(self.lex);enc=SyntheticEncoder();idx.embed_documents(enc,self.lex['entries'])
  changed=copy.deepcopy(self.lex);changed['entries'][0]['senses'][0]['prohibitions']=['Do not confuse weight.']
  with self.assertRaises(RuntimeError):idx.rank(changed['entries'],'weighing grain',enc)
  idx.build(changed);before=sum(map(len,enc.calls));idx.embed_documents(enc,changed['entries'])
  self.assertGreater(sum(map(len,enc.calls)),before)
  with self.assertRaises(ValueError):retrieval.LexicalIndex(self.path,space={**retrieval.DEFAULT_SPACE,'dimensions':1536})
 def test_invalid_rebuild_does_not_replace_usable_index(self):
  idx=retrieval.LexicalIndex(self.path);idx.build(self.lex);enc=SyntheticEncoder();idx.embed_documents(enc,self.lex['entries']);expected=idx.rank(self.lex['entries'],'weighing grain',enc)
  bad=copy.deepcopy(self.lex);bad['entries'].append(copy.deepcopy(bad['entries'][0]))
  with self.assertRaises(ValueError):idx.build(bad)
  self.assertEqual(idx.rank(self.lex['entries'],'weighing grain'),expected)
 def test_overlong_source_is_retained_as_unembedded_candidate_not_truncated(self):
  self.lex['entries'][0]['senses'][0]['short_english']='word '*700
  idx=retrieval.LexicalIndex(self.path);idx.build(self.lex);enc=SyntheticEncoder();report=idx.embed_documents(enc,self.lex['entries'])
  self.assertEqual(len(report['size_holds']),1)
  result=idx.rank(self.lex['entries'],'weighing grain',enc)
  held=next(x for x in result if x['sense_id']=='mind');self.assertEqual(held['status'],'input_too_long');self.assertIsNone(held['score'])
  self.assertEqual(held['sense']['short_english'],'word '*700)
 def test_policy_routes_ranked_evidence_without_selecting_or_weakening_decision_contract(self):
  idx=retrieval.LexicalIndex(self.path);idx.build(self.lex);enc=SyntheticEncoder();idx.embed_documents(enc,self.lex['entries'])
  line={'id':'x','roman':'man','source_text':'मन','sourceLanguage':'hi'}
  with patch.object(policy,'policy_payload',return_value={'lexicon':self.lex}),patch.dict('os.environ',{'BHAKTI_LEXICAL_INDEX':str(self.path)}),patch.object(retrieval,'configured_encoder',return_value=enc):
   text=policy.guidance([line],['Hindi']);self.assertIn('CONTEXTUAL SENSE RANKING',text);self.assertIn('weight',text);self.assertIn('mind',text)
   self.assertEqual(len(policy.token_candidates([line],['Hindi'])['x'][0]['candidates'][0]['senses']),2)
   decision={'word_index':0,'roman':'man','evidence_status':'dictionary_supported','chosen':[{'entry_id':'hi.man','sense_id':'mind'}],'rejected':[],'contextual_reason':'context','grammatical_role':'noun'}
   self.assertTrue(policy.sense_decision_errors([line],[{'id':'x','sense_decisions':[decision]}],['Hindi']))

 def test_unused_entries_cause_no_embedding_calls_during_lazy_query(self):
  unused=copy.deepcopy(self.lex['entries'][0]);unused['entry_id']='hi.unused';unused['lemma']='unused';unused['roman_search_aliases']=['unused'];unused['source_spellings']=['अप्रयुक्त']
  self.lex['entries'].append(unused);idx=retrieval.LexicalIndex(self.path);idx.build(self.lex);enc=SyntheticEncoder()
  idx.rank([self.lex['entries'][0]],'weighing grain',enc)
  self.assertEqual(sum(map(len,enc.calls)),3)
  self.assertFalse(any('unused' in text for batch in enc.calls for text in batch))
 def test_actual_performed_context_changes_query_and_batch_order_is_not_context(self):
  line={'id':'x','roman':'man','source_text':'मन'}
  before={'id':'a','roman':'tol','source_text':'तोल'};after={'id':'b','roman':'soch','source_text':'सोच'}
  first={**line,'performed_context':[{'before':[before],'after':[]}]};second={**line,'performed_context':[{'before':[after],'after':[]}]}
  self.assertNotEqual(retrieval.query_context(first,'man',['Hindi']),retrieval.query_context(second,'man',['Hindi']))
  explicit=retrieval.query_context(line,'man',['Hindi'],context_lines=[line,after,before],performance_order=[{'ref':'a'},{'ref':'x'},{'ref':'b'}])
  self.assertEqual(json.loads(explicit)['performed_context'][0]['before'][0]['id'],'a')
  self.assertEqual(json.loads(retrieval.query_context(line,'man',['Hindi'],context_lines=[before,line,after]))['performed_context'],[])
 def test_native_binding_requires_existing_unambiguous_source_map(self):
  line={'id':'x','source_text':'मन','roman':'mana','sourceLanguage':'hi','sourceWords':[{'text':'मन','wordIndices':[0]}]}
  self.assertEqual(len(retrieval.token_candidates([line],[],self.lex)['x'][0]['candidates']),1)
  line['sourceWords'][0]['wordIndices']=[1]
  with self.assertRaises(ValueError):retrieval.token_candidates([line],[],self.lex)

 def test_actual_compound_subdivisions_preserve_reader_word_indices(self):
  line=json.loads((Path(__file__).parent/'fixtures/vishnu_invocation_3.json').read_text())
  expected=[word['roman'] for word in line['words']]
  self.assertIn('pautramakalmaṣam',line['roman']);self.assertIn('pautram',expected);self.assertIn('akalmaṣam',expected)
  reader={'SONG_LINES':{'invocation-3':line},'SONG_SEQUENCE':[{'ref':'invocation-3','section':'invocation'}]}
  adapted=retranslate.source_lines(reader)[0]
  self.assertEqual(adapted['lexical_tokens'],expected);self.assertNotIn('words',adapted)
  self.assertEqual(adapted['sourceWords'],line['sourceWords'])
  rows=retrieval.token_candidates([adapted],['Sanskrit'],{'entries':[]})['invocation-3']
  self.assertEqual([(row['word_index'],row['roman']) for row in rows],list(enumerate(expected)))
  for bad in [expected[:-1],list(reversed(expected)),expected+['invented']]:
   with self.subTest(tokens=bad),self.assertRaises(ValueError):retrieval.word_tokens({**adapted,'lexical_tokens':bad})
 def test_validated_split_token_alias_enters_indexed_subset_without_native_guess(self):
  line={'id':'x','roman':'manas','source_text':'मनस्','lexical_tokens':['man','as'],'sourceWords':[{'text':'मनस्','wordIndices':[0,1]}]}
  idx=retrieval.LexicalIndex(self.path);idx.build(self.lex);subset=idx.lexicon_for([line],['Hindi'])
  rows=retrieval.token_candidates([line],['Hindi'],subset)['x']
  self.assertEqual([len(w['candidates']) for w in rows],[1,0]);self.assertEqual(rows[0]['roman'],'man')
 def test_actual_existing_reader_adapter_retains_reviewed_native_map_and_language(self):
  line={'source':'मन','roman':'man','sourceLanguage':'hi','words':[{'roman':'man','gloss':'mind'}],'sourceWords':[{'text':'मन','wordIndices':[0]}]}
  reader={'SONG_LINES':{'x':line},'SONG_SEQUENCE':[{'ref':'x','section':'verse'}]}
  actual=retranslate.source_lines(reader)[0]
  self.assertEqual(actual['sourceWords'],line['sourceWords']);self.assertEqual(actual['sourceLanguage'],'hi')
  self.assertEqual(len(retrieval.token_candidates([actual],[],self.lex)['x'][0]['candidates']),1)

 def test_private_corpus_path_is_hashed_into_policy_configuration(self):
  corpus=Path(self.temp.name)/'private.json';corpus.write_text(json.dumps(self.lex))
  with patch.dict(os.environ,{'BHAKTI_LEXICON_PATH':str(corpus)}):
   first=policy.policy_payload();self.assertEqual(first['lexicon'],self.lex)
   changed=copy.deepcopy(self.lex);changed['entries'][0]['senses'][0]['short_english']='changed attested context';corpus.write_text(json.dumps(changed))
   self.assertNotEqual(retrieval.digest(first),retrieval.digest(policy.policy_payload()))
 def test_indexed_subset_matches_exact_native_lemma_language_and_register_rules(self):
  e=self.lex['entries'][0];e['lemma_links']=[{'source_form':'मनां','roman_form':'manāṃ','language':'hi','reason':'reviewed fixture','evidence':'fixture:1'}]
  unused=copy.deepcopy(e);unused['entry_id']='sa.man';unused['language']='sa';unused['lemma_links']=[];self.lex['entries'].append(unused)
  for n in range(30):
   other=copy.deepcopy(e);other.update(entry_id=f'hi.unused{n}',source_spellings=[f'अप्रयुक्त{n}'],roman_search_aliases=[f'unused{n}'],lemma_links=[]);self.lex['entries'].append(other)
  idx=retrieval.LexicalIndex(self.path);idx.build(self.lex)
  lines=[{'id':'native','source_text':'मन','roman':'mana','sourceWords':[{'text':'मन','wordIndices':[0]}]}, {'id':'lemma','source_text':'मनां','roman':'manāṃ'}, {'id':'accent','source_text':'मान','roman':'mān'}, {'id':'register','roman':'man','lexicalRegister':'modern'}, {'id':'other-language','roman':'man','sourceLanguage':'pa'}, {'id':'compound','source_text':'मन','roman':'mana hi','sourceWords':[{'text':'मन','wordIndices':[0,1]}]}]
  subset=idx.lexicon_for(lines,['Hindi'])
  self.assertEqual([e['entry_id'] for e in subset['entries']],['hi.man'])
  actual=retrieval.token_candidates(lines,['Hindi'],subset);self.assertEqual(actual,retrieval.token_candidates(lines,['Hindi'],self.lex))
  self.assertEqual([len(actual[k][0]['candidates']) for k in ['native','lemma','accent','register','other-language','compound']],[1,1,0,0,0,0])
 def test_indexed_guidance_never_loads_full_corpus_and_fingerprint_is_metadata_only(self):
  corpus=Path(self.temp.name)/'private.json';corpus.write_text(json.dumps(self.lex));idx=retrieval.LexicalIndex(self.path);idx.build_file(corpus)
  line={'id':'x','source_text':'मन','roman':'man','sourceLanguage':'hi'}
  original=Path.read_text
  def guarded(path,*args,**kwargs):
   if path.resolve()==corpus.resolve():raise AssertionError('full corpus read in runtime')
   return original(path,*args,**kwargs)
  with patch.dict(os.environ,{'BHAKTI_LEXICON_PATH':str(corpus),'BHAKTI_LEXICAL_INDEX':str(self.path)},clear=True),patch.object(Path,'read_text',guarded):
   payload=policy.policy_payload();self.assertNotIn('lexicon',payload);self.assertEqual(payload['retrieval']['lexicon_hash'],retrieval.digest(self.lex))
   self.assertEqual(policy.token_candidates([line],['Hindi']),retrieval.token_candidates([line],['Hindi'],self.lex))
   guidance=policy.guidance([line],['Hindi']);self.assertIn('hi.man',guidance);self.assertIn('query_not_cached',guidance)
 def test_indexed_config_rejects_changed_corpus_accepts_unchanged_bytes_and_retains_vectors(self):
  corpus=Path(self.temp.name)/'private.json';corpus.write_text(json.dumps(self.lex));idx=retrieval.LexicalIndex(self.path);idx.build_file(corpus)
  idx.rank(self.lex['entries'],'weighing grain',SyntheticEncoder());vector_count=idx.db.execute('SELECT count(*) FROM vectors').fetchone()[0]
  with patch.dict(os.environ,{'BHAKTI_LEXICON_PATH':str(corpus),'BHAKTI_LEXICAL_INDEX':str(self.path)},clear=True):
   os.utime(corpus,None);policy.policy_payload()
   self.assertEqual(idx.db.execute('SELECT count(*) FROM vectors').fetchone()[0],vector_count)
   changed=copy.deepcopy(self.lex);changed['entries'][0]['senses'][0]['short_english']='heart';corpus.write_text(json.dumps(changed))
   with self.assertRaisesRegex(RuntimeError,'corpus'):policy.policy_payload()
 def test_concurrent_index_cache_misses_embed_each_document_query_once(self):
  retrieval.LexicalIndex(self.path).build(self.lex);entered=threading.Event();release=threading.Event();duplicate=threading.Event()
  class BlockingEncoder(SyntheticEncoder):
   def embed(self,texts):
    if '"sense_id"' in texts[0]:
     if entered.is_set():duplicate.set()
     entered.set();release.wait(2)
    return super().embed(texts)
  enc=BlockingEncoder()
  def rank(_):
   with retrieval.LexicalIndex(self.path) as idx:return idx.rank(self.lex['entries'],'weighing grain',enc)
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
   first=pool.submit(rank,0);self.assertTrue(entered.wait(1));second=pool.submit(rank,1)
   overlapped=duplicate.wait(.2);release.set();results=[first.result(),second.result()]
  self.assertFalse(overlapped);self.assertEqual(results[0],results[1]);self.assertEqual(sum(map(len,enc.calls)),3)

class TransportTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.sent=[]
 def transport(self,payload,response_path,timeout):
  self.sent.append(payload);raw={'model':client.MODEL,'data':[{'index':i,'embedding':vec(i%2)} for i in reversed(range(len(payload['input'])))],'usage':{'prompt_tokens':12}}
  response_path.write_text(json.dumps(raw));return raw
 def make(self,**kw):return client.EmbeddingClient(self.root/kw.pop('ledger_name','ledger.json'),budget_usd=kw.pop('budget_usd',.05),max_calls=kw.pop('max_calls',2),deadline_at=kw.pop('deadline_at',time.time()+60),transport=kw.pop('transport',self.transport),**kw)
 def test_real_payload_and_out_of_order_response_indices(self):
  out=self.make().embed(['mind','weighing']);self.assertEqual(out,[vec(0),vec(1)])
  p=self.sent[0];self.assertEqual(p['model'],client.MODEL);self.assertEqual(p['dimensions'],768);self.assertEqual(p['encoding_format'],'float');self.assertNotIn('input_type',p)
  self.assertNotIn('Authorization',json.dumps(p))
 def test_bad_cardinality_duplicate_indices_model_dimensions_nonfinite_zero_reject(self):
  valid={'model':client.MODEL,'data':[{'index':0,'embedding':vec(0)}]}
  bad=[]
  for field,value in [('model','other')]:x=copy.deepcopy(valid);x[field]=value;bad.append(x)
  x=copy.deepcopy(valid);x['data']=[];bad.append(x)
  x=copy.deepcopy(valid);x['data']*=2;bad.append(x)
  for v in [[1.0],[0.0]*768,[float('nan')]+[0.0]*767,[True]+[0.0]*767]:x=copy.deepcopy(valid);x['data'][0]['embedding']=v;bad.append(x)
  for packet in bad:
   with self.subTest(packet=str(packet)[:80]),self.assertRaises(ValueError):client.validate_response(packet,1,768)
 def test_actual_google_vertex_response_alias_is_exact_and_other_models_reject(self):
  actual=json.loads((Path(__file__).parent/'fixtures/embedding_google_vertex_response.json').read_text())
  self.assertEqual(actual['model'],'gemini-embedding-001');self.assertEqual(actual['provider'],'Google')
  self.assertEqual(len(client.validate_response(actual,2,768)),2)
  for alias in ['other/gemini-embedding-001','gemini-embedding-002','text-embedding-001']:
   with self.subTest(alias=alias),self.assertRaises(ValueError):client.validate_response({**actual,'model':alias},2,768)
 def test_known_reported_cost_survives_invalid_vector_response(self):
  def malformed(payload,path,timeout):
   raw={'model':client.MODEL,'data':[],'usage':{'cost':.00001}};path.write_text(json.dumps(raw));return raw
  with self.assertRaises(RuntimeError):self.make(transport=malformed).embed(['mind'])
  ledger=json.loads((self.root/'ledger.json').read_text());self.assertTrue(ledger['blocked'])
  self.assertEqual(ledger['requests'][0]['reported_cost_usd'],.00001);self.assertGreater(ledger['requests'][0]['reservation_usd'],0)
 def test_budget_deadline_count_and_size_reject_before_dispatch(self):
  with self.assertRaises(RuntimeError):self.make(budget_usd=.00000001,ledger_name='budget.json').embed(['mind'])
  self.assertEqual(self.sent,[])
  with self.assertRaises(RuntimeError):self.make(deadline_at=time.time()-1,ledger_name='expired.json').embed(['mind'])
  self.assertEqual(self.sent,[])
  for value in ['', 'x'*2049]:
   with self.assertRaises(ValueError):self.make().embed([value])
  self.assertEqual(self.sent,[])
 def test_error_retains_reservation_and_blocks_resume_without_retry(self):
  def fail(payload,path,timeout):self.sent.append(payload);raise TimeoutError('unknown outcome')
  cli=self.make(transport=fail)
  with self.assertRaises(RuntimeError):cli.embed(['mind'])
  with self.assertRaises(RuntimeError):self.make().embed(['mind'])
  self.assertEqual(len(self.sent),1);ledger=json.loads((self.root/'ledger.json').read_text());self.assertTrue(ledger['blocked']);self.assertGreater(ledger['requests'][0]['reservation_usd'],0)
 def test_embedding_allowance_is_independent_of_chat_environment(self):
  with patch.dict(os.environ,{'BHAKTI_API_RUN_MAX_CALLS':'1','BHAKTI_API_MAX_CALLS':'1'}):
   cli=self.make();cli.embed(['one']);cli.embed(['two'])
  self.assertEqual(len(self.sent),2)
 def test_concurrent_failure_serializes_and_blocks_the_waiting_dispatch(self):
  entered=threading.Event();release=threading.Event();second_sent=threading.Event();calls=[]
  def fail(payload,path,timeout):
   calls.append(payload);entered.set()
   if len(calls)>1:second_sent.set()
   release.wait(2);raise TimeoutError('first failed')
  cli=self.make(transport=fail)
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
   first=pool.submit(cli.embed,['first']);self.assertTrue(entered.wait(1));second=pool.submit(cli.embed,['second'])
   overlapped=second_sent.wait(.2);release.set()
   for future in [first,second]:
    with self.assertRaises(RuntimeError):future.result()
  self.assertFalse(overlapped);self.assertEqual(len(calls),1)
 def test_cannot_reuse_a_chat_model_spending_ledger(self):
  (self.root/'ledger.json').write_text(json.dumps({'version':1,'budget_usd':.05,'blocked':False,'requests':[{'model':'google/gemini-3.7-flash','reservation_usd':.01}]}))
  with self.assertRaises(RuntimeError):self.make()
  self.assertEqual(self.sent,[])
 def test_existing_client_observes_durable_deadline_shortening(self):
  first=self.make();self.make(deadline_at=time.time()-1)
  with self.assertRaises(RuntimeError):first.embed(['mind'])
  self.assertEqual(self.sent,[])
 def test_crashed_unfinished_request_holds_resume_without_refunding(self):
  self.make();path=self.root/'ledger.json';state=json.loads(path.read_text())
  state['requests'].append({'id':'interrupted','model':client.MODEL,'status':'dispatched','reservation_usd':.001});path.write_text(json.dumps(state))
  with self.assertRaises(RuntimeError):self.make().embed(['same uncached query'])
  self.assertEqual(self.sent,[]);after=json.loads(path.read_text());self.assertTrue(after['blocked']);self.assertEqual(after['requests'][0]['reservation_usd'],.001)
 def test_existing_client_holds_interrupted_sibling_before_new_reservation(self):
  cli=self.make();path=self.root/'ledger.json';state=json.loads(path.read_text())
  state['requests'].append({'id':'interrupted','model':client.MODEL,'status':'reserved','reservation_usd':.001});path.write_text(json.dumps(state))
  with self.assertRaises(RuntimeError):cli.embed(['same uncached query'])
  self.assertEqual(self.sent,[]);after=json.loads(path.read_text());self.assertTrue(after['blocked']);self.assertEqual(len(after['requests']),1);self.assertEqual(after['requests'][0]['reservation_usd'],.001)
 def test_call_limit_and_persisted_deadline_survive_reopen(self):
  cli=self.make(max_calls=1);cli.embed(['mind'])
  with self.assertRaises(RuntimeError):self.make(max_calls=1).embed(['other'])
  self.assertEqual(len(self.sent),1)
  with self.assertRaises(RuntimeError):self.make(max_calls=9)

if __name__=='__main__':unittest.main()

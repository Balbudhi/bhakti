"""Source-audio selection contract; expected counts come from frozen real readers.

A/B first slice only. No network or implementation stub supplies expected decisions.
"""
import copy,hashlib,importlib.util,json,pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('generic_source_adapter',ROOT/'scripts/bhakti_library_source_pass.py');adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
FIX=ROOT/'tests/fixtures'
def hash_json(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def identity(reader):
 lines={lid:{key:line.get(key) for key in ('source','roman','sourceWords')} for lid,line in reader['SONG_LINES'].items()}
 order=[{'ref':event['ref'],'section':event.get('section','verse')} for event in reader['SONG_SEQUENCE'] for _ in range(event.get('repeats',1))]
 return {'audio_sha256':'a'*64,'trim_sha256':'b'*64,'reader_source_sha256':hash_json({'lines':lines,'order':order})}
class AudioPlanTests(unittest.TestCase):
 def setUp(self):
  self.reader=json.loads((FIX/'kya-tan-majhata-audio-reader.json').read_text());self.duration=230.233991
  self.evidence={'identity':identity(self.reader),'audit_sha256':'c'*64,'coverage_requested':True,'disagreements':[],'timing_required':False}
 def receipt(self):return {'version':1,'status':'accepted','scope':'whole_recording','identity':copy.deepcopy(self.evidence['identity']),'audit_sha256':'c'*64,'source_contract_version':1,'unresolved_disagreements':[],'observed_start':True,'observed_end':True}
 def plan(self,flags=None):return adapter.plan_audio_review(self.reader,source_evidence=self.evidence,flags=flags or {},duration_seconds=self.duration)
 def test_exact_bound_whole_receipt_is_reused_without_units(self):
  self.evidence['coverage_receipt']=self.receipt();result=self.plan();self.assertEqual(result['mode'],'reuse');self.assertEqual(result['units'],[]);self.assertEqual(result['coverage']['status'],'accepted');self.assertEqual(result['remaining_obligations'],[])
 def test_absent_coverage_is_pending_audit_not_claimed_missing_lyrics(self):
  result=self.plan();self.assertEqual(result['mode'],'whole_recording');self.assertEqual(result['coverage']['status'],'pending');self.assertIn('coverage',result['remaining_obligations']);self.assertNotIn('missing-lyrics',json.dumps(result))
 def test_paid_receipt_mismatch_never_claims_reuse(self):
  for key in ['audio_sha256','trim_sha256','reader_source_sha256']:
   with self.subTest(key=key):
    self.evidence['coverage_receipt']=self.receipt();self.evidence['coverage_receipt']['identity'][key]='d'*64;result=self.plan();self.assertEqual(result['mode'],'whole_recording');self.assertEqual(result['coverage']['status'],'pending')
 def test_audit_hash_contract_edge_or_scope_mismatch_invalidates_receipt(self):
  for key,value in [('audit_sha256','e'*64),('source_contract_version',0),('observed_start',False),('observed_end',False),('scope','focused')]:
   with self.subTest(key=key):
    self.evidence['coverage_receipt']=self.receipt();self.evidence['coverage_receipt'][key]=value;self.assertEqual(self.plan()['coverage']['status'],'pending')
 def test_provenance_or_credit_gap_does_not_trigger_retranscription_with_good_coverage(self):
  self.evidence['coverage_receipt']=self.receipt();self.evidence['metadata_gaps']=['writer unknown','no modern semantic frame'];self.reader['SONG_META']['credit']='';self.assertEqual(self.plan()['units'],[])
 def test_focused_disagreement_does_not_certify_unknown_whole_coverage(self):
  self.evidence['disagreements']=[{'id':'kya-pasa-asa','line_ids':['v4-janam-janam-2'],'occurrence_ids':[],'alternatives':[{'source_text':'पासा'},{'source_text':'आसा'}],'reason':'Actual first/audit disagreement','evidence':[{'path':'paid-audit.json','sha256':'f'*64}]}]
  result=self.plan();self.assertEqual(result['mode'],'focused');self.assertEqual(result['coverage']['status'],'pending');self.assertEqual(result['source']['status'],'pending');self.assertIn('coverage',result['remaining_obligations']);self.assertEqual(len(result['units']),1)
  unit=result['units'][0];self.assertEqual(unit['target_occurrence_ids'],['occ-014']);self.assertEqual(unit['hypotheses'],self.evidence['disagreements']);self.assertIn(15,unit['context_occurrence_indices']);self.assertEqual(unit['clip_end'],self.duration)
 def test_good_whole_coverage_does_not_hide_new_flag_or_disagreement(self):
  self.evidence['coverage_receipt']=self.receipt()
  result=self.plan({'audio':True,'line_ids':['v4-janam-janam-2'],'reason':'new source doubt'});self.assertEqual(result['mode'],'focused');self.assertEqual(result['source']['status'],'pending')
  self.evidence['disagreements']=[{'id':'different-hearing','line_ids':['v4-janam-janam-2'],'occurrence_ids':[],'alternatives':[{'source_text':'पासा'},{'source_text':'आसा'}],'reason':'two actual audio witnesses differ','evidence':[{'path':'paid.json','sha256':'f'*64}]}]
  self.assertEqual(self.plan()['mode'],'focused')
 def test_focused_acceptance_advances_coverage_without_clearing_timing(self):
  dispute={'id':'kya-pasa-asa','line_ids':['v4-janam-janam-2'],'occurrence_ids':[],'alternatives':[{'source_text':'पासा'},{'source_text':'आसा'}],'reason':'conflicting actual witnesses','evidence':[{'path':'paid.json','sha256':'f'*64}]}
  self.evidence['disagreements']=[dispute];self.evidence['timing_required']=True;self.assertEqual(self.plan()['mode'],'focused')
  self.evidence['focused_receipts']=[{'version':1,'status':'accepted','source_contract_version':1,'identity':copy.deepcopy(self.evidence['identity']),'before_identity':copy.deepcopy(self.evidence['identity']),'disagreement_sha256':hash_json(dispute),'resolved_disagreement_id':dispute['id'],'source_lineage':[]}]
  next_plan=self.plan();self.assertEqual(next_plan['mode'],'whole_recording');self.assertEqual(next_plan['coverage']['status'],'pending');self.assertEqual(next_plan['source']['status'],'accepted');self.assertEqual(next_plan['timing']['status'],'pending')
  for field,value in [('alternatives',[{'source_text':'एक'}]),('evidence',[{'path':'new-paid.json','sha256':'d'*64}])]:
   changed=copy.deepcopy(dispute);changed[field]=value;self.evidence['disagreements']=[changed]
   with self.subTest(field=field):self.assertEqual(self.plan()['mode'],'focused')
 def test_section_classification_is_bound_to_source_receipt_identity(self):
  self.reader['SONG_SEQUENCE'][0]['section']='spoken'
  with self.assertRaises(ValueError):self.plan()
 def test_invalid_repeats_and_unknown_references_fail_before_draft_expansion(self):
  for invalid in [0,-1,True,'2',1.5]:
   reader=copy.deepcopy(self.reader);reader['SONG_SEQUENCE'][0]['repeats']=invalid
   with self.subTest(repeats=invalid),self.assertRaises(ValueError):adapter.source_draft(reader)
  reader=copy.deepcopy(self.reader);reader['SONG_SEQUENCE'][0]['ref']='missing'
  with self.assertRaises(ValueError):adapter.source_draft(reader)
 def test_source_receipt_never_clears_independent_timing_obligation(self):
  self.evidence['coverage_receipt']=self.receipt();self.evidence['timing_required']=True;result=self.plan();self.assertEqual(result['coverage']['status'],'accepted');self.assertEqual(result['timing']['status'],'pending');self.assertIn('timing',result['remaining_obligations'])
 def test_line_flag_selects_every_existing_return_without_printed_additions(self):
  flags={'audio':True,'reason':'refrain clipped?','line_ids':['refrain-kya-tan']};result=self.plan(flags);target_ids={v for unit in result['units'] for v in unit['target_occurrence_ids']};expected={f'occ-{i:03d}' for i,row in enumerate(self.reader['SONG_SEQUENCE']) if row['ref']=='refrain-kya-tan'};self.assertEqual(target_ids,expected)
  draft=result['expanded_draft'];self.assertEqual(set(row['id'] for row in draft['lines']),set(self.reader['SONG_LINES']))
 def test_occurrence_flag_does_not_select_all_returns(self):
  result=self.plan({'audio':True,'occurrence_ids':['occ-015'],'reason':'final return'});self.assertEqual({v for unit in result['units'] for v in unit['target_occurrence_ids']},{'occ-015'})
 def test_unknown_or_malformed_occurrence_fails_before_dispatch(self):
  for flags in [{'audio':True,'line_ids':['made-up']},{'audio':True,'occurrence_ids':['occ-999']},{'audio':True,'occurrence_ids':['15']}]:
   with self.subTest(flags=flags),self.assertRaises(ValueError):self.plan(flags)
 def test_invalid_routing_intervals_fail_without_guessing(self):
  for timing in [{'start':-1,'end':5},{'start':8,'end':2},{'start':float('nan'),'end':5},{'start':0,'end':self.duration+1}]:
   original=copy.deepcopy(self.reader['SONG_TIMINGS']);self.reader['SONG_TIMINGS'][14]=timing
   with self.subTest(timing=timing),self.assertRaises(ValueError):self.plan({'audio':True,'line_ids':['v4-janam-janam-2']})
   self.reader['SONG_TIMINGS']=original
 def test_human_english_is_not_sent_to_audio_or_used_to_skip_verification(self):
  self.reader['SONG_META']['humanTranslation']='Owner exact positive translation';result=self.plan();self.assertEqual(result['mode'],'whole_recording');draft=json.dumps(result['expanded_draft']);self.assertNotIn('Owner exact',draft);self.assertNotIn('english',draft);self.assertNotIn('gloss',draft)
 def test_stale_supplied_source_identity_rejected(self):
  self.evidence['identity']['reader_source_sha256']='0'*64
  with self.assertRaises(ValueError):self.plan()
 def test_real_harivarasanam_instrumental_cues_remain_blank_and_ordered(self):
  reader=json.loads((FIX/'harivarasanam-audio-reader.json').read_text());draft=adapter.source_draft(reader)
  expected=[row['ref'] for row in reader['SONG_SEQUENCE'] for _ in range(row.get('repeats',1))]
  self.assertEqual([row['line_id'] for row in draft['performance_order']],expected)
  blanks=[row for row in draft['lines'] if row['kind']=='instrumental'];self.assertEqual([row['id'] for row in blanks],['inst-intro','inst-flute-strings-1','inst-flute-2','inst-outro']);self.assertTrue(all(row['source_text']==row['roman']=='' for row in blanks))
  mixed=copy.deepcopy(reader);mixed['SONG_SEQUENCE'].append({'ref':'inst-intro','section':'verse','repeats':1})
  with self.assertRaises(ValueError):adapter.source_draft(mixed,[0])
  reader['SONG_SEQUENCE'][0]['section']='verse'
  with self.assertRaises(ValueError):adapter.source_draft(reader)
 def test_nonmonotonic_context_cannot_silently_exclude_target_audio(self):
  self.reader['SONG_TIMINGS'][13]={'start':220,'end':225}
  # Target14 still starts208.2, so a clip beginning at neighbor220 would miss it.
  with self.assertRaises(ValueError):self.plan({'audio':True,'line_ids':['v4-janam-janam-2'],'reason':'actual disputed source'})
 def test_source_draft_expands_real_kya16_blocks_to25_performances(self):
  draft=adapter.source_draft(self.reader);self.assertEqual(len(self.reader['SONG_SEQUENCE']),16);self.assertEqual(len(draft['performance_order']),25)
  expected=[event['ref'] for event in self.reader['SONG_SEQUENCE'] for _ in range(event.get('repeats',1))];self.assertEqual([row['line_id'] for row in draft['performance_order']],expected);self.assertEqual(len(draft['performance_order'][-2:]),2);self.assertEqual([x['line_id'] for x in draft['performance_order'][-2:]],['refrain-kya-tan']*2)
 def test_sunta_outro_targets_last_actual_block_and_full_recording_end(self):
  self.reader=json.loads((FIX/'sunta-hai-audio-reader.json').read_text());self.duration=255.901;self.evidence['identity']=identity(self.reader)
  result=self.plan({'audio':True,'line_ids':['gagan-mein-aawaz-outro'],'reason':'eleven or twelve audible jhini tokens'});unit=result['units'][0];self.assertEqual(unit['target_occurrence_ids'],['occ-013']);self.assertEqual(unit['clip_end'],255.901);self.assertIn(12,unit['context_occurrence_indices'])
if __name__=='__main__':unittest.main()

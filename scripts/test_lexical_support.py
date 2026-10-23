"""Witnessed lexical support, actual caller/cache and owner-lock regressions.

Run: PYTHONPATH=scripts python3 -m unittest test_lexical_support
Provider fixtures prove delivery and guards, not semantic translation quality.
"""
import argparse, copy, hashlib, json, pathlib, tempfile, unittest
from unittest.mock import patch
import bhakti_lexical_support as support
import bhakti_pipeline as pipeline
from test_sense_decisions import decisions_for

FIX=pathlib.Path(__file__).parent/'fixtures'/'lexical_support'
def sha(b): return hashlib.sha256(b).hexdigest()
def write_json(p,x): p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')

def fixture(root):
    """Reconstitute actual WordNet bytes at original offsets, not fabricated senses."""
    wn=json.loads((FIX/'wordnet-adjective-subset.json').read_text());d=root/'wordnet';d.mkdir()
    (d/'index.adj').write_text(wn['license_header']+''.join(wn['index_rows']))
    with (d/'data.adj').open('wb') as f:
        f.write(wn['license_header'].encode())
        for row in wn['data_rows']: f.seek(row['offset']);f.write(row['raw'].encode())
    write_json(d/'manifest.json',{'edition':'3.1','available_pos':['adj'],'complete_for_lemmas':wn['complete_for_lemmas'],'source':wn['data_source'],'data_sha256':{'adj':sha((d/'data.adj').read_bytes())},'index_sha256':{'adj':sha((d/'index.adj').read_bytes())}})
    text=(FIX/'pati-witness.txt').read_text();(root/'witness.txt').write_text(text)
    evidence={'id':'ks-pati','kind':'traditional_formation','language':'sa','lemma':'pati','work':'Kṣīrasvāmin, Amarakośodghāṭana','locus':'printed p0097, verse35','quotation':text,'witness':{'path':'witness.txt','sha256':sha(text.encode())},'limitations':['Traditional formation; no modern historical claim.']}
    lines=[{'id':'p','source_text':'पति','roman':'pati','sourceLanguage':'sa','kind':'verse'}]
    # Adjectives are authentic English parser/caller evidence, not claimed translations of pati.
    manifest={'version':1,'witnesses':[evidence],'wordnet':{'directory':'wordnet','edition':'3.1','lemmas':['biddable','governable']},'targets':[{'id':'choice-p','line_id':'p','word_indices':[0],'surfaces':['pati'],'source_language':'sa','source_evidence_ids':['ks-pati'],'background_evidence_ids':[],'language_link_evidence_ids':[],'english_candidates':[{'id':'c-governable','expression':'governable','kind':'word','english_lemmas':['governable']},{'id':'c-biddable','expression':'biddable','kind':'word','english_lemmas':['biddable']}]}]}
    write_json(root/'manifest.json',manifest);return manifest,lines,d

class SupportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name)
        self.manifest,self.lines,self.wn=fixture(self.root)
    def build(self):
        write_json(self.root/'manifest.json',self.manifest)
        return support.build_support(self.root/'manifest.json',self.lines,['Sanskrit'])
    def test_actual_wordnet_all_senses_and_exact_definitions(self):
        rows=support.lookup_wordnet(self.wn,['adamantine','biddable','governable'],edition='3.1')
        self.assertEqual(len(rows),5)
        by={r['synset_offset']:r for r in rows}
        self.assertEqual(set(by),{2613736,1154749,1028427,1617155,1478085})
        self.assertEqual(by[1154749]['gloss'],'having the hardness of a diamond')
        self.assertIn('without protest',by[1617155]['gloss'])
        self.assertEqual(by[1478085]['gloss'],'capable of being controlled')
        for row in rows:self.assertEqual(row['edition'],'3.1');self.assertTrue(row['witness_sha256']);self.assertTrue(row['raw'].startswith(f'{row["synset_offset"]:08d}'))
    def test_authentic_syntactic_markers_hex_counts_and_collocations(self):
        rows=json.loads((FIX/'wordnet-parser-extra.json').read_text())
        words,gloss=support.parse_wordnet_row(rows[0]['raw'],19769,'a')
        self.assertEqual(words,['handy','ready to hand']);self.assertIn('easy to reach',gloss)
        words,gloss=support.parse_wordnet_row(rows[1]['raw'],280484,'a')
        self.assertEqual(len(words),10);self.assertEqual(words[0],'aglitter');self.assertEqual(words[-1],'sparkly')
        self.assertIn("archaic term",gloss)
        with self.assertRaises(ValueError):support.parse_wordnet_row(rows[1]['raw'].replace(' 0a aglitter',' 09 aglitter'),280484,'a')

    def test_compositional_phrase_and_compound_do_not_need_invented_whole_entry(self):
        # Constructed structural control, not an accepted public song translation.
        lines=[{'id':'x','source_text':'अखण्ड ज्योति','roman':'akhaṇḍa jyoti','sourceLanguage':'sa'}]
        for expression,kind in [('unbroken light','compositional_phrase'),('unbroken-light','transparent_compound')]:
            packet={'version':1,'evidence':[],'targets':[{'id':'x-choice','line_id':'x','word_indices':[0,1],'surfaces':['akhaṇḍa','jyoti'],'source_language':'sa','source_evidence_ids':[],'background_evidence_ids':[],'language_link_evidence_ids':[],'english_candidates':[{'id':'c','expression':expression,'kind':kind,'english_evidence_ids':[]}]}]}
            support.validate_support(packet,lines,['Sanskrit'])
            gloss=[{'id':'x','support_decisions':[{'target_id':'x-choice','used_evidence_ids':[],'role':'operative_meaning','reason':'Contextual reading; no dictionary claim.'}]}]
            draft=[{'id':'x','literal_english':expression,'segments':[{'text':expression,'word_indices':[0,1]}],'wording_decisions':[{'target_id':'x-choice','chosen_candidate_id':'c','expression':expression,'kind':kind,'english_evidence_ids':[],'word_indices':[0,1],'ordinary_paraphrase':'light that is not broken','component_word_indices':[[0],[1]],'reason':'Preserves both source members; linguistic review still required.'}]}]
            self.assertEqual(support.support_decision_errors(packet,gloss,draft),[])
            draft[0]['wording_decisions'][0]['component_word_indices']=[[0],[2]]
            self.assertTrue(support.support_decision_errors(packet,gloss,draft))

    def test_duplicate_lemma_queries_do_not_duplicate_evidence(self):
        one=support.lookup_wordnet(self.wn,['affectionate','fond'],edition='3.1')
        two=support.lookup_wordnet(self.wn,['affectionate','fond','fond'],edition='3.1')
        self.assertEqual(one,two);self.assertEqual(len(one),4)
    def test_incomplete_subset_is_not_a_certified_dictionary_miss(self):
        with self.assertRaisesRegex(ValueError,'coverage|subset|available|complete'):
            support.lookup_wordnet(self.wn,['unacquired_word'],edition='3.1')
    def test_tampered_wordnet_data_fails_before_lookup(self):
        with (self.wn/'data.adj').open('r+b') as f:f.seek(1617155);f.write(b'99999999')
        with self.assertRaises(ValueError):support.lookup_wordnet(self.wn,['biddable'],edition='3.1')
    def test_build_produces_real_evidence_and_preserves_source(self):
        original=copy.deepcopy(self.lines);packet=self.build();support.validate_support(packet,self.lines,['Sanskrit'])
        by={e['id']:e for e in packet['evidence']};self.assertIn('ks-pati',by)
        self.assertEqual(by['ks-pati']['quotation'],(FIX/'pati-witness.txt').read_text());self.assertEqual(self.lines,original)
        self.assertEqual(len([e for e in by.values() if e['kind']=='english_definition']),2)
        self.assertIn('Traditional formation',by['ks-pati']['limitations'][0])
    def test_actual_builder_cli_loads_witnesses_and_emits_same_packet(self):
        import subprocess,sys
        write_json(self.root/'lines.json',self.lines)
        result=subprocess.run([sys.executable,'-m','bhakti_lexical_support','build','--manifest',str(self.root/'manifest.json'),'--lines',str(self.root/'lines.json'),'--languages','Sanskrit','--output',str(self.root/'support.json')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads((self.root/'support.json').read_text()),self.build())

    def test_capitalized_english_queries_attach_canonical_lookup_evidence(self):
        self.manifest['wordnet']['lemmas']=['Governable']
        self.manifest['targets'][0]['english_candidates']=[{'id':'c','expression':'Governable','kind':'word','english_lemmas':['Governable']}]
        packet=self.build()
        self.assertEqual(packet['targets'][0]['english_candidates'][0]['english_lemmas'],['governable'])
        self.assertEqual(packet['english_lookup']['lemmas'],['governable'])
        self.assertEqual(len(packet['targets'][0]['english_candidates'][0]['english_evidence_ids']),1)

    def test_chosen_word_definition_must_attest_that_word(self):
        self.manifest['targets'][0]['english_candidates'][0]['english_lemmas']=['governable','biddable']
        packet=self.build()
        wrong=next(e['id'] for e in packet['evidence'] if e['kind']=='english_definition' and 'biddable' in e['lemmas'])
        right=next(e['id'] for e in packet['evidence'] if e['kind']=='english_definition' and 'governable' in e['lemmas'])
        g=[{'id':'p','support_decisions':[{'target_id':'choice-p','used_evidence_ids':[],'role':'background_only','reason':'Transport control.'}]}]
        d=[{'id':'p','literal_english':'governable','segments':[{'text':'governable','word_indices':[0]}],'wording_decisions':[{'target_id':'choice-p','chosen_candidate_id':'c-governable','expression':'governable','kind':'word','english_evidence_ids':[wrong],'word_indices':[0],'reason':'Transport control.'}]}]
        self.assertTrue(support.support_decision_errors(packet,g,d))
        d[0]['wording_decisions'][0]['english_evidence_ids']=[right]
        self.assertEqual(support.support_decision_errors(packet,g,d),[])

    def test_modified_quote_hash_and_path_escape_fail(self):
        original=copy.deepcopy(self.manifest)
        for kind in ('quote','hash','escape'):
            with self.subTest(kind=kind):
                self.manifest=copy.deepcopy(original);e=self.manifest['witnesses'][0]
                if kind=='quote':e['quotation']='Not in this witness'
                elif kind=='hash':e['witness']['sha256']='0'*64
                else:e['witness']['path']='../witness.txt'
                with self.assertRaises(ValueError):self.build()
    def test_loaded_packet_cannot_drop_an_english_sense_from_its_complete_lookup(self):
        self.manifest['wordnet']['lemmas']=['adamantine']
        self.manifest['targets'][0]['english_candidates']=[{'id':'c-adamantine','expression':'adamantine','kind':'word','english_lemmas':['adamantine']}]
        packet=self.build();candidate=packet['targets'][0]['english_candidates'][0]
        self.assertEqual(len(candidate['english_evidence_ids']),3)
        missing=candidate['english_evidence_ids'].pop()
        packet['evidence']=[e for e in packet['evidence'] if e['id']!=missing]
        with self.assertRaisesRegex(ValueError,'population|complete|lookup'):
            support.validate_support(packet,self.lines,['Sanskrit'])

    def test_source_binding_rejects_wrong_index_surface_or_language(self):
        for key,value in [('word_indices',[1]),('surfaces',['pāta']),('source_language','hi')]:
            old=copy.deepcopy(self.manifest);self.manifest['targets'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.build()
            self.manifest=old
    def test_cross_language_only_background_without_relationship(self):
        self.lines[0]['sourceLanguage']='hi';target=self.manifest['targets'][0];target['source_language']='hi'
        write_json(self.root/'manifest.json',self.manifest)
        with self.assertRaisesRegex(ValueError,'language|relationship|background'):
            support.build_support(self.root/'manifest.json',self.lines,['Hindi'])
        target['background_evidence_ids']=target.pop('source_evidence_ids');target['source_evidence_ids']=[]
        write_json(self.root/'manifest.json',self.manifest)
        packet=support.build_support(self.root/'manifest.json',self.lines,['Hindi'])
        self.assertEqual(packet['targets'][0]['source_evidence_ids'],[])
        self.assertEqual(packet['targets'][0]['background_evidence_ids'],['ks-pati'])
    def test_projection_is_targeted_and_lossless_without_mutation(self):
        packet=self.build();saved=copy.deepcopy(packet)
        chosen=support.project_support(packet,['p']);self.assertEqual(chosen,packet)
        self.assertIsNone(support.project_support(packet,['other']));self.assertEqual(packet,saved)
        self.assertIsNone(support.project_support(None,['p']))
    def test_wording_choice_must_map_to_actual_english_segment_indices(self):
        packet=self.build();target=packet['targets'][0];candidate=target['english_candidates'][0]
        g=[{'id':'p','support_decisions':[{'target_id':'choice-p','used_evidence_ids':[],'role':'background_only','reason':'Control.'}]}]
        d=[{'id':'p','literal_english':'governable','segments':[{'text':'governable','word_indices':[0]}],'wording_decisions':[{'target_id':'choice-p','chosen_candidate_id':candidate['id'],'expression':'governable','kind':'word','english_evidence_ids':candidate['english_evidence_ids'],'word_indices':[0],'reason':'Control.'}]}]
        self.assertEqual(support.support_decision_errors(packet,g,d),[])
        d[0]['segments'][0]['word_indices']=[1]
        self.assertTrue(support.support_decision_errors(packet,g,d))

    def test_invented_evidence_and_missing_target_decision_fail(self):
        packet=self.build();gloss=[{'id':'p','support_decisions':[{'target_id':'choice-p','used_evidence_ids':['ks-pati'],'role':'operative_meaning','reason':'Fixture-only structural example.'}]}]
        self.assertEqual(support.support_decision_errors(packet,gloss),[])
        gloss[0]['support_decisions'][0]['used_evidence_ids']=['invented']
        self.assertTrue(support.support_decision_errors(packet,gloss))
        self.assertTrue(support.support_decision_errors(packet,[{'id':'p','support_decisions':[]}]))

class ActualCallerTests(unittest.TestCase):
    """Delivery/cache tests use real stage and disk code; canned responses do not prove translation quality."""
    build = SupportTests.build
    def setUp(self):
        SupportTests.setUp(self);self.packet=self.build();self.calls=[];self.song=self.root/'song';self.song.mkdir()
        self.options=argparse.Namespace(model='fixture-model',force=False,timeout=1,gloss_batch_size=3,gloss_workers=1,max_attempts=1,semantic_lexical_support=self.packet)
        self.audited={'packet':{'verified_lines':self.lines,'metadata':{'languages':['Sanskrit']},'performance_order':[{'line_id':'p','occurrence':1}]}}
        for p in [patch.object(pipeline.gemini,'key',return_value='fixture-only'),patch.object(pipeline.gemini,'call',side_effect=self.provider)]:p.start();self.addCleanup(p.stop)
    def provider(self,model,key,prompt,**kw):
        kind=kw['schema_name'];self.calls.append((kind,prompt,copy.deepcopy(kw['response_schema'])))
        if kind=='bhakti_word_glosses':
            decisions=decisions_for(self.lines,['Sanskrit'])
            row={'id':'p','word_glosses':[{'roman':'pati','gloss':'governable','concept_key':'','preserve_in_english':False}],'semantic_frame':{k:'' for k in pipeline.SEMANTIC_FRAME_FIELDS},'grammar_note':'','uncertainty':'','sense_decisions':decisions['p']}
            if getattr(self.options,'semantic_lexical_support',None):row['support_decisions']=[{'target_id':'choice-p','used_evidence_ids':['ks-pati'],'role':'background_only','reason':'Structural fixture: English adjectives do not translate this source.'}]
            return {'packet':{'glosses':[row]}}
        if kind=='bhakti_translation_review':
            return {'packet':{'reviews':[{'id':'p','passes':True,'human_review_recommended':False,'agency_preserved':True,'imagery_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[],'material_choice':'','reason':'Fixture transport only','issues':[]}]}}
        row={'id':'p','literal_english':'governable','segments':[{'text':'governable','word_indices':[0]}],'human_review_recommended':False,'material_alternatives':[],'choice_note':'','uncertainty':'','fidelity':{'agency_and_image_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[],'notes':''}}
        if getattr(self.options,'semantic_lexical_support',None):
            row['wording_decisions']=[{'target_id':'choice-p','chosen_candidate_id':'c-governable','expression':'governable','kind':'word','english_evidence_ids':next(t['english_candidates'][0]['english_evidence_ids'] for t in self.packet['targets'] if t['id']=='choice-p'),'reason':'Transport fixture only: not a semantic correctness claim.','word_indices':[0],'ordinary_paraphrase':'governable','component_word_indices':[[0]]}]
        return {'packet':{'translations':[row],'comparison':[]}}
    def run_stages(self):
        g=pipeline.gloss(self.song,self.audited,self.options)
        return pipeline.translate(self.song,self.audited,g,{'languages':['Sanskrit']},self.options,candidate_only=True)
    def test_real_three_stages_receive_full_evidence_not_only_writer_verdict(self):
        self.run_stages();self.assertEqual({c[0] for c in self.calls},{'bhakti_word_glosses','bhakti_literal_translation','bhakti_translation_review'})
        for kind,prompt,_ in self.calls:
            with self.subTest(kind=kind):
                self.assertIn('TARGETED LEXICAL SUPPORT:\n',prompt);self.assertIn('without protest',prompt);self.assertIn('पातेर्डतिः',prompt);self.assertIn('c-governable',prompt);self.assertIn('c-biddable',prompt)
        review=next(c[1] for c in self.calls if c[0]=='bhakti_translation_review');self.assertIn('support_decisions',review);self.assertIn('wording_decisions',review)
    def test_fresh_or_seeded_bad_wording_is_rejected_before_review_and_cache(self):
        for candidate_only,seeded in [(False,False),(True,False),(True,True)]:
            for defect in ('missing','wrong_index','unknown_evidence'):
                with self.subTest(candidate_only=candidate_only,seeded=seeded,defect=defect):
                    song=self.root/(str(candidate_only)+str(seeded)+defect);song.mkdir()
                    gloss=pipeline.gloss(song,self.audited,self.options)
                    original=self.provider
                    def faulty(model,key,prompt,**kw):
                        result=original(model,key,prompt,**kw)
                        if kw['schema_name']=='bhakti_literal_translation':
                            row=result['packet']['translations'][0]
                            if defect=='missing':row.pop('wording_decisions')
                            elif defect=='wrong_index':row['wording_decisions'][0]['word_indices']=[1]
                            else:row['wording_decisions'][0]['english_evidence_ids']=['invented']
                        return result
                    options=copy.copy(self.options)
                    if seeded:options.semantic_seed_translation=faulty('fixture','fixture','',schema_name='bhakti_literal_translation',response_schema={})
                    self.calls=[]
                    with patch.object(pipeline.gemini,'call',side_effect=faulty),self.assertRaisesRegex(RuntimeError,'lexical support'):
                        pipeline.translate(song,self.audited,gloss,{'languages':['Sanskrit']},options,candidate_only=candidate_only)
                    self.assertFalse(any(kind=='bhakti_translation_review' for kind,_,_ in self.calls))
                    self.assertFalse((song/'.transcription/pipeline/05-translation.json').exists())
                    self.assertFalse((song/'.transcription/pipeline/translation-candidate.json').exists())

    def test_assembled_partial_repair_rechecks_retained_wording_decisions(self):
        gloss=pipeline.gloss(self.song,self.audited,self.options)
        options=copy.copy(self.options);options.semantic_lexical_support=copy.deepcopy(self.packet)
        extra=copy.deepcopy(options.semantic_lexical_support['targets'][0]);extra.update(id='choice-q',line_id='q');options.semantic_lexical_support['targets'].append(extra)
        audited=copy.deepcopy(self.audited);audited['packet']['verified_lines'].append({**self.lines[0],'id':'q'})
        other=copy.deepcopy(gloss['packet']['glosses'][0]);other['id']='q';other['support_decisions'][0]['target_id']='choice-q';gloss['packet']['glosses'].append(other)
        seed=self.provider('fixture','fixture','',schema_name='bhakti_literal_translation',response_schema={})
        original=copy.deepcopy(seed['packet']['translations'][0]);retained=copy.deepcopy(original);retained['id']='q';retained.pop('wording_decisions')
        options.semantic_seed_translation=seed;options.semantic_translation_targets=['p'];options.semantic_previous_translations=[original,retained]
        self.calls=[]
        with self.assertRaisesRegex(RuntimeError,'lexical support'):
            pipeline.translate(self.song,audited,gloss,{'languages':['Sanskrit']},options,candidate_only=True)
        self.assertEqual(self.calls,[])
        self.assertFalse((self.song/'.transcription/pipeline/05-translation.json').exists())

    def test_same_support_reuses_disk_changed_evidence_invalidates_text(self):
        self.run_stages();before=len(self.calls);self.run_stages();self.assertEqual(len(self.calls),before)
        self.options.semantic_lexical_support=copy.deepcopy(self.packet)
        self.options.semantic_lexical_support['evidence'][0]['limitations'].append('Additional witness limitation')
        self.run_stages();self.assertGreater(len(self.calls),before)
    def test_relocated_identical_witnesses_reuse_actual_text_cache(self):
        self.run_stages();before=len(self.calls)
        destination=self.root/'relocated';destination.mkdir()
        _,lines,_=fixture(destination)
        relocated=support.build_support(destination/'manifest.json',lines,['Sanskrit'])
        self.assertNotEqual(self.packet['evidence'][0]['witness_path'],relocated['evidence'][0]['witness_path'])
        original_policy=pipeline.semantic_stage_policy(self.options)
        self.options.semantic_lexical_support=relocated
        self.assertEqual(original_policy,pipeline.semantic_stage_policy(self.options))
        self.run_stages();self.assertEqual(len(self.calls),before)

    def test_no_support_keeps_old_conditional_schema(self):
        del self.options.semantic_lexical_support;self.run_stages()
        for kind,prompt,schema in self.calls:
            self.assertNotIn('TARGETED LEXICAL SUPPORT:',prompt)
            self.assertNotIn('support_decisions',json.dumps(schema));self.assertNotIn('wording_decisions',json.dumps(schema))
    def test_support_policy_is_text_only_and_changes_with_content(self):
        before=pipeline.semantic_stage_policy(self.options)
        self.options.semantic_lexical_support=copy.deepcopy(self.packet);self.options.semantic_lexical_support['evidence'][0]['limitations'].append('new')
        self.assertNotEqual(before,pipeline.semantic_stage_policy(self.options))

class SharedBoundaryTests(unittest.TestCase):
    def test_actual_library_slug_packet_reaches_routed_review_and_resume(self):
        import test_library_execution as fixtures
        f=fixtures.CurrentContentExecutionTests('test_real_source_first_review_preserves_legacy_reader_and_resumes_without_call');f.setUp();self.addCleanup(f.doCleanups)
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);root=pathlib.Path(temporary.name)
        manifest,lines,_=fixture(root);packet=support.build_support(root/'manifest.json',lines,['Sanskrit'])
        target=packet['targets'][0];target.update(line_id='one',surfaces=['mana'],source_language='hi',source_evidence_ids=[],background_evidence_ids=['ks-pati'])
        f.options.lexical_support_packets={'fixture':packet};data=fixtures.reader()
        response={'packet':{'reviews':[fixtures.review()]}}
        with patch.object(pipeline.gemini,'key',return_value='unused'),patch.object(pipeline.gemini,'call',return_value=response) as call:
            first=f.execute(data);second=f.execute(data)
        self.assertEqual(first,second);self.assertEqual(call.call_count,1)
        self.assertIn('TARGETED LEXICAL SUPPORT:',call.call_args.args[2]);self.assertIn('without protest',call.call_args.args[2])
        self.assertFalse(hasattr(f.options,'semantic_lexical_support'))

    def test_outer_library_run_resumes_after_identical_witness_relocation(self):
        import bhakti_library_pass as library
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);left=root/'left';right=root/'right';state=root/'state'
            left.mkdir();right.mkdir();state.mkdir()
            _,lines,_=fixture(left);fixture(right)
            packets=[support.build_support(place/'manifest.json',lines,['Sanskrit']) for place in (left,right)]
            options=argparse.Namespace(model='fixture',pro_model='fixture-pro',budget_usd=1,max_calls=1,deadline_seconds=60,slugs=[],workers=1,lexical_support_packets={'fixture':packets[0]})
            inventory={'catalogueRevision':'fixture','songs':[{'slug':'fixture','fingerprints':{'all':'fixture'}}]}
            with patch.object(library,'execute_song',return_value={'status':'unresolved','publicationEligible':False}) as execute:
                first=library._execute_inventory(root,inventory,state,options)
                options.lexical_support_packets={'fixture':packets[1]}
                second=library._execute_inventory(root,inventory,state,options)
            self.assertEqual(first['identity'],second['identity']);self.assertEqual(execute.call_count,1)

    def test_actual_audio_observation_cache_ignores_lexical_support(self):
        import test_generic_source_caller as fixtures
        f=fixtures.CallerTests('test_missing_02_03_reaches_actual_audio_auditor_before_old_reads');f.setUp();self.addCleanup(f.doCleanups)
        first=f.observed(f.invoke());count=f.call.call_count
        f.options.semantic_lexical_support={'version':1,'evidence':[{'id':'changed-English-evidence'}],'targets':[]}
        second=f.observed(f.invoke())
        self.assertEqual(f.call.call_count,count)
        self.assertEqual(first['input_fingerprint'],second['input_fingerprint'])
        self.assertEqual(first['receipt_path'],second['receipt_path'])

    def test_existing_reader_owner_lock_still_rejects_supported_alternative(self):
        import test_retranslate_bhakti as fixtures
        f=fixtures.ExistingReaderRepairTests('test_saved_owner_baseline_is_supplied_not_current_reader_wording');f.setUp();self.addCleanup(f.doCleanups)
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=pathlib.Path(temporary.name);manifest,lines,_=fixture(root)
        packet=support.build_support(root/'manifest.json',lines,['Sanskrit'])
        target=packet['targets'][0];target.update(line_id='a',word_indices=[0],surfaces=['man'],source_language='hi',source_evidence_ids=[],background_evidence_ids=['ks-pati'])
        f.options.semantic_lexical_support=packet;f.english['a']='governable'
        original=f.provider
        def provider(*args,**kwargs):
            result=original(*args,**kwargs);kind=kwargs['schema_name']
            if 'word_gloss' in kind:
                for row in result['packet']['glosses']:
                    if row['id']=='a':row['support_decisions']=[{'target_id':'choice-p','used_evidence_ids':['ks-pati'],'role':'background_only','reason':'Transport fixture only.'}]
            elif kind!='bhakti_translation_review':
                for row in result['packet']['translations']:
                    if row['id']=='a':
                        candidate=next(c for c in target['english_candidates'] if c['expression']==f.english['a'])
                        row['wording_decisions']=[{'target_id':'choice-p','chosen_candidate_id':candidate['id'],'expression':f.english['a'],'kind':'word','english_evidence_ids':candidate['english_evidence_ids'],'reason':'Transport fixture only.','word_indices':[0],'ordinary_paraphrase':f.english['a'],'component_word_indices':[[0]]}]
            return result
        with patch.object(pipeline.gemini,'call',side_effect=provider):
            f.baselines['songs']['sample']={'policy':'preserve_english','englishSha256':'0'*64,'plainEnglishByLine':f.english.copy()};f.write_baselines()
            before=f.path.read_bytes();fixtures.repair.run_slug('sample',f.options);self.assertEqual(f.path.read_bytes(),before)
            f.english['a']='biddable';f.options.reuse_glosses=True
            with self.assertRaisesRegex(RuntimeError,'owner-designated English changed'):
                fixtures.repair.run_slug('sample',f.options)
            self.assertEqual(f.path.read_bytes(),before)

if __name__=='__main__':unittest.main()

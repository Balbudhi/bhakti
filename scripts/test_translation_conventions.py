"""Actual readers, lineage and prompt constructors. No provider calls."""
import argparse
import copy
from collections import Counter
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import audit_bhakti_contract as contract
import bhakti_library_pass as library
import bhakti_library_source_pass as source_pass
import bhakti_pipeline as pipeline
import bhakti_translation_policy as policy
import bhakti_lexical_retrieval as lexical
from test_sense_decisions import decisions_for

ROOT=Path(__file__).resolve().parents[1]
CANDIDATE=ROOT/'data/translation_conventions.json'
SLUG='har-jiyo-kirpa-karo'

class Captured(BaseException):pass

class NamingConventionRequirements(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records=[r for r in json.loads(CANDIDATE.read_text())['occurrences'] if r['source_language']=='pa']
        for record in cls.records:record['authority']='docs/RECENT_SONG_EDITORIAL_REVIEW.md: Gurbāṇī name consistency — 22 October 2026'
        cls.readers={slug:contract.load_data(ROOT/'songs'/slug/'data.js')
                     for slug in {r['source_slug'] for r in cls.records}}

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='bhakti-naming-review-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'data').mkdir()
        shutil.copy(ROOT/'data/bhakti_lexicon.json',self.root/'data/bhakti_lexicon.json')
        self.registry=self.root/'data/translation_conventions.json'
        self.registry.write_text(json.dumps({'version':1,'occurrences':self.records},ensure_ascii=False))
        self.lines,self.glosses,self.drafts=library.reader_evidence(self.readers[SLUG])
        self.ids=['refrain-1','rahao-2','v2-2']
        self.targets=[r for r in self.lines if r['id'] in self.ids]
        self.opts=argparse.Namespace(model='fixture',force=False,timeout=10,max_attempts=1,
            gloss_batch_size=40,gloss_workers=1,source_slug=SLUG,semantic_stage_escalation=False,
            semantic_repair_rounds=0,semantic_repair_seconds=60,
            semantic_full_source=self.targets,semantic_performance_order=[{'line_id':r['id']} for r in self.targets])
        self.audit={'packet':{'metadata':{'languages':['Punjabi']},'verified_lines':self.targets,
            'performance_order':self.opts.semantic_performance_order,'uncertainties':[]}}
        for p in (patch.object(pipeline,'ROOT',ROOT),patch.object(policy,'ROOT',self.root),patch.dict('os.environ',{'BHAKTI_AUTO_LEXICAL':'0','BHAKTI_LEXICAL_INDEX':''}),
                  patch.object(pipeline.gemini,'key',return_value='OFFLINE')):
            p.start();self.addCleanup(p.stop)

    def resolve(self,lines=None,full=None,slug=SLUG):
        return policy.resolve_naming_conventions(slug,self.targets if lines is None else lines,
            ['Punjabi'],full_source=self.lines if full is None else full)

    def test_actual_inventory_binds_all30_distinct_source_tokens(self):
        counts=Counter();seen=set()
        for record in self.records:
            reader=self.readers[record['source_slug']]
            rows,_,_=library.reader_evidence(reader);row=next(r for r in rows if r['id']==record['line_id'])
            self.assertEqual(record['source_text'],row['source_text'])
            tokens=lexical.word_tokens(row)
            self.assertEqual([tokens[i] for i in record['word_indices']],record['roman_surfaces'])
            key=(record['source_slug'],record['line_id'],tuple(record['word_indices']))
            self.assertNotIn(key,seen);seen.add(key)
            counts[record['roman_surfaces'][0].casefold()]+=1
        self.assertEqual(len(seen),30)
        self.assertEqual(counts['hari'],24)
        self.assertEqual(sum(v for k,v in counts.items() if k.startswith('gobind')),3)
        self.assertEqual(sum(v for k,v in counts.items() if k.startswith('murār')),3)

    def test_excerpt_absent_unrelated_records_is_not_scope_failure(self):
        result=self.resolve(lines=self.targets[:1],full=self.targets[:1])
        self.assertEqual(result['conflicts'],[])
        self.assertEqual(len(result['matches']),1)
        self.assertEqual(result['matches'][0]['english_head'],'Lord')
        self.assertEqual(result['matches'][0]['word_indices'],[0])

    def test_same_surface_in_unassociated_poem_gets_no_convention(self):
        result=self.resolve(slug='an-unrelated-poem')
        self.assertEqual(result,{'matches':[],'conflicts':[]})

    def test_corrected_target_surface_becomes_local_conflict_not_forced_old_index(self):
        changed=copy.deepcopy(self.targets[0]);changed.update(source_text='ਮਨ ਜੀਉ ਕ੍ਰਿਪਾ ਕਰਹੁ',roman='mana jīu kripā karahu')
        changed.pop('lexical_tokens',None);changed.pop('sourceWords',None)
        before=copy.deepcopy(changed)
        result=self.resolve(lines=[changed],full=[changed])
        self.assertEqual(result['matches'],[]);self.assertEqual(len(result['conflicts']),1)
        self.assertEqual(result['conflicts'][0]['line_id'],changed['id'])
        self.assertEqual(changed,before)
        # The changed line must not block a separate exact unaffected target.
        other=self.targets[1]
        result=self.resolve(lines=[other],full=[changed,other])
        self.assertEqual(result['conflicts'],[]);self.assertEqual(len(result['matches']),1)

    def test_existing_source_planner_keeps_naming_identity_for_unique_id_only_rename(self):
        reader=copy.deepcopy(self.readers[SLUG]);old={r['id']:r for r in self.lines}
        rebuilt={'verified_lines':[{**copy.deepcopy(row),'id':'renamed-'+row['id']} for row in self.lines],
            'performance_order':[{'line_id':'renamed-'+lid,'occurrence':1} for lid in old],'uncertainties':[]}
        plan=source_pass.plan_source(reader,rebuilt)
        self.assertEqual(plan['new_target_ids'],[])
        for lid in old:
            self.assertEqual(plan['raw_to_final']['renamed-'+lid],lid)
            self.assertEqual(plan['reuse_by_id'][lid]['english'],reader['SONG_LINES'][lid]['english'])

    def capture(self,call):
        captured=[]
        def provider(model,key,prompt,**kwargs):captured.append(prompt);raise Captured()
        with patch.object(pipeline.gemini,'call',side_effect=provider):
            with self.assertRaises(Captured):call()
        self.assertEqual(len(captured),1)
        return captured[0]

    def assert_packet(self,prompt):
        packet=json.JSONDecoder().raw_decode(prompt.split('SCOPED NAMING CONVENTIONS:\n',1)[1])[0]
        self.assertEqual(len(packet['matches']),3)
        self.assertTrue(all(r['english_head']=='Lord' for r in packet['matches']))
        self.assertTrue(all('Viṣṇu/Kṛṣṇa' in r['gloss_identity'] for r in packet['matches']))
        self.assertEqual({r['line_id'] for r in packet['matches']},set(self.ids))
        self.assertNotIn('PRIOR ENGLISH SENTINEL',json.dumps(packet))

    def test_complete_original_slug_reaches_initial_gloss_despite_round_directory(self):
        prompt=self.capture(lambda:pipeline.complete_semantics(self.root/'case-id',self.audit,{'slug':SLUG,'languages':['Punjabi']},self.opts))
        self.assert_packet(prompt)
        self.assertNotIn('PRIOR ENGLISH SENTINEL',prompt)
        self.assertIn('ਹਰਿ',prompt)

    def test_standalone_gloss_receives_exact_projection(self):
        self.assert_packet(self.capture(lambda:pipeline.gloss(self.root/'standalone',self.audit,self.opts)))

    def test_direct_reviewer_receives_same_exact_projection(self):
        gs=[r for r in self.glosses if r['id'] in self.ids]
        ts=[r for r in self.drafts if r['id'] in self.ids]
        prompt=self.capture(lambda:pipeline.independently_review_translations(self.root/'review',self.targets,gs,ts,
            '(none supplied)',self.opts,languages=['Punjabi']))
        self.assert_packet(prompt)

    def test_evidenced_kabir_person_spelling_is_scoped_not_final_a_stripping(self):
        reader=contract.load_data(ROOT/'songs/rehna-nahi-isa-desa/data.js')
        sources,_,_=library.reader_evidence(reader)
        line=next(r for r in sources if r['id']=='verse-3-line-1')
        record={'source_slug':'rehna-nahi-isa-desa','source_language':'hi',
            'line_id':line['id'],'source_text':line['source_text'],'word_indices':[1],
            'roman_surfaces':['kabīra'],'native_surfaces':['कबीर'],'english_head':'Kabīr',
            'gloss_identity':'Kabīr, the poet named in this source line',
            'authority':'data/source_credits.json: LA_lHx9qroQ',
            'reason':'Verified historical personal-name spelling, not general Sanskrit final-a deletion.'}
        self.registry.write_text(json.dumps({'version':1,'occurrences':self.records+[record]},ensure_ascii=False))
        result=policy.resolve_naming_conventions('rehna-nahi-isa-desa',[line],['Hindi'],full_source=[line])
        self.assertEqual(len(result['matches']),1)
        self.assertEqual(result['matches'][0]['english_head'],'Kabīr')
        self.assertEqual(line['roman'],'kahata kabīra sunō bhāī sādhō')
        other=policy.resolve_naming_conventions('modern-artist-song',[line],['Hindi'],full_source=[line])
        self.assertEqual(other,{'matches':[],'conflicts':[]})

    def test_protected_full_population_guard_still_blocks_before_naming_can_bypass_it(self):
        shutil.copy(ROOT/'data/preserved_terms.json',self.root/'data/preserved_terms.json')
        baseline={'version':1,'songs':{SLUG:{'policy':'preserve_english','englishSha256':'a'*64,
            'plainEnglishByLine':{'owner-line':'OWNER EXACT ENGLISH'}}}}
        path=self.root/'data/editorial_baselines.json';path.write_text(json.dumps(baseline));original=path.read_bytes()
        with patch.object(pipeline,'ROOT',self.root),patch.object(pipeline.gemini,'call',side_effect=AssertionError('No paid dispatch')):
            with self.assertRaisesRegex(RuntimeError,'owner baseline.*population'):
                pipeline.complete_semantics(self.root/SLUG,self.audit,{'slug':SLUG},self.opts)
        self.assertEqual(path.read_bytes(),original)

    def valid_provider(self,model,key,prompt,**kwargs):
        kind=kwargs['schema_name'];self.provider_calls.append(kind)
        if kind=='bhakti_word_glosses':
            rows=[copy.deepcopy(r) for r in self.glosses if r['id'] in self.ids]
            senses=decisions_for(self.targets,['Punjabi'])
            for row in rows:
                row.update(semantic_frame={f:'' for f in pipeline.SEMANTIC_FRAME_FIELDS},
                           uncertainty='',sense_decisions=senses[row['id']])
                for word in row['word_glosses']:word['preserve_in_english']=False
            return {'packet':{'glosses':rows}}
        if kind=='bhakti_literal_translation':
            rows=[copy.deepcopy(r) for r in self.drafts if r['id'] in self.ids]
            for row in rows:row.update(human_review_recommended=False,material_alternatives=[],choice_note='',uncertainty='',
                fidelity={'agency_and_image_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[],'notes':''})
            return {'packet':{'translations':rows}}
        return {'packet':{'reviews':[{'id':r['id'],'passes':True,'human_review_recommended':False,
            'agency_preserved':True,'imagery_preserved':True,'all_meaning_accounted_for':True,
            'unsupported_additions':[],'material_choice':'','reason':'Offline control, not semantic quality evidence.','issues':[]}
            for r in self.targets]}}

    def complete(self):
        return pipeline.complete_semantics(self.root/'private-case',self.audit,{'slug':SLUG,'languages':['Punjabi']},self.opts)

    def test_actual_accepted_resume_changes_only_for_relevant_convention_content(self):
        self.provider_calls=[]
        with patch.object(pipeline.gemini,'call',side_effect=self.valid_provider):
            original=self.complete();self.assertEqual(len(self.provider_calls),3)
            self.assertEqual(self.complete(),original);self.assertEqual(len(self.provider_calls),3)
            value=json.loads(self.registry.read_text())
            unrelated=next(r for r in value['occurrences'] if r['source_slug']!=SLUG)
            unrelated['reason']+=' Additional unrelated editorial note.'
            self.registry.write_text(json.dumps(value,ensure_ascii=False))
            self.assertEqual(self.complete(),original);self.assertEqual(len(self.provider_calls),3)
            moved=self.root/'relocated-policy';shutil.copytree(self.root/'data',moved/'data')
            with patch.object(policy,'ROOT',moved):
                self.assertEqual(self.complete(),original);self.assertEqual(len(self.provider_calls),3)
            target=next(r for r in value['occurrences'] if r['source_slug']==SLUG)
            target['gloss_identity']+=' This occurrence is a divine name in the reviewed address.'
            self.registry.write_text(json.dumps(value,ensure_ascii=False))
            self.complete()
            self.assertEqual(self.provider_calls[3:],['bhakti_word_glosses','bhakti_literal_translation','bhakti_translation_review'])
            count=len(self.provider_calls);self.complete();self.assertEqual(len(self.provider_calls),count)

    def test_changed_registered_target_cannot_use_accepted_fast_path_or_spend_to_force_old_name(self):
        self.provider_calls=[]
        with patch.object(pipeline.gemini,'call',side_effect=self.valid_provider):self.complete()
        changed=copy.deepcopy(self.targets[0]);changed.update(source_text='ਮਨ ਜੀਉ ਕ੍ਰਿਪਾ ਕਰਹੁ',roman='mana jīu kripā karahu')
        changed.pop('lexical_tokens',None);changed.pop('sourceWords',None)
        self.audit=copy.deepcopy(self.audit);self.audit['packet']['verified_lines'][0]=changed
        self.opts.semantic_full_source=self.audit['packet']['verified_lines']
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('Scope conflict must precede dispatch')):
            with self.assertRaisesRegex((ValueError,RuntimeError),'naming.*scope|convention.*source|naming.*conflict'):
                self.complete()
        self.assertEqual(len(self.provider_calls),3)

    def test_actual_library_options_forward_original_slug_without_mutating_input(self):
        original=copy.copy(self.opts);del original.source_slug
        original.semantic_full_source=self.lines
        prepared=library.lexical_options(original,SLUG,self.lines,['Punjabi'])
        self.assertEqual(prepared.source_slug,SLUG)
        self.assertFalse(hasattr(original,'source_slug'))

    def test_actual_fresh_source_caller_forwards_original_slug_through_private_rounds(self):
        opts=copy.copy(self.opts);del opts.source_slug
        opts.model=pipeline.gemini.model_routes.FLASH_MODEL;opts.pro_model=pipeline.gemini.model_routes.PRO_MODEL
        plan={'lines':self.targets,'new_target_ids':[r['id'] for r in self.targets],
              'performance_order':self.opts.semantic_performance_order,'reuse_by_id':{}}
        import time
        prompt=self.capture(lambda:source_pass.process_new_targets(self.root/SLUG,plan,{'languages':['Punjabi']},
            opts,self.root/'fresh-routes',time.time()+60))
        self.assert_packet(prompt)
        self.assertFalse(hasattr(opts,'source_slug'))

    def test_standalone_writer_receives_naming_before_producing_english(self):
        rows=[copy.deepcopy(r) for r in self.glosses if r['id'] in self.ids]
        senses=decisions_for(self.targets,['Punjabi'])
        for row in rows:
            row.update(semantic_frame={f:'' for f in pipeline.SEMANTIC_FRAME_FIELDS},uncertainty='',
                       sense_decisions=senses[row['id']])
        prompt=self.capture(lambda:pipeline.translate(self.root/'writer',self.audit,{'packet':{'glosses':rows}},
            {'slug':SLUG,'languages':['Punjabi']},self.opts,candidate_only=True))
        self.assert_packet(prompt)



import audit_translation_style as style
import retranslate_bhakti as retranslate

class NamingCliRequirements(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        NamingConventionRequirements.setUpClass.__func__(cls)
    capture = NamingConventionRequirements.capture
    assert_packet = NamingConventionRequirements.assert_packet
    def setUp(self):
        NamingConventionRequirements.setUp(self)
        song=self.root/'songs'/SLUG;song.mkdir(parents=True)
        shutil.copy(ROOT/'songs'/SLUG/'data.js',song/'data.js')
        self.original_bytes=(song/'data.js').read_bytes()
        shutil.copy(ROOT/'data/editorial_baselines.json',self.root/'data/editorial_baselines.json')
        for p in (patch.object(style,'ROOT',self.root),patch.object(retranslate,'ROOT',self.root)):
            p.start();self.addCleanup(p.stop)

    def test_retranslate_actual_first_gloss_receives_original_slug(self):
        options=copy.copy(self.opts);del options.source_slug;del options.force
        options.reuse_glosses=False
        del options.semantic_full_source;del options.semantic_performance_order
        prompt=self.capture(lambda:retranslate.run_slug(SLUG,options))
        self.assert_packet(prompt)
        self.assertFalse(hasattr(options,'source_slug'))
        self.assertEqual((self.root/'songs'/SLUG/'data.js').read_bytes(),self.original_bytes)

    def test_style_actual_audit_prompt_receives_current_scoped_records(self):
        options=copy.copy(self.opts);del options.source_slug;options.batch_size=100
        del options.semantic_full_source;del options.semantic_performance_order
        prompt=self.capture(lambda:style.run_slug(SLUG,options))
        self.assert_packet(prompt)
        self.assertFalse(hasattr(options,'source_slug'))
        self.assertEqual((self.root/'songs'/SLUG/'data.js').read_bytes(),self.original_bytes)

    def test_style_actual_cached_acceptance_revalidates_only_relevant_naming(self):
        options=copy.copy(self.opts);del options.source_slug;options.batch_size=100
        del options.semantic_full_source;del options.semantic_performance_order
        calls=[]
        def provider(model,key,prompt,**kwargs):
            calls.append(prompt)
            targets=json.JSONDecoder().raw_decode(prompt.split('TARGETS (return these IDs only, in this order):\n',1)[1])[0]
            return {'packet':{'reviews':[{'id':row['id'],'change_needed':False,
                'current_english':row['current_english'],'revised_english':row['current_english'],
                'segments':[{'text':row['current_english'],'word_indices':list(range(len(row['word_glosses'])))}],
                'reason':'Offline cache control only.','uncertainty':''} for row in targets]}}
        with patch.object(style.gemini,'call',side_effect=provider):
            style.run_slug(SLUG,options);self.assertEqual(len(calls),1)
            style.run_slug(SLUG,options);self.assertEqual(len(calls),1)
            value=json.loads(self.registry.read_text())
            next(r for r in value['occurrences'] if r['source_slug']!=SLUG)['reason']+=' Unrelated.'
            self.registry.write_text(json.dumps(value,ensure_ascii=False))
            style.run_slug(SLUG,options);self.assertEqual(len(calls),1)
            next(r for r in value['occurrences'] if r['source_slug']==SLUG)['gloss_identity']+=' Reviewed divine-name identity.'
            self.registry.write_text(json.dumps(value,ensure_ascii=False))
            style.run_slug(SLUG,options);self.assertEqual(len(calls),2)
        self.assertEqual((self.root/'songs'/SLUG/'data.js').read_bytes(),self.original_bytes)

if __name__=='__main__':unittest.main()

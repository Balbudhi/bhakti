"""Actual semantic caller tests; fixtures establish contracts, not model quality."""
import argparse
import copy
import importlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import bhakti_pipeline as pipeline
import bhakti_semantic_repair as semantic
from test_library_shared_semantic import review as review_row
from test_sense_decisions import decisions_for

HERE=Path(__file__).parent
BAD="The True Guru's Name is the true dwelling."
GOOD="The True Guru's Name is the dwelling."

def parsed(prompt,marker):
    return json.JSONDecoder().raw_decode(prompt.rsplit(marker,1)[1].lstrip())[0]

def ref(line,index):
    item=next(item for item in line['sourceWords'] if index in item['wordIndices'])
    return {'line_id':line['id'],'domain':'word_glosses','word_indices':[index],'source_quote':item['text']}

def evidence_rows(line,indices,bases=None):
    return [{'unit':i,'bases':(bases or {}).get(i,['lexical']),
             'references':[ref(line,index)],'reason':'WRITER_ONLY_WARRANT: '+str(i)}
            for i,index in enumerate(indices)]

class WordAccountabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='bhakti-word-accountability-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.fixture=json.loads((HERE/'fixtures/word_accountability/two-row.json').read_text())
        self.audit=self.fixture['audited'];self.lines=self.audit['packet']['verified_lines'];self.mode='good'
        self.calls=[];self.gloss_count=0;self.writer_count=0;self.serial=0;self.custom=None
        self.options=argparse.Namespace(model='google/gemini-3.7-flash',pro_model='google/gemini-3.1-pro-preview',
            force=False,timeout=60,gloss_batch_size=40,gloss_workers=1,max_attempts=1,
            semantic_stage_escalation=False,semantic_repair_rounds=1,semantic_repair_seconds=120,
            semantic_deadline_at=time.time()+120,semantic_full_source=self.lines,
            semantic_performance_order=self.audit['packet']['performance_order'],source_slug='rehna-nahi-isa-desa')
        for p in (patch.dict(os.environ,{'BHAKTI_AUTO_LEXICAL':'0','BHAKTI_ENGLISH_DISCOVERY':'0',
                    'BHAKTI_API_RUN_LEDGER':str(self.root/'ledger.json'),'BHAKTI_API_RUN_BUDGET_USD':'2'}),
                  patch.object(pipeline.gemini,'key',return_value='OFFLINE'),
                  patch.object(pipeline.gemini,'call',side_effect=self.provider)):
            p.start();self.addCleanup(p.stop)
    def issue(self,kind):
        return {'kind':kind,'target_line_ids':[self.lines[-1]['id']],
                'references':[ref(self.lines[-1],2)],
                'explanation':{'gloss_sense':'The popup adds authenticity to the abode.',
                    'frame_relation':'literal_image_and_agency asserts only without a source exclusivity expression.',
                    'english_realization':'The predicate true adds authenticity; the source compound modifier attaches to the teacher.'}[kind],
                'evidence':'The native predicate noun means an abode; its modifier is not repeated from the subject compound.',
                'hold_reason':'','needed_evidence':''}
    def glosses(self):
        if self.custom is not None:return copy.deepcopy(self.custom['glosses'])
        rows=copy.deepcopy(self.fixture['glosses'])
        bad=self.mode=='source-defect' and self.gloss_count==1
        if not bad:
            rows[-1]['word_glosses'][2]['gloss']='dwelling; abode'
            rows[-1]['semantic_frame'].update(patient_or_complement='a dwelling',
                literal_image_and_agency='The Name is predicated as a dwelling.',idiom_or_phrase='',
                negation_or_modality='affirmative copular statement')
        return rows
    def writer(self):
        if self.custom is not None:return copy.deepcopy(self.custom['translations'])
        rows=copy.deepcopy(self.fixture['translations'])
        bad=self.mode in {'english-defect','source-defect','unmatched-word-defect','owner-rewrite','mixed-units','mixed-missing-issue'} and self.writer_count==1
        row=rows[-1];row['literal_english']=BAD if bad else GOOD
        row['segments']=[{'text':"The True Guru's ",'word_indices':[0]}, {'text':'Name ','word_indices':[1]},
                         {'text':'is ','word_indices':[3]}, {'text':'the '+('true ' if bad else '')+'dwelling.','word_indices':[2]}]
        rows[0]['word_support']=evidence_rows(self.lines[0],[1,0,2,3,4])
        row['word_support']=evidence_rows(self.lines[-1],[0,0,0,1,3,2,2,2] if bad else [0,0,0,1,3,2,2],
            {0:['grammar'],2:['lexical','grammar'],5:['grammar'],**({6:['context']} if bad else {})})
        if self.mode=='missing-writer-unit':row['word_support'].pop(5)
        if self.mode=='duplicate-writer-unit':row['word_support'][-1]['unit']=0
        if self.mode=='invented-source-quote':row['word_support'][-1]['references'][0]['source_quote']='NOT IN SOURCE'
        if self.mode=='neighbor-misquote':
            rows[0]['word_support'][0]['references'][0]['source_quote']=ref(self.lines[0],0)['source_quote']
        if self.mode=='wrong-local-map':row['word_support'][-1]['references']=[ref(self.lines[-1],0)]
        return rows
    def provider(self,model,key,prompt,**kw):
        schema=kw['schema_name'];self.calls.append((schema,prompt,kw))
        if schema=='bhakti_word_glosses':
            self.gloss_count+=1;targets={r['id'] for r in parsed(prompt,'TARGET LYRICS (return these IDs only):\n')}
            return {'packet':{'glosses':[r for r in self.glosses() if r['id'] in targets]}}
        if schema=='bhakti_literal_translation':
            self.writer_count+=1;targets={r['id'] for r in parsed(prompt,'TARGET audited source lines (return these IDs only):\n')}
            return {'packet':{'translations':[r for r in self.writer() if r['id'] in targets],'comparison':[]}}
        self.assertEqual(schema,'bhakti_translation_review')
        evidence=parsed(prompt,'EVIDENCE:\n');rows=[]
        for item in evidence:
            line=item['source'];draft=item['draft'];bad=draft['literal_english']==BAD
            issues=[]
            if bad and self.mode in {'english-defect','source-defect'}:
                issues=[self.issue('english_realization')]
                if self.mode=='source-defect':issues=[self.issue('gloss_sense'),self.issue('frame_relation')]+issues
            row=review_row(line['id'],issues)
            source_indices=([1,0,2,3,4] if line['id']==self.lines[0]['id'] else
                            [0,0,0,1,3,2,2,2] if bad else [0,0,0,1,3,2,2])
            row['word_judgments']=(copy.deepcopy(self.custom['judgments'][line['id']]) if self.custom is not None
                                   else evidence_rows(line,source_indices))
            for judgment in row['word_judgments']:
                judgment['status']='supported';judgment['reason']='INDEPENDENT_SOURCE_WARRANT: '+judgment['references'][0]['source_quote']
            if bad:
                row['word_judgments'][6].update(status='defect',bases=['context'],
                    reason='The source predicate has no authenticity qualifier; context does not repeat the compound modifier.')
            if self.mode in {'mixed-units','mixed-missing-issue'} and line['id']==self.lines[-1]['id']:
                unresolved=self.issue('english_realization')
                unresolved.update(kind='unresolved_evidence',hold_reason='audited_source_ambiguity',
                    needed_evidence='Resolve two consequential source constructions.',
                    explanation='The supplied hypothetical fixture leaves the predicate relation unresolved.')
                row.update(passes=False,human_review_recommended=True,
                    issues=[self.issue('english_realization')]+([unresolved] if self.mode=='mixed-units' else []))
                row['component_judgments']['english']={'status':'unresolved','reason':unresolved['explanation']}
                row['word_judgments'][7].update(status='unresolved',reason=unresolved['explanation'])
            if self.mode=='missing-review-unit':row['word_judgments'].pop()
            if self.mode=='pro-contradiction' and line['id']==self.lines[-1]['id']:
                row.update(human_review_recommended=True,material_choice='Dwelling versus refuge remains materially unresolved.')
            rows.append(row)
        return {'packet':{'reviews':rows}}
    def complete(self,*,job=None):
        return pipeline.complete_semantics(self.root/'song',self.audit,job or {'languages':['Hindi']},self.options)
    def sequence(self):
        return [schema for schema,_,_ in self.calls]
    def test_writer_schema_and_review_are_independent_and_accepted_resume_is_free(self):
        original=copy.deepcopy(self.fixture);result=self.complete()
        writer=next(c for c in self.calls if c[0]=='bhakti_literal_translation')
        schema=writer[2]['response_schema']['properties']['translations']['items']
        self.assertIn('word_support',schema['required'])
        critic=next(c for c in self.calls if c[0]=='bhakti_translation_review')
        self.assertIn('word_judgments',critic[2]['response_schema']['properties']['reviews']['items']['required'])
        self.assertNotIn('WRITER_ONLY_WARRANT',critic[1])
        self.assertNotIn('semantic frame is authoritative',writer[1])
        evidence=parsed(critic[1],'EVIDENCE:\n')
        self.assertEqual([u['text'] for u in evidence[-1]['english_units']],['The','True',"Guru's",'Name','is','the','dwelling'])
        self.assertNotIn('word_support',evidence[-1]['draft'])
        self.assertIn('word_support',result[1]['packet']['translations'][-1])
        before=len(self.calls);self.assertEqual(self.complete(),result);self.assertEqual(len(self.calls),before)
        self.assertEqual(self.fixture,original)
    def test_missing_duplicate_or_fabricated_writer_support_blocks_before_review(self):
        for mode in ('missing-writer-unit','duplicate-writer-unit','invented-source-quote','wrong-local-map','neighbor-misquote'):
            with self.subTest(mode=mode):
                self.mode=mode;self.calls=[];self.root=self.root/mode;self.root.mkdir()
                if mode=='neighbor-misquote':
                    self.lines[-1]['performed_context']=[{'before':[{key:self.lines[0][key] for key in ('id','source_text','roman')}],'after':[]}]
                with self.assertRaises((ValueError,RuntimeError)):self.complete()
                self.assertEqual(self.sequence(),['bhakti_word_glosses','bhakti_literal_translation'])
    def test_incomplete_independent_word_judgments_cannot_pass(self):
        self.mode='missing-review-unit'
        with self.assertRaises((ValueError,RuntimeError)):self.complete()
        self.assertEqual(len(self.calls),3)
    def test_word_defect_cannot_be_hidden_by_clean_component_and_empty_issues(self):
        self.mode='unmatched-word-defect'
        with self.assertRaises((ValueError,RuntimeError)):self.complete()
        self.assertEqual(len(self.calls),3)
    def test_actual_english_defect_reuses_gloss_and_reviews_repaired_words(self):
        self.mode='english-defect';result=self.complete()
        self.assertEqual(self.sequence(),['bhakti_word_glosses','bhakti_literal_translation','bhakti_translation_review',
                                         'bhakti_literal_translation','bhakti_translation_review'])
        self.assertEqual(result[1]['packet']['translations'][-1]['literal_english'],GOOD)
        self.assertEqual(len(result[1]['packet']['translations'][-1]['independent_review']['word_judgments']),7)
    def test_actual_popup_and_frame_defect_routes_gloss_instead_of_silent_english_deviation(self):
        self.mode='source-defect';result=self.complete()
        self.assertEqual(self.sequence(),['bhakti_word_glosses','bhakti_literal_translation','bhakti_translation_review']*2)
        self.assertEqual(result[0]['packet']['glosses'][-1]['word_glosses'][2]['gloss'],'dwelling; abode')
        self.assertNotIn('only',result[0]['packet']['glosses'][-1]['semantic_frame']['literal_image_and_agency'])
        self.assertEqual(result[1]['packet']['translations'][-1]['literal_english'],GOOD)
    def test_saved_pro_style_human_hold_without_unresolved_issue_is_not_normalized(self):
        self.mode='pro-contradiction'
        with self.assertRaises((ValueError,RuntimeError)):self.complete()
        self.assertEqual(len(self.calls),3)
    def test_locked_owner_words_are_not_rewritten_to_fit_a_new_explanation(self):
        locked=self.root/'owner.json';locked.write_text(json.dumps({self.lines[0]['id']:self.fixture['translations'][0]['literal_english'],self.lines[1]['id']:GOOD}))
        self.mode='owner-rewrite'
        with self.assertRaisesRegex((ValueError,RuntimeError),'locked_baseline_conflict'):self.complete(job={'languages':['Hindi'],'providedTranslation':str(locked)})
        self.assertNotIn('bhakti_translation_review',self.sequence())
        self.assertEqual(json.loads(locked.read_text())[self.lines[1]['id']],GOOD)
    def test_real_caller_preserves_names_possession_compounds_negation_and_necessary_grammar(self):
        specs=[('name', 'राम का घर प्रकाश से भरा है', 'rāma kā ghara prakāśa se bharā hai',
                ['the deity named here','of','home','light','with','filled','is'],
                "Rāma's home is light-filled.", [[0,1],[2],[6],[3,4],[5]],
                [['lexical','grammar'],['lexical'],['lexical'],['lexical','grammar'],['lexical']]),
               ('grammar','घर खाली नहीं है','ghara khālī nahīṁ hai',
                ['home','empty','not','is'],"The home isn't empty.",[[0],[0],[2,3],[1]],
                [['grammar'],['lexical'],['lexical','grammar'],['lexical']]),
               ('compound','कविपति','kavi-pati',['poet','lord'],'Lord of poets.',[[1],[0,1],[0]],
                [['lexical'],['grammar'],['lexical']])]
        lines=[];glosses=[];translations=[];judgments={}
        for line_id,native,roman,meanings,english,mapping,bases in specs:
            line={'id':line_id,'source_text':native,'roman':roman,'kind':'verse','sourceLanguage':'hi',
                'sourceWords':[{'text':word,'wordIndices':[i]} for i,word in enumerate(native.split())]}
            if line_id=='compound':
                line['lexical_tokens']=['kavi','pati'];line['sourceWords']=[{'text':native,'wordIndices':[0,1]}]
            tokens=line.get('lexical_tokens',roman.split())
            lines.append(line)
            glosses.append({'id':line_id,'word_glosses':[{'roman':word,'gloss':meaning,'concept_key':'','preserve_in_english':False}
                for word,meaning in zip(tokens,meanings)],'semantic_frame':{k:'' for k in pipeline.SEMANTIC_FRAME_FIELDS},
                'grammar_note':'Possession/compound predication.' if line_id=='name' else 'Negative copular clause.',
                'sense_decisions':decisions_for([line],['Hindi'])[line_id],'uncertainty':''})
            accounting=[{'unit':i,'bases':basis,'references':[ref(line,k) for k in indices],
                'reason':'Possession or compound contribution is retained.' if line_id=='name' else
                         'A required article, nominal meaning, or copula plus negation is retained.'}
                for i,(indices,basis) in enumerate(zip(mapping,bases))]
            translations.append({'id':line_id,'literal_english':english,
                'segments':[{'text':english,'word_indices':list(range(len(meanings)))}],
                'word_support':accounting,'fidelity':{'agency_and_image_preserved':True,'all_meaning_accounted_for':True,
                    'unsupported_additions':[],'notes':''},'material_alternatives':[],
                'human_review_recommended':False,'choice_note':'','uncertainty':''})
            judgments[line_id]=copy.deepcopy(accounting)
        self.lines=lines;self.audit={'packet':{'verified_lines':lines,'metadata':{'languages':['Hindi']},
            'performance_order':[{'ref':line['id'],'repeats':1} for line in lines]}}
        self.options.semantic_full_source=lines;self.options.semantic_performance_order=self.audit['packet']['performance_order']
        self.custom={'glosses':glosses,'translations':translations,'judgments':judgments}
        result=self.complete()
        self.assertEqual([r['literal_english'] for r in result[1]['packet']['translations']],[s[4] for s in specs])
        self.assertEqual(len(self.calls),3)
        evidence=parsed(next(c[1] for c in self.calls if c[0]=='bhakti_translation_review'),'EVIDENCE:\n')
        self.assertEqual([u['text'] for u in evidence[0]['english_units']],["Rāma's",'home','is','light','filled'])
        self.assertEqual([u['text'] for u in evidence[1]['english_units']],['The','home',"isn't",'empty'])
        self.assertEqual(result[1]['packet']['translations'][1]['independent_review']['word_judgments'][2]['references'],
                         [ref(lines[1],2),ref(lines[1],3)])

    def test_existing_writer_gets_fresh_independent_judgments_without_invented_writer_rationales(self):
        rows=self.writer()
        for row in rows:row.pop('word_support')
        candidate={'packet':{'translations':rows,'comparison':[]}}
        before=copy.deepcopy(candidate)
        result=pipeline.review_translation(self.root/'legacy-review',self.audit,
            {'packet':{'glosses':self.glosses()}},{'languages':['Hindi']},self.options,candidate,prepared=True)
        self.assertEqual(self.sequence(),['bhakti_translation_review'])
        self.assertEqual(candidate,before)
        self.assertTrue(all('word_support' not in row for row in result['packet']['translations']))
        self.assertTrue(all(row['independent_review']['word_judgments'] for row in result['packet']['translations']))
        evidence=parsed(self.calls[0][1],'EVIDENCE:\n')
        self.assertEqual(len(evidence[-1]['english_units']),7)
        self.assertNotIn('WRITER_ONLY_WARRANT',self.calls[0][1])

    def test_native_substring_cannot_impersonate_a_different_indexed_word(self):
        line={'id':'substring','source_text':'राम आराम','roman':'rāma ārāma','kind':'verse',
            'sourceWords':[{'text':'राम','wordIndices':[0]},{'text':'आराम','wordIndices':[1]}]}
        gloss={'id':line['id'],'word_glosses':[{'roman':'rāma','gloss':'the deity Rāma','concept_key':'','preserve_in_english':False},
            {'roman':'ārāma','gloss':'rest','concept_key':'','preserve_in_english':False}],
            'sense_decisions':decisions_for([line],['Hindi'])[line['id']],
            'semantic_frame':{key:'' for key in pipeline.SEMANTIC_FRAME_FIELDS},'grammar_note':'','uncertainty':''}
        row={'id':line['id'],'literal_english':'Rāma rests.',
            'segments':[{'text':'Rāma ','word_indices':[0]},{'text':'rests.','word_indices':[1]}],
            'word_support':evidence_rows(line,[0,1]),'fidelity':{'agency_and_image_preserved':True,
            'all_meaning_accounted_for':True,'unsupported_additions':[],'notes':''},
            'material_alternatives':[],'human_review_recommended':False,'choice_note':'','uncertainty':''}
        row['word_support'][0]['references'][0]['source_quote']='आराम'
        self.custom={'glosses':[gloss],'translations':[row]}
        self.options.semantic_full_source=[line];self.options.semantic_performance_order=[{'ref':line['id'],'repeats':1}]
        audit={'packet':{'verified_lines':[line],'metadata':{'languages':['Hindi']},'performance_order':self.options.semantic_performance_order}}
        with self.assertRaises((ValueError,RuntimeError)):
            pipeline.translate(self.root/'bad-substring',audit,{'packet':{'glosses':[gloss]}},
                {'languages':['Hindi']},self.options,defer_review=True)
        self.assertEqual(self.sequence(),['bhakti_literal_translation'])
        row['word_support'][0]['references'][0]['source_quote']='राम'
        good=pipeline.translate(self.root/'correct-span',audit,{'packet':{'glosses':[gloss]}},
            {'languages':['Hindi']},self.options,defer_review=True)
        self.assertEqual(good['packet']['translations'][0]['literal_english'],'Rāma rests.')
        self.assertEqual(self.sequence(),['bhakti_literal_translation']*2)

    def test_mixed_defect_and_unresolved_units_keep_typed_hold_without_impossible_component_status(self):
        for mode in ('mixed-units','mixed-missing-issue'):
            with self.subTest(mode=mode):
                self.mode=mode;self.writer_count=1
                candidate={'packet':{'translations':self.writer(),'comparison':[]}}
                call=lambda:pipeline.review_translation(self.root/mode,self.audit,
                    {'packet':{'glosses':self.glosses()}},{'languages':['Hindi']},self.options,candidate,prepared=True)
                if mode=='mixed-units':
                    result=call();review=result['packet']['translations'][-1]['independent_review']
                    self.assertFalse(review['passes']);self.assertTrue(review['human_review_recommended'])
                    self.assertEqual([review['word_judgments'][i]['status'] for i in (6,7)],['defect','unresolved'])
                    self.assertEqual(review['component_judgments']['english']['status'],'unresolved')
                else:
                    with self.assertRaises((ValueError,RuntimeError)):call()
        self.assertEqual(self.sequence(),['bhakti_translation_review']*2)

    def test_accepted_previous_contract_refreshes_review_only_without_inventing_writer_support(self):
        from test_word_accountability_fixtures import previous_word_contract
        original_provider=self.provider
        def legacy(*args,**kwargs):
            response=original_provider(*args,**kwargs)
            for row in response['packet'].get('translations',[]):row.pop('word_support',None)
            for row in response['packet'].get('reviews',[]):row.pop('word_judgments',None)
            return response
        with previous_word_contract(),patch.object(pipeline.gemini,'call',side_effect=legacy):
            previous=self.complete()
        self.assertEqual(self.sequence(),['bhakti_word_glosses','bhakti_literal_translation','bhakti_translation_review'])
        frozen=copy.deepcopy(previous);self.calls=[]
        old_writer=copy.deepcopy(previous[1]['packet']['translations'])
        self.assertTrue(all('word_support' not in row for row in old_writer))
        result=self.complete()
        self.assertEqual(self.sequence(),['bhakti_translation_review'])
        self.assertEqual(result[0]['packet'],previous[0]['packet'])
        self.assertTrue(all('word_support' not in row for row in result[1]['packet']['translations']))
        self.assertEqual(semantic.writer_rows(result[1]['packet']['translations']),semantic.writer_rows(old_writer))
        self.assertTrue(all(row['independent_review']['word_judgments'] for row in result[1]['packet']['translations']))
        count=len(self.calls);self.assertEqual(self.complete(),result);self.assertEqual(len(self.calls),count)
        self.assertEqual(previous,frozen)

    def test_medium_writer_uses_existing_bounded_children_without_extra_stages(self):
        source=self.lines[0];gloss=self.glosses()[0];draft=self.writer()[0]
        lines=[];glosses=[];rows=[]
        for i in range(21):
            line=copy.deepcopy(source);line['id']='line'+str(i);line.pop('performed_context',None);lines.append(line)
            word=copy.deepcopy(gloss);word['id']=line['id'];glosses.append(word)
            row=copy.deepcopy(draft);row['id']=line['id']
            for record in row['word_support']:
                for reference in record['references']:reference['line_id']=line['id']
            rows.append(row)
        self.options.semantic_full_source=lines
        self.options.semantic_performance_order=[{'ref':line['id'],'repeats':1} for line in lines]
        calls=[]
        def provider(model,key,prompt,**kw):
            self.assertEqual(kw['schema_name'],'bhakti_translation_batch')
            ids=[row['id'] for row in parsed(prompt,'TARGET audited source lines (return these IDs only):\n')]
            calls.append(ids)
            return {'packet':{'translations':[row for row in rows if row['id'] in ids],
                'comparison':[{'id':line_id,'supplied':'','chosen':'','material_change':False,'reason':''} for line_id in ids]}}
        audit={'packet':{'verified_lines':lines,'metadata':{'languages':['Hindi']},
            'performance_order':self.options.semantic_performance_order}}
        with patch.object(pipeline.gemini,'call',side_effect=provider):
            result=pipeline.translate(self.root/'medium',audit,{'packet':{'glosses':glosses}},
                {'languages':['Hindi']},self.options,candidate_only=True,defer_review=True)
            self.assertEqual([len(ids) for ids in calls],[10,10,1])
            self.assertEqual([row['id'] for row in result['packet']['translations']],[line['id'] for line in lines])
            count=len(calls)
            self.assertEqual(pipeline.translate(self.root/'medium',audit,{'packet':{'glosses':glosses}},
                {'languages':['Hindi']},self.options,candidate_only=True,defer_review=True),result)
            self.assertEqual(len(calls),count)

    def test_tokenizer_preserves_apostrophe_contributions_hyphen_parts_unicode_and_repetitions(self):
        module=importlib.import_module('bhakti_word_accountability')
        text="Rāma's light-filled home isn't empty—no, no. Cafe\u0301."
        units=module.english_units(text)
        self.assertEqual([x['text'] for x in units],["Rāma's",'light','filled','home',"isn't",'empty','no','no','Cafe\u0301'])
        self.assertEqual([x['unit'] for x in units],list(range(9)))
        for unit in units:self.assertEqual(text[unit['start']:unit['end']],unit['text'])

if __name__=='__main__':unittest.main()

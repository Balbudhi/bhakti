"""Existing-reader adapter contract. Actual coordinator/storage; provider-only fixture."""
import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import bhakti_library_pass as library
import test_library_execution as fixtures
def review(line_id, issues=None):
    issues=issues or []
    result=fixtures.review(line_id, issues)
    if library.pipeline.REVIEW_TASK_VERSION >= 3:
        kinds={issue['kind'] for issue in issues}
        result['component_judgments']={key:{'status':'defect' if kinds & triggers else 'supported',
            'reason':'The supplied source and this component were checked independently.'}
            for key,triggers in {'gloss':{'gloss_sense'},'frame':{'frame_relation'},
                                 'english':{'english_realization','line_scope'}}.items()}
    return result
from test_sense_decisions import decisions_for


def block(prompt, marker):
    return json.JSONDecoder().raw_decode(prompt.split(marker,1)[1].lstrip())[0]

class SharedExistingReaderTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.TargetedRepairExecutionTests('runTest');self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.directory;self.options=self.fixture.options
        self.options.semantic_repair_rounds=1;self.options.semantic_repair_seconds=120
        self.data=self.fixture.data;self.before=None;self.calls=[];self.mode='clean';self.post_count=0;self.writer_count=0;self.gloss_count=0
        self.data['SONG_LINES']['one'].update(source='मन मेरा',roman='mana merā',
            english='{0:body }{1:mine}',grammarNote='Original grammar, retain exactly.',
            sourceWords=[{'text':'मन','wordIndices':[0]},{'text':'मेरा','wordIndices':[1]}],
            words=[{'roman':'mana','gloss':'body','editorial':'keep this field'},
                   {'roman':'merā','gloss':'mine','editorial':'keep unapproved token'}])
        self.fixture.issue.update(kind='gloss_sense',explanation='The noun means mind, not body.',
            evidence='The source मन has the cognitive noun sense.')
        self.before=copy.deepcopy(self.data)
        for p in (patch.dict(os.environ,{'BHAKTI_AUTO_LEXICAL':'0','BHAKTI_API_RUN_LEDGER':str(self.root/'ledger.json'),
                                         'BHAKTI_API_RUN_BUDGET_USD':'2'}),
                  patch.object(library.pipeline.gemini,'key',return_value='OFFLINE'),
                  patch.object(library.pipeline.gemini,'call',side_effect=self.provider)):
            p.start();self.addCleanup(p.stop)
        self.pre=self.fixture.execute(self.data)
        self.calls=[]

    def issue(self,kind):
        result=copy.deepcopy(self.fixture.issue);result['kind']=kind
        return result

    def provider(self,model,key,prompt,**kwargs):
        schema=kwargs['schema_name'];self.calls.append({'schema':schema,'model':model,'prompt':prompt,'kwargs':kwargs})
        if schema=='bhakti_translation_review':
            evidence=block(prompt,'EVIDENCE:\n')
            original=block(prompt,'ORIGINAL READER ROWS FOR REPAIR COMPARISON:\n')
            if not original:
                return {'packet':{'reviews':[review(e['source']['id'],[self.fixture.issue] if e['source']['id']=='one' else []) for e in evidence]}}
            self.post_count+=1
            if self.mode=='malformed-review' and self.post_count==1:return {'packet':{'reviews':[]}}
            if self.mode=='unknown-all' or (self.mode=='unknown-review' and self.post_count==1):
                raise library.pipeline.gemini.model_routes.UnitTransportFailure('unknown-outcome',worker_terminated=True)
            rows=[]
            obligations=block(prompt,'FINDING OBLIGATIONS FOR THIS REPAIR:\n')
            for item in evidence:
                issue=[]
                if self.mode=='english-failure' and self.post_count==1:issue=[self.issue('english_realization')]
                if self.mode=='source-failure' and self.post_count==1:
                    defect=self.issue('frame_relation')
                    defect.update(explanation='The nominal phrase contains no rising sun or emergence action.',
                                  evidence='मन मेरा denotes my mind; the frame invents a rising sun.')
                    issue=[defect]
                if self.mode=='scope-expansion' and self.post_count==1:issue=[copy.deepcopy(self.expansion_issue)]
                row=review(item['source']['id'],issue)
                row['finding_dispositions']=[{'finding_id':f['finding_id'],'status':'unresolved' if issue else 'repaired',
                    'source_quote':f['issue']['references'][0]['source_quote'],
                    'explanation':'The exact noun and linked English are corrected.' if not issue else 'The same exact source defect remains.'}
                    for f in obligations if item['source']['id'] in f['issue']['target_line_ids']]
                rows.append(row)
            return {'packet':{'reviews':rows}}
        is_gloss='word_gloss' in schema
        targets=block(prompt,'TARGET LYRICS (return these IDs only):\n' if is_gloss else 'TARGET audited source lines (return these IDs only):\n')
        if is_gloss:
            self.gloss_count+=1
            frame={key:'' for key in library.pipeline.SEMANTIC_FRAME_FIELDS}
            if self.mode=='source-failure':
                frame.update(action_or_state='a sun rises' if self.gloss_count==1 else 'nominal possession; no action',
                    literal_image_and_agency='rising sun' if self.gloss_count==1 else 'the speaker’s mind')
            senses=decisions_for(targets,['Hindi'])
            return {'packet':{'glosses':[{'id':line['id'],
                'word_glosses':[{'roman':'mana','gloss':'mind','concept_key':'','preserve_in_english':False},
                               {'roman':'merā','gloss':'UNAPPROVED REWRITE','concept_key':'','preserve_in_english':False}],
                'semantic_frame':copy.deepcopy(frame),
                'sense_decisions':senses[line['id']],'grammar_note':'UNAPPROVED GRAMMAR REWRITE','uncertainty':''}
                for line in targets]}}
        self.writer_count+=1
        english='body mine' if self.mode=='english-failure' and self.writer_count==1 else 'mind mine'
        return {'packet':{'translations':[{'id':line['id'],'literal_english':english,
            'segments':[{'text':english.split()[0]+' ','word_indices':[0]},{'text':'mine','word_indices':[1]}],
            'fidelity':{'agency_and_image_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[]},
            'human_review_recommended':False,'material_alternatives':[],'choice_note':'','uncertainty':''}
            for line in targets],'comparison':[]}}

    def repair(self):return self.fixture.repair(self.pre)
    def stages(self):return ['gloss' if 'word_gloss' in c['schema'] else 'review' if c['schema']=='bhakti_translation_review' else 'writer' for c in self.calls]

    def assert_public_scope(self,result):
        self.assertEqual(self.data,self.before)
        self.assertEqual(result['reader']['SONG_LINES']['two'],self.before['SONG_LINES']['two'])
        self.assertEqual(result['reader']['SONG_META'],self.before['SONG_META'])
        self.assertEqual(result['reader']['SONG_TIMINGS'],self.before['SONG_TIMINGS'])
        self.assertEqual(result['reader']['SONG_SEQUENCE'],self.before['SONG_SEQUENCE'])
        line=result['reader']['SONG_LINES']['one'];original=self.before['SONG_LINES']['one']
        self.assertEqual(line['grammarNote'],original['grammarNote'])
        self.assertEqual(line['words'][1],original['words'][1])
        self.assertEqual(line['words'][0],{**original['words'][0],'gloss':'mind'})
        self.assertEqual(line['sourceWords'],original['sourceWords'])

    def test_real_library_calls_shared_coordinator_and_initial_feedback_reaches_first_flash(self):
        with patch.object(library.pipeline,'complete_semantics',wraps=library.pipeline.complete_semantics) as complete:
            result=self.repair()
        self.assertEqual(complete.call_count,1)
        self.assertEqual(self.stages(),['gloss','writer','review'])
        self.assertEqual(self.calls[0]['model'],self.options.model)
        feedback=block(self.calls[0]['prompt'],'REPAIR FEEDBACK:\n')
        self.assertIn(self.fixture.issue,feedback)
        self.assert_public_scope(result)

    def test_initial_authenticated_repair_context_is_not_dropped_at_round_zero(self):
        lines,glosses,drafts=library.reader_evidence(self.data)
        local=copy.copy(self.options)
        local.semantic_full_source=lines
        local.semantic_context_evidence=[{'source':a,'gloss':b,'draft':c} for a,b,c in zip(lines,glosses,drafts)]
        local.semantic_performance_order=copy.deepcopy(self.data['SONG_SEQUENCE'])
        local.semantic_original_reader={'one':copy.deepcopy(self.data['SONG_LINES']['one'])}
        local.semantic_confirmed_issues=[self.fixture.issue]
        local.semantic_repair_findings=[f for f in self.pre['finding_snapshot']['findings'] if f['kind']=='defect']
        local.semantic_initial_repair={'version':1,'reader_digest':self.pre['reader_digest'],
            'dependency_fingerprint':'frozen-recording-and-source',
            'original_reader':copy.deepcopy(self.data),'pre_review':copy.deepcopy(self.pre),
            'target_line_ids':['one'],'gloss_word_indices':{'one':[0]}}
        local.unit_deadline_at=self.fixture.deadline
        audited={'packet':{'verified_lines':[lines[0]],'metadata':{'languages':['Hindi']},
                           'performance_order':[self.data['SONG_SEQUENCE'][0]]}}
        try:
            library.pipeline.complete_semantics(self.root/'direct'/'fixture',audited,
                {'slug':'fixture','languages':['Hindi']},local)
        finally:
            first=next(c for c in self.calls if 'word_gloss' in c['schema'])
            self.assertEqual(first['model'],self.options.model)
            self.assertIn('REPAIR FEEDBACK:\n',first['prompt'])
            self.assertIn(self.fixture.issue,block(first['prompt'],'REPAIR FEEDBACK:\n'))

    def test_owner_english_cannot_be_replaced_by_an_automatic_repair(self):
        protected={key:library.editorial_baselines.plain_english(row['english']) for key,row in self.data['SONG_LINES'].items()}
        with self.assertRaises((ValueError,RuntimeError)):
            library.repair_current_reader(self.data,slug='fixture',pre_review=self.pre,
                workspace=self.root/'song',route_dir=self.root/'routes',options=self.options,
                dependency_fingerprint='frozen-recording-and-source',deadline_at=self.fixture.deadline,
                protected_english=protected)
        self.assertEqual(self.data,self.before)
        self.assertFalse((self.root/'song/data.js').exists())

    def test_authorized_gloss_projection_precedes_both_writer_and_reviewer(self):
        result=self.repair();self.assert_public_scope(result)
        writer=next(c for c in self.calls if c['schema']!='bhakti_translation_review' and 'word_gloss' not in c['schema'])
        gloss=block(writer['prompt'],'TARGET word gloss record:\n')[0]
        reviewer=next(c for c in self.calls if c['schema']=='bhakti_translation_review')
        reviewed=block(reviewer['prompt'],'EVIDENCE:\n')[0]['gloss']
        for supplied in (gloss,reviewed):
            self.assertEqual(supplied['word_glosses'],result['reader']['SONG_LINES']['one']['words'])
            self.assertEqual(supplied['grammar_note'],self.before['SONG_LINES']['one']['grammarNote'])

    def test_malformed_reviewer_escalates_only_reviewer_without_repaying_gloss_or_writer(self):
        self.mode='malformed-review';result=self.repair()
        self.assertEqual(self.stages(),['gloss','writer','review','review'])
        self.assertEqual([c['model'] for c in self.calls],[self.options.model]*3+[self.options.pro_model])
        self.assert_public_scope(result)

    def test_valid_english_issue_repairs_english_only_and_then_zero_call_resume(self):
        self.mode='english-failure';result=self.repair()
        self.assertEqual(self.stages(),['gloss','writer','review','writer','review'])
        self.assertEqual([c['model'] for c in self.calls if c['schema']!='bhakti_translation_review' and 'word_gloss' not in c['schema']],
                         [self.options.model,self.options.pro_model])
        frozen=[(p,p.read_bytes()) for p in self.root.rglob('route-state.json')]
        count=len(self.calls);again=self.repair()
        self.assertEqual(again,result);self.assertEqual(len(self.calls),count)
        self.assertTrue(all(p.read_bytes()==raw for p,raw in frozen));self.assert_public_scope(result)

    def test_valid_source_issue_routes_gloss_only_to_pro_preserving_projection(self):
        self.mode='source-failure';result=self.repair()
        self.assertEqual(self.stages(),['gloss','writer','review','gloss','writer','review'])
        self.assertEqual([c['model'] for c in self.calls if 'word_gloss' in c['schema']],[self.options.model,self.options.pro_model])
        self.assertEqual([c['model'] for c in self.calls if c['schema']!='bhakti_translation_review' and 'word_gloss' not in c['schema']],
                         [self.options.model,self.options.model])
        frame=result['glosses']['packet']['glosses'][0]['semantic_frame']
        self.assertEqual(frame['action_or_state'],'nominal possession; no action')
        self.assertEqual(frame['literal_image_and_agency'],'the speaker’s mind')
        reviewed=[block(c['prompt'],'EVIDENCE:\n')[0]['gloss']['semantic_frame'] for c in self.calls if c['schema']=='bhakti_translation_review']
        self.assertEqual(reviewed[0]['literal_image_and_agency'],'rising sun')
        self.assertEqual(reviewed[-1],frame)
        self.assert_public_scope(result)

    def test_new_unauthorized_word_issue_holds_before_paid_scope_expansion(self):
        self.data['SONG_LINES']['one']['words'][1]['gloss']='your'
        self.data['SONG_LINES']['one']['english']='{0:body }{1:yours}'
        self.before=copy.deepcopy(self.data)
        self.pre=self.fixture.execute(self.data);self.calls=[]
        self.expansion_issue=self.issue('gloss_sense')
        self.expansion_issue['references']=[{'line_id':'one','domain':'word_glosses','word_indices':[1],'source_quote':'मेरा'}]
        self.expansion_issue.update(explanation='merā denotes first-person possession, not your.',
                                    evidence='The source possessive मेरा is first person.')
        journal=Path(self.pre['finding_journal_path']);journal_bytes=journal.read_bytes()
        self.mode='scope-expansion'
        with self.assertRaises((ValueError,RuntimeError)):self.repair()
        self.assertEqual(self.stages(),['gloss','writer','review'])
        self.assertEqual(self.data,self.before);self.assertEqual(journal.read_bytes(),journal_bytes)
        retained=[]
        def visit(value):
            if isinstance(value,dict):
                if value==self.expansion_issue:retained.append(value)
                for item in value.values():visit(item)
            elif isinstance(value,list):
                for item in value:visit(item)
        for path in self.root.rglob('*.json'):
            visit(json.loads(path.read_text()))
        self.assertTrue(retained,'The exact out-of-scope issue must remain in retained candidate/hold evidence')
        count=len(self.calls)
        with self.assertRaises((ValueError,RuntimeError)):self.repair()
        self.assertEqual(len(self.calls),count)
        self.assertFalse((self.root/'song/data.js').exists())

    def legacy_repair(self):
        namespace=dict(vars(library))
        fixture=Path(__file__).parent / 'fixtures/library_shared_semantic/legacy_repair.py'
        exec(compile(fixture.read_text(),str(fixture),'exec'),namespace)
        return namespace['repair_current_reader'](self.data,slug='fixture',pre_review=self.pre,
            workspace=self.root/'song',route_dir=self.root/'routes',options=self.options,
            dependency_fingerprint='frozen-recording-and-source',deadline_at=self.fixture.deadline)

    def test_exact_legacy_accepted_route_reuses_proven_result_without_paid_reconstruction(self):
        old=self.legacy_repair();count=len(self.calls)
        states={p:p.read_bytes() for p in self.root.rglob('route-state.json')}
        result=self.repair()
        self.assertEqual(result,old);self.assertEqual(len(self.calls),count)
        self.assertTrue(all(p.read_bytes()==data for p,data in states.items()))
        self.assert_public_scope(result)

    def test_unknown_legacy_route_cannot_be_hidden_by_new_coordinator_identity(self):
        self.mode='unknown-all'
        with self.assertRaises((ValueError,RuntimeError)):self.legacy_repair()
        count=len(self.calls);states={p:p.read_bytes() for p in self.root.rglob('route-state.json')}
        self.mode='clean'
        with self.assertRaises((ValueError,RuntimeError)):self.repair()
        self.assertEqual(len(self.calls),count)
        self.assertTrue(all(p.read_bytes()==data for p,data in states.items()))
        self.assertEqual(self.data,self.before)

    def version_two_history(self,unknown=False):
        # Use a fresh private history so this fixture does not inherit setUp's
        # current-version audit/journal; every receipt is produced by old code.
        self.root=self.root/'v2-history';self.root.mkdir()
        self.fixture.directory=self.root
        with patch.object(library.pipeline,'REVIEW_TASK_VERSION',2),patch.object(library.pipeline,'PRIOR_REVIEW_TASK_VERSIONS',(0,1)):
            self.pre=self.fixture.execute(self.data)
            self.mode='unknown-all' if unknown else 'clean'
            if unknown:
                with self.assertRaises((ValueError,RuntimeError)):self.legacy_repair()
                result=None
            else:result=self.legacy_repair()
        self.mode='clean'
        return result

    def test_unknown_v2_route_cannot_be_abandoned_under_review_v3(self):
        self.version_two_history(unknown=True)
        count=len(self.calls);states={p:p.read_bytes() for p in self.root.rglob('route-state.json')}
        with patch.object(library.pipeline,'REVIEW_TASK_VERSION',3),patch.object(library.pipeline,'PRIOR_REVIEW_TASK_VERSIONS',(0,1,2)):
            with self.assertRaises((ValueError,RuntimeError)):self.repair()
        self.assertEqual(len(self.calls),count)
        self.assertTrue(all(p.read_bytes()==raw for p,raw in states.items()))
        self.assertEqual(self.data,self.before)

    def test_accepted_v2_route_needs_current_review_or_explicit_hold_without_regloss(self):
        old=self.version_two_history();self.assertEqual(old['post_review']['review_task_version'],2)
        count=len(self.calls);states={p:p.read_bytes() for p in self.root.rglob('route-state.json')}
        with patch.object(library.pipeline,'REVIEW_TASK_VERSION',3),patch.object(library.pipeline,'PRIOR_REVIEW_TASK_VERSIONS',(0,1,2)):
            try:result=self.repair()
            except (ValueError,RuntimeError):
                self.assertEqual(len(self.calls),count,'Unsupported historical migration must hold before new calls')
            else:
                self.assertEqual(result['post_review']['review_task_version'],3)
                new=self.calls[count:]
                self.assertEqual([c['schema'] for c in new],['bhakti_translation_review'])
                self.assertEqual(result['reader'],old['reader'])
        self.assertTrue(all(p.read_bytes()==raw for p,raw in states.items()))
        self.assertEqual(self.data,self.before)

    def test_ordinary_fresh_gloss_still_rejects_missing_preservation_fields(self):
        lines,_,_=library.reader_evidence(self.data)
        target=[lines[0]];decisions=decisions_for(target,['Hindi'])
        rows=[{'id':'one','word_glosses':[{'roman':'mana','gloss':'mind'},{'roman':'merā','gloss':'mine'}],
            'semantic_frame':{key:'' for key in library.pipeline.SEMANTIC_FRAME_FIELDS},
            'grammar_note':'','uncertainty':'','sense_decisions':decisions['one']}]
        self.assertTrue(library.pipeline.fresh_gloss_contract_errors(target,rows,['Hindi']))
        self.assertTrue(library.pipeline.bhakti_semantic_repair.scoped_gloss_contract_errors(
            library.pipeline,target,rows,['Hindi'],self.options))

    def test_malformed_existing_preservation_value_is_not_defaulted(self):
        self.data['SONG_LINES']['one']['words'][0]['preserve_in_english']='WRONG'
        self.before=copy.deepcopy(self.data);self.pre=self.fixture.execute(self.data);self.calls=[]
        with self.assertRaises((ValueError,RuntimeError)):self.repair()
        self.assertEqual(self.stages(),['gloss'])
        self.assertEqual(self.data,self.before)
        self.assertEqual(self.data['SONG_LINES']['one']['words'][0]['preserve_in_english'],'WRONG')

    def test_changed_retained_journal_blocks_before_new_paid_stages(self):
        self.pre['finding_snapshot']['findings'][0]['issue']['references'][0]['word_indices']=[1]
        with self.assertRaises((ValueError,RuntimeError)):self.repair()
        self.assertFalse(self.calls);self.assertEqual(self.data,self.before)

    def test_expired_deadline_holds_without_starting_new_scope(self):
        self.fixture.deadline=0
        with self.assertRaises((ValueError,RuntimeError)):self.repair()
        self.assertFalse(self.calls);self.assertEqual(self.data,self.before)

if __name__=='__main__':unittest.main()

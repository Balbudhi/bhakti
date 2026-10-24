"""Grammar-note scope specification through actual callers and persisted guards.
No implementation overlays and no model/network calls. Provider fixture only.
"""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import bhakti_library_pass as library
import bhakti_model_routes as routes
import bhakti_candidate_guard as guard
import bhakti_semantic_repair as semantic
import test_library_execution as fixtures
from test_library_shared_semantic import block, review
from test_sense_decisions import decisions_for
from test_word_accountability_fixtures import account_response

OLD_NOTE = 'The noun denotes a physical limb.'
NEW_NOTE = 'The noun denotes the speaker’s mind.'


class GrammarNoteScopeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.TargetedRepairExecutionTests('runTest'); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.directory; self.options = self.fixture.options
        self.options.semantic_stage_escalation = False
        self.options.semantic_repair_rounds = 1
        self.reader = self.fixture.data
        self.reader['SONG_LINES']['one'].update(source='मन मेरा', roman='mana merā',
            english='{1 :my }{0:mind}', grammarNote=OLD_NOTE,
            sourceWords=[{'text':'मन','wordIndices':[0]},{'text':'मेरा','wordIndices':[1]}],
            words=[{'roman':'mana','gloss':'mind','editorial':'keep noun metadata'},
                   {'roman':'merā','gloss':'my','editorial':'keep possessive metadata'}])
        self.reader['SONG_LINES']['two'].update(english='{0:body}', grammarNote='The noun denotes mind.')
        self.note_issue = {'kind':'frame_relation','target_line_ids':['one'],
            'references':[{'line_id':'one','domain':'grammar_note','word_indices':[0],
                'source_quote':'मन','note_quote':OLD_NOTE}],
            'explanation':'The note incorrectly describes the cognitive noun as a physical limb.',
            'evidence':'मन and its selected mind sense describe the mind; मेरा marks the possessor.',
            'hold_reason':'','needed_evidence':''}
        self.english_issue = copy.deepcopy(self.fixture.issue)
        self.english_issue['target_line_ids']=['two']
        self.english_issue['references'][0]['line_id']='two'
        self.initial = {'one':[self.note_issue], 'two':[self.english_issue]}
        self.calls=[]; self.mode='clean'; self.writer_count=0; self.writer_outputs=[]; self.post_inputs=[]; self.post_responses=[]; self.pre=None
        provider=patch.object(library.pipeline.gemini,'call',side_effect=self.provider)
        provider.start();self.addCleanup(provider.stop)
        key=patch.object(library.pipeline.gemini,'key',return_value='OFFLINE')
        key.start();self.addCleanup(key.stop)

    def provider(self, model, key, prompt, **kw):
        schema=kw['schema_name'];self.calls.append((schema,model,prompt))
        if schema=='bhakti_translation_review':
            evidence=block(prompt,'EVIDENCE:\n')
            original=block(prompt,'ORIGINAL READER ROWS FOR REPAIR COMPARISON:\n')
            if not original:
                return account_response({'packet':{'reviews':[review(row['source']['id'],copy.deepcopy(self.initial.get(row['source']['id'],[]))) for row in evidence]}}, prompt, schema)
            self.post_inputs.append(copy.deepcopy(evidence))
            obligations=block(prompt,'FINDING OBLIGATIONS FOR THIS REPAIR:\n')
            rows=[]
            for item in evidence:
                line_id=item['source']['id'];issues=[]
                if self.mode=='second-english-round' and line_id=='two' and item['draft']['literal_english']=='body':
                    issues=[copy.deepcopy(self.english_issue)]
                if self.mode=='stale-post-note-quote' and line_id=='one':
                    issues=[copy.deepcopy(self.note_issue)]
                if self.mode=='new-note-outside-scope' and line_id=='two':
                    issues=[copy.deepcopy(self.later_note_issue)]
                row=review(line_id,issues)
                row['finding_dispositions']=[{'finding_id':finding['finding_id'],
                    'status':'unresolved' if issues and self.mode!='new-note-outside-scope' else 'repaired',
                    'source_quote':finding['issue']['references'][0]['source_quote'],
                    'explanation':'The exact source-linked defect has been corrected.' if not issues else 'The English still names the body instead of the mind.'}
                    for finding in obligations if line_id in finding['issue']['target_line_ids']]
                rows.append(row)
            response=account_response({'packet':{'reviews':rows}}, prompt, schema)
            self.post_responses.append(copy.deepcopy(response))
            return response
        is_gloss='word_gloss' in schema
        lines=block(prompt,'TARGET LYRICS (return these IDs only):\n' if is_gloss else 'TARGET audited source lines (return these IDs only):\n')
        if is_gloss:
            senses=decisions_for(lines,['Hindi']);rows=[]
            for line in lines:
                old=self.reader['SONG_LINES'][line['id']]
                words=[{'roman':w['roman'],'gloss':w['gloss'],'concept_key':'','preserve_in_english':False} for w in old['words']]
                if self.mode=='unapproved-popup' and line['id']=='one':words[0]['gloss']='a physical limb'
                rows.append({'id':line['id'],'word_glosses':words,
                    'semantic_frame':{field:'' for field in library.pipeline.SEMANTIC_FRAME_FIELDS},
                    'sense_decisions':senses[line['id']], 'uncertainty':'',
                    'grammar_note':NEW_NOTE if line['id']=='one' else 'UNAUTHORIZED NOTE REWRITE'})
            return {'packet':{'glosses':rows}}
        self.writer_count+=1;rows=[]
        for line in lines:
            if line['id']=='one':
                text='my mind';segments=[{'text':'my ','word_indices':[1]},{'text':'mind','word_indices':[0]}]
                if self.mode=='changed-locked-english':
                    text='my consciousness';segments[1]['text']='consciousness'
                if self.mode=='changed-locked-segments':
                    segments=[{'text':'my ','word_indices':[0]},{'text':'mind','word_indices':[1]}]
            else:
                text='body' if self.mode=='second-english-round' and self.writer_count==1 else 'mind'
                segments=[{'text':text,'word_indices':[0]}]
            rows.append({'id':line['id'],'literal_english':text,'segments':segments,
                'fidelity':{'agency_and_image_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[]},
                'human_review_recommended':False,'material_alternatives':[],'choice_note':'','uncertainty':''})
        response = account_response({'packet':{'translations':rows,'comparison':[]}}, prompt, schema)
        self.writer_outputs.append(copy.deepcopy(response))
        return response

    def audit(self):
        self.pre=self.fixture.execute(self.reader)
        self.audit_calls=len(self.calls)
        return self.pre

    def repair(self, protected=None):
        return library.repair_current_reader(self.reader,slug='fixture',pre_review=self.pre,
            workspace=self.root/'song',route_dir=self.root/'routes',options=self.options,
            dependency_fingerprint='frozen-recording-and-source',deadline_at=self.fixture.deadline,
            protected_english=protected)

    def kinds_after_audit(self):
        return ['gloss' if 'word_gloss' in name else 'review' if name=='bhakti_translation_review' else 'writer'
                for name,_,_ in self.calls[self.audit_calls:]]

    def assert_exact_other_fields(self,result,before):
        for key in ('SONG_META','SONG_SEQUENCE','SONG_TIMINGS'):
            self.assertEqual(result['reader'][key],before[key])
        expected=copy.deepcopy(before)
        expected['SONG_LINES']['one']['grammarNote']=NEW_NOTE
        expected['SONG_LINES']['two']['english']='{0:mind}'
        self.assertEqual(result['reader'],expected)
        self.assertEqual(self.reader,before)
        self.assertFalse((self.root/'song/data.js').exists())

    def test_actual_mixed_note_and_english_repair_preserves_other_fields_then_resumes_free(self):
        before=copy.deepcopy(self.reader);self.audit()
        snapshot=copy.deepcopy(self.pre['finding_snapshot'])
        with patch.object(library.pipeline,'complete_semantics',wraps=library.pipeline.complete_semantics) as complete:
            result=self.repair()
        scope=complete.call_args.args[3].semantic_initial_repair
        self.assertEqual(scope['version'],2)
        self.assertEqual(scope['grammar_note_line_ids'],['one'])
        self.assertEqual(scope['english_line_ids'],['two'])
        self.assertEqual(scope['gloss_word_indices'],{})
        self.assert_exact_other_fields(result,before)
        self.assertEqual(self.kinds_after_audit(),['gloss','writer','review'])
        self.assertEqual(len(result['authorization']['resolved_findings']),2)
        self.assertEqual(result['authorization']['pending_findings'],[])
        self.assertEqual(self.post_inputs[0][0]['gloss']['grammar_note'],NEW_NOTE)
        self.assertEqual(self.post_inputs[0][0]['draft']['segments'],[
            {'text':'my ','word_indices':[1]},{'text':'mind','word_indices':[0]}])
        self.assertEqual(self.pre['finding_snapshot'],snapshot)
        saved={str(p):p.read_bytes() for p in self.root.rglob('route-state.json')};count=len(self.calls)
        self.assertEqual(self.repair(),result);self.assertEqual(len(self.calls),count)
        self.assertEqual({str(p):p.read_bytes() for p in self.root.rglob('route-state.json')},saved)

    def test_original_note_quote_survives_corrected_note_and_later_feedback(self):
        self.mode='second-english-round';self.audit();result=self.repair()
        self.assertEqual(self.kinds_after_audit(),['gloss','writer','review','writer','review'])
        self.assertEqual([rows[0]['gloss']['grammar_note'] for rows in self.post_inputs],[NEW_NOTE,NEW_NOTE])
        retained=self.pre['finding_snapshot']['findings'][0]['issue']['references'][0]['note_quote']
        self.assertEqual(retained,OLD_NOTE)
        # Exercise the real inherited-lookup validator with an already
        # authenticated original obligation and the corrected current glossary.
        lines,_,_=library.reader_evidence(self.reader)
        packet=copy.deepcopy(result['translations']);packet['automatic_lexical_feedback']=[self.note_issue]
        audited={'packet':{'verified_lines':lines,'metadata':{'languages':['Hindi']},
                           'performance_order':self.reader['SONG_SEQUENCE']}}
        options,glosses=semantic.derived_support_view(library.pipeline,self.root/'lookup',audited,
            result['glosses'],packet,self.options)
        self.assertEqual(glosses['packet']['glosses'][0]['grammar_note'],NEW_NOTE)
        self.assertEqual(options.semantic_repair_feedback[0]['references'][0]['note_quote'],OLD_NOTE)
        count=len(self.calls);self.repair();self.assertEqual(len(self.calls),count)

    def assert_writer_violation_before_review(self,mode,*,path='routed'):
        if path == 'direct':
            self.audit()
            with patch.object(library.pipeline,'complete_semantics',wraps=library.pipeline.complete_semantics) as complete:
                accepted=self.repair()
            _,audited,job,options=complete.call_args.args
            directory=self.root/'direct-admission'
            self.mode=mode; self.calls=[]; self.writer_outputs=[]; self.post_inputs=[]; self.audit_calls=0
            def invoke():
                return library.pipeline.translate(directory,audited,accepted['glosses'],job,options,candidate_only=True)
            with self.assertRaises((ValueError,RuntimeError)):invoke()
            self.assertEqual(self.kinds_after_audit(),['writer'])
            self.assertEqual(self.post_inputs,[])
            candidate_path=directory/'.transcription/pipeline/translation-candidate.json'
            candidate=json.loads(candidate_path.read_text())
            self.assertEqual(candidate['packet']['translations'],self.writer_outputs[0]['packet']['translations'])
            self.assert_rejected_writer_row(candidate['packet']['translations'],mode)
            retained=candidate_path.read_bytes();count=len(self.calls)
            with self.assertRaises((ValueError,RuntimeError)):invoke()
            self.assertEqual(len(self.calls),count)
            self.assertEqual(candidate_path.read_bytes(),retained)
            return
        self.mode=mode;self.audit()
        with self.assertRaises((ValueError,RuntimeError)):self.repair()
        self.assertEqual(self.kinds_after_audit(),['gloss','writer'])
        self.assertEqual(self.post_inputs,[])
        writer_routes = [(path, json.loads(path.read_text()))
                         for path in self.root.rglob('route-state.json')
                         if json.loads(path.read_text()).get('unit_id', '').endswith(':semantic-writer')]
        self.assertEqual(len(writer_routes), 1)
        state_path, state = writer_routes[0]
        # Validate the actual persisted route and candidate hash, not merely
        # another stage's candidate.json (the audit has one too).
        checked = routes.read_unit_cache(state_path)
        self.assertEqual(checked['state'], state)
        self.assertEqual(state['status'], 'unresolved')
        self.assertEqual(len(state['attempts']), 1)
        self.assertEqual(state['attempts'][0]['status'], 'quality-failed')
        candidate_path = state_path.parent / 'flash' / 'candidate.json'
        candidate = json.loads(candidate_path.read_text())
        self.assertEqual(len(self.writer_outputs), 1)
        if 'writer_diagnostics' in candidate:
            self.assertEqual(candidate['writer_diagnostics'], self.writer_outputs)
            saved_rows = candidate['writer_diagnostics'][0]['packet']['translations']
        else:
            saved_rows = candidate['packet']['translations']
            self.assertEqual(saved_rows, self.writer_outputs[0]['packet']['translations'])
        self.assert_rejected_writer_row(saved_rows,mode)
        self.assertFalse(any(json.loads(path.read_text()).get('unit_id', '').endswith(':semantic-review')
                             for path in self.root.rglob('route-state.json')))
        retained = {path: path.read_bytes() for path in (state_path, candidate_path)}
        count=len(self.calls)
        with self.assertRaises((ValueError,RuntimeError)):self.repair()
        self.assertEqual(len(self.calls),count)
        self.assertEqual({path: path.read_bytes() for path in retained}, retained)

    def assert_rejected_writer_row(self,saved_rows,mode):
        rejected = next(row for row in saved_rows if row['id'] == 'one')
        self.assertEqual(rejected['literal_english'],
                         'my consciousness' if mode == 'changed-locked-english' else 'my mind')
        self.assertEqual(rejected['segments'],
            [{'text':'my ','word_indices':[1]},{'text':'consciousness','word_indices':[0]}]
            if mode == 'changed-locked-english' else
            [{'text':'my ','word_indices':[0]},{'text':'mind','word_indices':[1]}])

    def test_direct_writer_note_only_text_violation_rejected_before_review(self):
        self.assert_writer_violation_before_review('changed-locked-english',path='direct')

    def test_direct_writer_note_only_segment_violation_rejected_before_review(self):
        self.assert_writer_violation_before_review('changed-locked-segments',path='direct')

    def test_later_review_cannot_quote_old_note_against_corrected_note_evidence(self):
        self.mode='stale-post-note-quote';self.audit()
        with self.assertRaises((ValueError,RuntimeError)) as caught:self.repair()
        self.assertNotIsInstance(caught.exception,semantic.SemanticQualityHold)
        self.assertEqual(self.kinds_after_audit(),['gloss','writer','review'])
        self.assertEqual(self.post_inputs[0][0]['gloss']['grammar_note'],NEW_NOTE)
        review_routes=[(p,json.loads(p.read_text())) for p in self.root.rglob('route-state.json')
                       if json.loads(p.read_text()).get('unit_id','').endswith(':semantic-review')]
        self.assertEqual(len(review_routes),1)
        state_path,state=review_routes[0]
        self.assertEqual(state['status'],'unresolved')
        self.assertEqual(state['attempts'][0]['status'],'quality-failed')
        returned=self.post_responses[0]['packet']['reviews'][0]['issues'][0]
        self.assertEqual(returned['references'][0]['note_quote'],OLD_NOTE)
        self.assertTrue(state['attempts'][0]['issues'])
        count=len(self.calls)
        with self.assertRaises((ValueError,RuntimeError)):self.repair()
        self.assertEqual(len(self.calls),count)

    def test_later_note_defect_on_english_target_is_retained_without_scope_expansion(self):
        self.reader['SONG_LINES']['two']['grammarNote']=OLD_NOTE
        self.later_note_issue=copy.deepcopy(self.note_issue)
        self.later_note_issue['target_line_ids']=['two']
        self.later_note_issue['references'][0]['line_id']='two'
        self.later_note_issue['evidence']='मन and its selected mind sense describe the mind, not a physical limb.'
        self.mode='new-note-outside-scope';self.audit()
        snapshot=copy.deepcopy(self.pre['finding_snapshot'])
        with self.assertRaises(semantic.SemanticQualityHold) as caught:self.repair()
        self.assertEqual(caught.exception.reason,'additional_confirmed_scope_required')
        self.assertEqual(self.kinds_after_audit(),['gloss','writer','review'])
        self.assertIn(self.later_note_issue,caught.exception.issues)
        held=json.loads(Path(caught.exception.candidate_path).read_text())
        two=next(row for row in held['packet']['translations'] if row['id']=='two')
        self.assertEqual(two['literal_english'],'mind')
        self.assertEqual(two['independent_review']['issues'],[self.later_note_issue])
        records=list(self.root.rglob('additional-repair-findings.json'))
        self.assertEqual(len(records),1)
        record=json.loads(records[0].read_text())
        self.assertEqual(record['issues'],[self.later_note_issue])
        self.assertEqual(record['status'],'needs-expanded-confirmed-scope')
        self.assertEqual(self.pre['finding_snapshot'],snapshot)
        count=len(self.calls)
        with self.assertRaises(semantic.SemanticQualityHold) as resumed:self.repair()
        self.assertEqual(resumed.exception.issues,caught.exception.issues)
        self.assertEqual(len(self.calls),count)

    def test_note_only_english_change_rejected_at_writer_admission_before_paid_review(self):
        self.assert_writer_violation_before_review('changed-locked-english')

    def test_note_only_segment_change_rejected_at_writer_admission_before_paid_review(self):
        self.assert_writer_violation_before_review('changed-locked-segments')

    def test_note_finding_never_authorizes_popup_or_unrelated_note_changes(self):
        self.mode='unapproved-popup';before=copy.deepcopy(self.reader);self.audit();result=self.repair()
        self.assert_exact_other_fields(result,before)
        sources,glosses,_=library.reader_evidence(self.reader)
        for field in ('words','grammarNote'):
            candidate=copy.deepcopy(result['reader'])
            if field=='words':candidate['SONG_LINES']['one']['words'][0]['gloss']='physical limb'
            else:candidate['SONG_LINES']['two']['grammarNote']='Unrelated analysis.'
            post=copy.deepcopy(result['post_review']);post['reader_digest']=semantic.digest(candidate)
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'unapproved|unreferenced'):
                guard.authorize_semantic_candidate(self.reader,candidate,source_lines=sources,gloss_rows=glosses,
                    pre_review=self.pre,post_review=post,dependency_fingerprint='frozen-recording-and-source',
                    finding_snapshot=self.pre['finding_snapshot'],allow_partial=True)

    def test_same_target_mixed_note_word_references_cannot_grant_extra_rights(self):
        self.note_issue['references'].append({'line_id':'one','domain':'word_glosses',
            'word_indices':[0],'source_quote':'मन'})
        with self.assertRaises((ValueError,RuntimeError)):self.audit()
        self.assertTrue(self.calls)
        self.assertTrue(all(name=='bhakti_translation_review' for name,_,_ in self.calls))
        self.assertFalse(list(self.root.rglob('semantic-repair-state.json')))

    def test_changed_original_note_quote_cannot_be_authenticated_as_a_finding(self):
        self.note_issue['references'][0]['note_quote']='A different note not supplied to this review.'
        with self.assertRaises((ValueError,RuntimeError)):self.audit()
        self.assertTrue(all(name=='bhakti_translation_review' for name,_,_ in self.calls))

    def test_final_receipt_cannot_clear_unchanged_note_by_changing_authorized_english(self):
        self.reader['SONG_LINES']['one']['english']='{1:my }{0:body}'
        english=copy.deepcopy(self.english_issue);english['target_line_ids']=['one'];english['references'][0]['line_id']='one'
        self.initial={'one':[self.note_issue,english], 'two':[self.english_issue]}
        self.audit();before=copy.deepcopy(self.reader)
        candidate=copy.deepcopy(before);candidate['SONG_LINES']['one']['english']='{1:my }{0:mind}'
        candidate['SONG_LINES']['two']['english']='{0:mind}'
        snapshot=self.pre['finding_snapshot'];rows=[]
        for line_id in ('one','two'):
            row=review(line_id,[])
            row['finding_dispositions']=[{'finding_id':f['finding_id'],'status':'repaired',
                'source_quote':f['issue']['references'][0]['source_quote'],'explanation':'Claimed repaired.'}
                for f in snapshot['findings'] if line_id in f['issue']['target_line_ids']]
            rows.append(row)
        post={'reader_digest':semantic.digest(candidate),'dependency_fingerprint':'frozen-recording-and-source',
            'attempt_id':'independent-adversarial-post','reviews':rows}
        sources,glosses,_=library.reader_evidence(before)
        receipt=guard.authorize_semantic_candidate(before,candidate,source_lines=sources,gloss_rows=glosses,
            pre_review=self.pre,post_review=post,dependency_fingerprint='frozen-recording-and-source',
            finding_snapshot=snapshot,allow_partial=True)
        self.assertEqual([f['issue'] for f in receipt['pending_findings']],[self.note_issue])
        self.assertFalse(receipt['publicationEligible'])
        self.assertEqual(len(receipt['resolved_findings']),2)

    def test_owner_full_population_stays_locked_while_only_one_note_is_corrected(self):
        self.reader['SONG_LINES']['two']['english']='{0:mind}'
        self.initial={'one':[self.note_issue]};self.audit()
        protected={'one':'my mind','two':'mind'}
        result=self.repair(protected=protected)
        self.assertEqual(result['reader']['SONG_LINES']['one']['grammarNote'],NEW_NOTE)
        for line_id in ('one','two'):
            self.assertEqual(result['reader']['SONG_LINES'][line_id]['english'],self.reader['SONG_LINES'][line_id]['english'])
        self.assertEqual(self.kinds_after_audit(),['gloss','writer','review'])

    def test_old_word_domain_scope_does_not_gain_grammar_note_permission(self):
        self.reader['SONG_LINES']['one']['english']='{1:my }{0:body}'
        self.reader['SONG_LINES']['two']['english']='{0:mind}'
        issue=copy.deepcopy(self.english_issue);issue['target_line_ids']=['one'];issue['references'][0]['line_id']='one'
        self.initial={'one':[issue]};self.audit()
        result=self.repair()
        self.assertEqual(result['reader']['SONG_LINES']['one']['grammarNote'],OLD_NOTE)
        self.assertEqual(result['reader']['SONG_LINES']['one']['english'],'{1:my }{0:mind}')
        candidate=copy.deepcopy(result['reader']);candidate['SONG_LINES']['one']['grammarNote']=NEW_NOTE
        sources,glosses,_=library.reader_evidence(self.reader)
        post=copy.deepcopy(result['post_review']);post['reader_digest']=semantic.digest(candidate)
        with self.assertRaisesRegex(ValueError,'unapproved'):
            guard.authorize_semantic_candidate(self.reader,candidate,source_lines=sources,gloss_rows=glosses,
                pre_review=self.pre,post_review=post,dependency_fingerprint='frozen-recording-and-source',
                finding_snapshot=self.pre['finding_snapshot'],allow_partial=True)

    def test_note_reference_shape_and_kind_controls(self):
        sources, glosses, _ = library.reader_evidence(self.reader)
        for change in ('missing-quote', 'empty-quote', 'wrong-kind', 'non-target-note', 'missing-target-note'):
            issue = copy.deepcopy(self.note_issue)
            if change == 'missing-quote': issue['references'][0].pop('note_quote')
            elif change == 'empty-quote': issue['references'][0]['note_quote'] = ''
            elif change == 'wrong-kind': issue['kind'] = 'english_realization'
            elif change == 'non-target-note': issue['references'][0]['line_id'] = 'two'
            else: issue['target_line_ids'] = ['one', 'two']
            with self.subTest(change=change):
                self.assertTrue(semantic.issue_errors(sources, glosses, [issue]))

    def test_forged_note_scope_rejected_before_any_reconstruction(self):
        self.audit()
        with patch.object(library.pipeline, 'complete_semantics', wraps=library.pipeline.complete_semantics) as complete:
            self.repair()
        _, audited, _, options = complete.call_args.args
        for field, forged in (('english_line_ids', ['one', 'two']),
                              ('grammar_note_line_ids', ['one', 'two'])):
            changed = copy.deepcopy(options)
            changed.semantic_initial_repair[field] = forged
            before = len(self.calls)
            with self.subTest(field=field), self.assertRaises((ValueError, RuntimeError)):
                semantic.initial_repair_context(library.pipeline, changed,
                    audited['packet']['verified_lines'], ['Hindi'])
            self.assertEqual(len(self.calls), before)

    def test_direct_translate_rejects_forged_scope_before_writer_dispatch(self):
        self.audit()
        with patch.object(library.pipeline, 'complete_semantics', wraps=library.pipeline.complete_semantics) as complete:
            accepted = self.repair()
        _, audited, job, options = complete.call_args.args
        options = copy.deepcopy(options)
        options.semantic_initial_repair['english_line_ids'] = ['one', 'two']
        self.mode = 'changed-locked-english'
        count = len(self.calls)
        with self.assertRaises((ValueError, RuntimeError)):
            library.pipeline.translate(self.root/'forged-direct', audited, accepted['glosses'], job,
                                       options, candidate_only=True)
        self.assertEqual(len(self.calls), count)

    def test_nonjournal_guard_requires_note_change_even_with_passing_review(self):
        self.reader['SONG_LINES']['one']['english']='{1:my }{0:body}'
        english=copy.deepcopy(self.english_issue)
        english['target_line_ids']=['one'];english['references'][0]['line_id']='one'
        self.initial={'one':[self.note_issue,english], 'two':[self.english_issue]}
        self.audit(); result=self.repair()
        candidate=copy.deepcopy(result['reader'])
        candidate['SONG_LINES']['one']['grammarNote']=OLD_NOTE
        post=copy.deepcopy(result['post_review']);post['reader_digest']=semantic.digest(candidate)
        sources,glosses,_=library.reader_evidence(self.reader)
        with self.assertRaisesRegex(ValueError, 'note.*unchanged|unchanged.*note'):
            guard.authorize_semantic_candidate(self.reader,candidate,source_lines=sources,gloss_rows=glosses,
                pre_review=self.pre,post_review=post,dependency_fingerprint='frozen-recording-and-source')

    def test_nonjournal_note_quote_must_map_to_its_exact_word_indices(self):
        self.audit(); repaired = self.repair()
        sources, glosses, _ = library.reader_evidence(self.reader)
        count = len(self.calls)
        # The otherwise identical, correctly anchored direct guard call is valid.
        guard.authorize_semantic_candidate(self.reader, repaired['reader'],
            source_lines=sources, gloss_rows=glosses, pre_review=self.pre,
            post_review=repaired['post_review'], dependency_fingerprint='frozen-recording-and-source')
        forged = copy.deepcopy(self.pre)
        for issue in forged['issues']:
            if semantic.is_note_issue(issue): issue['references'][0]['source_quote'] = 'मेरा'
        for row in forged['reviews']:
            for issue in row['issues']:
                if semantic.is_note_issue(issue): issue['references'][0]['source_quote'] = 'मेरा'
        # Index0 remains मन; मेरा maps only to index1. The note quotation is unchanged.
        self.assertEqual(semantic.issue_errors(sources, glosses, forged['issues']), [])
        self.assertEqual(semantic.note_reference_errors(forged['issues'], glosses), [])
        with self.assertRaisesRegex(ValueError, 'source quote does not map'):
            guard.authorize_semantic_candidate(self.reader, repaired['reader'],
                source_lines=sources, gloss_rows=glosses, pre_review=forged,
                post_review=repaired['post_review'], dependency_fingerprint='frozen-recording-and-source')
        self.assertEqual(len(self.calls), count)


if __name__=='__main__':unittest.main()

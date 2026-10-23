"""Proposed review contract through real callers/storage; remote answers canned.
No production implementation imported from this private directory.
"""
import copy
import json
import unittest
from unittest.mock import patch
import bhakti_pipeline as pipeline
import bhakti_model_routes as routes
import test_automatic_semantic_repair as fixture

MARKER='WRITER RESERVATIONS:\n'

class ReviewDispositions(unittest.TestCase):
    def setUp(self):
        self.c=fixture.AutomaticRepairTests();self.c.setUp();self.addCleanup(self.c.doCleanups)
        self.c.options.pro_model=routes.PRO_MODEL
        self.c.options.semantic_stage_escalation=False
        self.calls=[];self.first_writer=None;self.mode='resolved';self.review_contexts=[];self.generated_gloss=None
        self.original=self.c.provider
        p=patch.object(pipeline.gemini,'call',side_effect=self.provider);p.start();self.addCleanup(p.stop)

    def provider(self,model,key,prompt,**kw):
        self.calls.append((model,kw['schema_name'],prompt))
        if self.mode=='unknown_history' and kw['schema_name']=='bhakti_literal_translation':
            raise routes.UnitTransportFailure('unknown-outcome',request_id='unknown-writer',worker_terminated=False)
        result=self.original(model,key,prompt,**kw)
        if 'word_gloss' in kw['schema_name']:
            lines=self.c.payload(prompt,'TARGET LYRICS (return these IDs only):\n')
            result['packet']['glosses']=self.c.rows(lines,repaired=True)
            self.generated_gloss=copy.deepcopy(result['packet'])
        elif kw['schema_name']=='bhakti_translation_review':
            context=self.c.payload(prompt,MARKER) if MARKER in prompt else None
            self.review_contexts.append(context)
            for row in result['packet']['reviews']:
                row['component_judgments']={k:{'status':'supported','reason':'The source grammatical subject remains the breath.'} for k in ('gloss','frame','english')}
                reservations=[r for r in (context or {}).get('reservations',[]) if r['line_id']==row['id']]
                if reservations:
                    row['writer_reservation_dispositions']=[{'reservation_id':r['reservation_id'],'status':'resolved',
                         'source_quote':'साँस','explanation':'Both English alternatives preserve the same supported breath agency; no consequential ambiguity remains.'} for r in reservations]
                if self.mode=='missing_component': row['component_judgments'].pop('frame')
                if self.mode=='unsupported_human_hold': row.update(passes=False,human_review_recommended=True,material_choice='abandons or leaves')
                if self.mode=='missing_disposition' or (self.mode=='malformed_review' and len(self.review_contexts)==1): row.pop('writer_reservation_dispositions',None)
                if self.mode in ('repair','hold') and len(self.review_contexts)==1:
                    issue=self.c.issue(row['id']);issue['kind']='english_realization'
                    status='repair_required';component='defect'
                    if self.mode=='hold':
                        issue.update(kind='unresolved_evidence',hold_reason='audited_source_ambiguity',needed_evidence='Source grammatical attachment cannot be resolved from supplied context.')
                        status='unresolved';component='unresolved'
                    row.update(passes=False,human_review_recommended=self.mode=='hold',issues=[issue])
                    row['component_judgments']['english']={'status':component,'reason':issue['explanation']}
                    for d in row.get('writer_reservation_dispositions',[]):d['status']=status
        else:
            rows=result['packet']['translations']
            if self.first_writer is None:
                rows[0].update(human_review_recommended=True,material_alternatives=['My breath leaves me.'],
                    uncertainty='Check whether abandons or leaves changes the source agency.',choice_note='Independent assessment requested.')
                if self.mode=='repair':
                    rows[0]['literal_english']='I abandon my breath.'
                    rows[0]['segments'][0]['text']='I abandon my breath.'
                if self.mode=='pro_history':rows[0]['segments'][0]['word_indices']=[999]
                if self.mode=='early_schema':rows.append('malformed')
                self.first_writer=copy.deepcopy(rows[0])
        result['resolved_model']=model
        return result

    def kinds(self):return [k for _,k,_ in self.calls]
    def complete(self):return self.c.complete()
    def assert_no_acceptance(self):self.assertFalse((self.c.packets/'semantic-acceptance.json').exists())

    def test_resolved_synonym_doubt_accepts_exact_writer_in_three_calls_and_resumes_free(self):
        g,t=self.complete()
        self.assertEqual(self.kinds(),['bhakti_word_glosses','bhakti_literal_translation','bhakti_translation_review'])
        row=t['packet']['translations'][0]
        self.assertEqual({k:row[k] for k in self.first_writer},self.first_writer)
        self.assertTrue(row['human_review_recommended'],'The original flag is retained, not cleared.')
        self.assertTrue(row['uncertainty'])
        self.assertEqual(row['independent_review']['issues'],[])
        context=t['writer_review_context']
        self.assertEqual({k:v for k,v in context.items() if k!='origins'},self.review_contexts[0])
        self.assertNotIn('origins',self.review_contexts[0])
        self.assertEqual(len(context['reservations']),1)
        # Current draft fields are already in EVIDENCE: references, not duplicated bundles.
        current=context['reservations'][0]
        self.assertNotIn('draft',current);self.assertNotIn('uncertainty',current)
        n=len(self.calls);self.assertEqual(self.complete(),(g,t));self.assertEqual(len(self.calls),n)
        originals=[p for p in self.c.packets.rglob('candidate.json') if 'writer' in p.read_text() or 'literal_english' in p.read_text()]
        self.assertTrue(originals)

    def test_long_draft_resolution_keeps_full_population_without_pro_or_writer_repair(self):
        self.c.lines[:]=[{**self.c.lines[0],'id':f'a{i}'} for i in range(41)]
        _,t=self.complete()
        self.assertTrue(all(model==routes.FLASH_MODEL for model,_,_ in self.calls))
        self.assertEqual(self.kinds().count('bhakti_translation_batch'),3)
        self.assertEqual([r['id'] for r in t['packet']['translations']],[r['id'] for r in self.c.lines])
        self.assertEqual(len(t['writer_review_context']['reservations']),1)
        self.assertTrue(next(row for row in t['packet']['translations'] if row['id']==self.first_writer['id'])['human_review_recommended'])
        self.assertEqual(sum(len(x['reservations']) for x in self.review_contexts if x),1,
                         'Only the owning target review receives its reservation, not adjacent review batches.')

    def test_fresh_target_resolution_retains_owner_neighbor_and_plan(self):
        import bhakti_library_source_pass as source
        retained={**copy.deepcopy(self.c.lines[0]),'id':'q'}
        plan={'lines':[retained,*copy.deepcopy(self.c.lines)],'new_target_ids':['a'],
              'performance_order':[{'line_id':'q','occurrence':1},{'line_id':'a','occurrence':1}],
              'reuse_by_id':{'q':{'source':retained['source_text'],'roman':retained['roman'],
                  'sourceLanguage':'hi','english':'{0:OWNER ENGLISH}',
                  'words':[{'roman':t,'gloss':'owner context'} for t in retained['roman'].split()],
                  'sourceWords':[{'text':token,'wordIndices':[i]} for i,token in enumerate(retained['source_text'].split())]}}}
        original=copy.deepcopy(plan)
        result=source.process_new_targets(self.c.song,plan,{'languages':['Hindi']},self.c.options,self.c.root/'source-routes',1120)
        self.assertEqual(plan,original)
        self.assertEqual(self.kinds(),['bhakti_word_glosses','bhakti_literal_translation','bhakti_translation_review'])
        self.assertIn('OWNER ENGLISH',self.calls[-1][2])
        self.assertTrue(result['translations']['packet']['translations'][0]['human_review_recommended'])
        self.assertEqual(source.fresh_target_errors(plan,{'languages':['Hindi']},result),[])
        changed=copy.deepcopy(plan)
        changed['lines'][0]['source_text']='तेरी साँस मुझे छोड़ती है'
        changed['lines'][0]['roman']='terī sāṃsa mujhe choṛatī hai'
        changed['reuse_by_id']['q']['source']=changed['lines'][0]['source_text']
        changed['reuse_by_id']['q']['roman']=changed['lines'][0]['roman']
        changed['reuse_by_id']['q']['words'][0]['roman']='terī'
        changed['reuse_by_id']['q']['sourceWords'][0]['text']='तेरी'
        self.assertTrue(source.fresh_target_errors(changed,{'languages':['Hindi']},result),
                        'Unchanged target proof cannot certify a changed actual source neighbor.')

    def test_missing_disposition_cannot_become_accepted_by_pass_flags(self):
        self.mode='missing_disposition'
        with self.assertRaises((RuntimeError,ValueError)):self.complete()
        self.assertEqual(self.kinds(),['bhakti_word_glosses','bhakti_literal_translation','bhakti_translation_review'])
        self.assert_no_acceptance()
        n=len(self.calls)
        with self.assertRaises((RuntimeError,ValueError)):self.complete()
        self.assertEqual(len(self.calls),n)

    def test_component_frame_cannot_be_silently_omitted(self):
        self.mode='missing_component'
        with self.assertRaises((RuntimeError,ValueError)):self.complete()
        self.assertEqual(self.kinds(),['bhakti_word_glosses','bhakti_literal_translation','bhakti_translation_review'])
        self.assert_no_acceptance()

    def test_synonym_list_alone_is_invalid_human_hold_not_quality_hold(self):
        self.mode='unsupported_human_hold'
        try:self.complete()
        except Exception as exc:self.assertNotIsInstance(exc,pipeline.bhakti_semantic_repair.SemanticQualityHold)
        else:self.fail('Malformed human-hold judgment must not be accepted.')
        self.assertIn('bhakti_translation_review',self.kinds());self.assert_no_acceptance()

    def test_real_unresolved_evidence_is_retained_typed_hold_and_never_replayed(self):
        self.mode='hold'
        with self.assertRaises(pipeline.bhakti_semantic_repair.SemanticQualityHold):self.complete()
        self.assertEqual(self.kinds(),['bhakti_word_glosses','bhakti_literal_translation','bhakti_translation_review'])
        self.assert_no_acceptance();n=len(self.calls)
        with self.assertRaises(pipeline.bhakti_semantic_repair.SemanticQualityHold):self.complete()
        self.assertEqual(len(self.calls),n)

    def test_real_english_defect_still_repairs_and_keeps_glossary(self):
        self.mode='repair';self.c.options.semantic_stage_escalation=True
        g,t=self.complete()
        self.assertEqual(self.kinds(),['bhakti_word_glosses','bhakti_literal_translation','bhakti_translation_review','bhakti_literal_translation','bhakti_translation_review'])
        self.assertEqual(self.calls[3][0],routes.PRO_MODEL)
        self.assertEqual(g['packet'],self.generated_gloss)
        self.assertIn('REPAIR FEEDBACK:',self.calls[3][2])
        self.assertFalse(t['packet']['translations'][0]['human_review_recommended'])
        self.assertEqual(self.first_writer['literal_english'],'I abandon my breath.')
        self.assertEqual(t['packet']['translations'][0]['literal_english'],'My breath abandons me.')
        self.assertTrue(self.review_contexts[1]['reservations'],'The prior reservation remains explicit after a new confident writer.')

    def test_pro_shape_repair_does_not_discard_original_writer_doubt(self):
        self.mode='pro_history';self.c.options.semantic_stage_escalation=True
        _,t=self.complete()
        self.assertEqual(self.kinds(),['bhakti_word_glosses','bhakti_literal_translation','bhakti_literal_translation','bhakti_translation_review'])
        context=self.review_contexts[0]
        self.assertIsNotNone(context,'Pro success must retain the earlier bound concern.')
        self.assertTrue(context['prior_concerns'])
        self.assertIn(self.first_writer['uncertainty'],json.dumps(context,ensure_ascii=False))
        self.assertEqual({k:v for k,v in t['writer_review_context'].items() if k!='origins'},context)
        self.assertNotIn('origins',context)

    def test_changed_saved_disposition_is_rejected_even_if_manifest_digest_recomputed(self):
        self.complete();n=len(self.calls)
        path=self.c.packets/'05-translation.json';value=json.loads(path.read_text())
        value['packet']['translations'][0]['independent_review']['writer_reservation_dispositions'][0]['reservation_id']='wrong-candidate'
        path.write_text(json.dumps(value))
        manifest_path=self.c.packets/'semantic-acceptance.json';manifest=json.loads(manifest_path.read_text())
        manifest['translation_sha256']=pipeline.bhakti_semantic_repair.digest(value);manifest_path.write_text(json.dumps(manifest))
        with self.assertRaises((RuntimeError,ValueError)):self.complete()
        self.assertEqual(len(self.calls),n)

    def test_publication_and_fresh_target_validation_consume_bound_resolution(self):
        import bhakti_library_source_pass as source
        g,t=self.complete()
        plan={'lines':self.c.lines,'new_target_ids':['a']}
        self.assertEqual(source.fresh_target_errors(plan,{'languages':['Hindi']},{'glosses':g,'translations':t}),[])
        # Exercise the actual publication gate with its timing-only dependencies replaced.
        with patch.object(pipeline,'timing_uncertainty_errors',return_value=[]):
            errors=pipeline.publication_errors(self.c.audit,{'packet':{'sequence':[]}},g,t)
        self.assertEqual(errors,[])
        bad=copy.deepcopy(t);bad.pop('writer_review_context')
        self.assertTrue(source.fresh_target_errors(plan,{'languages':['Hindi']},{'glosses':g,'translations':bad}))
        with patch.object(pipeline,'timing_uncertainty_errors',return_value=[]):
            self.assertTrue(pipeline.publication_errors(self.c.audit,{'packet':{'sequence':[]}},g,bad))

    def test_malformed_reservation_review_escalates_only_reviewer(self):
        self.mode='malformed_review';self.c.options.semantic_stage_escalation=True
        _,t=self.complete()
        self.assertEqual([(m,k) for m,k,_ in self.calls],[
            (routes.FLASH_MODEL,'bhakti_word_glosses'),(routes.FLASH_MODEL,'bhakti_literal_translation'),
            (routes.FLASH_MODEL,'bhakti_translation_review'),(routes.PRO_MODEL,'bhakti_translation_review')])
        self.assertEqual({k:t['packet']['translations'][0][k] for k in self.first_writer},self.first_writer)

    def test_stale_envelope_source_gloss_and_context_cannot_certify_current_acceptance(self):
        self.complete();n=len(self.calls)
        path=self.c.packets/'05-translation.json';saved=path.read_bytes()
        mp=self.c.packets/'semantic-acceptance.json';manifest_saved=mp.read_bytes()
        for field in ('source_sha256','gloss_sha256','context_identity'):
            with self.subTest(field=field):
                value=json.loads(saved);self.assertIn(field,value['writer_review_context'])
                value['writer_review_context'][field]='0'*64
                path.write_text(json.dumps(value))
                manifest=json.loads(manifest_saved);manifest['translation_sha256']=pipeline.bhakti_semantic_repair.digest(value)
                mp.write_text(json.dumps(manifest))
                with self.assertRaises((RuntimeError,ValueError)):self.complete()
                self.assertEqual(len(self.calls),n)
                path.write_bytes(saved);mp.write_bytes(manifest_saved)

    def test_publication_rejects_unchanged_proof_against_changed_actual_performance_order(self):
        self.c.audit['packet']['performance_order']=[{'line_id':'a','occurrence':1},{'line_id':'a','occurrence':2}]
        g,t=self.complete()
        changed=copy.deepcopy(self.c.audit)
        changed['packet']['performance_order']=[{'line_id':'a','occurrence':1}]
        with patch.object(pipeline,'timing_uncertainty_errors',return_value=[]):
            self.assertEqual(pipeline.publication_errors(self.c.audit,{'packet':{'sequence':[]}},g,t),[])
            self.assertTrue(pipeline.publication_errors(changed,{'packet':{'sequence':[]}},g,t),
                            'Target rows and stored envelope are identical, but actual order changed.')

    def test_prior_candidate_digest_tamper_blocks_accepted_resume_without_dispatch(self):
        self.mode='pro_history';self.c.options.semantic_stage_escalation=True
        self.complete();n=len(self.calls)
        states=[p for p in self.c.packets.rglob('route-state.json') if json.loads(p.read_text())['unit_id'].endswith(':semantic-writer')]
        self.assertEqual(len(states),1)
        state=json.loads(states[0].read_text());self.assertEqual(state['attempts'][0]['status'],'quality-failed')
        path=states[0].parent/'flash'/'candidate.json';value=json.loads(path.read_text())
        value['packet']['translations'][0]['uncertainty']='Altered original concern after review.'
        path.write_text(json.dumps(value))
        with self.assertRaises((RuntimeError,ValueError)):self.complete()
        self.assertEqual(len(self.calls),n)

    def test_unknown_writer_attempt_is_not_converted_to_reservation_or_replayed(self):
        self.mode='unknown_history';self.c.options.semantic_stage_escalation=True
        with self.assertRaises((RuntimeError,ValueError)):self.complete()
        self.assertEqual(self.kinds(),['bhakti_word_glosses','bhakti_literal_translation'])
        self.assert_no_acceptance();n=len(self.calls)
        state=json.loads((self.c.packets/'semantic-repair-state.json').read_text());deadline=state['deadline_at_epoch']
        with self.assertRaises((RuntimeError,ValueError)):self.complete()
        self.assertEqual(len(self.calls),n)
        self.assertEqual(json.loads((self.c.packets/'semantic-repair-state.json').read_text())['deadline_at_epoch'],deadline)

    def _remove_saved_resolution(self, mode):
        self.mode=mode;self.c.options.semantic_stage_escalation=True
        self.complete();n=len(self.calls)
        path=self.c.packets/'05-translation.json';value=json.loads(path.read_text())
        value.pop('writer_review_context')
        for row in value['packet']['translations']:
            row['independent_review'].pop('writer_reservation_dispositions',None)
        path.write_text(json.dumps(value))
        mp=self.c.packets/'semantic-acceptance.json';m=json.loads(mp.read_text())
        m['translation_sha256']=pipeline.bhakti_semantic_repair.digest(value);mp.write_text(json.dumps(m))
        with self.assertRaises((RuntimeError,ValueError)):self.complete()
        self.assertEqual(len(self.calls),n)

    def test_removing_prior_pro_obligations_cannot_turn_current_confidence_into_acceptance(self):
        self._remove_saved_resolution('pro_history')

    def test_removing_carried_repair_round_obligations_cannot_bypass_acceptance(self):
        self._remove_saved_resolution('repair')

    def test_removed_task_header_cannot_downgrade_current_accepted_review(self):
        self.mode='pro_history';self.c.options.semantic_stage_escalation=True
        self.complete();n=len(self.calls)
        path=self.c.packets/'05-translation.json';value=json.loads(path.read_text())
        value.pop('review_task_version')
        for row in value['packet']['translations']:row['independent_review'].pop('component_judgments')
        path.write_text(json.dumps(value))
        mp=self.c.packets/'semantic-acceptance.json';m=json.loads(mp.read_text())
        m['translation_sha256']=pipeline.bhakti_semantic_repair.digest(value);mp.write_text(json.dumps(m))
        with self.assertRaises((RuntimeError,ValueError)):self.complete()
        self.assertEqual(len(self.calls),n)

    def test_direct_new_candidate_preserves_old_proof_and_reaches_new_review(self):
        g=pipeline.gloss(self.c.song,self.c.audit,self.c.options)
        pipeline.translate(self.c.song,self.c.audit,g,{'slug':'fixture'},self.c.options)
        proof_files={p:p.read_bytes() for p in self.c.packets.rglob('*') if p.is_file() and 'writer' in str(p)}
        n=len(self.calls);self.c.options.force=True
        value=pipeline.translate(self.c.song,self.c.audit,g,{'slug':'fixture'},self.c.options)
        self.assertEqual([k for _,k,_ in self.calls[n:]],['bhakti_literal_translation','bhakti_translation_review'])
        self.assertFalse(value['packet']['translations'][0]['human_review_recommended'])
        for p,original in proof_files.items():self.assertEqual(p.read_bytes(),original)

    def test_direct_generate_cannot_downgrade_saved_current_review(self):
        self.first_writer = {}
        gloss = pipeline.gloss(self.c.song, self.c.audit, self.c.options)
        original = pipeline.translate(self.c.song, self.c.audit, gloss, {'slug':'fixture'}, self.c.options)
        changed = copy.deepcopy(original); changed.pop('review_task_version')
        for row in changed['packet']['translations']:
            row['independent_review'].pop('component_judgments')
        before = (self.c.packets/'05-translation.json').read_bytes()
        with patch.object(pipeline,'timing_uncertainty_errors',return_value=[]), patch.object(
                pipeline.naming,'canonical_person',side_effect=AssertionError('unqualified rendering')):
            with self.assertRaises((RuntimeError,ValueError)):
                pipeline._generate(self.c.song,{'slug':'fixture','displayTitle':'Fixture'}, {},
                    self.c.audit,{'packet':{'sequence':[]}},gloss,changed,write_catalogue_after=False)
        self.assertEqual((self.c.packets/'05-translation.json').read_bytes(),before)

    def test_direct_generate_accepts_exact_stored_legacy_review_boundary(self):
        self.first_writer = {}
        with patch.object(pipeline,'REVIEW_TASK_VERSION',2):
            gloss = pipeline.gloss(self.c.song,self.c.audit,self.c.options)
            legacy = pipeline.translate(self.c.song,self.c.audit,gloss,{'slug':'fixture'},self.c.options)
        class ReachedRendering(Exception): pass
        with patch.object(pipeline,'timing_uncertainty_errors',return_value=[]), patch.object(
                pipeline.naming,'canonical_person',side_effect=ReachedRendering):
            with self.assertRaises(ReachedRendering):
                pipeline._generate(self.c.song,{'slug':'fixture','displayTitle':'Fixture'}, {},
                    self.c.audit,{'packet':{'sequence':[]}},gloss,legacy,write_catalogue_after=False)

    def test_known_schema_failure_retains_actual_response_and_doubt_before_pro_review(self):
        self.mode='early_schema';self.c.options.semantic_stage_escalation=True
        _,t=self.complete()
        self.assertEqual(self.kinds(),['bhakti_word_glosses','bhakti_literal_translation','bhakti_literal_translation','bhakti_translation_review'])
        states=[p for p in self.c.packets.rglob('route-state.json') if json.loads(p.read_text())['unit_id'].endswith(':semantic-writer')]
        self.assertEqual(len(states),1)
        saved=json.loads((states[0].parent/'flash'/'candidate.json').read_text())
        response=saved['writer_diagnostics'][0]
        self.assertEqual(response['packet']['translations'],[self.first_writer,'malformed'])
        self.assertIn(self.first_writer['uncertainty'],json.dumps(self.review_contexts[0],ensure_ascii=False))
        self.assertTrue(t['writer_review_context']['prior_concerns'])

    def _delete_final_history(self, mode, erase_task=False):
        import bhakti_library_source_pass as source
        self.mode=mode;self.c.options.semantic_stage_escalation=True
        g,t=self.complete();bad=copy.deepcopy(t)
        bad.pop('writer_review_context')
        for row in bad['packet']['translations']:row['independent_review'].pop('writer_reservation_dispositions',None)
        if erase_task:
            bad.pop('writer_evidence');bad.pop('review_task_version')
            for row in bad['packet']['translations']:row['independent_review'].pop('component_judgments')
        else:
            receipt=bad['writer_evidence']
            receipt['history']=[item for item in receipt['history'] if item['proof']==receipt['current']]
        with patch.object(pipeline,'timing_uncertainty_errors',return_value=[]):
            self.assertTrue(pipeline.publication_errors(self.c.audit,{'packet':{'sequence':[]}},g,bad))
        self.assertTrue(source.fresh_target_errors({'lines':self.c.lines,'new_target_ids':['a']},
            {'languages':['Hindi']},{'glosses':g,'translations':bad}))

    def test_final_consumers_reconstruct_prior_pro_history_not_supplied_subset(self):
        self._delete_final_history('pro_history')

    def test_final_consumers_require_coordinator_prior_round_closure(self):
        self._delete_final_history('repair')

    def test_final_consumers_cannot_downgrade_current_packet_by_deleting_task_and_proofs(self):
        self._delete_final_history('pro_history',erase_task=True)

    def test_final_gate_cannot_erase_coordinator_declaration_with_prior_round_history(self):
        self.mode='repair';self.c.options.semantic_stage_escalation=True
        g,t=self.complete();bad=copy.deepcopy(t)
        for field in ('writer_review_context','semantic_repair_version','semantic_run_id','coordinator_acceptance'):
            bad.pop(field,None)
        receipt=bad['writer_evidence'];receipt['history']=[item for item in receipt['history'] if item['proof']==receipt['current']]
        for row in bad['packet']['translations']:row['independent_review'].pop('writer_reservation_dispositions',None)
        with patch.object(pipeline,'timing_uncertainty_errors',return_value=[]):
            self.assertTrue(pipeline.publication_errors(self.c.audit,{'packet':{'sequence':[]}},g,bad))

class ComponentContract(unittest.TestCase):
    def setUp(self):
        self.c=fixture.AutomaticRepairTests();self.c.setUp();self.addCleanup(self.c.doCleanups)
        self.lines=self.c.lines;self.glosses=self.c.rows(self.lines,repaired=True)
        self.row=self.c.translation(self.lines[0],True)
        self.review=self.c.review([{'source':self.lines[0],'gloss':self.glosses[0],'draft':self.row}])[0]
        self.review['component_judgments']={k:{'status':'supported','reason':'Source evidence supports this component.'} for k in ('gloss','frame','english')}
        self.row['independent_review']=self.review

    def errors(self):
        return pipeline.translation_review_contract_errors(self.lines,self.glosses,[self.row],review_task_version=3)

    def test_popup_only_defect_does_not_require_false_english_defect_or_human_hold(self):
        issue=self.c.issue();issue['kind']='gloss_sense'
        self.review.update(passes=False,human_review_recommended=False,issues=[issue])
        self.review['component_judgments']['gloss']={'status':'defect','reason':'The popup contradicts the source agent.'}
        self.assertEqual(self.errors(),[])
        self.assertEqual(self.review['component_judgments']['english']['status'],'supported')

    def test_frame_defect_requires_frame_issue_not_an_english_synonym_complaint(self):
        issue=self.c.issue();issue['kind']='english_realization'
        self.review.update(passes=False,issues=[issue])
        self.review['component_judgments']['frame']={'status':'defect','reason':'The frame gives the action to the wrong agent.'}
        self.assertTrue(self.errors())
        self.review['issues'][0]['kind']='frame_relation'
        self.assertEqual(self.errors(),[])

    def test_true_human_hold_without_unresolved_evidence_is_invalid(self):
        self.review.update(passes=False,human_review_recommended=True,material_choice='leaves / abandons')
        self.assertTrue(self.errors())

    def test_supported_component_cannot_hide_matching_typed_defect(self):
        self.review.update(passes=False,issues=[self.c.issue()])
        self.assertTrue(self.errors())

    def test_legacy_positive_rows_without_components_stay_valid_at_legacy_boundary(self):
        self.review.pop('component_judgments')
        self.assertEqual(pipeline.fresh_translation_contract_errors(self.lines,self.glosses,[self.row]),[])
        self.assertTrue(self.errors(),'Current version cannot call the same missing component proof complete.')

if __name__=='__main__':unittest.main()

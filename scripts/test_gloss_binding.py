"""Actual saved Rehna evidence; only transport/acquisition replay is mocked.
The saved reviewer missed a real semantic defect. These tests qualify bindings,
never its linguistic judgment, and never reopen the original paid route.
"""
import argparse, copy, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import bhakti_pipeline as pipeline
import bhakti_semantic_repair as semantic
import bhakti_lexical_producer as producer

FIXTURE=Path(__file__).parent/'fixtures/gloss_binding/rehna.json'

class RealGlossBinding(unittest.TestCase):
    def setUp(self):
        self.data=json.loads(FIXTURE.read_text())
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.song=Path(self.tmp.name)/'private-replay'
        self.authored=copy.deepcopy(self.data['authored']);self.prepared=copy.deepcopy(self.authored)
        self.prepared['packet']['glosses']=self.data['prepared']['gloss_rows']
        self.lines=self.data['audited']['packet']['verified_lines']
        self.binding={'version':1,'authored_sha256':semantic.digest(self.authored['packet']['glosses']),
                      'review_sha256':semantic.digest(self.prepared['packet']['glosses'])}
        self.options=argparse.Namespace(model='google/gemini-3.7-flash',timeout=180,force=False,
            semantic_full_source=self.data['full_source'],
            semantic_performance_order=self.data['audited']['packet']['performance_order'],
            semantic_lexical_support=self.data['prepared']['packet'],
            automatic_lexical_identity=self.data['writer']['automatic_evidence_receipt']['lexical_support'],
            automatic_source_discovery_identity=self.data['writer']['automatic_evidence_receipt']['source_discovery'],
            semantic_writer_gloss_binding=self.binding)
        self.addCleanup(patch.stopall)
        patch.object(pipeline.gemini,'key',return_value='OFFLINE').start()
        patch.object(pipeline.gemini,'call',side_effect=AssertionError('No network in evidence replay')).start()

    def reviewed(self, *, confident=False):
        candidate=copy.deepcopy(self.data['writer'])
        # New private direct-mode proof owns exactly the original linguistic
        # candidate, not the original live coordinator's unfinished status.
        candidate.pop('writer_coordinator_acceptance',None)
        candidate.pop('writer_route_state',None)
        candidate['writer_gloss_binding']=copy.deepcopy(self.binding)
        if confident:
            for row in candidate['packet']['translations']:
                row.update(human_review_recommended=False, uncertainty='', material_alternatives=[], choice_note='')
        response=copy.deepcopy({'packet':self.data['review_response']})
        if confident:
            for row in response['packet']['reviews']:
                row.pop('writer_reservation_dispositions',None)
        with patch.object(pipeline.gemini,'call',return_value=response) as calls:
            result=pipeline.review_translation(self.song,self.data['audited'],self.prepared,
                {'languages':['Hindi']},self.options,candidate,prepared=True)
        self.assertEqual(calls.call_count,1)
        self.assertEqual(semantic.writer_rows(result['packet']['translations']),
                         semantic.writer_rows(candidate['packet']['translations']))
        return result

    def test_actual_preparation_binds_exact_authored_and_enriched_rows(self):
        # Exercise actual prepare_translation's copy/binding boundary. Dictionary
        # acquisition/producer return their exact retained result, not a new API.
        options=copy.copy(self.options);del options.semantic_lexical_support
        del options.semantic_writer_gloss_binding
        config={'roots':[],'directory':self.song,'edition':'3.1','cache':self.song/'cache'}
        import bhakti_source_discovery as discovery
        with patch.object(producer,'settings',return_value=config), \
             patch.object(producer,'configuration_identity',return_value={}), \
             patch.object(discovery,'prepare',return_value=None), \
             patch.object(producer,'produce_support',return_value=copy.deepcopy(self.data['prepared'])):
            prepared_options,view=producer.prepare_translation(self.song,self.data['audited'],self.authored,options)
        self.assertEqual(prepared_options.semantic_writer_gloss_binding,self.binding)
        self.assertEqual(producer.writer_gloss_binding(self.authored['packet']['glosses'],self.prepared['packet']['glosses']),self.binding)
        self.assertEqual(view['packet']['glosses'],self.prepared['packet']['glosses'])
        self.assertEqual(self.authored,self.data['authored'])
        differences=[key for a,b in zip(self.authored['packet']['glosses'],view['packet']['glosses'])
                     for key in set(a)|set(b) if a.get(key)!=b.get(key)]
        self.assertEqual(differences,['support_decisions'])

    def test_actual_writer_persists_prepared_binding_outside_model_packet(self):
        response=copy.deepcopy(self.data['writer'])
        response.pop('writer_coordinator_acceptance',None)
        self.assertNotIn('writer_gloss_binding',response)
        with patch.object(producer,'prepare_translation',return_value=(self.options,self.prepared)), \
             patch.object(pipeline.gemini,'call',return_value=response):
            result=pipeline.translate(self.song,self.data['audited'],self.authored,{'languages':['Hindi']},
                self.options,candidate_only=True,defer_review=True)
        self.assertEqual(result['writer_gloss_binding'],self.binding)
        self.assertEqual(result['packet'],response['packet'])

    def test_actual_routed_review_uses_authored_view_at_outer_validation(self):
        candidate=copy.deepcopy(self.data['writer']);candidate.pop('writer_coordinator_acceptance',None)
        candidate['writer_gloss_binding']=copy.deepcopy(self.binding)
        observed=[]
        def stage(module,directory,name,inputs,options,execute,validate,**kwargs):
            if name=='writer':return candidate
            result=execute(self.song/'review',options)
            errors=validate(result);observed.extend(errors)
            self.assertEqual(errors,[])
            return result
        response=copy.deepcopy({'packet':self.data['review_response']})
        # Routed entry receives original options; preparation owns the view flag.
        original_options=copy.copy(self.options)
        del original_options.semantic_writer_gloss_binding
        with patch.object(semantic,'stage_routes_enabled',return_value=True), \
             patch.object(semantic,'semantic_stage_route',side_effect=stage), \
             patch.object(producer,'prepare_translation',return_value=(self.options,self.prepared)), \
             patch.object(pipeline.gemini,'call',return_value=response):
            result=semantic.routed_translation(pipeline,self.song,self.data['audited'],self.authored,
                {'languages':['Hindi']},original_options)
        self.assertEqual(observed,[])
        self.assertEqual(semantic.writer_rows(result['packet']['translations']),
                         semantic.writer_rows(candidate['packet']['translations']))

    def test_real_review_accepts_exact_base_and_review_views_explicitly(self):
        result=self.reviewed();context=result['writer_review_context']
        self.assertEqual(context['version'],2)
        self.assertEqual(context['gloss_sha256'],self.binding['authored_sha256'])
        self.assertEqual(context['review_gloss_sha256'],self.binding['review_sha256'])
        for representation,glosses in [('authored',self.authored),('review',self.prepared)]:
            with self.subTest(representation=representation):
                errors=pipeline.translation_review_contract_errors(self.lines,glosses['packet']['glosses'],
                    result['packet']['translations'],review_context=context,review_task_version=3,
                    expected_context_identity=context['context_identity'],gloss_representation=representation)
                self.assertEqual(errors,[])

    def test_changed_authored_gloss_and_changed_prepared_support_still_reject(self):
        result=self.reviewed();context=result['writer_review_context']
        for representation,packet,field in [('authored',self.authored,'grammar_note'),('review',self.prepared,'support_decisions')]:
            changed=copy.deepcopy(packet['packet']['glosses'])
            if field=='grammar_note':changed[-1][field]+=' Invented grammatical claim.'
            else:changed[-1][field][0]['reason']='A changed unsupported sense claim.'
            errors=pipeline.translation_review_contract_errors(self.lines,changed,result['packet']['translations'],
                review_context=context,review_task_version=3,expected_context_identity=context['context_identity'],
                gloss_representation=representation)
            self.assertTrue(any('gloss' in error and ('changed' in error or 'unbound' in error) for error in errors),errors)

    def test_forged_declared_hash_cannot_change_actual_direct_publication_evidence(self):
        result=self.reviewed();changed=copy.deepcopy(self.authored)
        changed['packet']['glosses'][-1]['grammar_note']+=' Invented grammatical claim.'
        result['writer_review_context']['gloss_sha256']=semantic.digest(changed['packet']['glosses'])
        basis=semantic.review_context_basis(self.lines,full_source=self.data['full_source'],
            performance_order=self.data['audited']['packet']['performance_order'])
        with patch.object(pipeline,'timing_uncertainty_errors',return_value=[]):
            errors=pipeline.publication_errors(self.data['audited'],{'packet':{'sequence':[]}},changed,result,
                review_context_input=basis)
        self.assertTrue(errors,'Caller-declared replacement hash must not override unchanged immutable writer proof.')
        self.assertTrue(any('gloss' in error or 'binding' in error for error in errors),errors)

    def test_confident_equal_view_writer_cannot_drop_binding_context(self):
        self.prepared=copy.deepcopy(self.authored)
        self.binding['review_sha256']=self.binding['authored_sha256']
        result=self.reviewed(confident=True)
        self.assertEqual(result['writer_review_context']['version'],2)
        self.assertEqual(result['writer_review_context']['reservations'],[])
        result.pop('writer_review_context')
        with self.assertRaisesRegex(ValueError,'gloss|binding'):
            pipeline.translation_packet_contract_kwargs(self.lines,result,final_consumer=True)

    def legacy_automatic_acceptance(self, *, confident=False):
        # Execute frozen pre-binding production callers with current shared
        # utilities. No fake old binding or prebuilt accepted result is supplied.
        namespace=dict(vars(pipeline))
        source=(Path(__file__).parent/'fixtures/gloss_binding/legacy_callers.py').read_text()
        exec(compile(source,'legacy_gloss_binding_callers','exec'),namespace)
        old_options=copy.copy(self.options);del old_options.semantic_writer_gloss_binding
        writer=copy.deepcopy(self.data['writer'])
        response={'packet':copy.deepcopy(self.data['review_response'])}
        if confident:
            for row in writer['packet']['translations']:
                row.update(human_review_recommended=False, uncertainty='', material_alternatives=[], choice_note='')
            for row in response['packet']['reviews']:
                row.pop('writer_reservation_dispositions',None)
        with patch.object(producer,'prepare_translation',return_value=(old_options,self.prepared)), \
             patch.object(pipeline.gemini,'call',side_effect=[writer,response]) as calls:
            old=namespace['translate'](self.song,self.data['audited'],self.authored,
                {'languages':['Hindi']},old_options)
        self.assertEqual(calls.call_count,2)
        self.assertNotIn('writer_gloss_binding',old)
        if confident:self.assertNotIn('writer_review_context',old)
        else:self.assertEqual(old['writer_review_context']['version'],1)
        return old

    def test_genuine_old_automatic_cache_renews_only_review_preserving_old_proof(self):
        old=self.legacy_automatic_acceptance()
        proof=old['writer_evidence']['current'];path=Path(proof['path']);before=path.read_bytes()
        response={'packet':copy.deepcopy(self.data['review_response'])}
        with patch.object(producer,'prepare_translation',return_value=(self.options,self.prepared)), \
             patch.object(pipeline,'REVIEW_TASK_VERSION',4), \
             patch.object(pipeline.gemini,'call',return_value=response) as calls:
            new=pipeline.translate(self.song,self.data['audited'],self.authored,{'languages':['Hindi']},self.options)
            self.assertEqual(calls.call_count,1)
            self.assertEqual(calls.call_args.kwargs['schema_name'],'bhakti_translation_review')
            self.assertEqual(semantic.writer_rows(new['packet']['translations']),semantic.writer_rows(old['packet']['translations']))
            self.assertEqual(path.read_bytes(),before)
            current=json.loads(Path(new['writer_evidence']['current']['path']).read_text())
            self.assertEqual(current['writer_binding_predecessor'],proof)
            self.assertEqual(current['writer_gloss_binding'],self.binding)
            self.assertEqual(pipeline.translate(self.song,self.data['audited'],self.authored,{'languages':['Hindi']},self.options),new)
            self.assertEqual(calls.call_count,1)

    def test_legacy_migration_rejects_changed_prepared_grammar_before_review(self):
        old=self.legacy_automatic_acceptance()
        altered=copy.deepcopy(self.prepared)
        altered['packet']['glosses'][-1]['grammar_note']+=' Invented grammatical claim.'
        options=copy.deepcopy(self.options)
        options.semantic_writer_gloss_binding['review_sha256']=semantic.digest(altered['packet']['glosses'])
        with patch.object(pipeline.gemini,'call',return_value={'packet':copy.deepcopy(self.data['review_response'])}) as calls:
            with self.assertRaisesRegex(ValueError,'legacy writer.*gloss|legacy writer.*view'):
                pipeline.review_translation(self.song,self.data['audited'],altered,
                    {'languages':['Hindi']},options,old,prepared=True)
        self.assertEqual(calls.call_count,0)

    def test_confident_legacy_renewal_binds_stored_writer_request(self):
        old=self.legacy_automatic_acceptance(confident=True)
        response={'packet':copy.deepcopy(self.data['review_response'])}
        for row in response['packet']['reviews']:row.pop('writer_reservation_dispositions',None)
        with patch.object(pipeline.gemini,'call',return_value=response) as calls:
            renewed=pipeline.review_translation(self.song,self.data['audited'],self.prepared,
                {'languages':['Hindi']},self.options,old,prepared=True)
        self.assertEqual(calls.call_count,1)
        self.assertEqual(renewed['writer_review_context']['reservations'],[])
        self.assertEqual(semantic.writer_rows(renewed['packet']['translations']),semantic.writer_rows(old['packet']['translations']))

    def test_confident_legacy_request_rejects_changed_view_without_context(self):
        old=self.legacy_automatic_acceptance(confident=True)
        altered=copy.deepcopy(self.prepared)
        altered['packet']['glosses'][-1]['grammar_note']+=' Invented grammatical claim.'
        options=copy.deepcopy(self.options)
        options.semantic_writer_gloss_binding['review_sha256']=semantic.digest(altered['packet']['glosses'])
        response={'packet':copy.deepcopy(self.data['review_response'])}
        for row in response['packet']['reviews']:row.pop('writer_reservation_dispositions',None)
        with patch.object(pipeline.gemini,'call',return_value=response) as calls:
            with self.assertRaisesRegex(ValueError,'legacy writer.*gloss|legacy writer.*view'):
                pipeline.review_translation(self.song,self.data['audited'],altered,
                    {'languages':['Hindi']},options,old,prepared=True)
        self.assertEqual(calls.call_count,0)

    def test_renewed_binding_cannot_lose_original_predecessor_evidence(self):
        old=self.legacy_automatic_acceptance()
        with patch.object(producer,'prepare_translation',return_value=(self.options,self.prepared)), \
             patch.object(pipeline,'REVIEW_TASK_VERSION',4), \
             patch.object(pipeline.gemini,'call',return_value={'packet':copy.deepcopy(self.data['review_response'])}) as calls:
            pipeline.translate(self.song,self.data['audited'],self.authored,{'languages':['Hindi']},self.options)
            Path(old['writer_evidence']['current']['path']).unlink()
            with self.assertRaises((ValueError,RuntimeError,OSError)):
                pipeline.translate(self.song,self.data['audited'],self.authored,{'languages':['Hindi']},self.options)
            self.assertEqual(calls.call_count,1)

    def test_saved_v1_context_stays_exact_and_is_not_reinterpreted_as_two_views(self):
        context=copy.deepcopy(self.data['legacy_context'])
        proof_path=self.song/'legacy-writer.json';proof_path.parent.mkdir(parents=True,exist_ok=True)
        proof_path.write_text(json.dumps(self.data['writer']))
        for origin in context['origins']:
            origin['proof']={'path':str(proof_path),'candidate_sha256':semantic.digest(self.data['writer'])}
        saved={'packet':{'translations':self.data['reviewed_rows']}}
        self.assertEqual(context['version'],1)
        self.assertEqual(semantic.writer_review_context_errors(self.lines,self.prepared['packet']['glosses'],
            saved['packet']['translations'],context,context['context_identity']),[])
        self.assertTrue(semantic.writer_review_context_errors(self.lines,self.authored['packet']['glosses'],
            saved['packet']['translations'],context,context['context_identity']))

if __name__=='__main__':unittest.main()

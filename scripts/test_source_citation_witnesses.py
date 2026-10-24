"""Actual paid writer citation and real caller/cache gates; canned provider only.

Citation admissibility is not semantic approval. In particular the saved
writer's extra 'true' must remain available for independent rejection.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import bhakti_pipeline as pipeline
import bhakti_source_discovery as source
import test_source_discovery_callers as caller_fixture
import bhakti_model_routes as routes
from test_word_accountability_fixtures import accounted_provider, records

FIXTURE=json.loads((Path(__file__).parent/'fixtures/source-citations/rehna-paid-writer.json').read_text())
PACKET=FIXTURE['source_discovery']
DECISION=FIXTURE['translations']['translations'][1]['source_discovery_decisions'][0]


class FormDefinitionSeparation(unittest.TestCase):
    def check(self,decision=None,packet=None):
        return source.discovery_decision_errors(packet or PACKET,[decision or DECISION])

    def test_actual_exact_head_and_exact_definition_can_be_cited_separately(self):
        self.assertIn(DECISION['quotation'],PACKET['entries'][0]['dictionary']['whole_entry_text'])
        self.assertIn(DECISION['attested_form'],PACKET['entries'][0]['source_spellings'])
        self.assertNotIn(DECISION['attested_form'],DECISION['quotation'])
        self.assertEqual(self.check(),[],'Citation validity cannot approve meaning_applied.')
        roman=copy.deepcopy(DECISION);roman['attested_form']='ṭhikānā'
        self.assertEqual(self.check(roman),[])

    def test_same_entry_substring_or_cognate_is_not_an_exact_attested_form(self):
        for form in ('ठिका','स्थिर'):
            decision=copy.deepcopy(DECISION);decision['attested_form']=form
            decision['quotation']=PACKET['entries'][0]['dictionary']['whole_entry_text']
            self.assertTrue(self.check(decision),form)

    def test_fabricated_definition_does_not_pass_with_genuine_headword(self):
        decision=copy.deepcopy(DECISION);decision['quotation']='The source literally contains an additional adjective meaning true.'
        self.assertTrue(self.check(decision))

    def test_definition_word_cannot_be_authenticated_as_target_headword(self):
        decision=copy.deepcopy(DECISION);decision['attested_form']='abode'
        self.assertTrue(self.check(decision))

    def test_compound_and_variant_relations_still_require_form_in_quote(self):
        for kind in ('compound_subentry','vernacular_variant'):
            decision=copy.deepcopy(DECISION);decision['relation_kind']=kind
            self.assertTrue(self.check(decision),kind)

    def test_wrong_language_or_foreign_entry_identity_still_rejected(self):
        packet=copy.deepcopy(PACKET);packet['entries'][0]['language']='ta'
        self.assertTrue(self.check(packet=packet))
        decision=copy.deepcopy(DECISION);decision['entry_id']='invented-entry'
        self.assertTrue(self.check(decision))

    def test_inflected_lemma_and_definition_need_separate_form_explanation(self):
        packet=copy.deepcopy(PACKET);target=packet['targets'][0]
        target['surfaces']=['ṭhikāne'];target['queries']=[{'text':'ठिकाने','origin':'native_surface'}]
        decision=copy.deepcopy(DECISION);decision['relation_kind']='inflected_form'
        decision['form_explanation']='The performed oblique ending must be interpreted in its clause; the dictionary head alone does not prove its relation.'
        self.assertEqual(self.check(decision,packet),[])
        decision['form_explanation']='';self.assertTrue(self.check(decision,packet))
        decision['form_explanation']='Inflected form.';decision['attested_form']='abode'
        self.assertTrue(self.check(decision,packet))
        decision=copy.deepcopy(DECISION)
        self.assertTrue(self.check(decision,packet),'An inflected target is not the exact headword.')


class ActualWriterReviewGate(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.song=Path(temporary.name)/'songs/rehna';self.song.mkdir(parents=True)
        self.lines=copy.deepcopy(FIXTURE['lines'])
        self.audit={'packet':{'verified_lines':self.lines,'metadata':{'languages':['Hindi']},
            'performance_order':[{'line_id':row['id'],'occurrence':1} for row in self.lines]}}
        self.glosses={'packet':{'glosses':copy.deepcopy(FIXTURE['glosses'])}}
        self.options=argparse.Namespace(model='fixture',force=False,timeout=30,
            automatic_source_discovery=copy.deepcopy(PACKET),
            automatic_source_discovery_identity=pipeline.bhakti_lexical_support.content_digest(PACKET))
        self.calls=[];self.review_payload=None
        for manager in (patch.dict(os.environ,{'BHAKTI_AUTO_LEXICAL':'0'}),
            patch.object(pipeline.gemini,'key',return_value='fixture'),
            patch.object(pipeline.gemini,'call',side_effect=self.provider)):
            manager.start();self.addCleanup(manager.stop)

    @accounted_provider
    def provider(self,model,key,prompt,**kw):
        kind=kw['schema_name'];self.calls.append(kind)
        if kind=='bhakti_literal_translation':
            return {'packet':copy.deepcopy(FIXTURE['translations'])}
        self.assertEqual(kind,'bhakti_translation_review')
        evidence=json.JSONDecoder().raw_decode(prompt.split('\nEVIDENCE:\n',1)[1])[0]
        self.review_payload=evidence
        self.assertIn(DECISION['quotation'],prompt)
        self.assertIn('attested_form',prompt)
        reservations=[]
        if 'WRITER RESERVATIONS:\n' in prompt:
            reservations=json.JSONDecoder().raw_decode(prompt.split('WRITER RESERVATIONS:\n',1)[1])[0]['reservations']
        rows=[]
        for item in evidence:
            lid=item['source']['id'];bad=lid=='verse-3-line-2'
            issues=[{'kind':'gloss_sense','target_line_ids':[lid],
                'references':[{'line_id':lid,'domain':'word_glosses','word_indices':[2],'source_quote':'ठिकाना'}],
                'explanation':'Synthetic semantic objection: the added qualifier true is not established by citation formatting.',
                'evidence':'The quoted definition says fixed/permanent abode; valid headword evidence is not itself evidence for an extra adjective.',
                'hold_reason':'','needed_evidence':''}] if bad else []
            if bad:
                issues.append({**copy.deepcopy(issues[0]),'kind':'english_realization',
                    'explanation':'The second true in English is an unsupported added adjective.'})
            row={'id':lid,'passes':not bad,'agency_preserved':True,'imagery_preserved':True,
                'all_meaning_accounted_for':True,'unsupported_additions':[],
                'human_review_recommended':False,'material_choice':'','reason':'Canned semantic objection; not a model-quality judgment.','issues':issues,
                'component_judgments':{component:{'status':'defect' if bad and component in {'gloss','english'} else 'supported',
                    'reason':'The added qualifier is a concrete defect.' if bad and component in {'gloss','english'} else 'Synthetic citation-delivery control.'}
                    for component in ('gloss','frame','english')},
                'writer_reservation_dispositions':[{'reservation_id':r['reservation_id'],
                    'status':'repair_required' if bad else 'resolved','source_quote':item['source']['source_text'],
                    'explanation':'Remove the unsupported added qualifier; the retained writer concern is not silently cleared.' if bad else 'The signature and address remain supported.'}
                    for r in reservations if r['line_id']==lid]}
            row['word_judgments']=records(item['source'],item['draft'])
            for record in row['word_judgments']:
                record['status']='defect' if bad and record['unit']==6 else 'supported'
                record['reason']='The additional true has no separate source contribution.' if record['status']=='defect' else 'Synthetic contribution bookkeeping for this unchanged phrase.'
            rows.append(row)
        return {'packet':{'reviews':rows}}

    def assert_semantic_hold(self,result):
        row=next(r for r in result['packet']['translations'] if r['id']=='verse-3-line-2')
        self.assertFalse(row['independent_review']['passes'])
        self.assertEqual(row['source_discovery_decisions'],[DECISION])
        self.assertIn('true resting place',row['literal_english'])
        actual=next(item for item in self.review_payload if item['source']['id']=='verse-3-line-2')
        self.assertIn('true',actual['gloss']['word_glosses'][2]['gloss'])
        self.assertEqual(actual['draft']['source_discovery_decisions'],[DECISION])
        self.assertFalse((self.song/'.transcription/pipeline/05-translation.json').exists())

    def test_paid_writer_reaches_independent_review_without_semantic_autoapproval(self):
        result=pipeline.translate(self.song,self.audit,self.glosses,{},self.options,candidate_only=True)
        self.assertEqual(self.calls,['bhakti_literal_translation','bhakti_translation_review'])
        self.assert_semantic_hold(result)

    def test_saved_paid_writer_can_be_reviewed_without_gloss_or_writer_dispatch(self):
        result=pipeline.review_translation(self.song,self.audit,self.glosses,{},self.options,
            {'packet':copy.deepcopy(FIXTURE['translations'])})
        self.assertEqual(self.calls,['bhakti_translation_review'])
        self.assert_semantic_hold(result)


    def test_invalid_returned_citation_escalates_resolved_control_before_review(self):
        self.options.model=routes.FLASH_MODEL;self.options.pro_model=routes.PRO_MODEL
        self.options.semantic_deadline_at=time.time()+60
        dispatches=[]
        def provider(model,key,prompt,**kwargs):
            dispatches.append((model,kwargs['schema_name']))
            result=self.provider(model,key,prompt,**kwargs)
            if kwargs['schema_name']=='bhakti_literal_translation':
                decision=result['packet']['translations'][1]['source_discovery_decisions'][0]
                decision['quotation']=('invented definition not in the dictionary' if model==routes.FLASH_MODEL
                    else PACKET['entries'][0]['dictionary']['whole_entry_text'])
                # Deliberately resolved synthetic routing control, not the paid
                # writer's actual unresolved status (tested separately below).
                if model==routes.PRO_MODEL:
                    result['packet']['translations'][1]['human_review_recommended']=False
            return result
        with patch.object(pipeline.gemini,'call',side_effect=provider):
            result=pipeline.bhakti_semantic_repair.routed_translation(
                pipeline,self.song,self.audit,self.glosses,{},self.options)
        self.assertEqual(dispatches,[(routes.FLASH_MODEL,'bhakti_literal_translation'),
            (routes.PRO_MODEL,'bhakti_literal_translation'),(routes.FLASH_MODEL,'bhakti_translation_review')])
        self.assertEqual(result['resolved_model'],routes.PRO_MODEL)
        self.assertFalse(result['packet']['translations'][1]['independent_review']['passes'])
        count=len(dispatches)
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('resume dispatch')):
            self.assertEqual(pipeline.bhakti_semantic_repair.routed_translation(
                pipeline,self.song,self.audit,self.glosses,{},self.options),result)
        self.assertEqual(len(dispatches),count)

    def test_paid_writer_doubt_survives_citation_retry_and_receives_concrete_review(self):
        self.options.model=routes.FLASH_MODEL;self.options.pro_model=routes.PRO_MODEL
        self.options.semantic_deadline_at=time.time()+60;dispatches=[]
        def provider(model,key,prompt,**kwargs):
            dispatches.append((model,kwargs['schema_name']))
            value=self.provider(model,key,prompt,**kwargs)
            if model==routes.FLASH_MODEL and kwargs['schema_name']=='bhakti_literal_translation':
                value['packet']['translations'][1]['source_discovery_decisions'][0]['quotation']='invented quotation'
            return value
        with patch.object(pipeline.gemini,'call',side_effect=provider):
            result=pipeline.bhakti_semantic_repair.routed_translation(
                pipeline,self.song,self.audit,self.glosses,{},self.options)
        self.assertEqual(dispatches,[(routes.FLASH_MODEL,'bhakti_literal_translation'),
            (routes.PRO_MODEL,'bhakti_literal_translation'),(routes.FLASH_MODEL,'bhakti_translation_review')])
        self.assert_semantic_hold(result)
        row=result['packet']['translations'][1]
        self.assertTrue(row['human_review_recommended'],'Writer uncertainty must remain in its original evidence.')
        self.assertTrue(row['independent_review']['writer_reservation_dispositions'])
        self.assertTrue(all(d['status']=='repair_required' for d in row['independent_review']['writer_reservation_dispositions']))
        saved=next(path for path in self.song.rglob('candidate.json') if path.parent.name=='pro')
        candidate=json.loads(saved.read_text())
        original_fields=copy.deepcopy(candidate['packet'])
        for line in original_fields['translations']:line.pop('word_support',None)
        self.assertEqual(original_fields,FIXTURE['translations'])
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('resume dispatch')):
            self.assertEqual(pipeline.bhakti_semantic_repair.routed_translation(
                pipeline,self.song,self.audit,self.glosses,{},self.options),result)

    def test_invalid_local_writer_seed_holds_without_pro_attempt_or_provider(self):
        self.options.model=routes.FLASH_MODEL;self.options.pro_model=routes.PRO_MODEL
        self.options.semantic_deadline_at=time.time()+60
        self.options.semantic_seed_translation={'packet':copy.deepcopy(FIXTURE['translations'])}
        self.options.semantic_seed_translation['packet']['translations'][1]['source_discovery_decisions'][0]['quotation']='invented definition'
        with self.assertRaisesRegex(RuntimeError,'source discovery|quotation'):
            pipeline.bhakti_semantic_repair.routed_translation(
                pipeline,self.song,self.audit,self.glosses,{},self.options)
        self.assertEqual(self.calls,[])
        states=list((self.song/'.transcription/pipeline/stage-routes').rglob('route-state.json'))
        self.assertEqual(len(states),1)
        self.assertEqual(len(json.loads(states[0].read_text())['attempts']),1)


class RelationCacheVersion(unittest.TestCase):
    def test_relation_policy_change_renews_only_english_review_and_retains_dictionary(self):
        case=caller_fixture.SourceDiscoveryCallerTests('runTest');case.setUp();self.addCleanup(case.doCleanups)
        old=source.RELATION_POLICY_VERSION
        with patch.object(source,'RELATION_POLICY_VERSION',2):
            first=case.case.complete();old_id=case.case.state()['run_id']
        count=len(case.case.calls);http=len(case.http_calls)
        with patch.object(source,'RELATION_POLICY_VERSION',3):
            current=case.case.complete()
            self.assertEqual(case.case.kinds()[count:],['bhakti_literal_translation','bhakti_translation_review'])
            self.assertEqual(current[0]['packet'],first[0]['packet'])
            self.assertNotEqual(case.case.state()['run_id'],old_id)
            self.assertEqual(len(case.http_calls),http)
            count=len(case.case.calls);self.assertEqual(case.case.complete(),current)
            self.assertEqual(len(case.case.calls),count)
        self.assertEqual(old,4,'The corrected witness contract needs a materialized policy version.')


if __name__=='__main__':unittest.main()

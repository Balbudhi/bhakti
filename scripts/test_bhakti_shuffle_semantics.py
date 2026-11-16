"""Contract cases: supported spans/roles, independent review, coverage, cache and abstention.

Expected public strengths are derived from whole-song prominence (central=1,
supporting=.4, incidental=0), normalized per facet to a total no greater than1.
These fixtures describe semantics; they are not claims about a model's accuracy.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import bhakti_shuffle_semantics as sem


TAXONOMY = {'schemaVersion': 1, 'vocabularyVersion': 1, 'concepts': [
    {'id': 'theme.longing', 'facet': 'theme', 'label': 'Longing', 'definition': 'Yearning for an absent or sought beloved.', 'exclude': ['Mere name mention.']},
    {'id': 'action.petition', 'facet': 'action', 'label': 'Petition', 'definition': 'Asking the addressed other for something.', 'exclude': []},
    {'id': 'subject.sai', 'facet': 'subject', 'label': 'Śirḍī Sāī', 'definition': 'The identified saint of Shirdi.', 'exclude': ['saiya meaning beloved']},
    {'id': 'subject.kabir', 'facet': 'subject', 'label': 'Kabīr', 'definition': 'The identified poet/saint.', 'exclude': []}
]}
READER = {'SONG_META': {'languages': ['Hindi'], 'subjectTags': [], 'sourceStatus':'reviewed', 'translationStatus':'reviewed'}, 'SONG_LINES': {
    'a': {'source': 'तोरे बिन सइयाँ', 'roman': 'tore bina saiyā̃', 'english': 'without You, my beloved', 'words': [{'roman': 'saiyā̃', 'gloss': 'beloved'}]},
    'b': {'source': 'कहत कबीर सुनो', 'roman': 'kahata kabīra suno', 'english': 'Says Kabīr, listen', 'words': []}
}, 'SONG_SEQUENCE': [{'ref': 'a', 'section': 'refrain', 'repeats': 3}, {'ref': 'b', 'section': 'verse', 'repeats': 1}], 'SONG_TIMINGS': []}


def assertion(aid='a1', concept='theme.longing', facet='theme', role='theme', prominence='central', line='a', quote='तोरे बिन'):
    return {'id': aid, 'conceptId': concept, 'facet': facet, 'role': role, 'prominence': prominence, 'evidence': [{'lineId': line, 'sourceQuote': quote}], 'rationale': 'Direct textual evidence in context.'}


def fixture_roles(assertions, decisions=None):
    accepted = {d['assertionId'] for d in decisions if d['status']=='accept'} if decisions is not None else {a['id'] for a in assertions}
    result={}
    for a in assertions:
        if a['facet']!='subject':continue
        item=result.setdefault(a['conceptId'],{'conceptId':a['conceptId'],'supportedRoles':[],'reason':'Fixture independent audit.'})
        if a['id'] in accepted:item['supportedRoles'].append({'role':a['role'],'evidence':[{'lineId':e['lineId']} for e in a['evidence']],'reason':'Fixture supported role.'})
    return list(result.values())


def make_record(assertions=None, decisions=None, unresolved=None):
    assertions = [assertion()] if assertions is None else assertions
    extraction = {'assertions': assertions, 'unresolved': unresolved or [], 'coverage': {'complete': True, 'lineCount': 2}, 'newConcepts': []}
    return sem.assemble_record(READER, TAXONOMY, extraction,
        {'decisions': decisions if decisions is not None else [{'assertionId': a['id'], 'status': 'accept', 'reason': 'Supported by full supplied text.'} for a in assertions],
         'omissions': [], 'subjectRoleChecks': fixture_roles(assertions, decisions), 'coverage': {'complete': True, 'lineCount': 2}},
        extraction_request_id='extract-1', review_request_id='review-1', model='test-model')


class SemanticContract(unittest.TestCase):
    def test_v3_citations_bind_exact_source_without_reconstructing_words(self):
        raw = make_record()['extraction']['rawPacket']
        raw['assertions'][0]['evidence'] = [{'lineId': 'a'}]
        bound = sem.bind_source_citations(READER, raw)
        self.assertEqual(bound['assertions'][0]['evidence'][0]['sourceQuote'], READER['SONG_LINES']['a']['source'])
        self.assertNotIn('sourceQuote', raw['assertions'][0]['evidence'][0])
        self.assertNotIn('sourceQuote', sem.response_schema('extraction')['properties']['assertions']['items']['properties']['evidence']['items']['properties'])
        for evidence in ([{'lineId': 'missing'}], [{'lineId':'a'}, {'lineId':'a'}]):
            bad=copy.deepcopy(raw);bad['assertions'][0]['evidence']=evidence
            with self.assertRaises(ValueError):sem.bind_source_citations(READER,bad)
        r=make_record();r['extraction']['citationBinding']['parentExtractionHash']='forged'
        with self.assertRaises(ValueError):sem.validate_semantic_record(READER,TAXONOMY,r)

    def test_subject_roles_coexist_but_duplicate_role_rejects(self):
        signature=assertion(concept='subject.kabir',facet='subject',role='poet_signature',line='b',quote='कबीर')
        narrative=assertion(aid='a2',concept='subject.kabir',facet='subject',role='narrative_subject',line='b',quote='कबीर',prominence='supporting')
        r=make_record([signature,narrative])
        features=sem.build_semantic_features(READER,TAXONOMY,r)['subjects']
        self.assertEqual(features,[{'id':'subject.kabir','role':'narrative_subject','weight':.4}])
        narrative['role']='poet_signature'
        with self.assertRaises(ValueError):sem.validate_semantic_record(READER,TAXONOMY,make_record([signature,narrative]))

    def test_v3_reviewer_tests_citation_entailment_and_role_gaps(self):
        prompt=sem._prompt('review',{}, {})
        for phrase in ('unrelated citation','precise taxonomy definition','missing secondary subject roles','generic rescue/deliverance','relevant contrary passages'):
            self.assertIn(phrase,prompt)
        self.assertEqual(sem.semantic_method_fingerprint(method_version=4),'9ba75380b2d80aca6114f0faac0f0e34a038303da72333e8cbc997fcd7aa7bb8')
        self.assertEqual(sem.semantic_method_fingerprint(method_version=3),'7045c7708c43d631d221d3e0aef55a5626965e50e5e8a76a0c1829741911ea0e')
        self.assertEqual(sem.semantic_method_fingerprint(method_version=1),'6e10c458125a79978ebb2b4135947ea10c42664543ca72d3158a900c1b0b0356')
        self.assertEqual(sem.semantic_method_fingerprint(method_version=2),'d2c9d17c70d04e562c627de8be778edda20a820d0ee5f705edb863a18e662e28')

    def test_v4_omits_interpretive_grammar_but_retains_literal_evidence(self):
        reader=copy.deepcopy(READER);reader['SONG_LINES']['a']['grammarNote']='INTERPRETIVE CLAIM NOT IN LYRICS'
        payload=sem._evidence_payload(reader,TAXONOMY)
        self.assertNotIn('INTERPRETIVE CLAIM',json.dumps(payload))
        self.assertIn('beloved',json.dumps(payload))
        self.assertIn('Evidence hierarchy',sem._prompt('review',payload,{}))
        self.assertIn('subjectRoleChecks',sem.response_schema('review')['required'])

    def test_v4_role_audit_never_invents_missing_secondary_role(self):
        a=assertion(concept='subject.kabir',facet='subject',role='poet_signature',line='b',quote='कबीर')
        r=make_record([a]);audit=r['review']['packet']['subjectRoleChecks'][0]
        audit['supportedRoles'].append({'role':'narrative_subject','evidence':[{'lineId':'b'}],'reason':'Second evidenced role omitted from proposal.'})
        self.assertEqual(sem.build_semantic_features(READER,TAXONOMY,r)['subjects'],[])
        r=make_record([a]);r['review']['packet']['subjectRoleChecks'][0]['supportedRoles']=[]
        self.assertEqual(sem.build_semantic_features(READER,TAXONOMY,r)['subjects'],[])
        r=make_record([a]);r['review']['packet']['subjectRoleChecks']=[]
        with self.assertRaises(ValueError):sem.validate_semantic_record(READER,TAXONOMY,r)
        r=make_record([a]);r['review']['packet']['subjectRoleChecks'][0]['supportedRoles'][0]['evidence']=[{'lineId':'missing'}]
        with self.assertRaises(ValueError):sem.validate_semantic_record(READER,TAXONOMY,r)

    def test_extra_independent_role_audit_is_private_and_cannot_invent_features(self):
        r=make_record()
        audit={'conceptId':'subject.kabir','supportedRoles':[{'role':'poet_signature','evidence':[{'lineId':'b'}],'reason':'Independently noticed signature.'}],'reason':'Additional role observation.'}
        r['review']['packet']['subjectRoleChecks']=[audit]
        self.assertEqual(sem.build_semantic_features(READER,TAXONOMY,r)['subjects'],[])
        audit['supportedRoles'][0]['role']='worship_focus'
        self.assertEqual(sem.build_semantic_features(READER,TAXONOMY,r)['subjects'],[])
        audit['conceptId']='subject.invented'
        with self.assertRaises(ValueError):sem.validate_semantic_record(READER,TAXONOMY,r)

    def test_projection_retains_exact_positive_intersection_without_fabricating_extra_roles(self):
        theme=assertion()
        subject=assertion(aid='a2',concept='subject.kabir',facet='subject',role='narrative_subject',line='b',quote='कबीर')
        r=make_record([theme,subject]);audit=r['review']['packet']['subjectRoleChecks'][0]
        audit['supportedRoles'].append({'role':'worship_focus','evidence':[{'lineId':'b'}],'reason':'Additional role independently noticed.'})
        r['review']['packet']['omissions']=[{'facet':'subject','reason':'An additional role was omitted.'}]
        features=sem.build_semantic_features(READER,TAXONOMY,r)
        self.assertEqual(features['subjects'],[{'id':'subject.kabir','role':'narrative_subject','weight':1.0}])
        self.assertEqual(features['themes'],[{'id':'theme.longing','weight':1.0}])
        audit['supportedRoles']=[{'role':'poet_signature','evidence':[{'lineId':'b'}],'reason':'Narrative role is unsupported.'}]
        self.assertEqual(sem.build_semantic_features(READER,TAXONOMY,r)['subjects'],[])
        self.assertEqual(sem.build_semantic_features(READER,TAXONOMY,r)['themes'],[{'id':'theme.longing','weight':1.0}])
        r['review']['packet']['omissions'][0]['facet']='ambiguous prose'
        self.assertEqual(sem.semantic_summary(READER,TAXONOMY,r)['outcome'],'known')
        self.assertEqual(r['review']['packet']['omissions'][0]['reason'],'An additional role was omitted.')
        summary=sem.semantic_summary(READER,TAXONOMY,r)
        self.assertEqual(summary['method']['projectionVersion'],3)
        self.assertEqual(summary['method']['projectionFingerprint'],sem.projection_fingerprint())

    def test_accepted_supported_theme_projects_with_bound(self):
        record = make_record()
        sem.validate_semantic_record(READER, TAXONOMY, record)
        self.assertEqual(sem.build_semantic_features(READER, TAXONOMY, record), {'themes': [{'id': 'theme.longing', 'weight': 1.0}], 'actions': [], 'subjects': []})

    def test_quote_and_concept_and_coverage_must_be_real(self):
        for mutate in (
            lambda r: r['extraction']['packet']['assertions'][0]['evidence'][0].update(sourceQuote='invented'),
            lambda r: r['extraction']['packet']['assertions'][0].update(conceptId='theme.invented'),
            lambda r: r['review']['packet']['coverage'].update(lineCount=1),
            lambda r: r['review']['packet']['coverage'].update(complete=False),
        ):
            r = make_record(); mutate(r)
            with self.assertRaises(ValueError): sem.validate_semantic_record(READER, TAXONOMY, r)

    def test_review_binds_proposal_and_is_a_distinct_request(self):
        r = make_record(); r['review']['requestId'] = r['extraction']['requestId']
        with self.assertRaises(ValueError): sem.validate_semantic_record(READER, TAXONOMY, r)
        r = make_record(); r['extraction']['packet']['assertions'][0]['rationale'] = 'changed after review'
        with self.assertRaises(ValueError): sem.validate_semantic_record(READER, TAXONOMY, r)

    def test_rejected_false_identity_cannot_enter_features(self):
        r = make_record([assertion(concept='subject.sai',facet='subject',role='worship_focus',quote='सइयाँ')],
                        [{'assertionId':'a1','status':'reject','reason':'Beloved is not the saint name.'}])
        self.assertEqual(sem.build_semantic_features(READER,TAXONOMY,r)['subjects'], [])

    def test_signature_is_valid_reference_but_never_public_subject(self):
        r=make_record([assertion(concept='subject.kabir',facet='subject',role='poet_signature',line='b',quote='कबीर')])
        self.assertEqual(sem.build_semantic_features(READER,TAXONOMY,r)['subjects'], [])

    def test_every_assertion_requires_exactly_one_review_decision(self):
        for decisions in ([], [{'assertionId':'a1','status':'accept','reason':'yes'}]*2):
            with self.assertRaises(ValueError): sem.validate_semantic_record(READER,TAXONOMY,make_record(decisions=decisions))

    def test_explicit_unknown_is_legal_but_not_invented_positive(self):
        r=make_record([], unresolved=[{'facet':'theme','reason':'No sufficiently grounded concept in this vocabulary.'}])
        self.assertEqual(sem.build_semantic_features(READER,TAXONOMY,r),{'themes':[],'actions':[],'subjects':[]})
        self.assertEqual(sem.semantic_summary(READER,TAXONOMY,r)['outcome'],'unknown')

    def test_material_text_change_invalidates_but_credit_does_not(self):
        r=make_record(); changed=copy.deepcopy(READER);changed['SONG_LINES']['a']['words'][0]['gloss']='saint'
        with self.assertRaises(ValueError):sem.validate_semantic_record(changed,TAXONOMY,r)
        changed=copy.deepcopy(READER);changed['SONG_META']['singer']='Other artist'
        sem.validate_semantic_record(changed,TAXONOMY,r)

    def test_material_omission_remains_private_without_erasing_supported_tag(self):
        r=make_record();r['review']['packet']['omissions']=[{'facet':'theme','reason':'A central supported theme was missed.'}]
        self.assertEqual(sem.semantic_summary(READER,TAXONOMY,r)['outcome'],'known')

    def test_cached_assessment_has_no_repeat_call(self):
        extraction=make_record()['extraction']['packet']; review=make_record()['review']['packet']; calls=[]
        def call(*args,**kwargs):
            calls.append(1);return {'packet':extraction if len(calls)==1 else review,'resolved_model':'test-model','usage':{}}
        with tempfile.TemporaryDirectory() as d:
            options=sem.SemanticOptions(model='test-model',call_model=call,allow_paid=True)
            sem.assess_semantics(READER,TAXONOMY,options=options,cache_dir=Path(d))
            sem.assess_semantics(READER,TAXONOMY,options=options,cache_dir=Path(d))
            self.assertEqual(len(calls),2)

    def test_failed_request_does_not_silently_retry_after_restart(self):
        calls=[]
        def call(*args,**kwargs):calls.append(1);raise TimeoutError('unknown upstream outcome')
        with tempfile.TemporaryDirectory() as d:
            options=sem.SemanticOptions(model='test-model',call_model=call,allow_paid=True)
            for _ in range(2):
                with self.assertRaises(Exception):sem.assess_semantics(READER,TAXONOMY,options=options,cache_dir=Path(d))
            self.assertEqual(len(calls),1)

    def test_requests_supply_full_original_evidence_and_exact_proposal(self):
        reader=copy.deepcopy(READER)
        for i in range(537):
            key=f"long-{i}"
            reader['SONG_LINES'][key]={'source':f"source boundary {i}", 'roman':f"roman {i}", 'english':f"meaning {i}", 'words':[{'roman':'token','gloss':f"gloss boundary {i}"}]}
            reader['SONG_SEQUENCE'].append({'ref':key,'section':'verse','repeats':1})
        extraction=make_record()['extraction']['packet']; extraction['coverage']['lineCount']=539
        review=make_record()['review']['packet']; review['coverage']['lineCount']=539
        prompts=[]
        def call(model,key,prompt,**kwargs):
            prompts.append(prompt)
            self.assertIn('source boundary 536',prompt)
            self.assertIn('gloss boundary 536',prompt)
            self.assertIn('theme.longing',prompt)
            self.assertIn('\"expectedLineCount\":539',prompt)
            self.assertIn('COPY that exact integer',prompt)
            if len(prompts)==2:
                self.assertIn('Direct textual evidence in context.',prompt)
                self.assertIn('without You, my beloved',prompt)
            return {'packet':extraction if len(prompts)==1 else review,'resolved_model':'test-model','usage':{}}
        with tempfile.TemporaryDirectory() as d:
            sem.assess_semantics(reader,TAXONOMY,options=sem.SemanticOptions(model='test-model',call_model=call,allow_paid=True),cache_dir=Path(d))
        self.assertEqual(len(prompts),2)

    def test_repeated_performance_does_not_multiply_semantic_strength(self):
        r=make_record();reader=copy.deepcopy(READER)
        reader['SONG_SEQUENCE']*=10
        a=r['extraction']['packet']; b=r['review']['packet']
        repeated=sem.assemble_record(reader,TAXONOMY,a,b,extraction_request_id='x',review_request_id='y',model='test-model')
        self.assertEqual(sem.build_semantic_features(reader,TAXONOMY,repeated),sem.build_semantic_features(READER,TAXONOMY,r))

    def test_facet_strength_is_bounded_and_prominence_preserved(self):
        taxonomy=copy.deepcopy(TAXONOMY)
        taxonomy['concepts'].append({'id':'theme.second','facet':'theme','label':'Second','definition':'Fixture','exclude':[]})
        a=assertion();b=assertion(aid='a2',concept='theme.second',prominence='supporting')
        extraction={'assertions':[a,b],'unresolved':[],'coverage':{'complete':True,'lineCount':2},'newConcepts':[]}
        review={'decisions':[{'assertionId':i,'status':'accept','reason':'Supported'} for i in ('a1','a2')],'omissions':[],'subjectRoleChecks':[],'coverage':{'complete':True,'lineCount':2}}
        r=sem.assemble_record(READER,taxonomy,extraction,review,extraction_request_id='x',review_request_id='y',model='test-model')
        weights={x['id']:x['weight'] for x in sem.build_semantic_features(READER,taxonomy,r)['themes']}
        self.assertAlmostEqual(sum(weights.values()),1.0)
        self.assertAlmostEqual(weights['theme.longing']/weights['theme.second'],2.5,places=5)

    def test_unknown_without_reason_is_rejected(self):
        with self.assertRaises(ValueError):sem.validate_semantic_record(READER,TAXONOMY,make_record([]))

    def test_unapproved_dispatch_never_calls_provider(self):
        calls=[]
        def call(*args,**kwargs):calls.append(1);raise AssertionError('must not dispatch')
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(Exception):sem.assess_semantics(READER,TAXONOMY,options=sem.SemanticOptions(call_model=call,allow_paid=False),cache_dir=Path(d))
        self.assertEqual(calls,[])

    def test_resume_never_rebinds_old_review_to_changed_cached_proposal(self):
        extraction=make_record()['extraction']['packet'];review=make_record()['review']['packet'];calls=[]
        def call(*args,**kwargs):
            calls.append(1);return {'packet':extraction if len(calls)==1 else review,'resolved_model':'test-model','usage':{}}
        with tempfile.TemporaryDirectory() as d:
            options=sem.SemanticOptions(model='test-model',call_model=call,allow_paid=True)
            save=sem._private_json
            def interrupt_before_acceptance(path,value):
                if path.name=='assessment.json':raise OSError('simulated interruption before acceptance persisted')
                save(path,value)
            with mock.patch.object(sem,'_private_json',side_effect=interrupt_before_acceptance):
                with self.assertRaises(OSError):sem.assess_semantics(READER,TAXONOMY,options=options,cache_dir=Path(d))
            path=next(Path(d).glob('*/extraction.json'));changed=json.loads(path.read_text())
            changed['packet']['assertions'][0]['rationale']='different interpretation introduced after review'
            path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):sem.assess_semantics(READER,TAXONOMY,options=options,cache_dir=Path(d))
            self.assertEqual(len(calls),2)

    def test_upstream_unreviewed_text_never_gets_positive_model_assessment(self):
        reader=copy.deepcopy(READER);reader['SONG_META']['sourceStatus']='source-script-migration-required'
        calls=[]
        def call(*args,**kwargs):calls.append(1);raise AssertionError('unsupported text must not dispatch')
        readiness=sem.semantic_input_readiness(reader)
        self.assertFalse(readiness['eligible']);self.assertIn('unavailable',readiness['reason'])
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):sem.assess_semantics(reader,TAXONOMY,options=sem.SemanticOptions(call_model=call,allow_paid=True),cache_dir=Path(d))
        self.assertEqual(calls,[])

    def test_prior_review_fingerprint_is_preserved_not_relabelled(self):
        record=make_record()
        prior=sem.assemble_record(READER,TAXONOMY,record['extraction']['packet'],record['review']['packet'],extraction_request_id='old-x',review_request_id='old-y',model='test-model',method_version=1)
        summary=sem.semantic_summary(READER,TAXONOMY,prior)
        self.assertEqual(summary['method']['version'],1)
        self.assertEqual(summary['method']['fingerprint'],sem.semantic_method_fingerprint('test-model',1))
        self.assertNotEqual(summary['method']['fingerprint'],sem.semantic_method_fingerprint('test-model',2))


if __name__ == '__main__': unittest.main()

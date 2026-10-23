"""Known source lookup obligations survive real semantic calls, caches and batching."""
import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import bhakti_lexical_producer as producer
import test_automatic_semantic_lexical as fixture

class ExplicitLexicalRequests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.AutomaticSemanticLexicalTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.request={'line_id':'v','word_indices':[0],'surfaces':['vajra'],'reason':'Compare physical hardness and figurative resolve using witnessed definitions.'}
        self.case.options.lexical_requested_spans=[self.request]

    def test_exact_known_target_is_present_in_initial_actual_gloss_prompt(self):
        result=self.case.complete()
        prompt=self.case.calls[0]['prompt']
        requests=json.JSONDecoder().raw_decode(prompt.split('Requested spans: ',1)[1])[0]
        self.assertEqual(requests,[self.request])
        self.assertIn('having the hardness of a diamond',self.case.calls[-1]['prompt'])
        self.assertEqual(self.case.kinds(),['bhakti_word_glosses','bhakti_literal_translation','bhakti_translation_review'])
        count=len(self.case.calls);self.assertEqual(self.case.complete(),result);self.assertEqual(len(self.case.calls),count)
        self.assertNotIn('support_decisions',result[0]['packet']['glosses'][0])

    def test_modern_empty_query_and_gap_cannot_skip_known_span_before_writer(self):
        original=self.case.transport
        def transport(*a,**kw):
            result=original(*a,**kw)
            if 'word_gloss' in kw['schema_name']:result['packet']['glosses'][0]['lexical_queries']=[]
            return result
        with patch.object(fixture.pipeline.gemini,'call',side_effect=transport):
            with self.assertRaisesRegex((ValueError,RuntimeError),'required lexical span|requested lexical'):
                self.case.complete()
        self.assertEqual(self.case.kinds(),['bhakti_word_glosses'])
        self.assertFalse((self.case.packets/'semantic-acceptance.json').exists())

    def test_stale_out_of_range_unknown_and_duplicate_requests_hold_before_calls(self):
        for change in [{'surfaces':['different']},{'word_indices':[1]},{'line_id':'absent'}, {'reason':''}]:
            with self.subTest(change=change):
                self.case.options.lexical_requested_spans=[{**self.request,**change}]
                with self.assertRaisesRegex((ValueError,RuntimeError),'requested lexical|lookup request'):
                    self.case.complete()
                self.assertFalse(self.case.calls)
        self.case.options.lexical_requested_spans=[self.request,copy.deepcopy(self.request)]
        with self.assertRaisesRegex((ValueError,RuntimeError),'duplicate|requested lexical'):self.case.complete()
        self.assertFalse(self.case.calls)

    def test_requested_identity_change_invalidates_accepted_gloss_not_audio(self):
        self.case.complete();count=len(self.case.calls);old_id=self.case.state()['run_id']
        self.case.options.lexical_requested_spans=[{**self.request,'reason':'Check the exact physical frame in this passage.'}]
        self.case.complete()
        self.assertNotEqual(self.case.state()['run_id'],old_id)
        self.assertEqual(self.case.kinds()[count:],['bhakti_word_glosses','bhakti_literal_translation','bhakti_translation_review'])
        count=len(self.case.calls);self.case.complete();self.assertEqual(len(self.case.calls),count)

    def test_unrequested_easy_modern_line_may_legitimately_have_no_lookup(self):
        self.case.options.lexical_requested_spans=[];original=self.case.transport
        def transport(*a,**kw):
            result=original(*a,**kw)
            if 'word_gloss' in kw['schema_name']:result['packet']['glosses'][0]['lexical_queries']=[]
            return result
        with patch.object(fixture.pipeline.gemini,'call',side_effect=transport):result=self.case.complete()
        self.assertEqual(self.case.state()['status'],'accepted')
        self.assertEqual(result[0]['packet']['glosses'][0]['lexical_queries'],[])

    def test_explicit_gap_is_honest_coverage_not_fabricated_evidence(self):
        original=self.case.transport
        def transport(*a,**kw):
            result=original(*a,**kw)
            if 'word_gloss' in kw['schema_name']:
                row=result['packet']['glosses'][0];row['lexical_queries']=[]
                row['lexical_query_gaps']=[{'word_indices':[0],'reason':'No bounded English query proposed; contextual reading remains a claim.'}]
            return result
        with patch.object(fixture.pipeline.gemini,'call',side_effect=transport):result=self.case.complete()
        self.assertIn('LEXICAL EVIDENCE COVERAGE GAPS',self.case.calls[-1]['prompt'])
        self.assertNotIn('TARGETED LEXICAL SUPPORT',self.case.calls[-1]['prompt'])
        self.assertEqual(result[0]['packet']['glosses'][0]['lexical_query_gaps'][0]['word_indices'],[0])

    def test_explicit_requests_require_enabled_config_before_complete_or_direct_gloss(self):
        for direct in (False,True):
            with self.subTest(direct=direct),patch.dict(os.environ,{'BHAKTI_AUTO_LEXICAL':'0'}):
                with self.assertRaisesRegex((ValueError,RuntimeError),'requested lexical.*automatic|automatic.*requested lexical'):
                    if direct:fixture.pipeline.gloss(self.case.song,self.case.audit,self.case.options)
                    else:self.case.complete()
                self.assertFalse(self.case.calls)

    def test_disabled_producer_with_no_requests_keeps_ordinary_path(self):
        self.case.options.lexical_requested_spans=[]
        with patch.dict(os.environ,{'BHAKTI_AUTO_LEXICAL':'0'}):
            self.case.complete()
        self.assertEqual(self.case.kinds(),['bhakti_word_glosses','bhakti_literal_translation','bhakti_translation_review'])

    def test_absent_and_empty_requests_preserve_exact_policy_identity(self):
        self.case.options.lexical_requested_spans=[]
        empty=fixture.pipeline.semantic_stage_policy(self.case.options,stage='gloss')
        del self.case.options.lexical_requested_spans
        absent=fixture.pipeline.semantic_stage_policy(self.case.options,stage='gloss')
        self.assertEqual(empty,absent)

    def test_route_context_omits_empty_and_canonicalizes_equivalent_request_order(self):
        semantic=fixture.pipeline.bhakti_semantic_repair
        self.case.options.lexical_requested_spans=[]
        empty=semantic.stage_context(self.case.options)
        del self.case.options.lexical_requested_spans
        self.assertEqual(empty,semantic.stage_context(self.case.options))
        other={**self.request,'line_id':'other'}
        self.case.options.lexical_requested_spans=[self.request,other]
        first=semantic.stage_context(self.case.options)
        self.case.options.lexical_requested_spans=[other,self.request]
        self.assertEqual(first,semantic.stage_context(self.case.options))

    def test_direct_gloss_stale_request_holds_before_provider(self):
        self.case.options.lexical_requested_spans=[{**self.request,'surfaces':['stale']}]
        with self.assertRaisesRegex((ValueError,RuntimeError),'requested lexical|lookup request'):
            fixture.pipeline.gloss(self.case.song,self.case.audit,self.case.options)
        self.assertFalse(self.case.calls)

    def test_actual_gloss_batches_receive_only_their_validated_requests(self):
        from test_sense_decisions import decisions_for
        case=self.case
        other={**copy.deepcopy(case.lines[0]),'id':'other'}
        case.lines.extend([{**copy.deepcopy(case.lines[0]),'id':'context-'+str(i)} for i in range(39)]+[other])
        case.options.gloss_batch_size=40
        case.options.lexical_requested_spans=[self.request,{**self.request,'line_id':'other','reason':'Check second source target.'}]
        expected={r['line_id']:r for r in case.options.lexical_requested_spans}
        seen=[]
        def transport(model,key,prompt,**kw):
            case.calls.append({'kind':kw['schema_name'],'prompt':prompt})
            self.assertIn('word_gloss',kw['schema_name'])
            requests=json.JSONDecoder().raw_decode(prompt.split('Requested spans: ',1)[1])[0]
            targets=json.JSONDecoder().raw_decode(prompt.split('TARGET LYRICS (return these IDs only):\n',1)[1])[0]
            expected_here=[expected[target['id']] for target in targets if target['id'] in expected]
            self.assertEqual(requests,expected_here)
            seen.extend(request['line_id'] for request in requests)
            rows=[]
            for target in targets:
                row=copy.deepcopy(case.gloss[0]);row['id']=target['id']
                row['sense_decisions']=decisions_for(case.lines,['Hindi'])[row['id']]
                row.update(semantic_frame={field:'' for field in fixture.pipeline.SEMANTIC_FRAME_FIELDS},grammar_note='',uncertainty='')
                rows.append(row)
            return {'packet':{'glosses':rows}}
        with patch.object(fixture.pipeline.gemini,'call',side_effect=transport):
            result=fixture.pipeline.gloss(case.song,case.audit,case.options)
        self.assertEqual(set(seen),{'v','other'})
        self.assertEqual(len(result['packet']['glosses']),41)

    def test_full_source_validation_then_batch_projection_and_typed_union(self):
        line=copy.deepcopy(self.case.lines[0]);other={**line,'id':'other'}
        self.case.options.semantic_full_source=[line,other]
        second={**self.request,'line_id':'other','reason':'Independent later occurrence.'}
        self.case.options.lexical_requested_spans=[self.request,second]
        self.case.options.semantic_repair_feedback=[{'kind':'english_realization','references':[{'line_id':'v','word_indices':[0]}]}]
        self.assertEqual(producer.required_spans(self.case.options,[line]),[self.request])
        self.assertEqual(producer.required_spans(self.case.options,[other]),[second])
        self.case.options.lexical_requested_spans[1]['surfaces']=['stale']
        with self.assertRaisesRegex(ValueError,'requested lexical|lookup request'):
            producer.required_spans(self.case.options,[line])

if __name__=='__main__':unittest.main()

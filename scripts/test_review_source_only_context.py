"""Real two-row excerpt context through review projection; no paid calls."""
import argparse
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import bhakti_pipeline as pipeline
import test_semantic_stage_routes as stage_fixture
import test_review_task_version as task_fixture
import test_bounded_review_payload as bounded_fixture

FIXTURE=json.loads((Path(__file__).parent/'fixtures/source-citations/rehna-paid-writer.json').read_text())


class SourceOnlyReviewContext(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.song=Path(self.tmp.name);self.lines=copy.deepcopy(FIXTURE['lines'])
        self.glosses=copy.deepcopy(FIXTURE['glosses'])
        self.drafts=copy.deepcopy(FIXTURE['translations']['translations'])
        self.options=argparse.Namespace(model='fixture',force=False,timeout=10,
            semantic_performance_order=[{'ref':line['id'],'repeats':2} for line in self.lines])
        self.calls=[]
        for manager in (patch.object(pipeline.gemini,'key',return_value='fixture'),
            patch.object(pipeline.gemini,'call',side_effect=self.provider)):
            manager.start();self.addCleanup(manager.stop)

    def provider(self,model,key,prompt,**kwargs):
        self.calls.append(prompt)
        ids=json.JSONDecoder().raw_decode(prompt.split('OUTPUT TARGET IDS (return exactly these, once each):\n',1)[1])[0]
        return {'packet':{'reviews':[{'id':lid,'passes':True,'agency_preserved':True,
            'imagery_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[],
            'human_review_recommended':False,'material_choice':'','reason':'Delivery control only.','issues':[]}
            for lid in ids]}}

    def reading(self):
        ids=[line['id'] for line in self.lines]
        return pipeline.translation_reading_context(self.lines,self.glosses,self.drafts,ids,
            performance_order=self.options.semantic_performance_order)

    def payload(self):
        target=[{'source':line,'gloss':gloss,'draft':draft} for line,gloss,draft in zip(self.lines,self.glosses,self.drafts)]
        return pipeline.translation_review_payload(target,self.reading())

    def review(self):
        return pipeline.independently_review_translations(self.song,self.lines,self.glosses,self.drafts,
            '(none supplied)',self.options,languages=['Hindi'])

    def test_actual_excerpt_keeps_native_definitions_and_bound_order_once(self):
        before=copy.deepcopy((self.lines,self.glosses,self.drafts))
        value=self.payload();context=value['reading_context']['source_only_context']
        definitions={row['id']:row for row in context['definitions']}
        self.assertEqual(set(definitions),{'refrain-1','refrain-des-veerana'})
        self.assertEqual(definitions['refrain-des-veerana']['source_text'],'देस ये वीराना है')
        expected=[{'anchor_id':line['id'],'before':[row['id'] for row in window['before']],
            'after':[row['id'] for row in window['after']]}
            for line in self.lines for window in line['performed_context']]
        self.assertEqual(context['windows'],expected)
        self.assertEqual(context['order_basis'],'source-bound-neighbor-windows')
        serialized=json.dumps(value,ensure_ascii=False)
        self.assertEqual(serialized.count('देस ये वीराना है'),1)
        self.assertNotIn('performed_context',serialized)
        for row in context['definitions']:
            self.assertFalse({'gloss','draft','english','semantic_frame','word_glosses'}&set(row))
        self.assertEqual(before,(self.lines,self.glosses,self.drafts))

    def test_actual_review_contains_neighbor_source_and_cache_tracks_its_change(self):
        self.review();self.assertEqual(len(self.calls),1)
        self.assertTrue('देस ये वीराना है' in self.calls[0]);self.assertTrue('source_only_context' in self.calls[0])
        self.review();self.assertEqual(len(self.calls),1)
        for line in self.lines:
            for window in line['performed_context']:
                for neighbor in window['before']+window['after']:
                    if neighbor['id']=='refrain-des-veerana':neighbor['source_text']='देस ये वीराना है — changed fixture'
        self.review();self.assertEqual(len(self.calls),2)
        self.assertIn('changed fixture',self.calls[-1])

    def test_unknown_id_only_context_holds_before_any_dispatch(self):
        self.lines[0]['performed_context'][0]['before'].append({'id':'missing-required-neighbor'})
        with self.assertRaisesRegex(ValueError,'source|context|neighbor'):self.review()
        self.assertEqual(len(self.calls),0)

    def test_id_only_reference_resolves_from_other_window_and_native_only_is_preserved(self):
        self.lines[0]['performed_context'][0]['before'][1]={'id':'refrain-des-veerana'}
        for line in self.lines:
            for window in line['performed_context']:
                for neighbor in window['before']+window['after']:
                    if neighbor['id']=='refrain-des-veerana':neighbor.pop('roman',None)
        context=self.payload()['reading_context']['source_only_context']
        row=next(row for row in context['definitions'] if row['id']=='refrain-des-veerana')
        self.assertEqual(row,{'id':'refrain-des-veerana','source_text':'देस ये वीराना है'})

    def test_conflicting_missing_or_known_neighbor_definition_holds_before_dispatch(self):
        original=copy.deepcopy(self.lines)
        for neighbor_id in ('refrain-des-veerana','verse-3-line-2'):
            self.lines=copy.deepcopy(original)
            for neighbor in self.lines[0]['performed_context'][0]['before']+self.lines[0]['performed_context'][0]['after']:
                if neighbor['id']==neighbor_id:
                    neighbor['source_text']='contradictory original source';break
            with self.subTest(neighbor_id=neighbor_id),self.assertRaisesRegex(ValueError,'conflict|source|context'):
                self.review()
        self.assertEqual(len(self.calls),0)

    def test_repeated_windows_deduplicate_text_without_recursive_context_growth(self):
        self.lines[0]['performed_context']*=20
        # Neighbors' incidental nested context is not a new review obligation.
        self.lines[0]['performed_context'][0]['before'][0]['performed_context']=[{'before':[{'id':'do-not-expand'}],'after':[]}]
        value=self.payload();context=value['reading_context']['source_only_context']
        self.assertEqual(len(context['windows']),21)
        self.assertEqual(len(context['definitions']),2)
        self.assertEqual(json.dumps(value,ensure_ascii=False).count('देस ये वीराना है'),1)
        self.assertNotIn('do-not-expand',json.dumps(value))

    def test_source_only_context_population_and_window_overflow_hold(self):
        original=copy.deepcopy(self.lines)
        self.lines[0]['performed_context']=[{'before':[{'id':f'extra-{i}','source_text':f'original source {i}'} for i in range(81)],'after':[]}]
        with self.assertRaisesRegex(ValueError,'limit|scope|exceed'):self.review()
        self.assertEqual(len(self.calls),0)
        self.lines=copy.deepcopy(original);self.lines[0]['performed_context']*=81
        with self.assertRaisesRegex(ValueError,'limit|scope|exceed'):self.review()
        self.assertEqual(len(self.calls),0)
        self.lines=copy.deepcopy(original)
        neighbor=copy.deepcopy(self.lines[0]['performed_context'][0]['before'][0])
        self.lines[0]['performed_context']=[{'before':[neighbor]*641,'after':[]}]
        with self.assertRaisesRegex(ValueError,'limit|scope|exceed'):self.review()
        self.assertEqual(len(self.calls),0)

    def test_known_ids_keep_unrepresented_source_bound_order_without_new_definitions(self):
        neighbor={key:self.lines[1][key] for key in ('id','source_text','roman')}
        self.lines[0]['performed_context']=[{'before':[neighbor],'after':[]}]
        self.lines[1]['performed_context']=[]
        context=self.payload()['reading_context']['source_only_context']
        self.assertEqual(context['definitions'],[])
        self.assertEqual(context['windows'],[{'anchor_id':self.lines[0]['id'],
            'before':[self.lines[1]['id']],'after':[]}])

    def test_known_complete_context_stays_deduplicated_and_bounded(self):
        case=bounded_fixture.BoundedReviewPayloadTests('runTest');case.setUp();self.addCleanup(case.doCleanups)
        case.review(['line-300']);evidence,reading=case.sections(case.calls[0][1])
        self.assertNotIn('source_only_context',reading)
        self.assertEqual({r['source']['id'] for r in evidence+reading['context_rows']},{f'line-{i}' for i in range(297,304)})
        self.assertLess(len(case.calls[0][1]),30000)


class ReviewContextVersion(unittest.TestCase):
    def test_accepted_complete_refreshes_only_review_for_context_task(self):
        case=stage_fixture.SemanticStageRoutesTests('runTest');case.setUp();self.addCleanup(case.doCleanups)
        with patch.object(pipeline,'REVIEW_TASK_VERSION',1):old=case.c.complete()
        count=len(case.calls)
        with patch.object(pipeline,'REVIEW_TASK_VERSION',2):
            new=case.c.complete();self.assertEqual([c['kind'] for c in case.calls[count:]],['bhakti_translation_review'])
            self.assertEqual(new[0]['packet'],old[0]['packet'])
            self.assertEqual(task_fixture.writer_rows(new[1]),task_fixture.writer_rows(old[1]))
            count=len(case.calls);self.assertEqual(case.c.complete(),new);self.assertEqual(len(case.calls),count)
        self.assertEqual(pipeline.REVIEW_TASK_VERSION,2)

    def test_audit_context_task_retains_prior_findings_then_resumes_free(self):
        case=task_fixture.LibraryAuditReviewVersion('runTest');case.setUp();self.addCleanup(case.doCleanups)
        pipeline.REVIEW_TASK_VERSION=1;case.defect=True;case.f.execute(case.data)
        pipeline.REVIEW_TASK_VERSION=2;case.defect=False
        new=case.f.execute(case.data)
        self.assertEqual(len(case.calls),2);self.assertTrue(new['finding_snapshot']['findings'])
        self.assertEqual(len(new['finding_snapshot']['reviews']),2)
        self.assertEqual(case.f.execute(case.data),new);self.assertEqual(len(case.calls),2)

if __name__=='__main__':unittest.main()

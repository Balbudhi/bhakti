"""Review-first actual semantic callers; only provider/HTTP transports replaced.

The reader fixture is an exact existing published row. Transcript case removes
reader-only fields. These are orchestration controls, not translation approval.
"""
import copy
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlparse

import bhakti_library_pass as library
import dictionary_corpus as corpus
import test_automatic_semantic_lexical as fixture
from test_sense_decisions import decisions_for

FIX=Path(__file__).parent/'fixtures/source_discovery'

class SourceDiscoveryCallerTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.AutomaticSemanticLexicalTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.reader=json.loads((FIX/'reader-line.json').read_text())
        self.case.lines=library.reader_evidence(self.reader)[0]
        self.case.audit={'packet':{'verified_lines':self.case.lines,'metadata':{'languages':['Hindi']},
            'performance_order':[{'line_id':self.case.lines[0]['id'],'occurrence':1}]}}
        Path(os.environ['BHAKTI_LEXICON_PATH']).write_text('{"entries":[]}')
        self.case.options.source_discovery_max_requests=4
        self.case.options.source_discovery_budget=fixture.pipeline.bhakti_source_discovery.configure_run_budget(
            self.case.root,self.case.options.semantic_repair_seconds+__import__('time').time(),self.case.options)
        self.case.options.source_discovery_opener=self.opener
        self.records={r['query']:r for r in json.loads((FIX/'acquisition.json').read_text())}
        self.http_calls=[];self.gloss_count=0;self.translation_count=0;self.needs_gloss_change=False
        self.patcher=patch.object(fixture.pipeline.gemini,'call',side_effect=self.transport)
        self.patcher.start();self.addCleanup(self.patcher.stop)

    def opener(self,url,timeout):
        query=parse_qs(urlparse(url).query)['qs'][0];self.http_calls.append(query)
        return io.BytesIO(corpus.load_cached_witness(FIX,self.records[query]))

    def transport(self,model,key,prompt,**kw):
        case=self.case;kind=kw['schema_name'];case.calls.append({'kind':kind,'prompt':prompt})
        line=case.lines[0];line_id=line['id']
        if 'word_gloss' in kind:
            self.gloss_count+=1
            query_schema=kw['response_schema']['properties']['glosses']['items']['properties']['lexical_queries']['items']['properties']
            self.assertIn('source_queries',query_schema)
            if self.gloss_count>1:
                self.assertIn('bajr-ang',prompt)
                self.assertIn('Having a hardy frame',prompt)
            initial_wrong=self.needs_gloss_change and self.gloss_count==1
            expression='strong' if initial_wrong else 'with adamantine limbs'
            tokens=fixture.pipeline.bhakti_translation_policy.word_tokens(line)
            glosses=['victory','victory','victory',expression,'strong']
            row={'id':line_id,'word_glosses':[{'roman':token,'gloss':glosses[i],'concept_key':'','preserve_in_english':False} for i,token in enumerate(tokens)],
                'semantic_frame':{field:'' for field in fixture.pipeline.SEMANTIC_FRAME_FIELDS},
                'grammar_note':'','uncertainty':'','sense_decisions':decisions_for(case.lines,['Hindi'])[line_id],
                'lexical_queries':[{'word_indices':[3],'surfaces':['bajaraṅga'],'reason':'Check the precise compound sense.',
                    'source_entry_ids':[],'source_queries':['वज्र'],
                    'english_candidates':[{'expression':expression,'kind':'compositional_phrase',
                        'english_lemmas':[] if initial_wrong else ['adamantine']}]}], 'lexical_query_gaps':[]}
            return {'packet':{'glosses':[row]}}
        self.assertIn('SOURCE DISCOVERY EVIDENCE:\n',prompt)
        discovery=json.JSONDecoder().raw_decode(prompt.split('SOURCE DISCOVERY EVIDENCE:\n',1)[1])[0]
        self.assertIn('bajr-ang',prompt);self.assertIn('Having a hardy frame',prompt)
        self.assertEqual(discovery['entries'][0]['source_spellings'],['वज्र'])
        if kind=='bhakti_translation_review':
            self.assertIn('source_discovery_decisions',prompt)
            return {'packet':{'reviews':[{'id':line_id,'passes':True,'human_review_recommended':False,
                'agency_preserved':True,'imagery_preserved':True,'all_meaning_accounted_for':True,
                'unsupported_additions':[],'material_choice':'','reason':'Transport control only.','issues':[]}]}}
        self.translation_count+=1
        support=json.JSONDecoder().raw_decode(prompt.split('TARGETED LEXICAL SUPPORT:\n',1)[1])[0]
        target=support['targets'][0];candidate=target['english_candidates'][0];expression=candidate['expression']
        initial_wrong=self.needs_gloss_change and self.translation_count==1
        english='Victory! Victory! Victory! '+expression+', strong!'
        quoted='vajrāng (˚ra+an˚), vulg. vajr-ang, bajr-ang, adj. & s.m. Having a hardy frame, hardy; — an epithet of Hauumān; — a robust or hardy man'
        row={'id':line_id,'literal_english':english,'segments':[{'text':'Victory! ','word_indices':[0]},
                {'text':'Victory! ','word_indices':[1]},{'text':'Victory! ','word_indices':[2]},
                {'text':expression,'word_indices':[3]},{'text':', strong!','word_indices':[4]}],
            'wording_decisions':[{'target_id':target['id'],'chosen_candidate_id':candidate['id'],
                'expression':expression,'kind':candidate['kind'],'english_evidence_ids':candidate['english_evidence_ids'],
                'word_indices':[3],'ordinary_paraphrase':'having limbs hard as diamond','component_word_indices':[[3]],'reason':'Literal compound control.'}],
            'source_discovery_decisions':[{'target_id':discovery['targets'][0]['id'],'entry_id':discovery['entries'][0]['entry_id'],
                'status':'matched','attested_form':'bajr-ang','quotation':quoted,'relation_kind':'compound_subentry',
                'meaning_applied':'having a hardy frame','changes_gloss':initial_wrong,
                'reason':'The witnessed whole compound adds limbs/frame, not a bare root-strength meaning.'}],
            'human_review_recommended':False,'material_alternatives':[],'choice_note':'','uncertainty':'',
            'fidelity':{'agency_and_image_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[],'notes':''}}
        return {'packet':{'translations':[row]}}

    def assert_happy_path(self):
        original=copy.deepcopy(self.case.audit)
        result=self.case.complete()
        self.assertEqual(self.case.kinds(),['bhakti_word_glosses','bhakti_literal_translation','bhakti_translation_review'])
        self.assertEqual(self.case.state()['status'],'accepted')
        self.assertEqual(self.case.audit,original)
        self.assertNotIn('support_decisions',result[0]['packet']['glosses'][0])
        calls=len(self.case.calls);http=len(self.http_calls)
        self.assertEqual(self.case.complete(),result)
        self.assertEqual(len(self.case.calls),calls);self.assertEqual(len(self.http_calls),http)
        return result

    def test_actual_reader_evidence_forwards_native_and_same_gloss_queries(self):
        self.assertIn('sourceWords',self.case.lines[0])
        self.assert_happy_path()
        self.assertEqual(self.http_calls,['बजरंग','वज्र'])

    def test_fresh_transcript_without_reader_fields_forwards_explicit_hypothesis(self):
        self.case.lines[:]=[{key:self.case.lines[0][key] for key in ('id','source_text','roman','sourceLanguage','kind')}]
        self.assert_happy_path()
        self.assertEqual(self.http_calls,['वज्र'])

    def test_new_source_gloss_disagreement_routes_actual_bounded_gloss_repair(self):
        self.needs_gloss_change=True
        result=self.case.complete()
        self.assertEqual(self.case.state()['status'],'accepted')
        self.assertEqual(self.case.kinds(),['bhakti_word_glosses','bhakti_literal_translation','bhakti_translation_review',
                                           'bhakti_word_glosses','bhakti_literal_translation','bhakti_translation_review'])
        self.assertEqual(self.http_calls,['बजरंग','वज्र'])
        self.assertEqual(result[0]['packet']['glosses'][0]['word_glosses'][3]['gloss'],'with adamantine limbs')
        self.assertIn('Having a hardy frame',self.case.calls[3]['prompt'])

    def test_fresh_missing_source_decisions_rejected_before_independent_review(self):
        def omit(*args,**kwargs):
            result=self.transport(*args,**kwargs)
            for row in result.get('packet',{}).get('translations',[]):
                row.pop('source_discovery_decisions',None)
            return result
        with patch.object(fixture.pipeline.gemini,'call',side_effect=omit):
            with self.assertRaisesRegex((ValueError,RuntimeError),'discovery|decision|candidate'):
                self.case.complete()
        self.assertEqual(self.case.kinds(),['bhakti_word_glosses','bhakti_literal_translation'])
        self.assertFalse((self.case.packets/'semantic-acceptance.json').exists())

    def test_malformed_source_witness_hash_holds_accepted_resume_without_call(self):
        self.assert_happy_path();count=len(self.case.calls)
        root=Path(os.environ['BHAKTI_LEXICAL_SUPPORT_CACHE'])/'source-discovery'/'platts-hi'
        row=next(record for record in json.loads((root/'acquisition.json').read_text()) if record['query']=='वज्र')
        path=root/row['path'];path.write_bytes(path.read_bytes()+b'changed without updated manifest')
        with self.assertRaisesRegex((ValueError,RuntimeError),'hash|witness'):
            self.case.complete()
        self.assertEqual(len(self.case.calls),count)

    def test_unrelated_dictionary_cache_growth_preserves_accepted_result(self):
        accepted=self.assert_happy_path();count=len(self.case.calls)
        root=Path(os.environ['BHAKTI_LEXICAL_SUPPORT_CACHE'])/'source-discovery'/'platts-hi'
        corpus.acquire_queries(root,['bajra'],opener=self.opener,timeout=1)
        http=len(self.http_calls)
        self.assertEqual(self.case.complete(),accepted)
        self.assertEqual(len(self.case.calls),count);self.assertEqual(len(self.http_calls),http)

    def test_changed_source_witness_renews_translation_and_review_with_unchanged_gloss(self):
        self.assert_happy_path();count=len(self.case.calls)
        root=Path(os.environ['BHAKTI_LEXICAL_SUPPORT_CACHE'])/'source-discovery'/'platts-hi'
        manifest=root/'acquisition.json';records=json.loads(manifest.read_text())
        row=next(record for record in records if record['query']=='वज्र')
        path=root/row['path'];raw=path.read_bytes()
        # Engineering mutation outside the selected compound quote: same entry ID,
        # same earlier relation still structurally valid, different complete evidence.
        self.assertIn(b'thunderbolt',raw)
        changed=raw.replace(b'thunderbolt',b'thunderbolt [changed fixture evidence]',1)
        path.write_bytes(changed);row['sha256']=corpus.sha(changed);manifest.write_text(json.dumps(records))
        renewed=self.case.complete()
        self.assertEqual(self.case.kinds()[count:],['bhakti_literal_translation','bhakti_translation_review'])
        self.assertIn('[changed fixture evidence]',self.case.calls[-1]['prompt'])
        self.assertEqual(self.gloss_count,1)
        calls=len(self.case.calls);self.assertEqual(self.case.complete(),renewed)
        self.assertEqual(len(self.case.calls),calls)

    def test_accepted_resume_cannot_drop_source_relation_decisions(self):
        self.assert_happy_path();count=len(self.case.calls)
        path=self.case.packets/'05-translation.json';value=json.loads(path.read_text())
        value['packet']['translations'][0].pop('source_discovery_decisions');path.write_text(json.dumps(value))
        manifest=self.case.packets/'semantic-acceptance.json';saved=json.loads(manifest.read_text())
        saved['translation_sha256']=fixture.pipeline.bhakti_semantic_repair.digest(value);manifest.write_text(json.dumps(saved))
        with self.assertRaisesRegex((ValueError,RuntimeError),'discovery|decision|candidate|relation'):
            self.case.complete()
        self.assertEqual(len(self.case.calls),count)

class DiscoveryRunOwnerTests(unittest.TestCase):
    def test_actual_library_workers_share_quota_and_resume_deadline(self):
        import test_parallel_library as library_fixture
        import bhakti_model_routes as routes
        case=library_fixture.ParallelLibraryTests();case.setUp();self.addCleanup(case.doCleanups)
        case.inventory['songs']=case.rows[:2]
        budgets=[]
        def worker(root,row,state,options,deadline):
            budget=copy.deepcopy(options.source_discovery_budget)
            self.assertEqual(budget['deadline_at'],deadline)
            self.assertTrue(Path(budget['path']).is_relative_to(case.state))
            budgets.append(budget)
            raise routes.RunFatal('Pause workers after observing shared source quota')
        with patch.object(library,'execute_song',side_effect=worker):
            first=case.run_inventory()
            second=case.run_inventory()
        self.assertGreaterEqual(len(budgets),2)
        self.assertTrue(all(value==budgets[0] for value in budgets))
        self.assertEqual(first['deadline_at'],second['deadline_at'])
        self.assertEqual(set(second['remaining']),{'alpha','beta'})

    def test_removed_intake_source_quota_cannot_reset_on_resume(self):
        import test_intake_run_prerequisites as intake_fixture
        case=intake_fixture.IntakeRunPrerequisites();case.setUp();self.addCleanup(case.tearDown)
        budgets=[]
        def worker(job,options):
            budgets.append(copy.deepcopy(options.source_discovery_budget));return case.worker(job,options)
        self.assertEqual(case.invoke(worker=worker,count=2),0)
        Path(budgets[0]['path']).unlink()
        self.assertEqual(case.invoke(worker=worker,count=2),1)
        self.assertFalse(Path(budgets[0]['path']).exists())
        self.assertEqual(len(budgets),2)

    def test_actual_intake_workers_share_persisted_source_quota_and_deadline(self):
        import test_intake_run_prerequisites as intake_fixture
        case=intake_fixture.IntakeRunPrerequisites();case.setUp();self.addCleanup(case.tearDown)
        budgets=[]
        def worker(job,options):
            budgets.append(copy.deepcopy(options.source_discovery_budget))
            return case.worker(job,options)
        self.assertEqual(case.invoke(worker=worker,count=2),0)
        self.assertEqual(budgets[0],budgets[1])
        self.assertEqual(budgets[0]['deadline_at'],case.calls[0]['deadline'])
        first=copy.deepcopy(budgets[0])
        self.assertEqual(case.invoke(worker=worker,count=2),0)
        self.assertEqual(budgets[-1],first)
        self.assertTrue(Path(first['path']).is_relative_to(case.root/'.transcription'/'intake-runs'))

if __name__=='__main__':unittest.main()

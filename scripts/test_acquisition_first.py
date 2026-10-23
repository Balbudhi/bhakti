"""Review-first controls: actual dictionary/parser/storage/semantic consumers; fake transports."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import bhakti_english_discovery as discovery
import bhakti_lexical_retrieval as lexical
import bhakti_lexical_support as support
import test_english_discovery_design as english_fixture
import test_source_discovery_callers as source_fixture

HERE=Path(__file__).parent/'fixtures'/'acquisition-first'

def actual_query():return json.loads((HERE/'actual-query.json').read_text())

class ProjectionContract(unittest.TestCase):
    def test_actual_eight_windows_and_whole_definition_are_losslessly_covered(self):
        q=actual_query();q['grammatical_role']=['compound epithet describing bodily frame'];before=copy.deepcopy(q)
        self.assertEqual(len(q['source_context']['windows']),8)
        self.assertEqual(len(q['source_hypotheses'][0]['definition']),1519)
        self.assertGreater(len(lexical.canonical(q).encode()),2048)
        r=discovery.query_projection(q)
        self.assertTrue(r['complete']);self.assertLessEqual(len(r['parts']),32)
        self.assertEqual(q,before)
        full=q['source_hypotheses'][0]['definition']
        for wi,window in enumerate(q['source_context']['windows']):
            slices=[]
            for part in r['parts']:
                self.assertLessEqual(len(part['text'].encode()),2048)
                if wi not in part['window_indices']:continue
                encoded=part['text']
                self.assertIn('bajaraṅga',encoded)
                self.assertIn('compound epithet describing bodily frame',encoded)
                self.assertIn(q['source_context']['target'],encoded)
                for side in ('before','after'):
                    for text in window[side]:self.assertIn(text,encoded)
                for item in part['evidence_slices']:
                    if item['role']=='source_hypothesis' and item['index']==0:
                        self.assertEqual(item['sha256'],hashlib.sha256(full.encode()).hexdigest())
                        self.assertIn(full[item['start']:item['end']],encoded)
                        self.assertIn('lookup_hypothesis',encoded)
                        slices.append((item['start'],item['end']))
            self.assertTrue(slices)
            self.assertEqual(sorted(set(slices))[0][0],0)
            cursor=0
            for start,end in sorted(set(slices)):
                self.assertEqual(start,cursor);self.assertGreater(end,start);cursor=end
            self.assertEqual(cursor,len(full))

    def test_short_query_stays_one_unchanged_encoder_input(self):
        q=actual_query();q['source_context']['windows']=[];q.pop('source_hypotheses')
        r=discovery.query_projection(q)
        self.assertTrue(r['complete']);self.assertEqual(len(r['parts']),1)
        self.assertEqual(r['parts'][0]['text'],lexical.canonical(q))

    def test_indivisible_context_and_part_limit_are_explicit_not_truncated(self):
        q=actual_query();q['source_context']['target']='क'*3000
        r=discovery.query_projection(q)
        self.assertFalse(r['complete']);self.assertTrue(r['diagnostics'])
        limited=discovery.query_projection(actual_query(),max_parts=1)
        self.assertFalse(limited['complete']);self.assertTrue(limited['diagnostics'])

    def test_real_dictionary_ranking_has_complete_parts_and_reuses_vectors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);wn=english_fixture.install_wordnet(root/'wn');encoder=english_fixture.FakeEncoder()
            args=dict(edition='3.1',query=actual_query(),cache_dir=root/'cache',encoder=encoder)
            result=discovery.discover_english(wn,['adamantine'],**args)
            self.assertTrue(result['query_coverage']['complete'])
            self.assertLessEqual(sum(map(len,encoder.calls)),64);self.assertLessEqual(len(encoder.calls),4)
            parts=result['query_coverage']['parts']
            ranked=[s for c in result['candidates'] for s in c['scores'] if s['status']=='ranked']
            self.assertTrue(ranked)
            for score in ranked:
                self.assertEqual(len(score['part_scores']),len(parts))
                self.assertEqual(score['score'],max(p['score'] for p in score['group_scores']))
            before=len(encoder.calls);again=discovery.discover_english(wn,['adamantine'],**args)
            self.assertEqual(again,result);self.assertEqual(len(encoder.calls),before)
            self.assertEqual(len(next(c for c in result['candidates'] if c['lemma']=='adamantine')['evidence_ids']),3)

    def test_incomplete_coverage_never_claims_numeric_ranking(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);wn=english_fixture.install_wordnet(root/'wn');encoder=english_fixture.FakeEncoder()
            q=actual_query();q['source_context']['target']='क'*3000
            result=discovery.discover_english(wn,['adamantine'],edition='3.1',query=q,cache_dir=root/'cache',encoder=encoder)
            self.assertFalse(result['query_coverage']['complete'])
            self.assertFalse(encoder.calls)
            self.assertTrue(result['evidence'])
            self.assertTrue(all(s['score'] is None and s['status']!='ranked' for c in result['candidates'] for s in c['scores']))


    def test_source_hypotheses_bind_exact_line_token_and_language(self):
        import bhakti_lexical_producer as producer
        q=actual_query()
        line={'id':'v','source_text':'बजरंग बली','roman':'bajaraṅga balī','sourceLanguage':'hi'}
        proposal={'word_indices':[0],'surfaces':['bajaraṅga']}
        gloss={'sense_decisions':[{'word_index':0,'chosen':[],'grammatical_role':'epithet'}],
               'word_glosses':[{'gloss':'adamantine-limbed'},{'gloss':'strong'}]}
        entry={'entry_id':'source:1','language':'hi','dictionary':{'whole_entry_text':q['source_hypotheses'][0]['definition']}}
        target={'id':'d:v:0','line_id':'v','word_indices':[0],'surfaces':['bajaraṅga'],'source_language':'hi','candidate_entry_ids':['source:1']}
        packet={'entries':[entry],'targets':[target,
            {**target,'id':'d:other:0','line_id':'other'},
            {**target,'id':'d:v:1','word_indices':[1],'surfaces':['balī']}]}
        def run():return producer._english_discovery_query(line,proposal,gloss,{},['Hindi'],[line],[],packet)
        result=run();self.assertEqual(len(result['source_hypotheses']),1)
        self.assertEqual(result['source_hypotheses'][0]['source_target_id'],'d:v:0')
        self.assertEqual(result['source_hypotheses'][0]['word_indices'],[0])
        entry['language']='ta'
        with self.assertRaisesRegex(ValueError,'language'):run()
        entry['language']='hi';target['surfaces']=['different']
        with self.assertRaisesRegex(ValueError,'token'):run()

    def test_existing_version_one_short_query_and_document_vectors_are_reused(self):
        fixture=json.loads((HERE/'legacy-vector-identities.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);wn=english_fixture.install_wordnet(root/'wn');encoder=english_fixture.FakeEncoder()
            cache=root/'cache'/'english-discovery-vectors'/support.digest(lexical.DEFAULT_SPACE);cache.mkdir(parents=True)
            for row in fixture['records']:
                vector=row['vector_prefix']+[0.]*766
                (cache/(row['key']+'.json')).write_text(json.dumps({'identity':row['identity'],'vector':vector,'sha256':support.digest(vector)}))
            result=discovery.discover_english(wn,['adamantine'],edition='3.1',query=fixture['query'],cache_dir=root/'cache',encoder=encoder)
            self.assertFalse(encoder.calls)
            self.assertTrue(any(s['status']=='ranked' for c in result['candidates'] for s in c['scores']))

    def test_fragment_count_does_not_let_one_irrelevant_peak_dominate_context(self):
        class ControlledEncoder(english_fixture.FakeEncoder):
            def embed(self,texts):
                self.calls.append(list(texts));self_test.assertTrue(all(len(t.encode())<=2048 for t in texts))
                result=[]
                for text in texts:
                    if 'source_span' in text:
                        pair=[1.,0.] if 'DENUNCIATION' in text or 'emotional resistance' in text else [.2,.98]
                    else:pair=[1.,0.] if 'impervious to pleas' in text else [0.,1.]
                    result.append(pair+[0.]*766)
                return result
        self_test=self
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);wn=english_fixture.install_wordnet(root/'wn');encoder=ControlledEncoder()
            q=actual_query();q['source_context']['windows']=q['source_context']['windows'][:1]
            q['source_hypotheses'][0]['definition']='STONE '*500+'DENUNCIATION '+'STONE '*500
            q['grammatical_role']=['physical bodily frame']
            args=dict(edition='3.1',query=q,cache_dir=root/'cache',encoder=encoder)
            result=discovery.discover_english(wn,['adamantine'],**args)
            scores={s['evidence_id']:s for c in result['candidates'] if c['lemma']=='adamantine' for s in c['scores']}
            wrong=scores['wordnet:3.1:a:01028427'];physical=scores['wordnet:3.1:a:01154749']
            self.assertEqual(max(p['score'] for p in wrong['part_scores']),1.)
            self.assertLess(wrong['score'],physical['score'],'raw maximum over fragments rewards one irrelevant peak')
            q['grammatical_role']=['metaphorical emotional resistance']
            second=discovery.discover_english(wn,['adamantine'],**args)
            scores2={s['evidence_id']:s for c in second['candidates'] if c['lemma']=='adamantine' for s in c['scores']}
            self.assertGreater(scores2['wordnet:3.1:a:01028427']['score'],scores2['wordnet:3.1:a:01154749']['score'])
            self.assertNotEqual(result['identity'],second['identity'])

    def test_input_budget_retains_all_definitions_and_declares_unranked_omissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);wn=english_fixture.install_wordnet(root/'wn');encoder=english_fixture.FakeEncoder()
            q=json.loads((HERE/'legacy-vector-identities.json').read_text())['query']
            result=discovery.discover_english(wn,['adamantine'],edition='3.1',query=q,cache_dir=root/'cache',encoder=encoder,max_embedding_inputs=2)
            self.assertLessEqual(sum(map(len,encoder.calls)),2)
            a=next(c for c in result['candidates'] if c['lemma']=='adamantine')
            self.assertEqual(len(a['evidence_ids']),3)
            self.assertTrue(any(s['status']=='embedding_budget_exhausted' and s['score'] is None for s in a['scores']))
            self.assertEqual({e['id'] for e in support.lookup_wordnet(wn,['adamantine'],edition='3.1')},set(a['evidence_ids']))

class ActualConsumers(unittest.TestCase):
    def setUp(self):
        self.case=source_fixture.SourceDiscoveryCallerTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.encoder=english_fixture.FakeEncoder()
        self.wn=english_fixture.install_wordnet(self.case.case.root/'discovery-wordnet')
        for manager in (patch.dict(os.environ,{'BHAKTI_ENGLISH_DISCOVERY':'1','BHAKTI_WORDNET_DIR':str(self.wn)}),
            patch.object(lexical,'configured_encoder',return_value=self.encoder)):
            manager.start();self.addCleanup(manager.stop)
        self.results=[];self.queries=[];self.original=discovery.discover_english

    def capture(self,*args,**kwargs):
        self.assertIn('वज्र',self.case.http_calls,'Actual source acquisition must precede initial English discovery')
        q=kwargs['query'];self.queries.append(copy.deepcopy(q))
        self.assertEqual(q['source_hypotheses'][0]['definition'].replace(' [changed fixture evidence]',''),actual_query()['source_hypotheses'][0]['definition'])
        self.assertEqual(q['source_hypotheses'][0]['status'],'lookup_hypothesis')
        r=self.original(*args,**kwargs);self.results.append(r);return r

    def test_first_completion_acquires_before_embeddings_and_keeps_full_writer_reviewer_evidence(self):
        with patch.object(discovery,'discover_english',side_effect=self.capture):
            self.case.assert_happy_path()
        self.assertTrue(self.results)
        full=actual_query()['source_hypotheses'][0]['definition']
        for call in self.case.case.calls[1:]:
            packet=json.JSONDecoder().raw_decode(call['prompt'].split('SOURCE DISCOVERY EVIDENCE:\n',1)[1])[0]
            self.assertEqual(packet['entries'][0]['dictionary']['whole_entry_text'],full)
            targeted=json.JSONDecoder().raw_decode(call['prompt'].split('TARGETED LEXICAL SUPPORT:\n',1)[1])[0]
            ranked=targeted['targets'][0]['english_discovery']
            self.assertNotIn('parts',ranked['query_coverage'])
            self.assertGreater(ranked['query_coverage']['part_count'],0)
            self.assertTrue(all('part_scores' not in score for candidate in ranked['candidates'] for score in candidate['scores']))
        self.assertTrue(any('Having a hardy frame' in text for batch in self.encoder.calls for text in batch))

    def test_changed_source_reaches_new_embeddings_then_English_review_and_free_resume(self):
        with patch.object(discovery,'discover_english',side_effect=self.capture):
            self.case.test_changed_source_witness_renews_translation_and_review_with_unchanged_gloss()
        self.assertTrue(any('[changed fixture evidence]' in q['source_hypotheses'][0]['definition'] for q in self.queries))
        self.assertTrue(any('[changed fixture evidence]' in text for batch in self.encoder.calls for text in batch))

    def test_actual_eight_performed_windows_reach_ranked_embedding_consumer(self):
        q=actual_query()
        # Reader line is authentic; add the exact performed context already extracted
        # by the real library reader. Each occurrence retains its own adjacent source.
        self.case.case.lines[0]['performed_context']=[{
            side:[{'source_text':text} for text in window[side]] for side in ('before','after')
        } for window in q['source_context']['windows']]
        with patch.object(discovery,'discover_english',side_effect=self.capture):
            self.case.assert_happy_path()
        r=self.results[0]
        self.assertEqual(len(self.queries[0]['source_context']['windows']),8)
        self.assertTrue(r['query_coverage']['complete'])
        self.assertTrue(any(s['status']=='ranked' for c in r['candidates'] for s in c['scores']))
        self.assertLessEqual(sum(map(len,self.encoder.calls)),64)

if __name__=='__main__':unittest.main()

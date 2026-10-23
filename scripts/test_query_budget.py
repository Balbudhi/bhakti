"""Real failed proposal + authentic all-POS WordNet subset; no external calls."""
import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import bhakti_lexical_producer as producer
import bhakti_lexical_support as support
import bhakti_english_discovery as discovery
import bhakti_lexical_retrieval as lexical
import test_automatic_semantic_lexical as semantic_fixture
import test_english_discovery_design as english_fixture

FIX=Path(__file__).parent/'fixtures'/'query_budget'
GLOSS=json.loads((FIX/'real-gloss.json').read_text())
AUDIT=json.loads((FIX/'source-input.json').read_text())
CANDIDATES=GLOSS['glosses'][1]['lexical_queries'][0]['english_candidates']
SEEDS=['resting','place','abode','true','dwelling','refuge']
ALL_SEEDS=json.loads((FIX/'wordnet-query-budget.json').read_text())['complete_for_lemmas']

class QueryBudgetRequirements(unittest.TestCase):
    def setUp(self):
        self.case=semantic_fixture.AutomaticSemanticLexicalTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.root=self.case.root
        with patch.object(english_fixture,'FIXTURE',FIX/'wordnet-query-budget.json'):
            self.wn=english_fixture.install_wordnet(self.root/'real-wordnet')
        self.lines=AUDIT['packet']['verified_lines']
        self.query={'source_language':'hi','source_span':{'roman':['ṭhikānā'],'word_indices':[2]},
            'source_context':{'target':self.lines[1]['source_text'],'windows':[]},
            'sense_evidence':['resting place; refuge / abode'],'grammatical_role':['predicate noun']}
        self.encoder=english_fixture.FakeEncoder()

    def test_actual_four_phrases_six_distinct_terms_are_valid_without_dropping_alternatives(self):
        self.assertEqual(len(CANDIDATES),4)
        self.assertEqual(set(SEEDS),{w for c in CANDIDATES for w in c['english_lemmas']})
        self.assertEqual(producer.proposal_errors(self.lines,GLOSS['glosses'],['Hindi']),[])

    def test_candidate_count_and_per_candidate_terms_have_distinct_limits(self):
        rows=copy.deepcopy(GLOSS['glosses']);proposal=rows[1]['lexical_queries'][0]
        proposal['english_candidates']=[{'expression':'phrase '+str(i),'kind':'compositional_phrase',
            'english_lemmas':ALL_SEEDS[i*4:i*4+4]} for i in range(4)]
        self.assertEqual(producer.proposal_errors(self.lines,rows,['Hindi']),[])
        proposal['english_candidates'][0]['english_lemmas'].append('fifth')
        self.assertTrue(producer.proposal_errors(self.lines,rows,['Hindi']))
        proposal['english_candidates']=copy.deepcopy(CANDIDATES)+[copy.deepcopy(CANDIDATES[0])]
        self.assertTrue(producer.proposal_errors(self.lines,rows,['Hindi']))

    def test_raw_array_bound_and_normalized_exact_multiword_query_agree(self):
        rows=copy.deepcopy(GLOSS['glosses']);proposal=rows[1]['lexical_queries'][0]
        proposal['english_candidates']=[{'expression':'dwelling place','kind':'compositional_phrase',
            'english_lemmas':['Dwelling_place',' dwelling place ','ABODE','abode']}]
        self.assertEqual(producer.proposal_errors(self.lines,rows,['Hindi']),[])
        self.assertEqual(support.english_queries(proposal['english_candidates'][0]['english_lemmas']),['dwelling place','abode'])
        proposal['english_candidates'][0]['english_lemmas'].append('ABODE')
        self.assertTrue(producer.proposal_errors(self.lines,rows,['Hindi']),'five raw strings must fail the same schema bound even when duplicated')

    def test_sixteen_term_preparation_keeps_all_original_phrases_with_partial_ranks(self):
        rows=copy.deepcopy(GLOSS['glosses'])
        for i,candidate in enumerate(rows[1]['lexical_queries'][0]['english_candidates']):
            candidate['english_lemmas']=ALL_SEEDS[i*4:i*4+4]
            candidate['kind']='compositional_phrase'
        with patch.dict(os.environ,{'BHAKTI_WORDNET_DIR':str(self.wn),'BHAKTI_ENGLISH_DISCOVERY':'1'}),\
             patch.object(lexical,'configured_encoder',return_value=self.encoder):
            local,derived=producer.prepare_translation(self.case.song,AUDIT,{'packet':{'glosses':rows}},self.case.options)
        packet=local.semantic_lexical_support;target=packet['targets'][0]
        self.assertTrue({c['expression'] for c in CANDIDATES}<={c['expression'] for c in target['english_candidates']})
        expected=support.lookup_wordnet(self.wn,ALL_SEEDS,edition='3.1')
        self.assertEqual({e['id'] for e in expected},{e['id'] for e in packet['evidence'] if e['kind']=='english_definition'})
        self.assertTrue(any(s['status']=='embedding_budget_exhausted' for c in target['english_discovery']['candidates'] for s in c['scores']))
        for stage in ('translation','review'):
            projected=json.JSONDecoder().raw_decode(support.prompt(packet,[target['line_id']],stage).split('TARGETED LEXICAL SUPPORT:\n',1)[1])[0]
            self.assertEqual({e['id'] for e in expected},{e['id'] for e in projected['evidence'] if e['kind']=='english_definition'})
        self.assertLessEqual(sum(map(len,self.encoder.calls)),64)

    def test_schema_expresses_four_terms_per_candidate_not_four_across_phrases(self):
        schema={'properties':{'glosses':{'items':{'properties':{},'required':[]}}}}
        out=producer.gloss_schema(schema,self.case.options)
        candidates=out['properties']['glosses']['items']['properties']['lexical_queries']['items']['properties']['english_candidates']
        self.assertEqual(candidates['maxItems'],4)
        self.assertEqual(candidates['items']['properties']['english_lemmas']['maxItems'],4)
        prompt=producer.gloss_prompt(self.case.options,self.lines)
        self.assertNotIn('at most four distinct lookup words per source span',prompt)

    def test_six_and_sixteen_seed_terms_keep_every_sense_under_fixed_embedding_cap(self):
        for seeds in [SEEDS,ALL_SEEDS]:
            with self.subTest(seeds=len(seeds)):
                encoder=english_fixture.FakeEncoder()
                result=discovery.discover_english(self.wn,seeds,edition='3.1',query=self.query,
                    cache_dir=self.root/('cache-'+str(len(seeds))),encoder=encoder)
                self.assertEqual(result['seed_lemmas'],seeds)
                self.assertLessEqual(sum(map(len,encoder.calls)),64);self.assertLessEqual(len(encoder.calls),4)
                expected=support.lookup_wordnet(self.wn,seeds,edition='3.1')
                for lemma in seeds:
                    candidate=next(c for c in result['candidates'] if c['lemma']==lemma)
                    self.assertEqual(set(candidate['evidence_ids']),{e['id'] for e in expected if lemma in e['requested_lemmas']})
                self.assertLessEqual(len(result['candidates'])-len(seeds),4)
                self.assertLessEqual(result['pool']['neighbor_synsets_visited'],8)
                if len(seeds)==16:
                    self.assertTrue(any(s['status']=='embedding_budget_exhausted' for c in result['candidates'] for s in c['scores']))
                count=len(encoder.calls)
                self.assertEqual(discovery.discover_english(self.wn,seeds,edition='3.1',query=self.query,
                    cache_dir=self.root/('cache-'+str(len(seeds))),encoder=encoder),result)
                self.assertEqual(len(encoder.calls),count)
        with self.assertRaises(ValueError):
            discovery.discover_english(self.wn,ALL_SEEDS+['seventeenth'],edition='3.1',query=self.query,
                cache_dir=self.root/'too-many',encoder=self.encoder)
        self.assertFalse(self.encoder.calls)

    def test_actual_gloss_and_producer_deliver_all_phrases_and_definitions_to_both_consumers(self):
        case=self.case;case.lines=copy.deepcopy(self.lines);case.audit=copy.deepcopy(AUDIT)
        case.options.semantic_full_source=case.lines
        case.options.lexical_requested_spans=[{'line_id':case.lines[1]['id'],'word_indices':[2],
            'surfaces':['ṭhikānā'],'reason':'Check contextual source meaning and English wording.'}]
        original=copy.deepcopy(GLOSS)
        def transport(*args,**kwargs):
            case.calls.append(kwargs['schema_name'])
            self.assertIn('word_gloss',kwargs['schema_name'])
            return {'packet':copy.deepcopy(GLOSS)}
        with patch.dict(os.environ,{'BHAKTI_WORDNET_DIR':str(self.wn),'BHAKTI_ENGLISH_DISCOVERY':'1'}),\
             patch.object(lexical,'configured_encoder',return_value=self.encoder),\
             patch.object(semantic_fixture.pipeline.gemini,'call',side_effect=transport):
            gloss=semantic_fixture.pipeline.gloss(case.song,case.audit,case.options)
            local,derived=producer.prepare_translation(case.song,case.audit,gloss,case.options)
            packet=local.semantic_lexical_support
            target=packet['targets'][0]
            expressions={c['expression'] for c in target['english_candidates']}
            self.assertTrue({c['expression'] for c in CANDIDATES}<=expressions)
            self.assertEqual(target['english_discovery']['seed_lemmas'],SEEDS)
            for stage in ('translation','review'):
                prompt=support.prompt(packet,[target['line_id']],stage)
                public=json.JSONDecoder().raw_decode(prompt.split('TARGETED LEXICAL SUPPORT:\n',1)[1])[0]
                self.assertTrue({c['expression'] for c in CANDIDATES}<={c['expression'] for c in public['targets'][0]['english_candidates']})
                self.assertEqual({e['id'] for e in public['evidence'] if e['kind']=='english_definition'},
                    {e['id'] for e in packet['evidence'] if e['kind']=='english_definition'})
            self.assertTrue(any(d['kind']=='english_word_unattested' and d['lemma']=='resting' for d in local.automatic_lexical_diagnostics))
            self.assertEqual(GLOSS,original)
            self.assertEqual(case.calls,['bhakti_word_glosses'])
            before=len(self.encoder.calls)
            producer.prepare_translation(case.song,case.audit,gloss,case.options)
            self.assertEqual(len(self.encoder.calls),before)

if __name__=='__main__':unittest.main()

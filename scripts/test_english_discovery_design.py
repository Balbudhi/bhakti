"""New-feature contract tests. Real dictionary/parser/cache; fake vectors are not quality proof."""
import copy
import importlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import bhakti_lexical_retrieval as lexical
import bhakti_lexical_support as support

FIXTURE=Path(__file__).parent/'fixtures/wordnet-english-discovery.json'


def install_wordnet(path):
    x=json.loads(FIXTURE.read_text());path.mkdir(parents=True)
    manifest={'edition':x['edition'],'source':x['source'],'available_pos':list(support.POS),
        'complete_for_lemmas':x['complete_for_lemmas'],'data_sha256':{},'index_sha256':{}}
    for name,pos in support.POS.items():
        data=path/('data.'+name)
        with data.open('wb') as f:
            f.write(x['license_header'].encode())
            for row in sorted((r for r in x['data_rows'] if r['pos']==pos),key=lambda r:r['synset_offset']):
                f.seek(row['synset_offset']);f.write(row['raw'].encode())
        index=path/('index.'+name);index.write_text(x['license_header']+''.join(x['index_rows'][name]))
        manifest['data_sha256'][name]=support.file_hash(data);manifest['index_sha256'][name]=support.file_hash(index)
    (path/'manifest.json').write_text(json.dumps(manifest))
    return path


class FakeEncoder:
    def __init__(self):self.calls=[]
    def embed(self,texts):
        self.calls.append(list(texts))
        assert 1<=len(texts)<=16
        assert all(len(t.encode())<=2048 for t in texts)
        vectors=[]
        for t in texts:
            # Deliberately rank an inappropriate obstinacy sense above diamond.
            # A translator can choose the lower-ranked physical sense.
            pair=[1.,0.] if ('impervious to pleas' in t or 'source_span' in t) else [0.,1.]
            vectors.append(pair+[0.]*766)
        return vectors


class EnglishDiscoveryRequirements(unittest.TestCase):
    def setUp(self):
        self.mod=importlib.import_module('bhakti_english_discovery')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.wn=install_wordnet(self.root/'wordnet')
        self.encoder=FakeEncoder()
        self.query={'source_language':'hi','source_span':'वज्र','source_context':'वज्र अङ्ग',
            'sense_evidence':[{'definition':'having a hardy frame; strong-built','witness':'real-source-evidence-id'}],
            'grammatical_role':'adjective describing bodily hardness'}
    def discover(self,**kw):
        args=dict(edition='3.1',query=self.query,cache_dir=self.root/'cache',encoder=self.encoder,
            space=lexical.DEFAULT_SPACE,max_neighbor_synsets=8,max_discovered_lemmas=4);args.update(kw)
        return self.mod.discover_english(self.wn,['adamantine'],**args)
    def candidate(self,result,lemma):return next(c for c in result['candidates'] if c['lemma']==lemma)

    def test_real_neighbor_discovers_nonseed_and_keeps_all_POS_senses(self):
        r=self.discover();c=self.candidate(r,'hard')
        self.assertNotIn('hard',r['seed_lemmas']);self.assertEqual(r['seed_lemmas'],['adamantine'])
        expected=support.lookup_wordnet(self.wn,['hard'],edition='3.1')
        self.assertEqual(len(expected),22) # Independently counted official index: 12 adjective + 10 adverb.
        self.assertEqual(set(c['evidence_ids']),{e['id'] for e in expected})
        self.assertEqual({x['evidence_id'] for x in c['scores']},set(c['evidence_ids']))
        self.assertTrue(any(route.get('pointer')=='&' and route.get('from_evidence_id')=='wordnet:3.1:a:01154749'
                            for route in c['discovered_by']))
        self.assertIn('bounded_pool_not_exhaustive',r['pool']['limitations'])
        a=self.candidate(r,'adamantine');self.assertEqual(len(a['evidence_ids']),3)
        scores={x['evidence_id']:x['score'] for x in a['scores']}
        self.assertGreater(scores['wordnet:3.1:a:01028427'],scores['wordnet:3.1:a:01154749'])
        self.assertEqual(len({e['id'] for e in r['evidence']}),len(r['evidence']))
        self.assertTrue(all('selected' not in c and 'chosen' not in c for c in r['candidates']))
        before=copy.deepcopy(r)
        r['evidence'][0]['gloss']='tampered return object'
        self.assertEqual(self.discover(),before)

    def test_shortlist_limits_new_lemmas_not_original_senses_or_private_pool(self):
        r=self.discover(max_discovered_lemmas=2)
        self.assertLessEqual(len(set(c['lemma'] for c in r['candidates'])-{'adamantine'}),2)
        self.assertEqual(len(self.candidate(r,'adamantine')['evidence_ids']),3)
        self.assertGreater(r['pool']['discovered_lemmas_omitted'],0)
        self.assertIn('wordnet:3.1:a:01154418',json.dumps(r['pool']['records']))
        seed_only=self.discover(max_discovered_lemmas=0)
        self.assertEqual([c['lemma'] for c in seed_only['candidates']],['adamantine'])
        self.assertEqual(len(seed_only['evidence']),3)
        self.assertIn('wordnet:3.1:a:01154418',json.dumps(seed_only['pool']['records']))

    def test_only_explored_definitions_are_embedded_not_all_expanded_senses(self):
        r=self.discover()
        hard=self.candidate(r,'hard')
        self.assertEqual(len(hard['evidence_ids']),22)
        self.assertTrue(any(x['status']=='outside_ranked_pool' and x['score'] is None for x in hard['scores']))
        self.assertTrue(any(x['status']=='ranked' for x in hard['scores']))
        # Exact fixture pool: three original seed senses, two distinct semantic neighbors, one query.
        self.assertLessEqual(sum(len(batch) for batch in self.encoder.calls),6)
        self.assertEqual(r['pool']['neighbor_synsets_visited'],2)

    def test_bound_pool_not_seed_alternatives_and_cold_cache_explicit(self):
        r=self.discover(max_neighbor_synsets=0,encoder=None)
        self.assertEqual(len(self.candidate(r,'adamantine')['evidence_ids']),3)
        self.assertFalse(any(c['lemma']=='hard' for c in r['candidates']))
        self.assertEqual(r['pool']['neighbor_synsets_visited'],0)
        self.assertGreater(r['pool']['neighbor_synsets_omitted'],0)
        self.assertTrue(all(x['score'] is None for c in r['candidates'] for x in c['scores']))
        self.assertTrue(all(x['status']!='ranked' for c in r['candidates'] for x in c['scores']))
        self.assertEqual(self.encoder.calls,[])

    def test_context_language_space_and_evidence_identity_but_not_cache_growth(self):
        first=self.discover();n=len(self.encoder.calls)
        self.assertEqual(self.discover(encoder=None),first)
        self.assertEqual(self.discover(),first);self.assertEqual(len(self.encoder.calls),n)
        changed=copy.deepcopy(self.query);changed['source_language']='pa'
        second=self.discover(query=changed)
        self.assertNotEqual(first['identity'],second['identity'])
        self.assertEqual(self.discover(),first) # Unrelated query cache growth does not invalidate this target.
        changed=copy.deepcopy(self.query);changed['source_context']='वज्र मन'
        self.assertNotEqual(first['identity'],self.discover(query=changed)['identity'])
        newspace={**lexical.DEFAULT_SPACE,'format_version':2}
        self.assertNotEqual(first['identity'],self.discover(space=newspace)['identity'])
        relocated=self.root/'elsewhere';shutil.copytree(self.wn,relocated);self.wn=relocated
        moved=self.discover()
        self.assertEqual(moved['identity'],first['identity'])
        self.assertEqual(support.content_digest({'evidence':moved['evidence']}),
                         support.content_digest({'evidence':first['evidence']}))
        data=self.wn/'data.adj';data.write_bytes(data.read_bytes().replace(b'hardness of a diamond',b'hardness of a crystal'))
        manifest=json.loads((self.wn/'manifest.json').read_text());manifest['data_sha256']['adj']=support.file_hash(data)
        (self.wn/'manifest.json').write_text(json.dumps(manifest))
        self.assertNotEqual(first['identity'],self.discover()['identity'])

    def test_oversize_query_preserves_evidence_without_truncated_rank_claim(self):
        query={**self.query,'source_context':'मन '*1500}
        r=self.discover(query=query)
        self.assertEqual(len(self.candidate(r,'hard')['evidence_ids']),22)
        self.assertTrue(all(x['score'] is None and x['status']=='query_input_too_long'
                            for c in r['candidates'] for x in c['scores']))
        self.assertFalse(any('मन '*100 in t for batch in self.encoder.calls for t in batch))

    def test_missing_subset_complete_coverage_is_not_silent_single_sense_lookup(self):
        manifest=json.loads((self.wn/'manifest.json').read_text())
        manifest['complete_for_lemmas'].remove('hard');(self.wn/'manifest.json').write_text(json.dumps(manifest))
        r=self.discover()
        self.assertEqual(len(self.candidate(r,'adamantine')['evidence_ids']),3)
        self.assertTrue(any(d.get('lemma')=='hard' and d.get('kind')=='english_coverage_unavailable' for d in r['diagnostics']))
        self.assertFalse(any(c['lemma']=='hard' for c in r['candidates']))
        self.assertIn('wordnet:3.1:a:01154418',json.dumps(r['pool']))

    def test_dictionary_witness_tamper_is_rejected_before_cached_rank_reuse(self):
        self.discover();n=len(self.encoder.calls)
        p=self.wn/'data.adj';p.write_bytes(p.read_bytes().replace(b'hardness of a diamond',b'hardness of a crystal'))
        with self.assertRaises(ValueError):self.discover()
        self.assertEqual(len(self.encoder.calls),n)

    def test_invalid_vectors_cannot_become_valid_cache(self):
        with patch.object(self.encoder,'embed',side_effect=lambda texts:[[float('nan')]*768 for _ in texts]):
            with self.assertRaises(ValueError):self.discover()
        # A predispatch/validation failure does not certify or poison future cached success.
        self.assertEqual(len(self.candidate(self.discover(),'adamantine')['evidence_ids']),3)



class EnglishDiscoveryCallerRequirements(unittest.TestCase):
    def test_real_gloss_translate_review_get_discovered_candidate_and_lower_rank_choice(self):
        import argparse,os
        import bhakti_pipeline as pipeline
        from test_lexical_producer import AutomaticProducerRequirements,PILOT
        from test_sense_decisions import decisions_for
        fixture=AutomaticProducerRequirements();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.lines[0]['english']='OWNER_ENGLISH_MUST_NOT_ENTER_EMBEDDING_QUERY'
        wn=install_wordnet(fixture.root/'discovery-wordnet')
        lexicon=fixture.root/'lexicon.json';lexicon.write_text(json.dumps({'entries':[fixture.entry]}))
        env={'BHAKTI_AUTO_LEXICAL':'1','BHAKTI_ENGLISH_DISCOVERY':'1','BHAKTI_WORDNET_DIR':str(wn),
            'BHAKTI_SOURCE_WITNESS_ROOTS':json.dumps([str(PILOT)]),
            'BHAKTI_LEXICAL_SUPPORT_CACHE':str(fixture.root/'cache'),'BHAKTI_LEXICON_PATH':str(lexicon)}
        encoder=FakeEncoder();calls=[];captured=[]
        def provider(model,key,prompt,**kw):
            kind=kw['schema_name'];calls.append(kind)
            if kind=='bhakti_word_glosses':
                row=copy.deepcopy(fixture.gloss[0]);row['sense_decisions']=decisions_for(fixture.lines,['Hindi'])['v']
                row.update(semantic_frame={field:'' for field in pipeline.SEMANTIC_FRAME_FIELDS},grammar_note='',uncertainty='')
                return {'packet':{'glosses':[row]}}
            packet=json.JSONDecoder().raw_decode(prompt.split('TARGETED LEXICAL SUPPORT:\n',1)[1])[0]
            target=packet['targets'][0];captured.append(copy.deepcopy(target))
            self.assertIn('Having a hardy frame',prompt)
            self.assertIn('hard',[c['expression'] for c in target['english_candidates']])
            self.assertIn('hard as diamond',[c['expression'] for c in target['english_candidates']])
            hard=next(c for c in target['english_candidates'] if c['expression']=='hard')
            self.assertEqual(len(hard['english_evidence_ids']),22)
            self.assertIn('english_discovery',target)
            for evidence in packet['evidence']:
                self.assertNotIn('raw',evidence)
                self.assertNotIn('witness_sha256',evidence)
                self.assertNotIn('witness_path',evidence)
            self.assertNotIn('records',target['english_discovery']['pool'])
            self.assertIn('bounded_pool_not_exhaustive',target['english_discovery']['pool']['limitations'])
            a=next(c for c in target['english_candidates'] if c['expression']=='adamantine')
            eid='wordnet:3.1:a:01154749' # Physical diamond, deliberately lower-ranked than obstinacy.
            if kind=='bhakti_translation_review':
                self.assertIn('Physical bodily hardness, not obstinacy.',prompt)
                return {'packet':{'reviews':[{'id':'v','passes':True,'human_review_recommended':False,
                    'agency_preserved':True,'imagery_preserved':True,'all_meaning_accounted_for':True,
                    'unsupported_additions':[],'material_choice':'','reason':'Transport fixture only.','issues':[]}]}}
            return {'packet':{'translations':[{'id':'v','literal_english':'Adamantine',
                'segments':[{'text':'Adamantine','word_indices':[0]}],
                'wording_decisions':[{'target_id':target['id'],'chosen_candidate_id':a['id'],'expression':'adamantine',
                    'kind':'word','english_evidence_ids':[eid],'word_indices':[0],'ordinary_paraphrase':'hard as diamond',
                    'component_word_indices':[[0]],'reason':'Physical bodily hardness, not obstinacy.'}],
                'human_review_recommended':False,'material_alternatives':[],'choice_note':'','uncertainty':'',
                'fidelity':{'agency_and_image_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[],'notes':''}}]}}
        options=argparse.Namespace(model='fixture',force=False,timeout=1,gloss_batch_size=40,gloss_workers=1,max_attempts=1)
        audited={'packet':{'verified_lines':fixture.lines,'metadata':{'languages':['Hindi']},
            'performance_order':[{'line_id':'v','occurrence':1}]}}
        song=fixture.root/'song';song.mkdir()
        with patch.dict(os.environ,env),patch.object(lexical,'configured_encoder',return_value=encoder),\
             patch.object(pipeline.gemini,'key',return_value='fixture'),patch.object(pipeline.gemini,'call',side_effect=provider):
            original=copy.deepcopy(audited)
            gloss=pipeline.gloss(song,audited,options);saved=copy.deepcopy(gloss)
            result=pipeline.translate(song,audited,gloss,{'languages':['Hindi']},options,candidate_only=True)
            n=len(encoder.calls)
            self.assertGreater(n,0)
            pipeline.translate(song,audited,gloss,{'languages':['Hindi']},options,candidate_only=True)
            self.assertEqual(len(encoder.calls),n)
            self.assertEqual(calls,['bhakti_word_glosses','bhakti_literal_translation','bhakti_translation_review'])
            self.assertEqual(audited,original);self.assertEqual(gloss,saved)
            self.assertEqual(result['packet']['translations'][0]['literal_english'],'Adamantine')
            self.assertEqual(captured[0],captured[1])
            materialized=json.loads((song/'.transcription/pipeline/automatic-lexical-support.json').read_text())
            self.assertIn('english_discovery',materialized['packet']['targets'][0])
            query=materialized['discovery_queries']['lexical:v:0']
            self.assertEqual(query['source_language'],'hi')
            self.assertEqual(query['source_span'],{'roman':['vajra'],'word_indices':[0]})
            self.assertEqual(query['source_context']['target'],'वज्र')
            self.assertEqual(query['grammatical_role'],[d['grammatical_role'] for d in gloss['packet']['glosses'][0]['sense_decisions']])
            self.assertEqual(query['sense_evidence'],[fixture.entry['senses'][0]['short_english']])
            self.assertNotIn('OWNER_ENGLISH_MUST_NOT_ENTER_EMBEDDING_QUERY',json.dumps(query))
            self.assertTrue(any(json.loads(t).get('source_span')==query['source_span']
                                for batch in encoder.calls for t in batch))

    def test_shared_synset_alias_cache_preserves_complete_lookup_equality(self):
        import bhakti_lexical_producer as producer
        with tempfile.TemporaryDirectory() as tmp:
            wn = install_wordnet(Path(tmp)/'wordnet')
            queries = ['adamantine', 'adamant']
            actual = producer.lookup_english_cached(wn, queries, edition='3.1', cache_dir=Path(tmp)/'cache')
            self.assertEqual(actual['evidence'], support.lookup_wordnet(wn, queries, edition='3.1'))

    def test_discovery_configuration_changes_translation_identity_not_gloss_contract(self):
        import argparse,os
        import bhakti_pipeline as pipeline
        from test_lexical_producer import AutomaticProducerRequirements,PILOT
        fixture=AutomaticProducerRequirements();fixture.setUp();self.addCleanup(fixture.doCleanups)
        env={'BHAKTI_AUTO_LEXICAL':'1','BHAKTI_WORDNET_DIR':str(fixture.wn),
            'BHAKTI_SOURCE_WITNESS_ROOTS':json.dumps([str(PILOT)]),'BHAKTI_ENGLISH_DISCOVERY':'0'}
        with patch.dict(os.environ,env):
            before_gloss=pipeline.semantic_stage_policy(argparse.Namespace(),stage='gloss')
            before_text=pipeline.semantic_stage_policy(argparse.Namespace(),stage='translation')
            os.environ['BHAKTI_ENGLISH_DISCOVERY']='1'
            self.assertEqual(before_gloss,pipeline.semantic_stage_policy(argparse.Namespace(),stage='gloss'))
            self.assertNotEqual(support.digest(before_text),support.digest(pipeline.semantic_stage_policy(argparse.Namespace(),stage='translation')))



class CompactEnglishEvidenceRequirements(unittest.TestCase):
    def test_actual_translation_and_review_prompts_keep_each_definition_once_with_private_proof_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            wn=install_wordnet(Path(tmp)/'wordnet')
            evidence=support.lookup_wordnet(wn,['adamantine','hard'],edition='3.1')
            candidates=[{'id':lemma,'expression':lemma,'kind':'word','english_lemmas':[lemma],
                'english_evidence_ids':[e['id'] for e in evidence if lemma in e['requested_lemmas']]}
                for lemma in ('adamantine','hard')]
            packet={'version':1,'targets':[{'id':'t','line_id':'v','word_indices':[0],'surfaces':['vajra'],
                'source_language':'hi','source_evidence_ids':[],'background_evidence_ids':[],
                'language_link_evidence_ids':[],'english_candidates':candidates}],
                'evidence':evidence,'english_lookup':support.wordnet_receipt(wn,'3.1',['adamantine','hard'])}
            original=copy.deepcopy(packet)
            lines=[{'id':'v','source_text':'वज्र','roman':'vajra','sourceLanguage':'hi'}]
            support.validate_support(packet,lines,['Hindi'])
            semantic_keys=('id','kind','language','edition','pos','lemmas','gloss','work','locus','source_url','limitations')
            expected={e['id']:{key:e[key] for key in semantic_keys} for e in evidence}
            for stage in ('translation','review'):
                prompt=support.prompt(packet,['v'],stage)
                actual=json.JSONDecoder().raw_decode(prompt.split('TARGETED LEXICAL SUPPORT:\n',1)[1])[0]
                self.assertEqual(len(actual['evidence']),25)
                self.assertEqual({e['id']:{key:e[key] for key in semantic_keys} for e in actual['evidence']},expected)
                self.assertEqual(actual['targets'][0]['english_candidates'],candidates)
                self.assertNotIn('english_lookup',actual)
                for e in actual['evidence']:
                    for private in ('raw','witness_path','witness_sha256','witness_span','quotation_sha256'):
                        self.assertNotIn(private,e)
            self.assertEqual(packet,original)
            support.validate_support(packet,lines,['Hindi'])

class WordNetGrammarProjectionRequirements(unittest.TestCase):
    def test_legacy_english_cache_derives_grammar_and_rejects_invented_grammar(self):
        import bhakti_lexical_producer as producer
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);wn=install_wordnet(root/'wordnet')
            producer.lookup_english_cached(wn,['adamantine'],edition='3.1',cache_dir=root/'cache')
            path=next((root/'cache'/'english').glob('*/*.json'))
            saved=json.loads(path.read_text())
            for row in saved['evidence']:row.pop('grammar',None)
            saved['sha256']=support.digest(saved['evidence']);path.write_text(json.dumps(saved))
            result=producer.lookup_english_cached(wn,['adamantine'],edition='3.1',cache_dir=root/'cache')
            self.assertTrue(all(row.get('grammar')=={'adjective_positions':[],'verb_frames':[]}
                                for row in result['evidence']))
            saved['evidence'][0]['grammar']={'adjective_positions':[
                {'word_index':0,'lemma':'adamant','position':'predicative'}],'verb_frames':[]}
            saved['sha256']=support.digest(saved['evidence']);path.write_text(json.dumps(saved))
            with self.assertRaisesRegex(ValueError,'grammar'):
                producer.lookup_english_cached(wn,['adamantine'],edition='3.1',cache_dir=root/'cache')

    def test_grammar_binds_english_identity_without_changing_original_glossary_policy(self):
        import argparse,os
        import bhakti_pipeline as pipeline
        with tempfile.TemporaryDirectory() as tmp:
            wn=install_wordnet(Path(tmp)/'wordnet')
            rows=support.lookup_wordnet(wn,['adamantine'],edition='3.1')
            for row in rows:row.pop('grammar',None)
            packet={'evidence':rows}
            old=copy.deepcopy(packet)
            for row in old['evidence']:row.pop('witness_path',None)
            original_digest=support.digest(old)
            self.assertNotEqual(support.content_digest(packet),original_digest)
            options=argparse.Namespace(semantic_lexical_support=packet)
            with patch.dict(os.environ,{'BHAKTI_AUTO_LEXICAL':'0'}):
                self.assertEqual(pipeline.semantic_stage_policy(options,stage='gloss')['lexical_support'],original_digest)
                self.assertNotEqual(pipeline.semantic_stage_policy(options,stage='translation')['lexical_support'],original_digest)

    def test_compact_prompts_preserve_lemma_positions_and_lemma_specific_frames(self):
        fixture=json.loads(FIXTURE.read_text())
        evidence=[]
        for source in fixture['grammar_rows']:
            words,gloss=support.parse_wordnet_row(source['raw'],source['offset'],source['pos'])
            evidence.append({'id':f"wordnet:3.1:{source['pos']}:{source['offset']:08d}",
                'kind':'english_definition','language':'en','edition':'3.1','pos':source['pos'],
                'synset_offset':source['offset'],'raw':source['raw'],'lemmas':words,'gloss':gloss,
                'work':'Princeton WordNet3.1','locus':str(source['offset']),
                'source_url':fixture['grammar_source'],'limitations':[]})
        target={'id':'g','line_id':'v','source_evidence_ids':[], 'english_candidates':[
            {'id':'c','expression':'grammar control','english_evidence_ids':[e['id'] for e in evidence]}]}
        packet={'targets':[target],'evidence':evidence};original=copy.deepcopy(packet)
        expected={
            'wordnet:3.1:a:00019769': {'adjective_positions':[
                {'word_index':1,'lemma':'ready to hand','position':'predicative'}], 'verb_frames':[]},
            'wordnet:3.1:a:00524413': {'adjective_positions':[
                {'word_index':0,'lemma':'dead','position':'attributive'}], 'verb_frames':[]},
            'wordnet:3.1:a:00014377': {'adjective_positions':[
                {'word_index':1,'lemma':'galore','position':'immediately_postnominal'}], 'verb_frames':[]},
            'wordnet:3.1:v:00027261': {'adjective_positions':[], 'verb_frames':[
                {'number':8,'template':'Somebody ----s something','word_indices':[0,1]},
                {'number':2,'template':'Somebody ----s','word_indices':[0]}]}}
        self.assertEqual(fixture['verb_frame_templates']['8'],'Somebody ----s something')
        self.assertEqual(fixture['verb_frame_templates']['2'],'Somebody ----s')
        for stage in ('translation','review'):
            prompt=support.prompt(packet,['v'],stage)
            projected=json.JSONDecoder().raw_decode(prompt.split('TARGETED LEXICAL SUPPORT:\n',1)[1])[0]
            self.assertEqual({e['id']:e.get('grammar') for e in projected['evidence']},expected)
            self.assertTrue(all('raw' not in e for e in projected['evidence']))
        self.assertEqual(packet,original)

if __name__=='__main__':unittest.main()

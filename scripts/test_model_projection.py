"""Lossless model-facing compression; actual storage/complete paths, no paid transport."""
import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import bhakti_lexical_support as support
import test_automatic_semantic_lexical as semantic_fixture
import test_english_discovery_design as english_fixture

FIX=Path(__file__).parent/'fixtures'/'model_projection'

def decode_prompt(packet,stage):
    return json.JSONDecoder().raw_decode(support.prompt(packet,[t['line_id'] for t in packet['targets']],stage).split('TARGETED LEXICAL SUPPORT:\n',1)[1])[0]

def restored(row,projection):
    row=copy.deepcopy(row)
    if 'dictionary_id' in row:row.update(projection['dictionaries'][row.pop('dictionary_id')])
    grammar=row.setdefault('grammar',{})
    grammar.setdefault('adjective_positions',[]);grammar.setdefault('verb_frames',[])
    for frame in grammar['verb_frames']:
        if 'template' not in frame:frame['template']=projection['verb_frame_templates'][str(frame['number'])]
    if row.get('id','').startswith('wordnet:') and 'synset_offset' not in row:
        row['synset_offset']=int(row['id'].rsplit(':',1)[1])
    return row

class ProjectionEvidence(unittest.TestCase):
    def setUp(self):self.packet=json.loads((FIX/'actual-support.json').read_text())
    def test_actual_sixty_one_definitions_grammar_provenance_candidates_and_ranks_survive(self):
        original=copy.deepcopy(self.packet)
        self.assertEqual(len(self.packet['evidence']),61)
        for stage in ('translation','review'):
            p=decode_prompt(self.packet,stage)
            self.assertIn('dictionaries',p);self.assertIn('verb_frame_templates',p)
            by={e['id']:restored(e,p) for e in p['evidence']}
            self.assertEqual(set(by),{e['id'] for e in original['evidence']})
            for before in original['evidence']:
                after=by[before['id']]
                for key in ('gloss','lemmas','pos','locus','work','source_url','edition','language','kind','limitations','requested_lemmas','synset_offset'):
                    self.assertEqual(after[key],before[key],(before['id'],key))
                self.assertEqual(after['grammar'],support.wordnet_grammar(before))
            for old,new in zip(original['targets'],p['targets']):
                self.assertEqual(new['english_candidates'],old['english_candidates'])
                a,b=old['english_discovery'],new['english_discovery']
                self.assertEqual(a['seed_lemmas'],b['seed_lemmas']);self.assertEqual(a['diagnostics'],b['diagnostics'])
                for old_c,new_c in zip(a['candidates'],b['candidates']):
                    self.assertEqual(new_c['lemma'],old_c['lemma'])
                    self.assertEqual([{k:s[k] for k in ('evidence_id','score','status')} for s in old_c['scores']],new_c['scores'])
                    self.assertEqual(set(old_c['evidence_ids']),{s['evidence_id'] for s in new_c['scores']})
                for key in ('neighbor_synsets_visited','neighbor_synsets_omitted','discovered_lemmas_omitted','max_neighbor_synsets','max_discovered_lemmas','limitations'):
                    self.assertEqual(b['pool'][key],a['pool'][key])
            raw=support.prompt(self.packet,[t['line_id'] for t in self.packet['targets']],stage).split('TARGETED LEXICAL SUPPORT:\n',1)[1]
            _,chars=json.JSONDecoder().raw_decode(raw)
            self.assertLess(chars,40000) # Actual emitted JSON, including its exact formatting.
        self.assertEqual(self.packet,original)

    def test_real_lemma_specific_verb_frames_and_adjective_positions_reconstruct_exactly(self):
        x=json.loads(english_fixture.FIXTURE.read_text());evidence=[]
        for raw in x['grammar_rows']:
            words,gloss=support.parse_wordnet_row(raw['raw'],raw['offset'],raw['pos'])
            evidence.append({'id':f"wordnet:3.1:{raw['pos']}:{raw['offset']:08d}",'kind':'english_definition',
                'language':'en','edition':'3.1','pos':raw['pos'],'synset_offset':raw['offset'],'raw':raw['raw'],
                'lemmas':words,'gloss':gloss,'work':'Princeton WordNet3.1','locus':str(raw['offset']),
                'source_url':x['grammar_source'],'limitations':[]})
        packet={'targets':[{'id':'t','line_id':'v','source_evidence_ids':[],
            'english_candidates':[{'id':'c','english_evidence_ids':[e['id'] for e in evidence]}]}],'evidence':evidence}
        for stage in ('translation','review'):
            p=decode_prompt(packet,stage)
            for old,new in zip(evidence,p['evidence']):self.assertEqual(restored(new,p)['grammar'],support.wordnet_grammar(old))
            self.assertTrue(any('template' not in frame for e in p['evidence'] for frame in e.get('grammar',{}).get('verb_frames',[])))

    def test_source_quotes_and_provenance_are_unchanged_and_gloss_prompt_stays_legacy(self):
        packet=copy.deepcopy(self.packet)
        e={'id':'source:control','kind':'current_language_usage','language':'hi','lemma':'control',
            'work':'Exact witnessed work','locus':'p.17','source_url':'https://example.test/dictionary',
            'quotation':'<hw>exact form</hw> Complete original quotation.','limitations':['Historical usage.']}
        packet['evidence'].append(e);packet['targets'][0]['source_evidence_ids'].append(e['id'])
        for stage in ('translation','review'):
            p=decode_prompt(packet,stage);self.assertEqual(next(row for row in p['evidence'] if row['id']==e['id']),e)
        legacy=decode_prompt(packet,'gloss')
        self.assertNotIn('dictionaries',legacy)
        self.assertTrue(all('work' in row for row in legacy['evidence']))

class ActualProjectionConsumers(unittest.TestCase):
    def setUp(self):
        self.case=semantic_fixture.AutomaticSemanticLexicalTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
    def test_writer_and_review_receive_shared_metadata_without_losing_definition(self):
        original=self.case.transport;seen=[]
        def transport(model,key,prompt,**kw):
            if 'word_gloss' not in kw['schema_name']:
                p=json.JSONDecoder().raw_decode(prompt.split('TARGETED LEXICAL SUPPORT:\n',1)[1])[0]
                self.assertIn('dictionaries',p)
                for e in p['evidence']:
                    if e['kind']=='english_definition':
                        self.assertEqual(restored(e,p)['work'],'Princeton WordNet 3.1')
                seen.append(kw['schema_name'])
            return original(model,key,prompt,**kw)
        with patch.object(semantic_fixture.pipeline.gemini,'call',side_effect=transport):self.case.complete()
        self.assertEqual(seen,['bhakti_literal_translation','bhakti_translation_review'])
    def test_auto_without_targets_projection_version_preserves_accepted_run_without_calls(self):
        self.case.gloss[0]['lexical_queries']=[]
        self.case.gloss[0]['lexical_query_gaps']=[]
        first=self.case.complete();state=self.case.state();count=len(self.case.calls)
        self.assertEqual(self.case.kinds(),['bhakti_word_glosses','bhakti_literal_translation','bhakti_translation_review'])
        self.assertTrue(all('TARGETED LEXICAL SUPPORT:' not in call['prompt'] for call in self.case.calls))
        with patch.object(support,'MODEL_PROJECTION_VERSION',support.MODEL_PROJECTION_VERSION+1):
            second=self.case.complete()
            self.assertEqual(len(self.case.calls),count)
            self.assertEqual(second,first);self.assertEqual(self.case.state(),state)
            self.assertEqual(self.case.complete(),first);self.assertEqual(len(self.case.calls),count)

    def test_projection_version_refreshes_English_review_only_then_resumes(self):
        first=self.case.complete();old_gloss=copy.deepcopy(first[0]);count=len(self.case.calls)
        old_policy=semantic_fixture.pipeline.semantic_stage_policy(self.case.options,stage='gloss')
        with patch.object(support,'MODEL_PROJECTION_VERSION',support.MODEL_PROJECTION_VERSION+1):
            self.assertEqual(semantic_fixture.pipeline.semantic_stage_policy(self.case.options,stage='gloss'),old_policy)
            second=self.case.complete()
            self.assertEqual(self.case.kinds()[count:],['bhakti_literal_translation','bhakti_translation_review'])
            self.assertEqual(second[0]['packet'],old_gloss['packet'])
            count=len(self.case.calls);self.assertEqual(self.case.complete(),second);self.assertEqual(len(self.case.calls),count)
    def test_no_support_policy_unaffected_and_explicit_writer_policy_versioned(self):
        pipeline=semantic_fixture.pipeline
        with patch.dict(os.environ,{'BHAKTI_AUTO_LEXICAL':'0'}):
            empty=pipeline.semantic_stage_policy(self.case.options)
            self.case.options.semantic_lexical_support=json.loads((FIX/'actual-support.json').read_text())
            before=pipeline.semantic_stage_policy(self.case.options,stage='gloss')
            writer=pipeline.semantic_stage_policy(self.case.options,stage='translation')
            with patch.object(support,'MODEL_PROJECTION_VERSION',support.MODEL_PROJECTION_VERSION+1):
                self.assertEqual(pipeline.semantic_stage_policy(self.case.options,stage='gloss'),before)
                self.assertNotEqual(pipeline.semantic_stage_policy(self.case.options,stage='translation'),writer)
                del self.case.options.semantic_lexical_support
                self.assertEqual(pipeline.semantic_stage_policy(self.case.options),empty)
            self.case.options.semantic_lexical_support={'targets':[],'evidence':[]}
            empty_packet=pipeline.semantic_stage_policy(self.case.options,stage='translation')
            with patch.object(support,'MODEL_PROJECTION_VERSION',support.MODEL_PROJECTION_VERSION+1):
                self.assertEqual(pipeline.semantic_stage_policy(self.case.options,stage='translation'),empty_packet)

if __name__=='__main__':unittest.main()

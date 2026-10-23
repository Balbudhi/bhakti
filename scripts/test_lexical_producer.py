"""Review-ready requirements; producer not implemented yet. No network/model calls.

Run after implementation with the automatic directory and repository scripts in PYTHONPATH.
Private authentic pilot fixture location will become a small repository fixture on integration.
"""
import copy
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import bhakti_lexical_retrieval as lexical
import bhakti_lexical_support as support
import dictionary_corpus as dictionaries
from test_lexical_support import fixture

PILOT=Path(__file__).parent/'fixtures/lexical_producer'

class AutomaticProducerRequirements(unittest.TestCase):
    def setUp(self):
        self.producer=importlib.import_module('bhakti_lexical_producer')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);_,_,self.wn=fixture(self.root)
        records=json.loads((PILOT/'acquisition.json').read_text())
        record=next(r for r in records if r['query']=='वज्र')
        raw=dictionaries.load_cached_witness(PILOT,record)
        entries=dictionaries.parse_platts_html(raw.decode(),query=record['query'],url=record['url'],witness_sha256=record['sha256'])
        self.entry=next(e for e in entries if 'vajra' in e['roman_search_aliases'])
        self.lines=[{'id':'v','source_text':'वज्र','roman':'vajra','sourceLanguage':'hi','kind':'verse'}]
        self.bindings=lexical.token_candidates(self.lines,['Hindi'],{'entries':[self.entry]})
        self.proposal={'word_indices':[0],'surfaces':['vajra'],'reason':'Physical hardness rather than mental obstinacy.',
            'source_entry_ids':[self.entry['entry_id']],
            'english_candidates':[{'expression':'adamantine','kind':'word','english_lemmas':['adamantine']},
                {'expression':'hard as diamond','kind':'compositional_phrase','english_lemmas':[]}]}
        self.gloss=[{'id':'v','word_glosses':[{'roman':'vajra','gloss':'hard; adamantine','concept_key':'','preserve_in_english':False}],
            'sense_decisions':[{'word_index':0,'roman':'vajra','evidence_status':'dictionary_supported','chosen':[{'entry_id':self.entry['entry_id'],'sense_id':self.entry['senses'][0]['sense_id']}],
                'rejected':[],'contextual_reason':'Physical adjective reading in this structural fixture.','grammatical_role':'adjective'}],
            'lexical_queries':[self.proposal],'lexical_query_gaps':[]}]

    def produce(self, **overrides):
        args=dict(token_candidates=self.bindings,acquisition_roots=[PILOT],wordnet_directory=self.wn,
            edition='3.1',cache_dir=self.root/'cache',context_lines=self.lines,
            performance_order=[{'line_id':'v','occurrence':1}])
        args.update(overrides)
        return self.producer.produce_support(self.lines,self.gloss,['Hindi'],**args)

    def test_proposal_limits_and_exact_source_binding(self):
        self.assertEqual(self.producer.proposal_errors(self.lines,self.gloss,['Hindi']),[])
        original=copy.deepcopy(self.gloss)
        for field,bad in [('word_indices',[1]),('surfaces',['vajrāṅga'])]:
            self.gloss=copy.deepcopy(original);self.gloss[0]['lexical_queries'][0][field]=bad
            self.assertTrue(self.producer.proposal_errors(self.lines,self.gloss,['Hindi']))
        self.gloss=copy.deepcopy(original)
        self.gloss[0]['lexical_queries'][0]['english_candidates'][0]['english_lemmas']=['one','two','three','four','five']
        self.assertTrue(self.producer.proposal_errors(self.lines,self.gloss,['Hindi']))

    def test_required_span_cannot_disappear_silently(self):
        self.gloss[0]['lexical_queries']=[]
        required=[{'line_id':'v','word_indices':[0]}]
        self.assertTrue(self.producer.proposal_errors(self.lines,self.gloss,['Hindi'],required_spans=required))
        self.gloss[0]['lexical_query_gaps']=[{'word_indices':[0],'reason':'No reliable lookup proposal; retain contextual review.'}]
        self.assertEqual(self.producer.proposal_errors(self.lines,self.gloss,['Hindi'],required_spans=required),[])

    def test_source_witness_is_reparsed_from_hash_bound_original_html(self):
        result=self.producer.resolve_source_witnesses([self.entry],[PILOT])
        self.assertEqual(result['gaps'],[])
        self.assertEqual(len(result['evidence']),1)
        evidence=result['evidence'][0]
        self.assertEqual(evidence['language'],'hi')
        self.assertIn('<entry>',evidence['quotation'])
        self.assertIn('Having a hardy frame',evidence['quotation'])
        self.assertIn(evidence['id'],result['entry_evidence_ids'][self.entry['entry_id']])
        self.assertEqual(evidence['witness_sha256'],self.entry['dictionary']['witness_sha256'])
        fake=copy.deepcopy(self.entry);fake['dictionary']['whole_entry_text']='Model-invented definition'
        with self.assertRaises(ValueError):self.producer.resolve_source_witnesses([fake],[PILOT])

    def test_emitted_citation_comes_from_reparsed_witness_not_input_metadata(self):
        expected={'work':self.entry['dictionary']['work'],
            'source_url':self.entry['dictionary']['url'],
            'locus':self.entry['dictionary']['entry_locator']}
        for field in ('work','url','entry_locator'):
            with self.subTest(field=field):
                tampered=copy.deepcopy(self.entry)
                tampered['dictionary'][field]='invented citation metadata'
                result=self.producer.resolve_source_witnesses([tampered],[PILOT])
                evidence=result['evidence'][0]
                self.assertEqual({key:evidence[key] for key in expected},expected)
                self.assertEqual(evidence['witness_sha256'],self.entry['dictionary']['witness_sha256'])

    def test_missing_source_witness_is_explicit_not_model_citation(self):
        result=self.producer.resolve_source_witnesses([self.entry],[self.root])
        self.assertEqual(result['evidence'],[])
        self.assertEqual(result['gaps'][0]['kind'],'source_witness_missing')
        self.assertEqual(result['gaps'][0]['entry_id'],self.entry['entry_id'])

    def test_missing_source_evidence_diagnostic_remains_available_to_model(self):
        from types import SimpleNamespace
        result=self.produce(acquisition_roots=[])
        self.assertEqual(result['packet']['targets'][0]['source_evidence_ids'],[])
        prompt=self.producer.diagnostics_prompt(SimpleNamespace(automatic_lexical_diagnostics=result['diagnostics']))
        self.assertIn('source_witness_missing',prompt)
        self.assertIn('not a dictionary miss',prompt)

    def test_all_english_senses_survive_cached_lookup_and_capitalization(self):
        kwargs=dict(edition='3.1',cache_dir=self.root/'english')
        with patch.object(support,'lookup_wordnet',wraps=support.lookup_wordnet) as actual:
            first=self.producer.lookup_english_cached(self.wn,['Adamantine','adamantine'],**kwargs)
            calls=actual.call_count
            second=self.producer.lookup_english_cached(self.wn,['adamantine'],**kwargs)
        self.assertEqual(first,second);self.assertEqual(actual.call_count,calls)
        self.assertEqual(len(first['evidence']),3)
        self.assertEqual({e['gloss'] for e in first['evidence']},
            {'consisting of or having the hardness of adamant','having the hardness of a diamond',
             '''impervious to pleas, persuasion, requests, reason; "he is adamant in his refusal to change his mind"; "Cynthia was inexorable; she would have none of him"- W.Churchill; "an intransigent conservative opposed to every liberal tendency"'''})
        self.assertEqual(first['misses'],[])

    def test_configuration_content_identity_precedes_acceptance_and_ignores_locations(self):
        import os, shutil
        source=self.root/'sources';shutil.copytree(PILOT,source)
        environment={'BHAKTI_AUTO_LEXICAL':'1','BHAKTI_WORDNET_DIR':str(self.wn),
            'BHAKTI_SOURCE_WITNESS_ROOTS':json.dumps([str(source)])}
        with patch.dict(os.environ,environment):
            before=self.producer.configuration_identity()
            moved=self.root/'moved';shutil.copytree(self.wn,moved)
            os.environ['BHAKTI_WORDNET_DIR']=str(moved)
            self.assertEqual(before,self.producer.configuration_identity())
            data=moved/'data.adj';data.write_bytes(data.read_bytes().replace(b'hardness of a diamond',b'hardness of a crystal'))
            manifest=json.loads((moved/'manifest.json').read_text())
            manifest['data_sha256']['adj']=support.file_hash(data)
            (moved/'manifest.json').write_text(json.dumps(manifest))
            self.assertNotEqual(before,self.producer.configuration_identity())
            os.environ['BHAKTI_WORDNET_DIR']=str(self.wn)
            records=json.loads((source/'acquisition.json').read_text())
            witness=source/records[0]['path'];witness.write_bytes(witness.read_bytes()+b'\n')
            records[0]['sha256']=support.file_hash(witness)
            (source/'acquisition.json').write_text(json.dumps(records))
            self.assertNotEqual(before,self.producer.configuration_identity())

    def test_subset_coverage_is_not_a_dictionary_miss(self):
        with self.assertRaisesRegex(ValueError,'coverage|subset|complete'):
            self.producer.lookup_english_cached(self.wn,['unacquired_word'],edition='3.1',cache_dir=self.root/'english')

    def test_automatic_packet_reaches_existing_support_contract_without_manual_manifest(self):
        before=copy.deepcopy(self.gloss)
        result=self.produce();packet=result['packet']
        support.validate_support(packet,self.lines,['Hindi'])
        self.assertEqual(self.gloss,before)
        self.assertEqual(len([e for e in packet['evidence'] if e['kind']=='english_definition']),3)
        self.assertEqual(len(packet['targets']),1)
        self.assertEqual(packet['targets'][0]['surfaces'],['vajra'])
        self.assertEqual(result['gloss_rows'][0]['word_glosses'],before[0]['word_glosses'])
        self.assertEqual(support.support_decision_errors(packet,result['gloss_rows']),[])
        for stage in ('translation','review'):
            prompt=support.prompt(packet,['v'],stage)
            self.assertIn('having the hardness of a diamond',prompt)
            self.assertIn('impervious to pleas',prompt)
            self.assertIn('Having a hardy frame',prompt)

    def test_hindi_dictionary_not_applied_to_identical_sanskrit_surface(self):
        self.lines[0]['sourceLanguage']='sa'
        self.bindings=lexical.token_candidates(self.lines,['Sanskrit'],{'entries':[self.entry]})
        self.assertEqual(self.bindings['v'][0]['candidates'],[])
        with self.assertRaisesRegex(ValueError,'bound|language|entry'):
            self.produce()

    def test_repeated_lookup_cannot_select_sense_or_rewrite_gloss(self):
        first=self.produce();second=self.produce()
        self.assertEqual(first['identity'],second['identity'])
        self.assertEqual(first['packet'],second['packet'])
        self.assertEqual(first['gloss_rows'][0]['sense_decisions'],self.gloss[0]['sense_decisions'])
        changed=copy.deepcopy(self.lines);changed[0]['source_text']='वज्र!'
        third=self.produce(context_lines=changed)
        self.assertNotEqual(first['identity'],third['identity'])


class AutomaticCallerRequirements(unittest.TestCase):
    """Real stage/storage route with canned provider only; not linguistic qualification."""
    setUp = AutomaticProducerRequirements.setUp

    def test_existing_three_calls_deliver_automatic_evidence_and_resume(self):
        self.run_actual_stages()

    def test_legacy_gloss_without_queries_never_triggers_a_gloss_only_call(self):
        self.run_actual_stages(legacy=True)

    def test_requested_span_is_delivered_through_selective_translation_repair(self):
        self.run_actual_stages(selective=True)

    def test_changed_dictionary_invalidates_translation_but_relocation_reuses(self):
        self.run_actual_stages(change_dictionary=True)

    def run_actual_stages(self, legacy=False, selective=False, change_dictionary=False):
        import argparse
        import os
        import bhakti_pipeline as pipeline
        from test_sense_decisions import decisions_for
        lexicon=self.root/'lexicon.json';lexicon.write_text(json.dumps({'entries':[self.entry]}))
        environment={'BHAKTI_AUTO_LEXICAL':'1','BHAKTI_WORDNET_DIR':str(self.wn),
            'BHAKTI_SOURCE_WITNESS_ROOTS':json.dumps([str(PILOT)]),
            'BHAKTI_LEXICAL_SUPPORT_CACHE':str(self.root/'producer-cache'),
            'BHAKTI_LEXICON_PATH':str(lexicon)}
        calls=[]
        changed=[False]
        def transport(model,key,prompt,**kw):
            kind=kw['schema_name'];calls.append((kind,prompt))
            if kind=='bhakti_word_glosses':
                self.assertIn('lexical_queries',kw['response_schema']['properties']['glosses']['items']['properties'])
                row=copy.deepcopy(self.gloss[0]);row['sense_decisions']=decisions_for(self.lines,['Hindi'])['v']
                row.update(semantic_frame={field:'' for field in pipeline.SEMANTIC_FRAME_FIELDS},grammar_note='',uncertainty='')
                return {'packet':{'glosses':[row]}}
            self.assertIn('TARGETED LEXICAL SUPPORT:',prompt)
            self.assertIn('having the hardness of a '+('crystal' if changed[0] else 'diamond'),prompt)
            self.assertIn('impervious to pleas',prompt)
            if kind=='bhakti_translation_review':
                return {'packet':{'reviews':[{'id':'v','passes':True,'human_review_recommended':False,
                    'agency_preserved':True,'imagery_preserved':True,'all_meaning_accounted_for':True,
                    'unsupported_additions':[],'material_choice':'','reason':'Transport fixture only.','issues':[]}]}}
            packet=json.JSONDecoder().raw_decode(prompt.split('TARGETED LEXICAL SUPPORT:\n',1)[1])[0]
            target=packet['targets'][0];candidate=next(c for c in target['english_candidates'] if c['expression']=='adamantine')
            eid=next(e['id'] for e in packet['evidence'] if e.get('gloss')=='having the hardness of a '+('crystal' if changed[0] else 'diamond'))
            return {'packet':{'translations':[{'id':'v','literal_english':'Adamantine',
                'segments':[{'text':'Adamantine','word_indices':[0]}],
                'wording_decisions':[{'target_id':target['id'],'chosen_candidate_id':candidate['id'],
                    'expression':'adamantine','kind':'word','english_evidence_ids':[eid],'word_indices':[0],
                    'ordinary_paraphrase':'hard as diamond','component_word_indices':[[0]],'reason':'Physical sense control.'}],
                'human_review_recommended':False,'material_alternatives':[],'choice_note':'','uncertainty':'',
                'fidelity':{'agency_and_image_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[],'notes':''}}]}}
        options=argparse.Namespace(model='fixture',force=False,timeout=1,gloss_batch_size=40,gloss_workers=1,max_attempts=1)
        audited={'packet':{'verified_lines':self.lines,'metadata':{'languages':['Hindi']},'performance_order':[{'line_id':'v','occurrence':1}]}}
        song=self.root/'song';song.mkdir()
        with patch.dict(os.environ,environment),patch.object(pipeline.gemini,'key',return_value='fixture'),patch.object(pipeline.gemini,'call',side_effect=transport):
            for _ in range(2):
                if legacy:
                    gloss={'packet':{'glosses':[copy.deepcopy(self.gloss[0])]}}
                    row=gloss['packet']['glosses'][0]
                    row.pop('lexical_queries');row.pop('lexical_query_gaps')
                    row['word_glosses'][0]['gloss']='adamantine'
                    row['sense_decisions']=decisions_for(self.lines,['Hindi'])['v']
                    row.update(semantic_frame={field:'' for field in pipeline.SEMANTIC_FRAME_FIELDS},grammar_note='',uncertainty='')
                else:
                    gloss=pipeline.gloss(song,audited,options)
                if selective:
                    options.semantic_translation_targets=['v']
                    options.semantic_previous_translations=[{'id':'v','literal_english':'Hard',
                        'segments':[{'text':'Hard','word_indices':[0]}]}]
                    options.semantic_repair_feedback=[{'kind':'english_realization','target_line_ids':['v'],
                        'references':[{'line_id':'v','word_indices':[0]}]}]
                saved=copy.deepcopy(gloss)
                result=pipeline.translate(song,audited,gloss,{'languages':['Hindi']},options,candidate_only=True)
                self.assertEqual(gloss,saved)
            if change_dictionary:
                import shutil
                relocated=self.root/'relocated-wordnet';shutil.copytree(self.wn,relocated)
                os.environ['BHAKTI_WORDNET_DIR']=str(relocated)
                pipeline.translate(song,audited,gloss,{'languages':['Hindi']},options,candidate_only=True)
                self.assertEqual(len(calls),3)
                data=relocated/'data.adj'
                data.write_bytes(data.read_bytes().replace(b'hardness of a diamond',b'hardness of a crystal'))
                manifest=json.loads((relocated/'manifest.json').read_text())
                manifest['data_sha256']['adj']=support.file_hash(data)
                (relocated/'manifest.json').write_text(json.dumps(manifest))
                changed[0]=True
                pipeline.translate(song,audited,gloss,{'languages':['Hindi']},options,candidate_only=True)
                self.assertEqual([kind for kind,_ in calls[3:]],['bhakti_literal_translation','bhakti_translation_review'])
        self.assertEqual([kind for kind,_ in calls[:3 if not legacy else 2]],([] if legacy else ['bhakti_word_glosses'])+['bhakti_literal_translation','bhakti_translation_review'])
        self.assertEqual(result['packet']['translations'][0]['literal_english'],'Adamantine')
        self.assertFalse(hasattr(options,'semantic_lexical_support'))

if __name__=='__main__':unittest.main()

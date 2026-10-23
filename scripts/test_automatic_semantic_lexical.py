"""Actual semantic completion + automatic dictionary cache transitions.

Authentic dictionary bytes and real storage/validators; canned transport proves
orchestration, not translation quality. Corpus mutations are test controls.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import bhakti_pipeline as pipeline
import bhakti_lexical_support as support
import test_lexical_producer as lexical_fixtures
from test_sense_decisions import decisions_for


class AutomaticSemanticLexicalTests(unittest.TestCase):
    def setUp(self):
        lexical_fixtures.AutomaticProducerRequirements.setUp(self)
        data = self.root/'data'; data.mkdir()
        original = Path(__file__).resolve().parent.parent/'data'
        shutil.copy(original/'preserved_terms.json', data/'preserved_terms.json')
        (data/'editorial_baselines.json').write_text('{"version":1,"songs":{}}')
        lexicon = self.root/'lexicon.json'; lexicon.write_text(json.dumps({'entries':[self.entry]}))
        self.sources = self.root/'sources'; shutil.copytree(lexical_fixtures.PILOT, self.sources)
        self.environment = {'BHAKTI_AUTO_LEXICAL':'1','BHAKTI_WORDNET_DIR':str(self.wn),
            'BHAKTI_SOURCE_WITNESS_ROOTS':json.dumps([str(self.sources)]),
            'BHAKTI_LEXICAL_SUPPORT_CACHE':str(self.root/'lookup-cache'), 'BHAKTI_LEXICON_PATH':str(lexicon),
            'BHAKTI_API_RUN_LEDGER':str(self.root/'ledger.json'), 'BHAKTI_API_RUN_BUDGET_USD':'1'}
        self.options = argparse.Namespace(model='fixture',force=False,timeout=10,gloss_batch_size=40,
            gloss_workers=1,max_attempts=1,semantic_repair_rounds=2,semantic_repair_seconds=60)
        self.audit = {'packet':{'verified_lines':self.lines,'metadata':{'languages':['Hindi']},
            'performance_order':[{'line_id':'v','occurrence':1}]}}
        self.song = self.root/'songs'/'fixture'; self.song.mkdir(parents=True)
        self.packets = self.song/'.transcription'/'pipeline'; self.calls=[]
        self.legacy_gloss=False
        for item in (patch.dict(os.environ,self.environment),patch.object(pipeline,'ROOT',self.root),
                     patch.object(pipeline.gemini,'key',return_value='fixture-only'),
                     patch.object(pipeline.gemini,'call',side_effect=self.transport)):
            item.start(); self.addCleanup(item.stop)

    def transport(self,model,key,prompt,**kw):
        kind=kw['schema_name'];self.calls.append({'kind':kind,'prompt':prompt})
        if 'word_gloss' in kind:
            row=copy.deepcopy(self.gloss[0]);row['word_glosses'][0]['gloss']='adamantine'
            row['sense_decisions']=decisions_for(self.lines,['Hindi'])['v']
            row.update(semantic_frame={field:'' for field in pipeline.SEMANTIC_FRAME_FIELDS},grammar_note='',uncertainty='')
            if self.legacy_gloss:
                row.pop('lexical_queries');row.pop('lexical_query_gaps')
            return {'packet':{'glosses':[row]}}
        if kind=='bhakti_translation_review':
            return {'packet':{'reviews':[{'id':'v','passes':True,'human_review_recommended':False,
                'agency_preserved':True,'imagery_preserved':True,'all_meaning_accounted_for':True,
                'unsupported_additions':[],'material_choice':'','reason':'Transport control, not quality proof.','issues':[],
                'component_judgments':{k:{'status':'supported','reason':'This canned transport fixture supports the component.'} for k in ('gloss','frame','english')}}]}}
        row={'id':'v','literal_english':'Adamantine','segments':[{'text':'Adamantine','word_indices':[0]}],
             'human_review_recommended':False,'material_alternatives':[],'choice_note':'','uncertainty':'',
             'fidelity':{'agency_and_image_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[],'notes':''}}
        if 'TARGETED LEXICAL SUPPORT:\n' in prompt:
            packet=json.JSONDecoder().raw_decode(prompt.split('TARGETED LEXICAL SUPPORT:\n',1)[1])[0]
            target=packet['targets'][0];candidate=next(c for c in target['english_candidates'] if c['expression']=='adamantine')
            entry=next(e for e in packet['evidence'] if e.get('gloss','').startswith('having the hardness of a '))
            row['wording_decisions']=[{'target_id':target['id'],'chosen_candidate_id':candidate['id'],
                'expression':'adamantine','kind':'word','english_evidence_ids':[entry['id']],'word_indices':[0],
                'ordinary_paraphrase':'hard as diamond','component_word_indices':[[0]],'reason':'Physical sense control.'}]
        return {'packet':{'translations':[row]}}

    def complete(self):
        return pipeline.complete_semantics(self.song,self.audit,{'slug':'fixture'},self.options)

    def kinds(self):return [call['kind'] for call in self.calls]
    def state(self):return json.loads((self.packets/'semantic-repair-state.json').read_text())

    def change_english_definition(self):
        data=Path(os.environ['BHAKTI_WORDNET_DIR'])/'data.adj'
        raw=data.read_bytes();self.assertIn(b'hardness of a diamond',raw)
        data.write_bytes(raw.replace(b'hardness of a diamond',b'hardness of a crystal'))
        path=data.parent/'manifest.json';manifest=json.loads(path.read_text())
        manifest['data_sha256']['adj']=support.file_hash(data);path.write_text(json.dumps(manifest))

    def test_new_completion_relocation_dictionary_change_and_resume_reuses_paid_gloss(self):
        original_audit=copy.deepcopy(self.audit);first=self.complete();first_id=self.state()['run_id']
        self.assertEqual(self.kinds(),['bhakti_word_glosses','bhakti_literal_translation','bhakti_translation_review'])
        initial_gloss=copy.deepcopy(first[0]['packet'])
        self.assertNotIn('support_decisions',initial_gloss['glosses'][0], 'Derived support must not accumulate in base04.')
        moved=self.root/'moved-wordnet';shutil.copytree(self.wn,moved)
        moved_source=self.root/'moved-source';shutil.copytree(self.sources,moved_source)
        os.environ['BHAKTI_WORDNET_DIR']=str(moved);os.environ['BHAKTI_SOURCE_WITNESS_ROOTS']=json.dumps([str(moved_source)])
        count=len(self.calls);second=self.complete()
        self.assertEqual(len(self.calls),count);self.assertEqual(second,first);self.assertEqual(self.state()['run_id'],first_id)
        self.change_english_definition();third=self.complete()
        self.assertNotEqual(self.state()['run_id'],first_id)
        self.assertEqual(self.kinds()[count:],['bhakti_literal_translation','bhakti_translation_review'])
        self.assertEqual(third[0]['packet'],initial_gloss)
        self.assertIn('having the hardness of a crystal',self.calls[-1]['prompt'])
        self.assertIn('support_decisions',self.calls[-1]['prompt']);self.assertIn('wording_decisions',self.calls[-1]['prompt'])
        count=len(self.calls);self.assertEqual(self.complete(),third);self.assertEqual(len(self.calls),count)
        self.assertEqual(self.audit,original_audit)

    def test_preautomatic_accepted_completion_enabling_support_keeps_gloss_and_requires_review(self):
        os.environ['BHAKTI_AUTO_LEXICAL']='0';self.legacy_gloss=True
        old=self.complete();old_gloss=copy.deepcopy(old[0]['packet']);old_id=self.state()['run_id'];count=len(self.calls)
        os.environ['BHAKTI_AUTO_LEXICAL']='1';new=self.complete()
        self.assertNotEqual(self.state()['run_id'],old_id)
        self.assertEqual(self.kinds()[count:],['bhakti_literal_translation','bhakti_translation_review'])
        self.assertEqual(new[0]['packet'],old_gloss)
        self.assertIn('wording_decisions',new[1]['packet']['translations'][0])
        self.assertIn('TARGETED LEXICAL SUPPORT:',self.calls[-1]['prompt'])

    def test_preautomatic_stage_seed_cannot_accept_english_without_new_support(self):
        os.environ['BHAKTI_AUTO_LEXICAL']='0';self.legacy_gloss=True
        gloss=pipeline.gloss(self.song,self.audit,self.options)
        pipeline.translate(self.song,self.audit,gloss,{},self.options)
        self.calls.clear();os.environ['BHAKTI_AUTO_LEXICAL']='1'
        new=self.complete()
        self.assertEqual(self.kinds(),['bhakti_literal_translation','bhakti_translation_review'])
        self.assertEqual(new[0]['packet'],gloss['packet'])
        self.assertIn('wording_decisions',new[1]['packet']['translations'][0])

    def test_current_automatic_stage_seed_adopts_without_reconstruction(self):
        gloss=pipeline.gloss(self.song,self.audit,self.options)
        original=pipeline.translate(self.song,self.audit,gloss,{},self.options)
        self.calls.clear();new=self.complete()
        # Unbound recording/order judgments remain review-only, but source/gloss/English must not regenerate.
        self.assertEqual(self.kinds(),['bhakti_translation_review'])
        self.assertEqual(new[0]['packet'],gloss['packet'])
        self.assertEqual(new[1]['packet']['translations'][0]['literal_english'],original['packet']['translations'][0]['literal_english'])

    def test_accepted_resume_checks_dictionary_witness_integrity_before_calls(self):
        self.complete();count=len(self.calls)
        path=self.wn/'data.adj';path.write_bytes(path.read_bytes()+b'\n')
        with self.assertRaisesRegex((ValueError,RuntimeError),'WordNet|hash|witness'):
            self.complete()
        self.assertEqual(len(self.calls),count)

    def test_accepted_resume_validates_persisted_english_lookup_cache(self):
        self.complete();count=len(self.calls)
        paths=list((self.root/'lookup-cache'/'english').glob('*/*.json'));self.assertTrue(paths)
        path=paths[0];value=json.loads(path.read_text());self.assertTrue(value['evidence'])
        value['evidence'][0]['gloss']='Invented unchecked definition';path.write_text(json.dumps(value))
        with self.assertRaisesRegex((ValueError,RuntimeError),'cache|content|identity'):
            self.complete()
        self.assertEqual(len(self.calls),count)

    def test_restored_corpus_after_failed_preflight_reuses_original_accepted_run(self):
        first=self.complete();old_state=self.state();count=len(self.calls)
        path=self.wn/'data.adj';original=path.read_bytes();path.write_bytes(original+b'\n')
        with self.assertRaisesRegex((ValueError,RuntimeError),'WordNet|hash|witness'):
            self.complete()
        path.write_bytes(original)
        self.assertEqual(self.complete(),first)
        self.assertEqual(self.state(),old_state)
        self.assertEqual(len(self.calls),count)

    def test_accepted_resume_checks_source_witness_integrity(self):
        self.complete();count=len(self.calls)
        record=json.loads((self.sources/'acquisition.json').read_text())[0]
        path=self.sources/record['path'];path.write_bytes(path.read_bytes()+b'\n')
        with self.assertRaisesRegex((ValueError,RuntimeError),'hash|witness|digest'):
            self.complete()
        self.assertEqual(len(self.calls),count)

    def test_accepted_automatic_english_still_requires_materialized_wording_decisions(self):
        self.complete();count=len(self.calls)
        path=self.packets/'05-translation.json';value=json.loads(path.read_text())
        value['packet']['translations'][0]['wording_decisions']=[];path.write_text(json.dumps(value))
        manifest=self.packets/'semantic-acceptance.json';saved=json.loads(manifest.read_text())
        saved['translation_sha256']=pipeline.bhakti_semantic_repair.digest(value);manifest.write_text(json.dumps(saved))
        # The immutable writer check may reject the removed decisions before
        # the lexical-support validator; either boundary must prevent reuse.
        with self.assertRaisesRegex((ValueError,RuntimeError),'decision|support|target|immutable writer evidence'):
            self.complete()
        self.assertEqual(len(self.calls),count)

    def test_english_only_repair_marker_interruption_keeps_accepted_gloss_seed(self):
        first=self.complete();old_id=self.state()['run_id'];old_gloss=copy.deepcopy(first[0]['packet'])
        count=len(self.calls);self.change_english_definition()
        original=pipeline.semantic_write_json;interrupted=False
        def write(path,value):
            nonlocal interrupted
            original(path,value)
            if Path(path).name=='semantic-repair-required.json' and value.get('run_id')!=old_id and not interrupted:
                interrupted=True
                raise KeyboardInterrupt('after new marker, before stage checkpoints')
        with patch.object(pipeline,'semantic_write_json',side_effect=write):
            with self.assertRaises(KeyboardInterrupt):self.complete()
        self.assertEqual(len(self.calls),count)
        repaired=self.complete()
        self.assertEqual(self.kinds()[count:],['bhakti_literal_translation','bhakti_translation_review'])
        self.assertEqual(repaired[0]['packet'],old_gloss)

    def test_no_early_state_write_can_erase_prior_acceptance_before_seed_is_durable(self):
        first=self.complete();old_id=self.state()['run_id'];old_gloss=copy.deepcopy(first[0]['packet'])
        count=len(self.calls);self.change_english_definition()
        original=pipeline.semantic_write_json
        def reject_unsafe_transition(path,value):
            if Path(path).name=='semantic-repair-state.json' and value.get('status')=='in-progress':
                seeds=list((self.packets/'semantic-repair').glob('*/adopted-seeds.json'))
                accepted=[json.loads(p.read_text()) for p in seeds]
                self.assertTrue(any(x['payload'].get('accepted_gloss_receipt') for x in accepted),
                    'Previous accepted state must survive until its reuse receipt is durably written.')
            original(path,value)
        with patch.object(pipeline,'semantic_write_json',side_effect=reject_unsafe_transition):
            repaired=self.complete()
        self.assertNotEqual(self.state()['run_id'],old_id)
        self.assertEqual(repaired[0]['packet'],old_gloss)
        self.assertEqual(self.kinds()[count:],['bhakti_literal_translation','bhakti_translation_review'])

    def test_standalone_gloss_reuses_source_when_only_english_dictionary_changes(self):
        first=pipeline.gloss(self.song,self.audit,self.options);count=len(self.calls)
        self.change_english_definition();second=pipeline.gloss(self.song,self.audit,self.options)
        self.assertEqual(first,second);self.assertEqual(len(self.calls),count)

    def test_invalid_automatic_corpus_rejected_before_first_paid_gloss(self):
        path=self.wn/'data.adj';path.write_bytes(path.read_bytes()+b'\n')
        with self.assertRaisesRegex((ValueError,RuntimeError),'WordNet|hash|witness'):
            pipeline.gloss(self.song,self.audit,self.options)
        self.assertEqual(self.calls,[])


if __name__=='__main__':unittest.main()

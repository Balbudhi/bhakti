"""Contextual pati policy contracts; fixtures do not certify model semantics."""
import argparse
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import gloss_policy
import bhakti_translation_policy as policy
import bhakti_pipeline as pipeline
import audit_bhakti_contract as audit
import bhakti_lexical_support as support
from test_sense_decisions import decisions_for
from test_lexical_support import fixture as source_fixture


class PatiContextTests(unittest.TestCase):
    def rows(self, roman='pati', native='पति', gloss='lord; master in this address'):
        lines=[{'id':'p','source_text':native,'roman':roman,'sourceLanguage':'sa','kind':'verse'}]
        rows=[{'id':'p','word_glosses':[{'roman':roman,'gloss':gloss,'concept_key':'','preserve_in_english':False}],
               'semantic_frame':{k:'' for k in pipeline.SEMANTIC_FRAME_FIELDS},
               'grammar_note':'The master relation is selected from this passage, not a universal derivation.',
               'uncertainty':'','sense_decisions':decisions_for(lines,['Sanskrit'])['p']}]
        return lines,rows
    def test_contextually_relational_lord_is_not_rejected_by_spelling(self):
        for roman,native,meaning in [('pati','पति','lord; master in this address'),
                                    ('raghupati','रघुपति',"lord of Raghu’s line"),
                                    ('girijāpati','गिरिजापति',"Girijā’s husband")]:
            with self.subTest(roman=roman):
                lines,rows=self.rows(roman,native,meaning)
                self.assertEqual(pipeline.fresh_gloss_contract_errors(lines,rows,['Sanskrit']),[])
                translation=[{'id':'p','literal_english':meaning,'segments':[{'text':meaning,'word_indices':[0]}]}]
                self.assertEqual(pipeline.validate_line_contract(lines,rows,translation),[])
    def test_real_public_reader_audit_does_not_ban_supported_lord(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);lines,rows=self.rows()
            reader={'SONG_META':{**{k:'' for k in audit.REQUIRED_META},'languages':['Sanskrit'],
                    'subjectTags':[],'timingStatus':'start-only-reviewed'},
                    'SONG_LINES':{'p':{'source':'पति','roman':'pati','english':'{0:master}',
                    'words':rows[0]['word_glosses'],'sourceWords':[{'text':'पति','wordIndices':[0]}]}},
                    'SONG_SEQUENCE':[{'ref':'p','section':'verse','repeats':1}],
                    'SONG_TIMINGS':[{'start':0,'end':1}]}
            (root/'data.js').write_text('\n'.join('window.'+k+'='+json.dumps(v)+';' for k,v in reader.items()))
            self.assertEqual(audit.audit_song(root)['problems'],[])
    def test_removing_word_ban_does_not_remove_semantic_review_gate(self):
        lines,rows=self.rows();translation=[{'id':'p','literal_english':'protector','segments':[{'text':'protector','word_indices':[0]}],
            'human_review_recommended':False,'uncertainty':'',
            'fidelity':{'agency_and_image_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[]},
            'independent_review':{'passes':False,'human_review_recommended':False,'agency_preserved':True,
                'imagery_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[]}}]
        self.assertTrue(any('independent' in x for x in pipeline.fresh_translation_contract_errors(lines,rows,translation)))
    def test_traditional_sanskrit_evidence_is_not_modern_hindi_sense_proof(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);manifest,lines,_=source_fixture(root)
            manifest.pop('wordnet');manifest['targets'][0]['english_candidates']=[
                {'id':'master-phrase','expression':'master of the house','kind':'compositional_phrase','english_lemmas':[]}]
            lines[0]['sourceLanguage']='hi';target=manifest['targets'][0];target['source_language']='hi'
            (root/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'language|relationship|background'):
                support.build_support(root/'manifest.json',lines,['Hindi'])
            target['source_evidence_ids']=[];target['background_evidence_ids']=['ks-pati']
            (root/'manifest.json').write_text(json.dumps(manifest))
            packet=support.build_support(root/'manifest.json',lines,['Hindi'])
            self.assertIn('पाति पतिः',packet['evidence'][0]['quotation'])
            self.assertEqual(packet['targets'][0]['source_evidence_ids'],[])
            self.assertEqual(packet['targets'][0]['background_evidence_ids'],['ks-pati'])
    def test_actual_gloss_prompt_qualifies_traditional_formation_and_allows_lord(self):
        lines,rows=self.rows(gloss='master in this address');prompts=[]
        def provider(model,key,prompt,**kwargs):
            prompts.append(prompt);return {'packet':{'glosses':rows}}
        options=argparse.Namespace(model='fixture',force=False,timeout=1,gloss_batch_size=3,gloss_workers=1,max_attempts=1)
        with tempfile.TemporaryDirectory() as folder,patch.object(pipeline.gemini,'key',return_value='fixture'),patch.object(pipeline.gemini,'call',side_effect=provider):
            pipeline.gloss(Path(folder),{'packet':{'verified_lines':lines,'metadata':{'languages':['Sanskrit']}}},options)
        self.assertEqual(len(prompts),1);prompt=prompts[0]
        self.assertNotIn('historically from √pā',prompt)
        self.assertNotIn('raghu-pati\u0060 is a guardian',prompt)
        self.assertIn('traditional formation',prompt.lower())
        self.assertIn('historical etymology',prompt.lower())
        self.assertIn('lord or master',prompt.lower())
        self.assertIn('source language',prompt.lower())


if __name__=='__main__':unittest.main()

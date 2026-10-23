"""Actual source observation/adoption, new-target semantics, merge and generation.
Only provider judgments and timing measurements are canned. The inserted source
nāma is translated as Name; retained owner reader rows must remain exact.
"""
import copy,json,os,unittest
from unittest.mock import patch
import bhakti_pipeline as pipeline
import bhakti_library_source_pass as source
from test_sense_decisions import decisions_for
import test_source_adoption_caller_design as fixture

class MixedSourceReview(unittest.TestCase):
    def test_actual_inserted_uncertain_writer_resolution_survives_mixed_generation(self):
        real_targets=source.process_new_targets
        c=fixture.SourceAdoptionCallerTests();c.setUp();self.addCleanup(c.doCleanups)
        c.add_source=True;c.options.semantic_stage_escalation=False
        c.options.semantic_repair_rounds=0;c.options.gloss_workers=1;c.options.gloss_batch_size=40;c.options.max_attempts=1
        calls=[];new_ids=[]
        def response(model,key,prompt,**kw):
            kind=kw['schema_name'];calls.append(kind)
            if kind=='bhakti_segment_audit':return c.provider(model,key,prompt,**kw)
            if kind=='bhakti_word_glosses':
                lines=json.JSONDecoder().raw_decode(prompt.split('TARGET LYRICS (return these IDs only):\n',1)[1].lstrip())[0]
                rows=[]
                for line in lines:
                    new_ids.append(line['id']);self.assertEqual(line['source_text'],'नाम')
                    rows.append({'id':line['id'],'word_glosses':[{'roman':'nāma','gloss':'name','concept_key':'','preserve_in_english':False}],
                        'semantic_frame':{k:'' for k in pipeline.SEMANTIC_FRAME_FIELDS},'grammar_note':'Noun.','uncertainty':'',
                        'sense_decisions':decisions_for(lines,['Hindi'])[line['id']]})
                return {'packet':{'glosses':rows},'resolved_model':model}
            if kind=='bhakti_literal_translation':
                return {'packet':{'translations':[{'id':i,'literal_english':'Name','segments':[{'text':'Name','word_indices':[0]}],
                    'material_alternatives':['the name'],'human_review_recommended':True,'choice_note':'Check whether an article is needed.',
                    'uncertainty':'English article choice needs review.','fidelity':{'agency_and_image_preserved':True,
                    'all_meaning_accounted_for':True,'unsupported_additions':[],'notes':''}} for i in new_ids]},'resolved_model':model}
            self.assertEqual(kind,'bhakti_translation_review')
            ids=json.JSONDecoder().raw_decode(prompt.split('OUTPUT TARGET IDS (return exactly these, once each):\n',1)[1].lstrip())[0]
            context=json.JSONDecoder().raw_decode(prompt.split('WRITER RESERVATIONS:\n',1)[1].lstrip())[0] if 'WRITER RESERVATIONS:\n' in prompt else {}
            return {'packet':{'reviews':[{'id':i,'passes':True,'human_review_recommended':False,'agency_preserved':True,'imagery_preserved':True,
                'all_meaning_accounted_for':True,'unsupported_additions':[],'material_choice':'','reason':'No consequential difference in this noun use.','issues':[],
                'component_judgments':{k:{'status':'supported','reason':'Name is the source noun here.'} for k in ('gloss','frame','english')},
                'writer_reservation_dispositions':[{'reservation_id':r['reservation_id'],'status':'resolved','source_quote':'नाम',
                    'explanation':'An article is not required to preserve the supplied noun sense.'} for r in context.get('reservations',[]) if r['line_id']==i]}
                for i in ids]},'resolved_model':model}
        real_generate = pipeline.generate
        checked_order = []
        def generate_with_order_check(song_dir, job, source_input, audited, timing, glosses, translations, **kwargs):
            changed = copy.deepcopy(audited)
            changed['packet']['performance_order'].reverse()
            self.assertNotEqual(changed['packet']['performance_order'], audited['packet']['performance_order'])
            errors = pipeline.publication_errors(changed, timing, glosses, translations,
                source_semantic_evidence=kwargs['source_semantic_evidence'])
            self.assertTrue(errors, 'Changed performed order must not reuse the original source-context proof.')
            checked_order.append(True)
            return real_generate(song_dir, job, source_input, audited, timing, glosses, translations, **kwargs)
        with patch.object(pipeline, 'generate', side_effect=generate_with_order_check), patch.dict(os.environ,{'BHAKTI_AUTO_LEXICAL':'0','BHAKTI_API_RUN_LEDGER':str(c.base/'ledger.json'),'BHAKTI_API_RUN_BUDGET_USD':'1'}), \
             patch.object(source,'process_new_targets',side_effect=real_targets),patch.object(pipeline.gemini,'call',side_effect=response):
            result=c.invoke()
        self.assertEqual(result['status'],'accepted',result)
        self.assertEqual(checked_order,[True])
        for line_id,row in c.reader['SONG_LINES'].items():self.assertEqual(result['reader']['SONG_LINES'][line_id],row)
        self.assertEqual(len(new_ids),1);self.assertIn('Name',result['reader']['SONG_LINES'][new_ids[0]]['english'])
        self.assertEqual(calls.count('bhakti_literal_translation'),1)
        self.assertEqual(calls.count('bhakti_word_glosses'),1)
        self.assertEqual(calls.count('bhakti_translation_review'),1)
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('Accepted source candidate cannot replay providers.')):
            self.assertEqual(c.invoke(),result)
        self.assertEqual((c.song/'data.js').read_bytes(),c.original)
        self.assertTrue((c.workspace/'songs'/c.slug/'index.html').is_file())

if __name__=='__main__':unittest.main()

"""Real source stages/router/storage; provider responses are explicit synthetic fixtures.

Empty-reader cases replace already qualified downstream semantics/timing only.
They prove source admission and private generation, not acoustic/translation quality.
"""
import argparse, copy, json, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
import bhakti_pipeline as pipeline
import bhakti_library_source_pass as source
import bhakti_model_routes as routes
import audit_bhakti_contract as contract
from test_generic_source_caller import make_audio, js
import test_source_adoption_caller_design as existing_caller


def packet(audit=False, uncertainty=False):
    return {'metadata':{'languages':['Hindi'],'script':'Devanagari','singer_candidates':[], 'credit_evidence':[]},
            'verified_lines' if audit else 'lines':[
                {'id':'mind','source_text':'मन','roman':'man','language':'Hindi','kind':'verse','notes':'','translation_notes':''},
                {'id':'body','source_text':'तन','roman':'tan','language':'Hindi','kind':'verse','notes':'','translation_notes':''}],
            'performance_order':[{'line_id':'mind','occurrence':1,'notes':''},{'line_id':'body','occurrence':1,'notes':''}],
            'changes':[], 'uncertainties':['masked word'] if uncertainty else []}

class SourceStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.song=Path(self.tmp.name)/'source-fixture';self.song.mkdir()
        self.audio=self.song/'audio.m4a';make_audio(self.audio,4)
        self.options=argparse.Namespace(model=pipeline.MODEL,pro_model=routes.PRO_MODEL,timeout=30,
            force=False,source_witness_audit=False,refresh_timing=False,unit_deadline_at=time.time()+180)
        self.calls=[];self.mixed_language=False;self.instrumental=False;self.bad_first=False;self.audit_uncertain=False;self.draft_uncertain=False;self.all_audits_uncertain=False
        self.addCleanup(patch.stopall)
        patch.object(pipeline.gemini,'key',return_value='fixture-not-a-key').start()
        patch.object(pipeline.gemini,'call',side_effect=self.provider).start()
        patch.object(pipeline.source_witness,'acquire',return_value=None).start()
        patch.object(pipeline.source_witness,'write_comparison_report').start()
    def provider(self,model,key,prompt,**kwargs):
        audit=kwargs.get('schema_name')=='bhakti_audited_transcript'
        self.calls.append(('audit' if audit else 'transcript',model,prompt))
        if audit:
            self.assertIn('मन',prompt)
            if not self.mixed_language:self.assertIn('तन',prompt)
        response=packet(audit,audit and (self.all_audits_uncertain or self.audit_uncertain and model==self.options.model)
                        or not audit and self.draft_uncertain)
        if self.mixed_language:
            response['metadata']['languages']=['Hindi','Sanskrit']
            lines=response['verified_lines' if audit else 'lines']
            lines[1].update(source_text='मन',roman='man',language='Sanskrit')
            if audit:
                fields=kwargs['response_schema']['properties']['verified_lines']['items']['properties']
                self.assertIn('language',fields,'typed short auditor must be able to return per-line language')
        if self.instrumental:
            response['verified_lines' if audit else 'lines'].insert(1,
                {'id':'attached-instrumental','source_text':'','roman':'','kind':'instrumental',
                 'notes':'Attached instrumental passage','translation_notes':''})
            response['performance_order'].insert(1,{'line_id':'attached-instrumental','occurrence':1,'notes':''})
        if not audit and self.bad_first and model==self.options.model:
            response['performance_order'][0]['line_id']='unknown-source'
        return {'packet':response,'resolved_model':model}
    def transcribe(self):return pipeline.transcript(self.song,{},self.audio,self.options)
    def audit(self,raw):return pipeline.audit_transcript(self.song,raw,self.audio,self.options)
    def test_malformed_first_draft_escalates_only_transcription_before_audit(self):
        self.bad_first=True;raw=self.transcribe();audited=self.audit(raw)
        self.assertEqual([(stage,model) for stage,model,_ in self.calls],
            [('transcript',self.options.model),('transcript',self.options.pro_model),('audit',self.options.model)])
        self.assertEqual([x['line_id'] for x in audited['packet']['performance_order']],['mind','body'])
    def test_uncertain_audit_escalates_without_replaying_valid_first_draft(self):
        raw=self.transcribe();original=(self.song/'.transcription/pipeline/01-transcript.json').read_bytes()
        self.audit_uncertain=True;audited=self.audit(raw)
        self.assertEqual([(stage,model) for stage,model,_ in self.calls],
            [('transcript',self.options.model),('audit',self.options.model),('audit',self.options.pro_model)])
        self.assertFalse(audited['packet']['uncertainties'])
        self.assertEqual((self.song/'.transcription/pipeline/01-transcript.json').read_bytes(),original)
    def test_wellformed_uncertain_draft_can_be_resolved_by_independent_flash_audit(self):
        self.draft_uncertain=True;raw=self.transcribe();self.assertTrue(raw['packet']['uncertainties'])
        audited=self.audit(raw);self.assertFalse(audited['packet']['uncertainties'])
        self.assertEqual([(stage,model) for stage,model,_ in self.calls],
            [('transcript',self.options.model),('audit',self.options.model)])
    def test_terminal_audit_uncertainty_preserves_firstpass_and_resumes_without_calls(self):
        raw=self.transcribe();self.all_audits_uncertain=True
        original=(self.song/'.transcription/pipeline/01-transcript.json').read_bytes()
        with self.assertRaises(routes.UnitUnresolved):self.audit(raw)
        self.assertEqual(len(self.calls),3)
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('resume cannot repay held audit')):
            self.assertEqual(self.transcribe(),raw)
            with self.assertRaises(routes.UnitUnresolved):self.audit(raw)
        self.assertEqual((self.song/'.transcription/pipeline/01-transcript.json').read_bytes(),original)
    def test_changed_rendered_request_context_cannot_accept_stale_audit_or_reset_paid_route(self):
        raw=self.transcribe()
        with patch.object(pipeline.source_witness,'prompt_context',return_value='Witness rendering A'):
            self.audit(raw)
        before=(self.song/'.transcription/pipeline/01-transcript.json').read_bytes()
        with patch.object(pipeline.source_witness,'prompt_context',return_value='Different witness rendering B'), \
             patch.object(pipeline.gemini,'call',side_effect=AssertionError('request drift cannot reset source route')):
            with self.assertRaises(ValueError):self.audit(raw)
        self.assertEqual((self.song/'.transcription/pipeline/01-transcript.json').read_bytes(),before)

    def test_legacy_single_language_draft_is_preserved_and_audited_as_untrusted_without_retranscription(self):
        from test_generic_source_caller import write_json
        target=self.song/'.transcription/pipeline/01-transcript.json'
        write_json(target,{'packet':packet(),'resolved_model':'historical-flash'})
        original=target.read_bytes();raw=self.transcribe();audited=self.audit(raw)
        self.assertEqual([(stage,model) for stage,model,_ in self.calls],[('audit',self.options.model)])
        self.assertIn('untrusted',self.calls[0][2].lower())
        self.assertEqual(target.read_bytes(),original)
        self.assertFalse(audited['packet']['uncertainties'])

    def test_short_mixed_language_schema_and_rows_reach_lexical_routing(self):
        import bhakti_lexical_retrieval as lexical
        self.mixed_language=True;raw=self.transcribe();audited=self.audit(raw)
        self.assertEqual([lexical.line_language(row,audited['packet']['metadata']['languages'])
                          for row in audited['packet']['verified_lines']],['hi','sa'])
        self.assertEqual([row['line_id'] for row in audited['packet']['performance_order']],['mind','body'])

    def test_existing_schema_instrumental_section_remains_without_invented_sung_words(self):
        self.instrumental=True;raw=self.transcribe();audited=self.audit(raw)
        row=next(row for row in audited['packet']['verified_lines'] if row['id']=='attached-instrumental')
        self.assertEqual((row['kind'],row['source_text'],row['roman']),('instrumental','',''))
        self.assertEqual([row['line_id'] for row in audited['packet']['performance_order']],
                         ['mind','attached-instrumental','body'])
        self.assertEqual([(stage,model) for stage,model,_ in self.calls],
            [('transcript',self.options.model),('audit',self.options.model)])

    def test_success_resume_checks_actual_route_candidate_before_cache_acceptance(self):
        raw=self.transcribe();self.audit(raw)
        candidates=list(self.song.rglob('candidate.json'));self.assertTrue(candidates,'source acceptance must retain router evidence')
        value=json.loads(candidates[0].read_text());value['corruption']='changed after acceptance'
        candidates[0].write_text(json.dumps(value))
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('corruption cannot dispatch')):
            with self.assertRaises((ValueError,routes.RunFatal)):
                self.audit(self.transcribe())
    def test_actual_new_intake_caller_uses_shared_bounded_source_operations(self):
        self.bad_first=True
        class ReachedTiming(Exception):pass
        def inspect_timing(song,audited,audio,options):
            self.assertEqual([r['line_id'] for r in audited['packet']['performance_order']],['mind','body'])
            raise ReachedTiming()
        with patch.object(pipeline,'intake',return_value=(self.song,{})), \
             patch.object(pipeline,'detect_youtube_trim',return_value={}), \
             patch.object(pipeline,'require_trim_adoption'),patch.object(pipeline,'apply_lossless_trim'), \
             patch.object(pipeline,'align',side_effect=inspect_timing):
            with self.assertRaises(ReachedTiming):pipeline.run_one({'slug':self.song.name},self.options)
        self.assertEqual([(stage,model) for stage,model,_ in self.calls],
            [('transcript',self.options.model),('transcript',self.options.pro_model),('audit',self.options.model)])

class EmptySourceCallerTests(unittest.TestCase):
    def semantics(self, song, plan, metadata, options, route, deadline):
        from test_sense_decisions import decisions_for
        result=existing_caller.SourceAdoptionCallerTests.semantics(self,song,plan,metadata,options,route,deadline)
        decisions=decisions_for(plan['lines'],metadata['languages'])
        meanings={row['id']: {'मन':'Mind','तन':'Body'}[row['source_text']] for row in plan['lines']}
        for row in result['glosses']['packet']['glosses']:
            row['sense_decisions']=decisions[row['id']]
            row['word_glosses'][0]['gloss']=meanings[row['id']].lower()
            row['grammar_note']='Noun.'
            row['semantic_frame']={key:'Names the '+meanings[row['id']].lower() for key in pipeline.SEMANTIC_FRAME_FIELDS}
        for row in result['translations']['packet']['translations']:
            row['literal_english']=meanings[row['id']]
            row['segments']=[{'text':meanings[row['id']],'word_indices':[0]}]
        return result
    align=existing_caller.SourceAdoptionCallerTests.align
    invoke=existing_caller.SourceAdoptionCallerTests.invoke
    library_row=existing_caller.SourceAdoptionCallerTests.library_row
    def setUp(self):
        existing_caller.SourceAdoptionCallerTests.setUp(self)
        self.reader.update(SONG_LINES={},SONG_SEQUENCE=[],SONG_TIMINGS=[])
        for root in (self.root,self.workspace):js(root/'songs'/self.slug/'data.js',self.reader)
        self.reader=contract.load_data(self.song/'data.js');self.original=(self.song/'data.js').read_bytes()
        self.calls=[];self.audit_uncertain=False
        self.options.unit_deadline_at=self.deadline
        patch.object(pipeline.source_witness,'acquire',return_value=None).start()
        patch.object(pipeline.source_witness,'write_comparison_report').start()
    def provider(self,model,key,prompt,**kwargs):
        schema=kwargs.get('schema_name')
        if schema=='bhakti_translation_review':
            return existing_caller.SourceAdoptionCallerTests.provider(self,model,key,prompt,**kwargs)
        audit=schema=='bhakti_audited_transcript';self.calls.append(('audit' if audit else 'transcript',model))
        return {'packet':packet(audit,self.audit_uncertain and audit),'resolved_model':model}
    def test_inventory_detects_empty_lyrics_and_actual_runner_reaches_shared_bootstrap_without_audio_flags(self):
        import bhakti_library_pass as library
        self.library_row()  # Establish actual committed source population.
        row=library.build_inventory(self.root,state_dir=self.library_state,flags={})['songs'][0]
        self.assertFalse(row['flags'])
        self.assertIn('audio-review',row['plannedStages'],'known empty lyrics must automatically enter source reconstruction')
        result=library.execute_song(self.root,row,self.library_state,self.options,self.deadline)
        self.assertEqual(result['status'],'accepted',result)
        self.assertTrue(result['publicationEligible'])
        self.assertEqual(self.calls,[('transcript',self.options.model),('audit',self.options.model)])
        self.assertEqual({line['source'] for line in result['source']['reader']['SONG_LINES'].values()},{'मन','तन'})
        self.assertEqual((self.song/'data.js').read_bytes(),self.original)

    def test_empty_reader_uses_shared_source_stages_then_existing_private_generation(self):
        result=self.invoke();self.assertEqual(result['status'],'accepted',result)
        self.assertEqual(self.calls,[('transcript',self.options.model),('audit',self.options.model)])
        self.assertEqual(len(self.fresh_targets),1);self.assertEqual(len(self.fresh_targets[0]),2)
        self.assertEqual({r['source'] for r in result['reader']['SONG_LINES'].values()},{'मन','तन'})
        self.assertEqual((self.song/'data.js').read_bytes(),self.original)
        self.assertEqual(contract.load_data(self.workspace/'songs'/self.slug/'data.js'),result['reader'])
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('accepted source must resume')):
            self.assertEqual(self.invoke(),result)
    def test_empty_reader_audit_failure_holds_before_semantics_timing_or_generation(self):
        self.audit_uncertain=True;result=self.invoke()
        self.assertEqual(result['status'],'unresolved');self.assertFalse(result['publicationEligible'])
        self.assertEqual(len(self.calls),3);self.semantic.assert_not_called();self.timing.assert_not_called()
        self.assertEqual((self.song/'data.js').read_bytes(),self.original)
        self.assertEqual((self.workspace/'songs'/self.slug/'data.js').read_bytes(),self.original)
    def test_malformed_nonempty_reader_cannot_be_discarded_as_missing_source(self):
        self.reader['SONG_LINES']={'owner':{'english':'OWNER ENGLISH','source':'','roman':''}}
        for root in (self.root,self.workspace):js(root/'songs'/self.slug/'data.js',self.reader)
        result=self.invoke();self.assertEqual(result['status'],'unresolved')
        self.assertEqual(self.calls,[]);self.semantic.assert_not_called();self.timing.assert_not_called()

if __name__=='__main__':unittest.main()

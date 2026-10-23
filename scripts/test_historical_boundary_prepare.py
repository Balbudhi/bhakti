"""Next caller contract: real private media, source adapter, files and readers.

The existing source caller's explicit synthetic hearing/timing boundaries are
reused. They are accepted fixture preconditions, NOT proof of acoustic quality.
This slice verifies private preparation only. Installation/clock qualification
remain explicit outstanding obligations, with separate private contract tests.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
import audit_bhakti_contract as contract
import bhakti_pipeline as p
import bhakti_library_source_pass as source
import bhakti_library_pass as library
import test_source_adoption_caller_design as source_tests
from test_generic_source_caller import js,write_json
from test_boundary_application import create_audio,accepted_crop


def snapshot(directory):
    return {str(path.relative_to(directory)):path.read_bytes() for path in directory.rglob('*') if path.is_file()}


class HistoricalBoundaryPreparation(unittest.TestCase):
    def provider(self, model, key, prompt, **kwargs):
        if kwargs['schema_name'] == 'bhakti_translation_review':
            self.translation_review_prompts.append(prompt)
            if self.fail_context_review:
                raise RuntimeError('fixture changed-context English review unavailable')
        remove=self.remove_source
        if kwargs['schema_name']=='bhakti_segment_audit' and p.gemini.duration_seconds(Path(kwargs['audio']))<3:
            self.remove_source=False  # Synthetic original-edge hearing includes the excluded line.
        try:return source_tests.SourceAdoptionCallerTests.provider(self,model,key,prompt,**kwargs)
        finally:self.remove_source=remove


    semantics=source_tests.SourceAdoptionCallerTests.semantics


    def setUp(self):
        self.translation_review_prompts=[];self.fail_context_review=False
        source_tests.SourceAdoptionCallerTests.setUp(self)
        (self.song/'audio.m4a').unlink();create_audio(self.song)
        expression='0.02*sin(2*PI*(220*t+11*t*t))+if(between(t,6,6.0001),0.8,0)+if(between(t,20,20.0001),0.6,0)'
        for name,codec in [('audio.m4a','aac'),('audio.webm','libopus')]:
            subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i',
                f"aevalsrc='{expression}':s=48000:d=30",'-c:a',codec,str(self.song/name)],check=True)
        self.duration=p.gemini.duration_seconds(p.preferred_listener_audio(self.song))
        self.reader['SONG_TIMINGS']=[{'start':value,'end':end} for value,end in [(5.,12.),(12.,20.),(20.,self.duration)]]
        self.reader['SONG_META']['audioSources']=p.listener_audio_sources(self.song)
        js(self.song/'data.js',self.reader)
        for name in ['01-transcript.json','02-transcript-audit.json','03-timing.json','04-glosses.json','05-translation.json','song-packet.json']:
            write_json(self.song/'.transcription/pipeline'/name,{'original_fixture_artifact':name})
        shutil.rmtree(self.workspace);shutil.copytree(self.root,self.workspace)
        self.boundary=accepted_crop(self.song,start=2.137,end=28.341)
        self.options.source_coverage_requested=False
        self.options.source_requested_stages=['focused-audio-review']
        self.options.unit_deadline_at=self.deadline
        self.options.boundary_route_dir=self.routes
        self.original_files=snapshot(self.song)
        self.owner_registry=(self.root/'data/editorial_baselines.json').read_bytes()
        self.source_calls=[];self.real_source=source.run_source_candidate


    def align(self,song,audited,audio,options):
        # Only timing measurement is synthetic; actual source reconciliation,
        # confirmation router, receipts, generation and parsing remain real.
        self.assertTrue(getattr(options,'timing_source_adoption',None))
        self.assertIn('audio_transform',options.timing_source_adoption,
            'accepted source lineage must explicitly bind changed media, never relax the old guard')
        rows=p.display_occurrences(audited['packet']);duration=p.gemini.duration_seconds(audio)
        points=[2.+index*6. for index in range(len(rows))]
        return {'sequence':[{**row,'start':point,'end':points[index+1] if index+1<len(points) else duration}
                            for index,(row,point) in enumerate(zip(rows,points))],
                'uncertain_occurrence_ids':[],'validation_errors':[]}


    def prepare(self):
        operation=getattr(p,'prepare_historical_boundary_candidate',None)
        self.assertTrue(callable(operation),'automatic historical private preparation is missing')
        def source_call(**kwargs):
            self.source_calls.append(kwargs)
            self.assertEqual(Path(kwargs['root']).resolve(),self.root.resolve(),
                'do not replace the authoritative original root with the cropped workspace')
            self.assertEqual(kwargs['reader'],self.reader)
            staged=Path(kwargs['workspace'])/'songs'/self.slug
            old_audio=p.preferred_listener_audio(self.song);new_audio=p.preferred_listener_audio(staged)
            self.assertNotEqual(source.file_hash(old_audio),source.file_hash(new_audio),
                'membership review must hear the prepared cropped candidate, not the old input')
            self.assertIsNotNone(getattr(kwargs['options'],'source_audio_transform',None),
                'source admission must validate the staged hash change explicitly too')
            declaration=kwargs['options'].source_audio_transform
            transform_path=Path(declaration['path'])
            self.assertEqual(source.file_hash(transform_path),declaration['sha256'])
            transform=json.loads(transform_path.read_text())
            self.assertEqual(transform['before']['audio_sha256'],source.file_hash(old_audio))
            self.assertEqual(transform['after']['audio_sha256'],source.file_hash(new_audio))
            return self.real_source(**kwargs)
        with mock.patch.object(source,'run_source_candidate',side_effect=source_call):
            result=operation(self.song,self.boundary,workspace=self.workspace,options=self.options)
        return result


    def assert_prepared(self,result):
        self.assertEqual(result['status'],'prepared',result)
        self.assertFalse(result['publicationEligible'],'private preparation is not public commit authorization')
        declaration=result['manifest'];path=Path(declaration['path'])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),declaration['sha256'])
        self.assertEqual(snapshot(self.song),self.original_files)
        target=Path(result['candidate_song_dir'])
        candidate=contract.load_data(target/'data.js')
        self.assertEqual(candidate['SONG_LINES'],self.reader['SONG_LINES'])
        self.assertEqual((self.root/'data/editorial_baselines.json').read_bytes(),self.owner_registry)
        return target,candidate


    def test_prepare_uses_existing_source_consumer_and_archives_all_originals_without_public_changes(self):
        prepared=self.prepare();target,candidate=self.assert_prepared(prepared)
        self.assertTrue(self.source_calls,'must use accepted source engine rather than hand-editing rows')
        self.assertTrue(self.hearings,'source membership cannot be granted by old timestamp subtraction')
        self.assertEqual(self.fresh_targets,[],'unchanged source/English must not be retransmitted for translation')
        self.assertEqual(self.translation_review_prompts,[],'pure timing repair may retain accepted English')
        archive=Path(prepared['original_archive'])
        for name,content in self.original_files.items():self.assertEqual((archive/name).read_bytes(),content)
        self.assertNotEqual((target/'audio.m4a').read_bytes(),self.original_files['audio.m4a'])
        audited=p.read_packet(target/'.transcription/pipeline/02-transcript-audit.json')['packet']
        expanded=[event['ref'] for event in candidate['SONG_SEQUENCE'] for _ in range(event['repeats'])]
        self.assertEqual([row['line_id'] for row in audited['performance_order']],expanded)
        timing=p.read_packet(target/'.transcription/pipeline/03-timing.json')
        self.assertEqual(candidate['SONG_TIMINGS'],[{'start':round(row['start'],3),'end':round(row['end'],3)} for row in timing['sequence']])
        for name in ['01-transcript.json','02-transcript-audit.json','03-timing.json','04-glosses.json','05-translation.json','song-packet.json']:
            self.assertNotIn('original_fixture_artifact',(target/'.transcription/pipeline'/name).read_text())


    def test_owner_english_is_preserved_on_same_population_and_conflict_holds_before_commit(self):
        registry={'version':1,'songs':{self.slug:{'policy':'preserve_english','englishSha256':'a'*64,
            'plainEnglishByLine':{lid:'OWNER ENGLISH' for lid in self.reader['SONG_LINES']}}}}
        write_json(self.root/'data/editorial_baselines.json',registry);write_json(self.workspace/'data/editorial_baselines.json',registry)
        self.owner_registry=(self.root/'data/editorial_baselines.json').read_bytes()
        self.assert_prepared(self.prepare())
        # A different reviewed interval/source finding gets a fresh PRIVATE
        # workspace, preserving the first prepared evidence and original files.
        self.remove_source=True;self.workspace=self.base/'protected-removal';shutil.copytree(self.root,self.workspace)
        self.options.boundary_route_dir=self.base/'protected-removal-routes'
        result=self.prepare()
        self.assertEqual(result['status'],'unresolved')
        self.assertFalse(result['publicationEligible'])
        self.assertTrue(result['issues'],'protected removal or out-of-scope source conflict must remain explicit')
        self.assertEqual(snapshot(self.song),self.original_files)
        self.assertEqual((self.root/'data/editorial_baselines.json').read_bytes(),self.owner_registry)


    def unrelated_prefix_fixture(self):
        # Accepted synthetic acoustic precondition: the first spoken occurrence
        # is unrelated; two subsequent performed lines are retained. No fixture
        # claim of actual lyric recognition is made for generated test audio.
        self.reader['SONG_SEQUENCE']=[{'ref':'line-1','section':'spoken','repeats':1},
            {'ref':'line-0','section':'verse','repeats':1},
            {'ref':'line-2','section':'verse','repeats':1}]
        self.reader['SONG_TIMINGS']=[{'start':.5,'end':5.},
            {'start':5.,'end':20.},{'start':20.,'end':self.duration}]
        js(self.song/'data.js',self.reader)
        shutil.rmtree(self.workspace);shutil.copytree(self.root,self.workspace)
        self.original_files=snapshot(self.song)
        self.remove_source=True


    def test_unprotected_unrelated_prefix_removal_keeps_retained_english_and_rechecks_whole_candidate(self):
        self.unrelated_prefix_fixture()
        with mock.patch.object(library,'audit_current_reader',wraps=library.audit_current_reader) as review, \
             mock.patch.object(library,'repair_current_reader',wraps=library.repair_current_reader) as gate:
            prepared=self.prepare()
        self.assertEqual(prepared['status'],'prepared',prepared)
        self.assertFalse(prepared['publicationEligible'])
        target=Path(prepared['candidate_song_dir']);candidate=contract.load_data(target/'data.js')
        self.assertEqual(list(candidate['SONG_LINES']),['line-0','line-2'])
        self.assertEqual([row['ref'] for row in candidate['SONG_SEQUENCE']],['line-0','line-2'])
        for lid in candidate['SONG_LINES']:
            self.assertEqual(candidate['SONG_LINES'][lid],self.reader['SONG_LINES'][lid])
        self.assertGreaterEqual(len(self.hearings),2,'removal needs independent source confirmation')
        self.assertEqual(self.fresh_targets,[],'deletion does not require reconstructing retained glosses')
        self.assertTrue(self.translation_review_prompts,'changed context still needs full candidate English review')
        review.assert_called_once();gate.assert_called_once()
        self.assertEqual(review.call_args.args[0],candidate)
        self.assertEqual(gate.call_args.args[0],candidate)
        self.assertEqual(snapshot(self.song),self.original_files)
        archive=Path(prepared['original_archive'])
        for name,content in self.original_files.items():self.assertEqual((archive/name).read_bytes(),content)


    def test_source_acceptance_cannot_bypass_failed_changed_context_english_review(self):
        self.unrelated_prefix_fixture();self.fail_context_review=True
        result=self.prepare()
        self.assertEqual(result['status'],'unresolved',result)
        self.assertFalse(result['publicationEligible'])
        self.assertTrue(self.translation_review_prompts,'must actually reach final English review')
        self.assertEqual(snapshot(self.song),self.original_files)
        self.assertFalse((self.song/'.transcription/trim-applied.json').exists())


    def test_prepared_resume_revalidates_without_model_calls_or_recropping(self):
        prepared=self.prepare();self.assert_prepared(prepared)
        with mock.patch.object(p.gemini,'call',side_effect=AssertionError('resume must not repay')), \
             mock.patch.object(p,'apply_lossless_trim',side_effect=AssertionError('valid prepared audio must be reused')):
            resumed=self.prepare()
        self.assertEqual(resumed,prepared)
        self.assertEqual(snapshot(self.song),self.original_files)

    def test_completed_preparation_rejects_changed_candidate_archive_or_source_receipt(self):
        prepared=self.prepare();target,_=self.assert_prepared(prepared)
        manifest=json.loads(Path(prepared['manifest']['path']).read_text())
        for path in (target/'data.js',Path(prepared['original_archive'])/'audio.m4a',
                     Path(manifest['source_result']['path'])):
            with self.subTest(path=str(path)):
                raw=path.read_bytes();path.write_bytes(raw+b' ')
                try:
                    with mock.patch.object(p.gemini,'call',side_effect=AssertionError('tamper cannot buy repair')):
                        result=self.prepare()
                    self.assertEqual(result['status'],'unresolved',result)
                    self.assertFalse(result['publicationEligible'])
                finally:path.write_bytes(raw)
        self.assertEqual(snapshot(self.song),self.original_files)

    def test_changed_original_cannot_reuse_a_previous_private_workspace(self):
        self.assert_prepared(self.prepare())
        path=self.song/'data.js';path.write_bytes(path.read_bytes()+b' ')
        changed=snapshot(self.song)
        with mock.patch.object(p.gemini,'call',side_effect=AssertionError('stale workspace cannot dispatch')):
            result=self.prepare()
        self.assertEqual(result['status'],'unresolved',result)
        self.assertFalse(result['publicationEligible'])
        self.assertEqual(snapshot(self.song),changed)

    def test_completed_preparation_does_not_ignore_changed_source_review_scope(self):
        self.assert_prepared(self.prepare())
        self.options.source_review_flags={'audio':True,'line_ids':['line-1']}
        with mock.patch.object(p.gemini,'call',side_effect=AssertionError('changed scope needs a fresh attempt')):
            result=self.prepare()
        self.assertEqual(result['status'],'unresolved',result)
        self.assertFalse(result['publicationEligible'])

    def test_interrupted_private_crop_recovers_before_any_source_call(self):
        target=self.workspace/'songs'/self.slug
        real=os.replace;fired=[]
        def interrupt(src,dst,*args,**kwargs):
            value=real(src,dst,*args,**kwargs)
            if Path(dst).resolve()==(target/'audio.webm').resolve() and not fired:
                fired.append(True);raise KeyboardInterrupt('private first-native cut')
            return value
        with mock.patch.object(os,'replace',side_effect=interrupt), \
             mock.patch.object(p.gemini,'call',side_effect=AssertionError('crop is not ready for source review')):
            with self.assertRaises(KeyboardInterrupt):self.prepare()
        self.assertEqual(fired,[True])
        self.assertEqual(snapshot(self.song),self.original_files)
        self.assertEqual(p.read_packet(target/'.transcription/trim-applied.json')['status'],'pending')
        self.assert_prepared(self.prepare())

    def test_private_preparation_remains_blocked_at_actual_generation_entrypoints(self):
        prepared=self.prepare();target,_=self.assert_prepared(prepared)
        with self.assertRaisesRegex(RuntimeError,'pending boundary adoption'):
            p.require_completed_boundary_transaction(target)
        with self.assertRaisesRegex(RuntimeError,'pending boundary adoption'):
            p.hydrate_pipeline_artifacts(target/'.transcription/pipeline')
        with self.assertRaisesRegex(RuntimeError,'pending boundary adoption'):
            p.generate(target,{}, {}, {}, {}, {}, {},write_catalogue_after=False)

    def test_interrupted_preparation_cannot_extend_its_original_deadline(self):
        import bhakti_historical_boundary as historical
        self.unrelated_prefix_fixture()
        original_deadline=self.options.unit_deadline_at
        with mock.patch.object(library,'audit_current_reader',side_effect=KeyboardInterrupt('before context review')):
            with self.assertRaises(KeyboardInterrupt):self.prepare()
        self.assertFalse(self.translation_review_prompts)
        self.options.unit_deadline_at=original_deadline+120
        with mock.patch.object(historical.time,'time',return_value=original_deadline+1), \
             mock.patch.object(p.gemini,'call',side_effect=AssertionError('expired preparation cannot start a new stage')):
            result=self.prepare()
        self.assertEqual(result['status'],'unresolved',result)
        self.assertRegex(json.dumps(result['issues']),'(?i)deadline')
        self.assertEqual(snapshot(self.song),self.original_files)

    def test_completed_read_only_resume_survives_expired_deadline(self):
        import bhakti_historical_boundary as historical
        prepared=self.prepare();self.assert_prepared(prepared)
        before=snapshot(self.workspace)
        self.options.unit_deadline_at-=30
        with mock.patch.object(historical.time,'time',return_value=self.options.unit_deadline_at+31), \
             mock.patch.object(p.gemini,'call',side_effect=AssertionError('completed resume is read-only')):
            self.assertEqual(self.prepare(),prepared)
        self.assertEqual(snapshot(self.workspace),before)

    def assert_route_tamper_rejected(self, prepared, route):
        import bhakti_model_routes as routes
        for path in (route.parent/'flash/candidate.json',route.parent/'accepted-result.json'):
            original=path.read_bytes()
            changed=json.loads(original);changed['changed_raw_evidence']=True
            path.write_text(json.dumps(changed))
            try:
                with self.assertRaises(routes.RunFatal):routes.read_unit_cache(route)
                with mock.patch.object(p.gemini,'call',side_effect=AssertionError('corruption cannot purchase repair')):
                    try:result=self.prepare()
                    except routes.RunFatal:pass
                    else:self.assertEqual(result['status'],'unresolved',result)
            finally:path.write_bytes(original)
        with mock.patch.object(p.gemini,'call',side_effect=AssertionError('restored evidence must reuse')):
            self.assertEqual(self.prepare(),prepared)

    def test_completed_preparation_revalidates_raw_pre_review_route_evidence(self):
        self.unrelated_prefix_fixture()
        reviews=[]
        def provider(model,key,prompt,**kwargs):
            if kwargs['schema_name']=='bhakti_translation_review':
                reviews.append(model)
                if len(reviews)==1:return {'packet':{'reviews':[]}}
            return self.provider(model,key,prompt,**kwargs)
        with mock.patch.object(p.gemini,'call',side_effect=provider):prepared=self.prepare()
        self.assertEqual(prepared['status'],'prepared',prepared)
        self.assertEqual(reviews,[self.options.model,self.options.pro_model])
        manifest=json.loads(Path(prepared['manifest']['path']).read_text())
        semantic=json.loads(Path(manifest['semantic_result']['path']).read_text())
        self.assertEqual(len(semantic['pre_review']['finding_snapshot']['reviews']),2)
        self.assert_route_tamper_rejected(prepared,Path(semantic['pre_review']['finding_route_state_path']))

    def test_completed_preparation_revalidates_actual_targeted_repair_route(self):
        from test_library_execution import review
        from test_sense_decisions import decisions_for
        self.reader['SONG_LINES']['line-0']['english']='{0:body}'
        self.reader['SONG_LINES']['line-0']['words'][0]['gloss']='mind'
        self.unrelated_prefix_fixture()
        issue={'kind':'english_realization','target_line_ids':['line-0'],
            'references':[{'line_id':'line-0','domain':'word_glosses','word_indices':[0],'source_quote':'मन'}],
            'explanation':'body conflicts with mind','evidence':'मन and the retained gloss mean mind',
            'hold_reason':'','needed_evidence':''}
        def block(prompt,marker):return json.JSONDecoder().raw_decode(prompt.split(marker,1)[1].lstrip())[0]
        def provider(model,key,prompt,**kwargs):
            kind=kwargs['schema_name']
            if kind=='bhakti_segment_audit':return self.provider(model,key,prompt,**kwargs)
            if kind=='bhakti_translation_review':
                rows=[]
                for item in block(prompt,'EVIDENCE:\n'):
                    bad=item['draft']['literal_english']=='body'
                    row=review(item['source']['id'],[issue] if bad else [])
                    obligations=block(prompt,'FINDING OBLIGATIONS FOR THIS REPAIR:\n')
                    if obligations and not bad:
                        row['finding_dispositions']=[{'finding_id':f['finding_id'],'status':'repaired',
                            'source_quote':'मन','explanation':'mind now agrees with the retained source gloss'} for f in obligations]
                    rows.append(row)
                return {'packet':{'reviews':rows}}
            if 'word_gloss' in kind:
                lines=block(prompt,'TARGET LYRICS (return these IDs only):\n')
                decisions=decisions_for(lines,['Hindi'])
                return {'packet':{'glosses':[{'id':line['id'],
                    'word_glosses':[{'roman':'man','gloss':'mind','concept_key':'','preserve_in_english':False}],
                    'semantic_frame':{field:'' for field in p.SEMANTIC_FRAME_FIELDS},
                    'grammar_note':'Noun.','uncertainty':'','sense_decisions':decisions[line['id']]} for line in lines]}}
            self.assertEqual(kind,'bhakti_literal_translation')
            return {'packet':{'translations':[{'id':'line-0','literal_english':'mind',
                'segments':[{'text':'mind','word_indices':[0]}],
                'fidelity':{'agency_and_image_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[]},
                'human_review_recommended':False,'material_alternatives':[],'choice_note':'','uncertainty':''}]}}
        with mock.patch.object(p.gemini,'call',side_effect=provider):prepared=self.prepare()
        self.assertEqual(prepared['status'],'prepared',prepared)
        candidate=contract.load_data(Path(prepared['candidate_song_dir'])/'data.js')
        self.assertEqual(candidate['SONG_LINES']['line-0']['english'],'{0:mind}')
        self.assertEqual(snapshot(self.song),self.original_files)
        repair_routes=[path for path in self.routes.rglob('route-state.json')
            if json.loads(path.read_text())['unit_id']==self.slug+':targeted-semantics']
        self.assertEqual(len(repair_routes),1)
        self.assert_route_tamper_rejected(prepared,repair_routes[0])

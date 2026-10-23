"""Actual source caller admission for explicitly measured private cropped media.

Only synthetic hearing/align boundaries are replaced; original/staged bytes,
existing source reconciliation, router receipts, and generated readers are real.
This does NOT qualify browser/canonical timing reuse.
"""
import copy
import json
import shutil
import subprocess
from pathlib import Path
import unittest
from unittest import mock
import bhakti_pipeline as p
import bhakti_library_source_pass as source
import test_source_adoption_caller_design as source_tests
from test_generic_source_caller import write_json,js
from test_boundary_application import create_audio,accepted_crop

def snapshot(directory):
    return {str(path.relative_to(directory)):path.read_bytes() for path in directory.rglob("*") if path.is_file()}


class BoundaryTransformAdmission(unittest.TestCase):
    def provider(self,model,key,prompt,**kwargs):
        if kwargs['schema_name']=='bhakti_segment_audit':
            self.audio_requests.append({'original_edge':self.original_edge_mode,
                'model':model,'duration':p.gemini.duration_seconds(Path(kwargs['audio'])),'prompt':prompt})
        remove=self.remove_source
        if self.original_edge_mode:self.remove_source=False
        try:return source_tests.SourceAdoptionCallerTests.provider(self,model,key,prompt,**kwargs)
        finally:self.remove_source=remove
    semantics=source_tests.SourceAdoptionCallerTests.semantics

    def align(self,song,audited,audio,options):
        self.assertIn('audio_transform',options.timing_source_adoption)
        rows=p.display_occurrences(audited['packet']);duration=p.gemini.duration_seconds(audio)
        points=[2.+index*6. for index in range(len(rows))]
        return {'sequence':[{**row,'start':point,'end':points[index+1] if index+1<len(points) else duration}
            for index,(row,point) in enumerate(zip(rows,points))],
            'uncertain_occurrence_ids':[],'validation_errors':[]}

    def setUp(self):
        self.audio_requests=[];self.original_edge_mode=False
        source_tests.SourceAdoptionCallerTests.setUp(self)
        (self.song/'audio.m4a').unlink();create_audio(self.song)
        self.duration=p.gemini.duration_seconds(p.preferred_listener_audio(self.song))
        self.reader['SONG_TIMINGS']=[{'start':start,'end':end} for start,end in [(5.,12.),(12.,20.),(20.,self.duration)]]
        self.reader['SONG_META']['audioSources']=p.listener_audio_sources(self.song)
        js(self.song/'data.js',self.reader)
        for name in ['01-transcript.json','02-transcript-audit.json','03-timing.json','04-glosses.json','05-translation.json','song-packet.json']:
            write_json(self.song/'.transcription/pipeline'/name,{'original_fixture_artifact':name})
        shutil.rmtree(self.workspace);shutil.copytree(self.root,self.workspace)
        self.options.unit_deadline_at=self.deadline
        self.target=self.workspace/'songs'/self.slug
        # Use the independently qualified impulse/chirp witness fixture; a
        # purely periodic tone can remain decoder-history ambiguous in Opus.
        expression='0.02*sin(2*PI*(220*t+11*t*t))+if(between(t,6,6.0001),0.8,0)+if(between(t,20,20.0001),0.6,0)'
        for name,codec in [('audio.m4a','aac'),('audio.webm','libopus')]:
            subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i',
                f"aevalsrc='{expression}':s=48000:d=30",'-c:a',codec,str(self.song/name)],check=True)
            shutil.copy2(self.song/name,self.target/name)
        self.boundary=accepted_crop(self.song,start=2.137,end=28.341)
        self.original_files=snapshot(self.song)
        p.apply_lossless_trim(self.target,self.boundary)
        native={}
        for name in ['audio.m4a','audio.webm']:
            result=p.measure_boundary_timebase(self.song/name,self.target/name,
                requested_start=self.boundary['trim_start'])
            self.assertEqual(result['status'],'verified',result)
            native[name]={'before':{'path':str(self.song/name),'sha256':source.file_hash(self.song/name)},
                'after':{'path':str(self.target/name),'sha256':source.file_hash(self.target/name)},'measurement':result}
        original_audio=p.preferred_listener_audio(self.song);candidate_audio=p.preferred_listener_audio(self.target)
        original_trim=self.song/'.transcription/trim-applied.json'
        target_trim=self.target/'.transcription/trim-applied.json'
        transform={'version':1,'kind':'boundary-timebase','status':'verified',
            'before':{'audio_sha256':source.file_hash(original_audio),
                'trim_sha256':source.file_hash(original_trim) if original_trim.exists() else None,
                'trim':p.read_packet(original_trim) or {},
                'reader_sha256':source.file_hash(self.song/'data.js'),'duration_seconds':self.duration},
            'after':{'audio_sha256':source.file_hash(candidate_audio),'trim_sha256':source.file_hash(target_trim),
                'trim':p.read_packet(target_trim),
                'duration_seconds':p.gemini.duration_seconds(candidate_audio)},
            'boundary':copy.deepcopy(self.boundary),'native':native,
            'timing_basis':{'status':'unresolved','reason':'native decoded evidence does not bind legacy browser/model origin'}}
        self.transform=self.base/'audio-transform.json';write_json(self.transform,transform)
        self.declaration={'path':str(self.transform),'sha256':source.file_hash(self.transform)}
        self.options.source_audio_transform=self.declaration
        self.options.source_requested_stages=['audio-review']
        self.options.source_coverage_requested=False

    def invoke(self):
        return source.run_source_candidate(root=self.root,slug=self.slug,reader=self.reader,
            workspace=self.workspace,route_dir=self.routes,options=self.options,deadline_at=self.deadline)

    def preserve_original_archive(self):
        archive=self.base/'original-archive'/self.slug
        shutil.copytree(self.song,archive)
        value=json.loads(self.transform.read_text())
        paths=['data.js','.transcription/trim-applied.json',
            '.transcription/pipeline/01-transcript.json',
            '.transcription/pipeline/02-transcript-audit.json',
            '.transcription/pipeline/03-timing.json',
            str(p.source_witness.cache_path(archive).relative_to(archive)),*value['native']]
        value['before']['archive_files']={name:source.file_hash(archive/name)
            if (archive/name).is_file() else None for name in paths}
        for name,row in value['native'].items():row['before']['path']=str(archive/name)
        self.rewrite_transform(value)
        return archive

    def test_archived_original_receipt_survives_live_install_with_edge_deletion(self):
        self.prefix_reader();membership=self.original_membership()
        value=json.loads(self.transform.read_text());value['original_edge_membership']=[membership]
        self.rewrite_transform(value);archive=self.preserve_original_archive()
        before=snapshot(archive)
        with mock.patch.object(source,'plan_audio_review',wraps=source.plan_audio_review) as planner:
            result=self.invoke()
        self.assertEqual(result['status'],'accepted',result)
        planned_artifacts=[item for call in planner.call_args_list
            for item in call.kwargs['source_evidence']['artifacts'].values() if item]
        self.assertTrue(planned_artifacts)
        self.assertTrue(all(Path(item['path']).resolve().is_relative_to(archive.resolve())
            for item in planned_artifacts),planned_artifacts)
        self.assertEqual(list(result['reader']['SONG_LINES']),['line-0','line-2'])
        # Install into real live paths, then replay the saved receipt. The
        # original bytes survive only in the archive; no hearing can be bought.
        shutil.rmtree(self.song);shutil.copytree(self.target,self.song)
        with mock.patch.object(p.gemini,'call',side_effect=AssertionError('replay cannot dispatch')):
            source.verify_source_result_evidence(result,self.reader)
        self.assertEqual(snapshot(archive),before)
        archived_artifact=archive/'.transcription/pipeline/01-transcript.json'
        archived_artifact.write_bytes(archived_artifact.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'(?i)(archive|snapshot|changed)'):
            source.verify_source_result_evidence(result,self.reader)

    def test_archived_transform_requires_unchanged_live_input_before_dispatch(self):
        archive=self.preserve_original_archive()
        for path in (self.song/'audio.webm',self.song/'data.js',
                     self.song/'.transcription/pipeline/01-transcript.json',archive/'audio.m4a'):
            with self.subTest(path=str(path)):
                raw=path.read_bytes();path.write_bytes(raw+b' ')
                try:
                    with mock.patch.object(p.gemini,'call',side_effect=AssertionError('drift cannot dispatch')):
                        result=self.invoke()
                    self.assertEqual(result['status'],'unresolved',result)
                    self.assertFalse(result['publicationEligible'])
                finally:path.write_bytes(raw)

    def test_archived_transform_cannot_omit_support_snapshot(self):
        self.preserve_original_archive()
        value=json.loads(self.transform.read_text());del value['before']['archive_files']
        self.rewrite_transform(value)
        with mock.patch.object(p.gemini,'call',side_effect=AssertionError('unbound archive cannot dispatch')):
            result=self.invoke()
        self.assertEqual(result['status'],'unresolved',result)
        self.assertFalse(result['publicationEligible'])

    def review_removed_edges(self,removed):
        import bhakti_boundary_adoption as boundary
        order=source.source_draft(self.reader)['performance_order']
        next_index=0;lineage=[]
        for i in range(len(order)):
            lineage.append({'old_index':i,'new_index':None if i in removed else next_index})
            if i not in removed:next_index+=1
        return boundary.review_boundary_memberships(self.declaration,self.song,self.target,
            self.reader,{'status':'proposed','occurrence_lineage':lineage},options=self.options,
            route_dir=self.routes/'automatic-memberships',deadline_at=self.deadline)

    def test_automatic_archived_edge_proof_drives_existing_caller_and_resumes_free(self):
        self.prefix_reader();archive=self.preserve_original_archive()
        self.original_edge_mode=True
        try:proof=self.review_removed_edges({0})
        finally:self.original_edge_mode=False
        self.assertEqual(proof['status'],'observed',proof)
        self.assertEqual(len(proof['memberships']),1)
        self.assertEqual(proof['memberships'][0]['old_expanded_indices'],[0])
        self.assertEqual(len(self.audio_requests),2,'one hearing and one independent confirmation')
        self.assertTrue(all(row['duration']<=self.boundary['trim_start']+.1 for row in self.audio_requests))
        with mock.patch.object(p.gemini,'call',side_effect=AssertionError('edge resume cannot repay')):
            self.assertEqual(self.review_removed_edges({0}),proof)
        value=json.loads(self.transform.read_text());value['original_edge_membership']=proof['memberships']
        self.rewrite_transform(value)
        result=self.invoke();self.assertEqual(result['status'],'accepted',result)
        self.assertEqual(list(result['reader']['SONG_LINES']),['line-0','line-2'])
        self.assertTrue((archive/'audio.webm').is_file())

    def test_automatic_edge_proof_handles_both_ends_without_interior_audio(self):
        self.prefix_reader()
        self.original_edge_mode=True
        try:proof=self.review_removed_edges({0,2})
        finally:self.original_edge_mode=False
        self.assertEqual(proof['status'],'observed',proof)
        self.assertEqual([(r['edge'],r['old_expanded_indices']) for r in proof['memberships']],
            [('start',[0]),('end',[2])])
        self.assertEqual(len(self.audio_requests),4)
        self.assertTrue(all(r['duration']<3 for r in self.audio_requests))

    def test_automatic_edge_proof_rejects_nonedge_and_full_deletion_without_payment(self):
        self.prefix_reader()
        for removed in ({1},{0,1,2}):
            with self.subTest(removed=removed),mock.patch.object(p.gemini,'call',
                    side_effect=AssertionError('invalid removal cannot dispatch')):
                with self.assertRaisesRegex(ValueError,'(?i)(edge|interior|entire|retained)'):
                    self.review_removed_edges(removed)
        with mock.patch.object(p.gemini,'call',side_effect=AssertionError('no deletion needs no hearing')):
            self.assertEqual(self.review_removed_edges(set()),
                {'status':'observed','memberships':[],'issues':[]})

    def test_automatic_edge_proof_does_not_accept_different_original_hearing(self):
        self.reader['SONG_SEQUENCE'][1]['repeats']=1
        js(self.song/'data.js',self.reader);js(self.target/'data.js',self.reader)
        value=json.loads(self.transform.read_text());value['before']['reader_sha256']=source.file_hash(self.song/'data.js')
        self.rewrite_transform(value);self.replace_source=True
        proof=self.review_removed_edges({0})
        self.assertEqual(proof['status'],'unresolved',proof)
        self.assertEqual(proof['memberships'],[])
        self.assertTrue(proof['issues'])
        self.assertEqual(len(self.audio_requests),1,'a mismatched original hearing is not a deletion proof')
        issue=proof['issues'][0]
        self.assertNotEqual(issue['expected_order'],issue['observed_order'])
        self.assertTrue(Path(issue['route_state_path']).is_file())

    def test_automatic_edge_confirmation_escalates_only_failed_question_and_retains_hold(self):
        self.prefix_reader();self.fail_confirmation=True;self.original_edge_mode=True
        try:proof=self.review_removed_edges({0})
        finally:self.original_edge_mode=False
        self.assertEqual(proof['status'],'unresolved',proof)
        self.assertEqual(proof['memberships'],[])
        self.assertEqual([r['model'] for r in self.audio_requests],
            [self.options.model,self.options.model,self.options.pro_model])
        self.assertTrue(proof['issues'])

    def test_automatic_edge_proof_rejects_incomplete_or_duplicate_lineage_before_dispatch(self):
        import bhakti_boundary_adoption as boundary
        self.prefix_reader()
        for lineage in (
            [{'old_index':0,'new_index':None},{'old_index':1,'new_index':0}],
            [{'old_index':0,'new_index':None},{'old_index':0,'new_index':0},{'old_index':2,'new_index':1}],
            [{'old_index':True,'new_index':None}],
        ):
            with self.subTest(lineage=lineage),mock.patch.object(p.gemini,'call',
                    side_effect=AssertionError('malformed scope cannot dispatch')):
                with self.assertRaisesRegex(ValueError,'(?i)(lineage|occurrence)'):
                    boundary.review_boundary_memberships(self.declaration,self.song,self.target,
                        self.reader,{'status':'proposed','occurrence_lineage':lineage},options=self.options,
                        route_dir=self.routes/'automatic-memberships',deadline_at=self.deadline)

    def test_source_caller_automatically_builds_missing_edge_proof_without_rebuying_crop_review(self):
        self.prefix_reader();self.preserve_original_archive()
        original_declaration=self.transform.read_bytes()
        def hearing(model,key,prompt,**kwargs):
            previous=self.original_edge_mode
            self.original_edge_mode=(kwargs['schema_name']=='bhakti_segment_audit'
                and p.gemini.duration_seconds(Path(kwargs['audio']))<3)
            try:return self.provider(model,key,prompt,**kwargs)
            finally:self.original_edge_mode=previous
        with mock.patch.object(p.gemini,'call',side_effect=hearing):
            result=self.invoke()
        self.assertEqual(result['status'],'accepted',result)
        self.assertEqual(list(result['reader']['SONG_LINES']),['line-0','line-2'])
        self.assertEqual(len([r for r in self.audio_requests if r['original_edge']]),2)
        self.assertEqual(len([r for r in self.audio_requests if not r['original_edge']]),2,
            'one cropped hearing plus independent confirmation; rebinding must reuse the first hearing')
        self.assertEqual(self.transform.read_bytes(),original_declaration)
        receipt=json.loads(Path(result['evidence']['source_adoption_receipt']['path']).read_text())
        self.assertNotEqual(receipt['audio_transform'],self.declaration)
        completed=json.loads(Path(receipt['audio_transform']['path']).read_text())
        self.assertEqual(completed['original_edge_membership'][0]['old_expanded_indices'],[0])
        with mock.patch.object(p.gemini,'call',side_effect=AssertionError('connected resume cannot repay')):
            self.assertEqual(self.invoke(),result)

    def test_focused_removed_edge_routes_from_projected_intervals_including_collapsed_hint(self):
        self.prefix_reader()
        self.reader['SONG_TIMINGS'][0]['end']=1.
        self.reader['SONG_TIMINGS'][1]['start']=1.
        js(self.song/'data.js',self.reader);js(self.target/'data.js',self.reader)
        value=json.loads(self.transform.read_text());value['before']['reader_sha256']=source.file_hash(self.song/'data.js')
        self.rewrite_transform(value)
        self.options.source_requested_stages=['focused-audio-review']
        self.options.source_review_flags={'audio':True,'occurrence_ids':['occ-000']}
        before=snapshot(self.song)
        def hearing(model,key,prompt,**kwargs):
            previous=self.original_edge_mode
            self.original_edge_mode=(kwargs['schema_name']=='bhakti_segment_audit'
                and p.gemini.duration_seconds(Path(kwargs['audio']))<3)
            try:return self.provider(model,key,prompt,**kwargs)
            finally:self.original_edge_mode=previous
        with mock.patch.object(p.gemini,'call',side_effect=hearing):
            result=self.invoke()
        self.assertEqual(result['status'],'accepted',result)
        self.assertEqual(list(result['reader']['SONG_LINES']),['line-0','line-2'])
        self.assertEqual(snapshot(self.song),before)
        staged=[row for row in self.audio_requests if not row['original_edge']]
        self.assertTrue(staged)
        self.assertTrue(all(row['duration']<20 for row in staged),'edge review must stay within its adjacent context')

    def test_measured_private_crop_passes_both_source_admission_guards_and_binds_receipt(self):
        result=self.invoke()
        self.assertEqual(result['status'],'accepted',result)
        self.assertTrue(self.hearings)
        after_duration=p.gemini.duration_seconds(p.preferred_listener_audio(self.target))
        self.assertTrue(self.audio_requests)
        self.assertTrue(all(row['duration']<=after_duration+.1 for row in self.audio_requests))
        # Whole short-fixture observation must end at the staged duration, not
        # claim the original 30-second time axis for a 26-second attachment.
        receipt=json.loads(Path(result['evidence']['source_adoption_receipt']['path']).read_text())
        observed_paths=[Path(name) for name in receipt['evidence_files'] if name.endswith('-source-observed.json')]
        self.assertEqual(len(observed_paths),1)
        observation=json.loads(observed_paths[0].read_text())['result']
        for item in observation['unit_results']:
            self.assertLessEqual(item['unit']['clip_end'],after_duration)
        self.assertEqual(result['reader']['SONG_LINES'],self.reader['SONG_LINES'])
        receipt=json.loads(Path(result['evidence']['source_adoption_receipt']['path']).read_text())
        self.assertEqual(receipt['audio_transform'],self.declaration)
        self.assertEqual(receipt['before_identity']['audio_sha256'],source.file_hash(p.preferred_listener_audio(self.target)))
        self.assertEqual(snapshot(self.song),self.original_files)

    def test_cropped_audio_without_declaration_stays_rejected_before_dispatch(self):
        del self.options.source_audio_transform
        with mock.patch.object(p.gemini,'call',side_effect=AssertionError('invalid crop cannot dispatch')):
            result=self.invoke()
        self.assertEqual(result['status'],'unresolved',result)
        self.assertFalse(result['publicationEligible'])
        self.assertEqual(snapshot(self.song),self.original_files)

    def test_changed_original_staged_or_transform_bytes_cannot_relax_admission(self):
        for kind in ['original','candidate','transform','marker']:
            with self.subTest(kind=kind):
                path={'original':p.preferred_listener_audio(self.song),
                      'candidate':p.preferred_listener_audio(self.target),'transform':self.transform,
                      'marker':self.target/'.transcription/trim-applied.json'}[kind]
                original=path.read_bytes();path.write_bytes(original+b' ')
                try:
                    with mock.patch.object(p.gemini,'call',side_effect=AssertionError('changed transform input cannot dispatch')):
                        result=self.invoke()
                    self.assertEqual(result['status'],'unresolved',result)
                    self.assertFalse(result['publicationEligible'])
                finally:path.write_bytes(original)

    def test_source_observation_rebind_includes_transform_identity_and_never_reuses_unbound_cache(self):
        first=self.invoke();self.assertEqual(first['status'],'accepted',first)
        with mock.patch.object(p.gemini,'call',side_effect=AssertionError('valid transform resume must not repay')):
            self.assertEqual(self.invoke(),first)
        # This does not change native bytes. It changes the declaration whose
        # accepted evidence is part of request authorization; a stale receipt
        # must be rejected or routed under a different identity, never reused.
        value=json.loads(self.transform.read_text());value['before']['reader_sha256']='f'*64
        write_json(self.transform,value);self.options.source_audio_transform={
            'path':str(self.transform),'sha256':source.file_hash(self.transform)}
        with mock.patch.object(p.gemini,'call',side_effect=AssertionError('changed original reader claim cannot dispatch')):
            result=self.invoke()
        self.assertEqual(result['status'],'unresolved',result)
        self.assertFalse(result['publicationEligible'])

    def rewrite_transform(self,value):
        write_json(self.transform,value)
        self.declaration={'path':str(self.transform),'sha256':source.file_hash(self.transform)}
        self.options.source_audio_transform=self.declaration

    def prefix_reader(self):
        self.reader['SONG_SEQUENCE']=[{'ref':'line-1','section':'spoken','repeats':1},
            {'ref':'line-0','section':'verse','repeats':1},{'ref':'line-2','section':'verse','repeats':1}]
        self.reader['SONG_TIMINGS']=[{'start':.5,'end':5.},{'start':5.,'end':20.},{'start':20.,'end':self.duration}]
        js(self.song/'data.js',self.reader);js(self.target/'data.js',self.reader)
        self.original_files=snapshot(self.song)
        value=json.loads(self.transform.read_text());value['before']['reader_sha256']=source.file_hash(self.song/'data.js')
        self.rewrite_transform(value);self.remove_source=True

    def original_membership(self,indices=None,edge='start'):
        indices=[0] if indices is None else indices
        all_source=source.source_draft(self.reader)
        selected=[all_source['performance_order'][i] for i in indices]
        ids={row['line_id'] for row in selected}
        draft={'lines':[row for row in all_source['lines'] if row['id'] in ids],'performance_order':selected}
        start=0. if edge=='start' else self.boundary['trim_end']
        end=self.boundary['trim_start'] if edge=='start' else self.boundary['duration']
        displays=sorted({int(row['display_occurrence_id'].split('-')[1]) for row in selected})
        unit={'id':'boundary-original-'+edge,'kind':'focused','segment_index':0,
            'clip_start':start,'clip_end':end,'core_start':start,'core_end':end,
            'core_occurrence_indices':displays,'context_occurrence_indices':displays,
            'target_occurrence_ids':sorted({row['display_occurrence_id'] for row in selected}),'expanded_draft':draft}
        identity=source.collect_source_evidence(self.song,self.reader,flags={'audio':True},coverage_requested=False)['identity']
        self.original_edge_mode=True
        try:
            first=source.review_audio_units(song_dir=self.song,units=[unit],audio=p.preferred_listener_audio(self.song),
                source_identity=identity,options=self.options,route_dir=self.routes/'original-edge',deadline_at=self.deadline)
            by_id={row['id']:row for row in draft['lines']}
            expected={unit['id']:[list(source._source_key(by_id[row['line_id']])) for row in draft['performance_order']]}
            confirmed=source.review_audio_units(song_dir=self.song,units=[unit],audio=p.preferred_listener_audio(self.song),
                source_identity=identity,options=self.options,route_dir=self.routes/'original-edge',deadline_at=self.deadline,
                expected_orders=expected)
        finally:self.original_edge_mode=False
        self.assertEqual(first['status'],'observed',first);self.assertEqual(confirmed['status'],'observed',confirmed)
        files={}
        for item in first['unit_results']+confirmed['unit_results']:
            state=Path(item['route_state_path']);files[str(state)]=source.file_hash(state)
            accepted=state.parent/'accepted-result.json';files[str(accepted)]=source.file_hash(accepted)
        return {'edge':edge,'source_identity':identity,'boundary_digest':source.digest(self.boundary[edge]),
            'excluded_interval':{'start':start,'end':end},'old_expanded_indices':indices,
            'observation':first,'confirmation':confirmed,'evidence_files':files}

    def test_agreeing_staged_absence_without_original_edge_mapping_cannot_remove_attached_speech(self):
        self.prefix_reader()
        result=self.invoke()
        self.assertEqual(result['status'],'unresolved',result)
        self.assertFalse(result['publicationEligible'])
        # The synthetic staged provider always omits the spoken row. Agreement
        # in that attachment cannot prove its original relationship to the work.
        self.assertEqual(result['reader']['SONG_LINES'],self.reader['SONG_LINES'])
        self.assertEqual(snapshot(self.song),self.original_files)
        self.assertRegex(json.dumps(result['issues']),'(?i)(original.edge|membership|unrelated)')

    def test_original_edge_source_and_independent_confirmation_authorize_exact_removed_occurrence(self):
        self.prefix_reader();membership=self.original_membership()
        value=json.loads(self.transform.read_text());value['original_edge_membership']=[membership]
        self.rewrite_transform(value)
        result=self.invoke();self.assertEqual(result['status'],'accepted',result)
        self.assertEqual(list(result['reader']['SONG_LINES']),['line-0','line-2'])
        self.assertGreaterEqual(len([row for row in self.audio_requests if row['original_edge']]),2)
        self.assertGreaterEqual(len([row for row in self.audio_requests if not row['original_edge']]),2)
        for lid in result['reader']['SONG_LINES']:
            self.assertEqual(result['reader']['SONG_LINES'][lid],self.reader['SONG_LINES'][lid])
        self.assertEqual(snapshot(self.song),self.original_files)

    def test_fallback_format_omission_change_and_pending_marker_cannot_authorize_crop(self):
        original=self.transform.read_bytes();fallback=self.target/'audio.m4a';fallback_bytes=fallback.read_bytes()
        marker=self.target/'.transcription/trim-applied.json';marker_bytes=marker.read_bytes()
        for kind in ('omitted-fallback','changed-fallback','pending'):
            with self.subTest(kind=kind):
                value=json.loads(original)
                if kind=='omitted-fallback':del value['native']['audio.m4a']
                elif kind=='changed-fallback':fallback.write_bytes(fallback_bytes+b'changed')
                else:
                    pending=json.loads(marker_bytes);pending['status']='pending';write_json(marker,pending)
                    value['after']['trim_sha256']=source.file_hash(marker)
                self.rewrite_transform(value)
                try:
                    with mock.patch.object(p.gemini,'call',side_effect=AssertionError('incomplete native set cannot dispatch')):
                        result=self.invoke()
                    self.assertEqual(result['status'],'unresolved',result)
                    self.assertFalse(result['publicationEligible'])
                finally:
                    fallback.write_bytes(fallback_bytes);marker.write_bytes(marker_bytes)
        self.rewrite_transform(json.loads(original))

    def test_changed_original_edge_route_evidence_cannot_authorize_removal(self):
        self.prefix_reader();membership=self.original_membership()
        value=json.loads(self.transform.read_text());value['original_edge_membership']=[membership]
        self.rewrite_transform(value)
        path=Path(next(iter(membership['evidence_files'])))
        path.write_bytes(path.read_bytes()+b' ')
        with mock.patch.object(p.gemini,'call',side_effect=AssertionError('changed original-edge proof cannot dispatch')):
            result=self.invoke()
        self.assertEqual(result['status'],'unresolved',result)
        self.assertFalse(result['publicationEligible'])
        self.assertEqual(snapshot(self.song),self.original_files)

    def test_original_edge_proof_for_different_occurrence_or_boundary_cannot_authorize_deletion(self):
        self.prefix_reader();membership=self.original_membership()
        original=json.loads(self.transform.read_text())
        for field,value in [('old_expanded_indices',[1]),('boundary_digest','f'*64)]:
            with self.subTest(field=field):
                transform=copy.deepcopy(original);wrong=copy.deepcopy(membership);wrong[field]=value
                transform['original_edge_membership']=[wrong]
                self.rewrite_transform(transform)
                with mock.patch.object(p.gemini,'call',side_effect=AssertionError('wrong membership target must hold before dispatch')):
                    result=self.invoke()
                self.assertEqual(result['status'],'unresolved',result)
                self.assertFalse(result['publicationEligible'])
                self.assertEqual(snapshot(self.song),self.original_files)

    def test_self_consistent_original_start_proof_cannot_authorize_interior_or_gapped_lineage(self):
        import bhakti_boundary_adoption as boundary
        self.reader['SONG_SEQUENCE'][1]['repeats']=1
        js(self.song/'data.js',self.reader)
        for indices in ([1],[0,2]):
            with self.subTest(indices=indices):
                membership=self.original_membership(indices=indices)
                transform=json.loads(self.transform.read_text());transform['original_edge_membership']=[membership]
                with self.assertRaisesRegex(ValueError,'(?i)(prefix|suffix|edge|lineage)'):
                    boundary.checked_original_memberships(transform,self.reader,self.song)

    def test_full_prefix_proof_does_not_authorize_retaining_first_but_deleting_interior(self):
        import bhakti_boundary_adoption as boundary
        self.reader['SONG_SEQUENCE'][1]['repeats']=1
        js(self.song/'data.js',self.reader)
        membership=self.original_membership(indices=[0,1])
        transform=json.loads(self.transform.read_text());transform['original_edge_membership']=[membership]
        for removed in ({1},{0}):
            with self.subTest(removed=removed), self.assertRaisesRegex(ValueError,'(?i)(prefix|suffix|edge|lineage)'):
                boundary.require_removed_membership(transform,self.reader,
                    {'occurrence_lineage':[{'old_index':i,'new_index':None if i in removed else i}
                        for i in range(3)]},self.song)

    def test_original_suffix_and_partial_repeated_prefix_preserve_expanded_edge_positions(self):
        import bhakti_boundary_adoption as boundary
        full=source.source_draft(self.reader);last=len(full['performance_order'])-1
        membership=self.original_membership(indices=[last],edge='end')
        transform=json.loads(self.transform.read_text());transform['original_edge_membership']=[membership]
        self.assertEqual(boundary.checked_original_memberships(transform,self.reader,self.song),{last})
        boundary.require_removed_membership(transform,self.reader,
            {'occurrence_lineage':[{'old_index':i,'new_index':i if i!=last else None} for i in range(last+1)]},self.song)
        # Put a two-performance block first. Removing only its first performed
        # instance is an edge prefix even though the line definition remains.
        self.reader['SONG_SEQUENCE']=[self.reader['SONG_SEQUENCE'][1],self.reader['SONG_SEQUENCE'][0],self.reader['SONG_SEQUENCE'][2]]
        js(self.song/'data.js',self.reader)
        membership=self.original_membership(indices=[0])
        transform['original_edge_membership']=[membership]
        self.assertEqual(boundary.checked_original_memberships(transform,self.reader,self.song),{0})
        boundary.require_removed_membership(transform,self.reader,
            {'occurrence_lineage':[{'old_index':0,'new_index':None},{'old_index':1,'new_index':0},
                {'old_index':2,'new_index':1},{'old_index':3,'new_index':2}]},self.song)

"""Next dependency: real source-adapter entrypoint and private generation.

Silent local audio plus explicit returned source fixtures test software behavior,
not recognition quality. Only provider output, fresh semantics and measured
timing boundaries are replaced. File storage, router, receipt reuse, rendering
and data.js parsing remain real. No paid calls.
"""
import argparse
import copy
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import audit_bhakti_contract as contract
import bhakti_library_source_pass as source
import bhakti_pipeline as pipeline
import bhakti_library_pass as library
from test_generic_source_caller import make_audio, reader_for, js, write_json
from test_source_caller import fresh


class SourceAdoptionCallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.root = self.base / 'root'; self.workspace = self.base / 'workspace'
        self.routes = self.base / 'routes'; self.slug = 'source-adoption-fixture'
        self.song = self.root / 'songs' / self.slug; self.song.mkdir(parents=True)
        make_audio(self.song / 'audio.m4a', 4)
        self.duration = pipeline.gemini.duration_seconds(self.song / 'audio.m4a')
        self.reader = reader_for(self.duration)
        self.reader['SONG_META'].update(credit='Singer', singer='Singer', writer='', composer='',
            subjectTags=['Rāma'], sourceStatus='reviewed', timingStatus='start-only-reviewed',
            translationStatus='gloss-derived literal', audioSources=[{'src':'audio.m4a','type':'audio/mp4'}])
        js(self.song / 'data.js', self.reader); (self.song / 'index.html').write_text('original HTML')
        write_json(self.root / 'data/editorial_baselines.json', {'version':1,'songs':{}})
        shutil.copytree(self.root, self.workspace)
        self.original = (self.song / 'data.js').read_bytes()
        self.options = argparse.Namespace(model=pipeline.MODEL, pro_model='google/gemini-3.1-pro-preview',
            timeout=30, force=False, source_witness_audit=False, source_requested_stages=['audio-review'],
            source_review_flags={'audio':True}, source_coverage_requested=True)
        self.deadline = time.time() + 120; self.hearings = []; self.fresh_targets = []
        self.add_source = False; self.fail_confirmation = False; self.mismatch_confirmation = False; self.fail_semantics = False
        self.remove_source = False; self.replace_source = False
        self.addCleanup(patch.stopall)
        patch.object(pipeline.gemini, 'key', return_value='fixture-not-a-key').start()
        patch.object(pipeline.gemini, 'call', side_effect=self.provider).start()
        self.semantic = patch.object(source, 'process_new_targets', side_effect=self.semantics).start()
        self.timing = patch.object(pipeline, 'align', side_effect=self.align).start()

    def provider(self, model, key, prompt, **kwargs):
        if kwargs['schema_name'] == 'bhakti_translation_review':
            from test_library_execution import review
            ids = json.JSONDecoder().raw_decode(prompt.split('OUTPUT TARGET IDS (return exactly these, once each):\n',1)[1].lstrip())[0]
            return {'packet':{'reviews':[review(line_id=lid) for lid in ids]},'resolved_model':model}
        self.assertEqual(kwargs['schema_name'], 'bhakti_segment_audit')
        self.assertNotIn('OWNER ENGLISH', prompt); self.assertNotIn('PRIVATE GLOSS', prompt)
        draft = json.JSONDecoder().raw_decode(prompt.split('FIRST TRANSCRIPT:\n', 1)[1].lstrip())[0]
        self.hearings.append(copy.deepcopy(draft))
        if self.add_source and not any(row['source_text'] == 'नाम' for row in draft['lines']):
            draft['lines'].append({'id':'heard-name','source_text':'नाम','roman':'nāma',
                'language':'Hindi','kind':'verse','partial':'none','notes':''})
            draft['performance_order'].insert(1, {'line_id':'heard-name','occurrence':1})
        if self.remove_source:
            removed={row['id'] for row in draft['lines'] if row['source_text']=='तन'}
            draft['lines']=[row for row in draft['lines'] if row['id'] not in removed]
            draft['performance_order']=[event for event in draft['performance_order'] if event['line_id'] not in removed]
        if self.replace_source:
            for row in draft['lines']:
                if row['source_text']=='मन':row.update(source_text='मान',roman='mān')
        draft['uncertainties'] = ['cannot resolve competing source readings'] if self.fail_confirmation and len(self.hearings) > 1 else []
        if self.mismatch_confirmation and len(self.hearings) > 1:
            for row in draft['lines']:
                if row['source_text'] == 'नाम':
                    row.update(source_text='काया', roman='kāyā')
        return {'packet':draft, 'resolved_model':model}

    def semantics(self, song, plan, metadata, options, route, deadline):
        self.fresh_targets.append(copy.deepcopy(plan['new_target_ids']))
        value = fresh(plan)
        if self.fail_semantics:
            value['translations']['packet']['translations'][0]['independent_review']['passes'] = False
        return value

    def align(self, song, audit, audio, options):
        occurrences = pipeline.display_occurrences(audit['packet'])
        step = self.duration / len(occurrences)
        return {'sequence':[{**row,'start':i*step,'end':(i+1)*step} for i,row in enumerate(occurrences)],
                'uncertain_occurrence_ids':[], 'validation_errors':[]}

    def invoke(self):
        return source.run_source_candidate(root=self.root, slug=self.slug, reader=self.reader,
            workspace=self.workspace, route_dir=self.routes, options=self.options, deadline_at=self.deadline)

    def test_same_source_with_missing_historical_packets_advances_to_private_candidate(self):
        result = self.invoke()
        self.assertEqual(result['status'], 'accepted', result)
        self.assertEqual(len(self.hearings), 1)
        self.semantic.assert_not_called()
        self.assertEqual(result['reader']['SONG_LINES'], self.reader['SONG_LINES'])
        self.assertEqual((self.song/'data.js').read_bytes(), self.original)
        self.assertEqual(contract.load_data(self.workspace/'songs'/self.slug/'data.js'), result['reader'])

    def test_source_prefix_deletion_keeps_heading_and_adaptation_with_their_lyric(self):
        self.reader['SONG_SEQUENCE']=[{'ref':'line-1','section':'spoken','repeats':1},
            {'ref':'line-0','section':'verse','repeats':1},{'ref':'line-2','section':'verse','repeats':1}]
        self.reader['SONG_META']['sectionNotices']=[
            {'sequenceIndex':1,'title':'Known section','poet':'Known poet','note':'Preserve the wording.'}]
        self.reader['SONG_META']['adaptedSequenceIndices']=[1]
        for folder in (self.song,self.workspace/'songs'/self.slug):js(folder/'data.js',self.reader)
        self.remove_source=True
        registry=self.base/'scripture-metadata.json'
        write_json(registry,{self.slug:{'writer':'Known poet','sectionNotices':[
            {**self.reader['SONG_META']['sectionNotices'][0],'expectedRef':'line-0'}]}})
        with patch.object(pipeline.scripture_metadata,'REGISTRY',registry):
            result=self.invoke()
        self.assertEqual(result['status'],'accepted',result)
        expected=copy.deepcopy(self.reader['SONG_META'])
        expected['sectionNotices'][0]['sequenceIndex']=0;expected['adaptedSequenceIndices']=[0]
        self.assertEqual(result['reader']['SONG_META'],expected)
        self.assertEqual(contract.load_data(self.workspace/'songs'/self.slug/'data.js')['SONG_META'],expected)
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('metadata resume cannot dispatch')):
            self.assertEqual(self.invoke(),result)
        changed=copy.deepcopy(result['reader']);changed['SONG_META']['title']='Unsupported replacement'
        with self.assertRaisesRegex(ValueError,'metadata'):
            source.assert_source_candidate(self.reader,changed,result['evidence']['plan'],result['evidence']['timing'])

    def test_source_insertion_shifts_later_credit_without_attributing_uncredited_material(self):
        self.reader['SONG_META']['sectionNotices']=[
            {'sequenceIndex':2,'title':'Closing work','poet':'Closing poet','note':''}]
        self.reader['SONG_META']['adaptedSequenceIndices']=[2]
        for folder in (self.song,self.workspace/'songs'/self.slug):js(folder/'data.js',self.reader)
        self.add_source=True
        result=self.invoke();self.assertEqual(result['status'],'accepted',result)
        self.assertEqual(result['reader']['SONG_META']['sectionNotices'][0]['sequenceIndex'],3)
        self.assertEqual(result['reader']['SONG_META']['adaptedSequenceIndices'],[3])

    def test_new_source_is_confirmed_then_only_new_semantics_generated_without_manual_map(self):
        self.add_source = True
        result = self.invoke()
        self.assertEqual(result['status'], 'accepted', result)
        self.assertEqual(len(self.hearings), 2, 'one initial audit and one independent changed-source confirmation')
        self.assertEqual(len(self.fresh_targets), 1); self.assertEqual(len(self.fresh_targets[0]), 1)
        after = result['reader']
        for lid, original in self.reader['SONG_LINES'].items():
            self.assertEqual(after['SONG_LINES'][lid], original)
        new = self.fresh_targets[0][0]
        self.assertEqual(after['SONG_LINES'][new]['source'], 'नाम')
        self.assertEqual([row['ref'] for row in after['SONG_SEQUENCE']], ['line-0',new,'line-1','line-2'])
        self.assertEqual(after['SONG_SEQUENCE'][2]['repeats'], 2)
        self.assertEqual((self.song/'data.js').read_bytes(), self.original)
        self.assertEqual(contract.audit_song(self.workspace/'songs'/self.slug)['status'], 'ready')

    def test_accepted_candidate_resume_uses_all_durable_results_without_calls(self):
        self.add_source = True; first = self.invoke()
        self.assertEqual(first['status'], 'accepted', first)
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('duplicate audio request')), \
             patch.object(source,'process_new_targets',side_effect=AssertionError('duplicate semantic request')), \
             patch.object(pipeline,'align',side_effect=AssertionError('duplicate timing request')):
            self.assertEqual(self.invoke(), first)

    def test_confirmed_deletion_removes_unperformed_definition_without_reinserting_old_rows(self):
        self.remove_source=True; result=self.invoke()
        self.assertEqual(result['status'],'accepted',result)
        self.assertEqual(len(self.hearings),2);self.semantic.assert_not_called()
        self.assertEqual(list(result['reader']['SONG_LINES']),['line-0','line-2'])
        self.assertEqual([row['ref'] for row in result['reader']['SONG_SEQUENCE']],['line-0','line-2'])
        archived=self.workspace/'songs'/self.slug/'.transcription/source-pass-original/data.js'
        self.assertEqual(archived.read_bytes(),self.original)
        self.assertEqual((self.song/'data.js').read_bytes(),self.original)

    def test_confirmed_word_correction_regenerates_source_mapping_and_preserves_other_lines(self):
        self.replace_source=True; result=self.invoke()
        self.assertEqual(result['status'],'accepted',result)
        self.assertEqual(len(self.hearings),2)
        self.assertEqual(len(self.fresh_targets),1);self.assertEqual(len(self.fresh_targets[0]),1)
        after=result['reader']['SONG_LINES'];new=self.fresh_targets[0][0]
        self.assertNotIn('line-0',after)
        self.assertEqual(after[new]['source'],'मान');self.assertEqual(after[new]['roman'],'mān')
        self.assertEqual(after[new]['sourceWords'],[{'text':'मान','wordIndices':[0]}])
        for lid in ('line-1','line-2'):self.assertEqual(after[lid],self.reader['SONG_LINES'][lid])
        self.assertEqual((self.song/'data.js').read_bytes(),self.original)

    def test_confirmation_uncertainty_holds_before_semantics_timing_or_generation(self):
        self.add_source = True; self.fail_confirmation = True
        result = self.invoke()
        self.assertEqual(result['status'], 'unresolved')
        self.assertFalse(result['publicationEligible'])
        self.assertGreater(len(self.hearings), 1, 'must attempt bounded independent source confirmation')
        self.semantic.assert_not_called(); self.timing.assert_not_called()
        self.assertEqual((self.song/'data.js').read_bytes(), self.original)
        self.assertEqual((self.workspace/'songs'/self.slug/'data.js').read_bytes(), self.original)

    def test_protected_population_addition_is_reported_without_owner_overwrite(self):
        baseline = {'version':1,'songs':{self.slug:{'policy':'preserve_english','englishSha256':'a'*64,
            'plainEnglishByLine':{lid:'OWNER ENGLISH' for lid in self.reader['SONG_LINES']}}}}
        for root in (self.root, self.workspace):
            write_json(root/'data/editorial_baselines.json', baseline)
        self.add_source = True; result = self.invoke()
        self.assertEqual(result['status'], 'unresolved')
        self.assertIn('locked_baseline_conflict', json.dumps(result))
        self.semantic.assert_not_called(); self.timing.assert_not_called()
        self.assertEqual((self.song/'data.js').read_bytes(), self.original)
        self.assertEqual((self.workspace/'songs'/self.slug/'data.js').read_bytes(), self.original)

    def test_confirmation_cannot_reuse_first_pass_legacy_observation_lookup(self):
        import bhakti_source_cache_compat as compatibility
        self.add_source=True
        with patch.object(compatibility,'lookup',wraps=compatibility.lookup) as lookup:
            result=self.invoke()
        self.assertEqual(result['status'],'accepted',result)
        self.assertEqual(len(self.hearings),2)
        self.assertTrue(lookup.call_args_list)
        self.assertTrue(all(':confirmation-' not in call.kwargs['unit_id']
                            for call in lookup.call_args_list))

    def test_protected_population_deletion_holds_before_timing_or_workspace_mutation(self):
        baseline = {'version':1,'songs':{self.slug:{'policy':'preserve_english','englishSha256':'a'*64,
            'plainEnglishByLine':{lid:'OWNER ENGLISH' for lid in self.reader['SONG_LINES']}}}}
        for root in (self.root, self.workspace):
            write_json(root/'data/editorial_baselines.json', baseline)
        self.remove_source = True
        result = self.invoke()
        self.assertEqual(result['status'], 'unresolved')
        self.assertIn('locked_baseline_conflict', json.dumps(result))
        self.semantic.assert_not_called(); self.timing.assert_not_called()
        self.assertEqual((self.workspace/'songs'/self.slug/'data.js').read_bytes(), self.original)
        self.assertEqual((self.song/'data.js').read_bytes(), self.original)
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('hold resume must use hearing cache')):
            resumed = self.invoke()
        self.assertEqual(resumed['status'], 'unresolved')
        self.assertIn('locked_baseline_conflict', json.dumps(resumed))
        self.assertNotIn('stale', json.dumps(resumed))

    def test_library_source_checkpoint_revalidates_raw_attempt_candidate_without_dispatch(self):
        self.add_source = True; row = self.library_row()
        first = library.execute_song(self.root, row, self.library_state, self.options, self.deadline)
        self.assertEqual(first['status'], 'accepted', first)
        source_result = json.loads(next(self.library_state.rglob('accepted-source-delta.json')).read_text())
        state_paths = [Path(name) for name in source_result['evidence_files'] if Path(name).name == 'route-state.json']
        self.assertTrue(state_paths)
        candidate = state_paths[0].parent/'flash/candidate.json'
        record = json.loads(candidate.read_text()); record['tampered'] = True
        write_json(candidate, record)
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('corrupt route must not trigger repayment')):
            resumed = library.execute_song(self.root, row, self.library_state, self.options, self.deadline)
        self.assertNotEqual(resumed['status'], 'accepted')
        self.assertFalse(resumed['publicationEligible'])

    def test_different_clear_confirmation_is_not_accepted_merely_because_uncertainty_is_empty(self):
        self.add_source = True; self.mismatch_confirmation = True
        result = self.invoke()
        self.assertEqual(result['status'], 'unresolved')
        self.assertFalse(result['publicationEligible'])
        self.assertEqual(len(self.hearings), 3, 'initial audit followed by bounded Flash/Pro disagreement confirmation')
        self.semantic.assert_not_called(); self.timing.assert_not_called()
        self.assertEqual((self.workspace/'songs'/self.slug/'data.js').read_bytes(), self.original)

    def test_changed_accepted_source_receipt_cannot_authorize_resume(self):
        self.add_source = True; result = self.invoke()
        self.assertEqual(result['status'], 'accepted', result)
        receipts = list(self.routes.rglob('accepted-source-delta.json'))
        self.assertEqual(len(receipts), 1)
        record = json.loads(receipts[0].read_text()); record['approved_source_order_digest'] = '0' * 64
        write_json(receipts[0], record)
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('tampering must not trigger repayment')):
            resumed = self.invoke()
        self.assertEqual(resumed['status'], 'unresolved')
        self.assertFalse(resumed['publicationEligible'])

    def test_failed_new_translation_retains_audio_evidence_and_does_not_publish(self):
        self.add_source = True; self.fail_semantics = True
        first = self.invoke()
        self.assertEqual(first['status'], 'unresolved')
        self.assertIn('source_semantic_contract', json.dumps(first))
        heard = len(self.hearings)
        self.assertEqual(heard, 2)
        self.timing.assert_not_called()
        self.assertEqual((self.song/'data.js').read_bytes(), self.original)
        self.fail_semantics = False
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('source must remain cached')):
            second = self.invoke()
        self.assertEqual(second['status'], 'accepted', second)
        self.assertEqual(len(self.hearings), heard)

    def library_row(self):
        # A real committed catalogue fixes the inventory's population and
        # original fingerprints; no mocked input guard or workspace builder.
        write_json(self.song/'.transcription/source.json', {'source_url':'https://www.youtube.com/watch?v=abcdefghijk'})
        catalogue = {'slug':self.slug,'title':self.reader['SONG_META']['title'], 'singer':'Singer',
                     'writer':'','languageTags':['Hindi'],'subjectTags':['Rāma']}
        js(self.root/'data/songs.js', {'BHAKTI_SONGS':[catalogue]})
        (self.root/'.gitignore').write_text('.transcription/\nsongs/*/audio.*\n')
        for arguments in (['init','-q'], ['config','user.name','Fixture'],
                          ['config','user.email','fixture@example.invalid'],
                          ['add','.gitignore','data/editorial_baselines.json','data/songs.js',
                           f'songs/{self.slug}/data.js',f'songs/{self.slug}/index.html'],
                          ['commit','-qm','source adoption fixture']):
            subprocess.run(['git','-C',str(self.root),*arguments],check=True,capture_output=True)
        self.library_state = self.base/'library-state'
        inventory = library.build_inventory(self.root, state_dir=self.library_state,
            flags={self.slug:{'audio':True,'coverage_requested':True}})
        row = inventory['songs'][0]
        self.assertTrue(row['dispatchEligible'], row)
        return row

    def test_actual_library_runner_consumes_source_candidate_and_completes_semantic_review(self):
        self.add_source = True; row = self.library_row()
        result = library.execute_song(self.root, row, self.library_state, self.options, self.deadline)
        self.assertEqual(result['status'], 'accepted', result)
        self.assertTrue(result['publicationEligible'])
        self.assertTrue(result['changed'])
        candidate = contract.load_data(Path(result['candidateRoot'])/'songs'/self.slug/'data.js')
        self.assertEqual(candidate['SONG_LINES']['line-0'], self.reader['SONG_LINES']['line-0'])
        self.assertEqual(len(candidate['SONG_LINES']), 4)
        self.assertEqual((self.song/'data.js').read_bytes(), self.original)

    def test_library_source_checkpoint_revalidates_actual_saved_candidate_before_reuse(self):
        self.add_source = True; row = self.library_row()
        first = library.execute_song(self.root, row, self.library_state, self.options, self.deadline)
        self.assertEqual(first['status'], 'accepted', first)
        path = Path(first['candidateRoot'])/'songs'/self.slug/'data.js'
        changed = contract.load_data(path); changed['SONG_LINES']['line-0']['english'] = '{0:Tampered wording}'
        js(path, changed)
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('drift must not trigger payment')):
            resumed = library.execute_song(self.root, row, self.library_state, self.options, self.deadline)
        self.assertNotEqual(resumed['status'], 'accepted')
        self.assertFalse(resumed['publicationEligible'])


if __name__ == '__main__':
    unittest.main()

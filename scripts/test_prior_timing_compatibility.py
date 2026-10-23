"""Prior evidence must survive later nochange/repair passes without new payment."""
import copy,json,shutil,unittest
from pathlib import Path
from unittest.mock import patch
import bhakti_pipeline as pipeline
import bhakti_library_source_pass as source
import test_source_timing_caller_design as fixtures

class PriorTimingCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.SourceTimingCallerDesignTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
    def test_actual_source_adoption_output_retains_its_verified_measurements_on_next_pass(self):
        f=self.f;f.setup_source(['A','B','C','D']);prior=f.invoke()
        self.assertEqual(f.calls,[])
        self.assertEqual(pipeline.timing_uncertainty_errors(prior),[])
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('reusing verified evidence must not dispatch')):
            plan=source.plan_source_timing(f.reader,f.delta,prior,audio_sha256=source.file_hash(f.audio),trim={},duration_seconds=40.)
        self.assertEqual(plan['retained_starts'],{'occ-000':2.,'occ-001':12.,'occ-002':22.,'occ-003':32.})
        self.assertEqual(plan['regions'],[])
    def test_prior_source_adoption_proof_cannot_be_replaced_by_selected_timestamp_claim(self):
        f=self.f;f.setup_source(['A','B','C','D']);prior=f.invoke()
        prior['sequence'][1]['start']=11.
        with self.assertRaises(ValueError):
            source.plan_source_timing(f.reader,f.delta,prior,audio_sha256=source.file_hash(f.audio),trim={},duration_seconds=40.)
    def ordinary_joint_prior(self):
        f=self.f;f.setup_source(['A','B','C','D']);f.target.unlink()
        del f.options.timing_source_adoption
        f.points={f'occ-{i:03d}-r01':2.+i*10 for i in range(4)}
        prior=f.invoke()
        self.assertEqual(len(f.calls),2)
        self.assertEqual([r['kind'] for r in prior['refinements']],['joint'])
        canonical=pipeline.canonical_timing_audio(f.audio,f.root/'canonical.m4a')
        return prior,source.file_hash(canonical)
    def plan_joint(self,prior,canonical_hash):
        f=self.f
        return source.plan_source_timing(f.reader,f.delta,prior,audio_sha256=source.file_hash(f.audio),
            trim={},duration_seconds=40.,model_audio_sha256=canonical_hash)
    def test_actual_ordinary_joint_output_reuses_raw_pairs_bound_to_current_model_audio(self):
        prior,canonical_hash=self.ordinary_joint_prior()
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('joint reuse must not dispatch')):
            plan=self.plan_joint(prior,canonical_hash)
        self.assertEqual(plan['retained_starts'],{'occ-000':2.,'occ-001':12.,'occ-002':22.,'occ-003':32.})
        self.assertEqual(plan['regions'],[])
    def test_actual_source_adoption_with_prior_joint_measures_only_inserted_return(self):
        prior,_=self.ordinary_joint_prior();f=self.f
        # Same native recording/source, with a subsequently accepted insertion.
        shutil.rmtree(f.song/'.transcription/source-pass-original')
        f.setup_source(['A','B','A','C','D'])
        archived=Path(f.declaration['prior_timing']['path']);fixtures.write_json(archived,prior)
        f.declaration['prior_timing']['sha256']=source.file_hash(archived)
        fixtures.write_json(f.target,prior)
        f.calls=[];f.points={'occ-002-r01':17.}
        result=f.invoke()
        self.assertEqual([row['start'] for row in result['sequence']],[2.,12.,17.,22.,32.])
        self.assertEqual([ids for _,ids,_ in f.calls],[['occ-002-r01']]*2)
        count=len(f.calls);self.assertEqual(f.invoke(),result);self.assertEqual(len(f.calls),count)
    def test_joint_wrong_canonical_audio_or_source_context_is_a_hold(self):
        prior,canonical_hash=self.ordinary_joint_prior()
        with self.assertRaises(ValueError):self.plan_joint(prior,'c'*64)
        changed=copy.deepcopy(prior)
        changed['refinements'][0]['region']['target_occurrences'][0]['source_text']='different source'
        with self.assertRaises(ValueError):self.plan_joint(changed,canonical_hash)
    def test_actual_joint_pair_selection_reuses_only_reconstructed_selected_pairs(self):
        prior,canonical_hash=self.ordinary_joint_prior();raw=prior['refinements'][0]
        evidence=[{'region':raw['region'],'input_fingerprint':raw['input_fingerprint'],
            'select_timing_ids':[r['timing_id'] for r in pipeline.expanded_timing_targets(raw['region']['target_occurrences'])],
            'report':raw}]
        pairs=pipeline.selected_joint_pairs(evidence,prior['ordered_occurrences'],40.,canonical_hash,prior['source_identity'])
        assembled=pipeline.assemble_joint_pair_evidence(prior['ordered_occurrences'],pairs,40.)
        selected=copy.deepcopy(prior);selected['refinements']=[{'kind':'joint-selection','plan_sha256':'a'*64,
            'audio_sha256':canonical_hash,'source_identity':prior['source_identity'],
            'ordered_occurrences':prior['ordered_occurrences'],'duration_seconds':40.,
            'evidence':evidence,'expanded_starts':assembled['expanded_starts']}]
        self.assertEqual(pipeline.timing_uncertainty_errors(selected),[])
        plan=self.plan_joint(selected,canonical_hash)
        self.assertEqual(plan['retained_starts'],{'occ-000':2.,'occ-001':12.,'occ-002':22.,'occ-003':32.})
        selected['refinements'][0]['expanded_starts'][1]['start']=11.
        with self.assertRaises(ValueError):self.plan_joint(selected,canonical_hash)
    def test_deleted_original_evidence_is_a_hold_not_permission_to_repay(self):
        f=self.f;f.setup_source(['A','B','C','D']);prior=f.invoke()
        Path(f.declaration['prior_timing']['path']).unlink()
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('lost evidence is not permission to repay')):
            with self.assertRaises(ValueError):
                source.plan_source_timing(f.reader,f.delta,prior,audio_sha256=source.file_hash(f.audio),trim={},duration_seconds=40.)

if __name__=='__main__':unittest.main()

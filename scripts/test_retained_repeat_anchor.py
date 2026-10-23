"""A retained repeated block's last proven onset bounds a newly inserted line."""
import copy,shutil,unittest
from pathlib import Path
from unittest.mock import patch
import bhakti_pipeline as pipeline
import bhakti_library_source_pass as source
import test_source_timing_caller_design as fixtures

class RetainedRepeatAnchorTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.SourceTimingCallerDesignTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        real=fixtures.timing_fixture
        self.fixture=patch.object(fixtures,'timing_fixture',side_effect=lambda old,heard:real(['A','B','B','C'],heard))
        self.fixture.start();self.addCleanup(self.fixture.stop)
        self.f.setup_source(['A','B','B','C']);self.grid_prior=copy.deepcopy(self.f.prior);self.f.target.unlink()
        del self.f.options.timing_source_adoption
        self.f.points={'occ-000-r01':2.,'occ-001-r01':12.,'occ-001-r02':18.,'occ-002-r01':22.}
        self.prior=self.f.invoke()
        self.assertEqual(len(self.f.calls),2)
        self.assertEqual(pipeline.timing_uncertainty_errors(self.prior),[])
        shutil.rmtree(self.f.song/'.transcription/source-pass-original')
        self.f.setup_source(['A','B','B','X','C'])
        archived=Path(self.f.declaration['prior_timing']['path']);fixtures.write_json(archived,self.prior)
        self.f.declaration['prior_timing']['sha256']=source.file_hash(archived)
        fixtures.write_json(self.f.target,self.prior)
        self.f.calls=[]
    def provider(self,model,key,prompt,**kwargs):
        self.f.points={'occ-002-r01':15. if model==self.f.options.model else 19.}
        return self.f.provider(model,key,prompt,**kwargs)
    def test_inserted_onset_before_proven_last_repeat_escalates_only_new_line(self):
        with patch.object(pipeline.gemini,'call',side_effect=self.provider):result=self.f.invoke()
        self.assertEqual([row['start'] for row in result['sequence']],[2.,12.,19.,22.])
        self.assertEqual([model for model,_,_ in self.f.calls],[self.f.options.model]*2+[self.f.options.pro_model]*2)
        self.assertEqual([ids for _,ids,_ in self.f.calls],[['occ-002-r01']]*4)
        self.assertEqual(result['sequence'][1]['repeats'],2)
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('successful boundary proof must resume')):
            self.assertEqual(self.f.invoke(),result)
    def test_legitimate_new_onset_after_last_repeat_uses_flash_without_remeasuring_old_repeats(self):
        self.f.points={'occ-002-r01':19.};result=self.f.invoke()
        self.assertEqual([row['start'] for row in result['sequence']],[2.,12.,19.,22.])
        self.assertEqual([ids for _,ids,_ in self.f.calls],[['occ-002-r01']]*2)
        self.assertEqual(pipeline.timing_uncertainty_errors(result),[])
    def test_own_source_adoption_output_keeps_last_repeat_proof_on_subsequent_adoption(self):
        # Separate stage roots preserve every prior declaration/archive byte.
        audio=self.f.audio
        self.f.root=self.f.root/'first-adoption';self.f.root.mkdir()
        self.f.song=self.f.root/'song';self.f.song.mkdir()
        self.f.audio=self.f.song/'audio.m4a';shutil.copy2(audio,self.f.audio)
        self.f.setup_source(['A','B','B','C'])
        archived=Path(self.f.declaration['prior_timing']['path']);fixtures.write_json(archived,self.prior)
        self.f.declaration['prior_timing']['sha256']=source.file_hash(archived)
        fixtures.write_json(self.f.target,self.prior);self.f.calls=[]
        own=self.f.invoke();self.assertEqual(self.f.calls,[])
        audio=self.f.audio
        self.f.root=self.f.root/'next-adoption';self.f.root.mkdir()
        self.f.song=self.f.root/'song';self.f.song.mkdir()
        self.f.audio=self.f.song/'audio.m4a';shutil.copy2(audio,self.f.audio)
        self.f.setup_source(['A','B','B','X','C'])
        archived=Path(self.f.declaration['prior_timing']['path']);fixtures.write_json(archived,own)
        self.f.declaration['prior_timing']['sha256']=source.file_hash(archived)
        fixtures.write_json(self.f.target,own);self.f.calls=[]
        with patch.object(pipeline.gemini,'call',side_effect=self.provider):result=self.f.invoke()
        self.assertEqual([row['start'] for row in result['sequence']],[2.,12.,19.,22.])
        self.assertEqual([ids for _,ids,_ in self.f.calls],[['occ-002-r01']]*4)
        self.assertEqual([model for model,_,_ in self.f.calls],[self.f.options.model]*2+[self.f.options.pro_model]*2)

    def test_legacy_display_only_repeat_proof_routes_missing_neighbor_measurements_without_guessing(self):
        archived=Path(self.f.declaration['prior_timing']['path']);fixtures.write_json(archived,self.grid_prior)
        self.f.declaration['prior_timing']['sha256']=source.file_hash(archived)
        fixtures.write_json(self.f.target,self.grid_prior)
        self.f.points={'occ-001-r01':12.,'occ-001-r02':18.,'occ-002-r01':19.}
        result=self.f.invoke()
        self.assertEqual([ids for _,ids,_ in self.f.calls],[['occ-001-r01','occ-001-r02','occ-002-r01']]*2)
        self.assertEqual([row['start'] for row in result['sequence']],[2.,12.,19.,22.])
        self.assertEqual(result['sequence'][1]['repeats'],2)

    def test_unresolved_boundary_case_preserves_old_artifact_and_cannot_repay_on_resume(self):
        from bhakti_model_routes import UnitUnresolved
        before=self.f.target.read_bytes();self.f.points={'occ-002-r01':15.}
        with self.assertRaises(UnitUnresolved):self.f.invoke()
        self.assertEqual(len(self.f.calls),4);self.assertEqual(self.f.target.read_bytes(),before)
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('terminal repeated boundary cannot repay')):
            with self.assertRaises(UnitUnresolved):self.f.invoke()
        self.assertEqual(self.f.target.read_bytes(),before)

if __name__=='__main__':unittest.main()

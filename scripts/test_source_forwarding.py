"""Narrow executor boundary test: actual execute_song forwards exact selection."""
import argparse,copy,importlib.util,json,os,pathlib,sys,tempfile,time,unittest
from unittest.mock import patch
BASE=pathlib.Path(__file__).resolve().parents[1]
MAIN=pathlib.Path(os.environ.get('BHAKTI_TEST_PIPELINE_ROOT',BASE if (BASE/'scripts/bhakti_pipeline.py').is_file() else pathlib.Path.cwd()))
sys.path.insert(0,str(MAIN/'scripts'))
spec=importlib.util.spec_from_file_location('source_forwarding_library',BASE/'scripts/bhakti_library_pass.py');library=importlib.util.module_from_spec(spec);spec.loader.exec_module(library)
import bhakti_library_source_pass as adapter
class ForwardingTests(unittest.TestCase):
 def test_actual_source_branch_forwards_scope_and_coverage_without_changing_options(self):
  for stages,flags in [(['focused-audio-review'],{'audio':True,'occurrence_ids':['occ-001']}),(['semantic-review'],{'coverage_requested':True})]:
   with self.subTest(flags=flags),tempfile.TemporaryDirectory() as td:
    root=pathlib.Path(td)/'root';state=pathlib.Path(td)/'state';song=root/'songs/fixture';song.mkdir(parents=True);(root/'data').mkdir()
    (song/'data.js').write_text('window.SONG_META = {}; window.SONG_LINES = {}; window.SONG_SEQUENCE = []; window.SONG_TIMINGS = [];')
    (root/'data/editorial_baselines.json').write_text(json.dumps({'version':1,'songs':{}}))
    options=argparse.Namespace(model='test/flash');row={'slug':'fixture','dispatchEligible':True,'plannedStages':stages,'flags':flags,'defects':[],'evidenceGaps':[],'fingerprints':{'all':'test-input'}}
    seen=[]
    def observe(**kw):seen.append(kw);return {'status':'unresolved','publicationEligible':False,'issues':['observed only']}
    with patch.object(library,'guard_original_inputs'),patch.object(library,'prepare_workspace',return_value=pathlib.Path(td)/'workspace'),patch.object(adapter,'run_source_candidate',side_effect=observe),patch.object(library,'audit_current_reader',side_effect=AssertionError('observation cannot become semantic acceptance')):
     result=library.execute_song(root,row,state,options,time.time()+60)
    self.assertFalse(result['publicationEligible']);self.assertEqual(len(seen),1)
    forwarded=seen[0]['options'];self.assertEqual(forwarded.source_review_flags,flags);self.assertEqual(forwarded.source_coverage_requested,flags.get('coverage_requested',False));self.assertFalse(hasattr(options,'source_review_flags'))
if __name__=='__main__':unittest.main()

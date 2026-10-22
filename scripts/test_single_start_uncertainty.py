"""Regression: Satgur occ064 boundary-cut responses must never become timings."""
import argparse
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import bhakti_pipeline as p

# Exact substantive packet fields from production raw responses:
# 5040c93b: source905.822–917.867s; 0eb823ce: same clip.
CUT_RESPONSES = [
    {'occurrence_id': 'occ-064', 'start': 0.0, 'uncertainty': 'cut off by clip start boundary'},
    {'occurrence_id': 'occ-064', 'start': 0.0, 'uncertainty': 'cut off at start of clip'},
]

class SingleStartUncertaintyTests(unittest.TestCase):
    def run_packets(self, packets, candidate=912.322, lower=911.822, upper=911.867):
        occurrences = [{'occurrence_id':'occ-064','source_text':'ਮਨ ਮੇਰੇ ਮਨ ਮੇਰੇ','roman':'Man mere man mere','ref':'line-000','repeats':1}]
        opts=argparse.Namespace(model='google/gemini-3.7-flash',timeout=600)
        with tempfile.TemporaryDirectory() as td, patch.object(p.subprocess,'run'), patch.object(p.gemini,'key',return_value='dummy'), patch.object(p.gemini,'call',side_effect=[{'packet':copy.deepcopy(x)} for x in packets]) as call:
            result=p.refine_single_start(Path('dummy.m4a'),occurrences,0,[candidate],957.226,opts,Path(td),lower_bound=lower,upper_bound=upper)
        return result,call

    def test_actual_two_agreeing_cut_off_responses_are_not_evidence(self):
        result,_=self.run_packets(CUT_RESPONSES)
        self.assertTrue(result['validation_errors'])
        self.assertTrue(all(a['validation_errors'] for a in result['attempts']))

    def test_other_substantive_uncertainty_blocks_even_corroborated_point(self):
        for note in ['perhaps later repetition','first syllable masked','unclear pickup']:
            with self.subTest(note=note):
                packet={'occurrence_id':'occ-064','start':6.5,'uncertainty':note,'onset_at_clip_start':False}
                result,_=self.run_packets([packet,packet])
                self.assertTrue(result['validation_errors'])

    def test_positive_clear_start_and_established_none_sentinels(self):
        for note in ['', 'none','No','null','n/a']:
            with self.subTest(note=note):
                packet={'occurrence_id':'occ-064','start':6.5,'uncertainty':note,'onset_at_clip_start':False}
                result,_=self.run_packets([packet,packet])
                self.assertFalse(result['validation_errors'])

    def test_zero_requires_explicit_complete_onset_evidence(self):
        for explicit in [False,None,1,'true']:
            packet={'occurrence_id':'occ-064','start':0.0,'uncertainty':''}
            if explicit is not None:packet['onset_at_clip_start']=explicit
            result,_=self.run_packets([packet,packet],candidate=0,lower=None,upper=None)
            self.assertTrue(result['validation_errors'])
        packet={'occurrence_id':'occ-064','start':0.0,'uncertainty':'','onset_at_clip_start':True}
        result,_=self.run_packets([packet,packet],candidate=0,lower=None,upper=None)
        self.assertFalse(result['validation_errors'])
        self.assertEqual(result['start'],0)

    def test_explicit_onset_flag_cannot_override_cut_off_uncertainty(self):
        packet={**CUT_RESPONSES[0],'onset_at_clip_start':True}
        result,_=self.run_packets([packet,packet])
        self.assertTrue(result['validation_errors'])

    def test_release_guard_rejects_legacy_accepted_cut_off_evidence(self):
        timing={'validation_errors':[],'uncertain_occurrence_ids':[], 'refinements':[{'kind':'single','occurrence_id':'occ-064','start':905.822,'validation_errors':[], 'attempts':[{'start':905.822,'validation_errors':[],'uncertainty_note':x['uncertainty'],'response':{'packet':x}} for x in CUT_RESPONSES]}]}
        with patch.object(p,'validate_ids',return_value=[]),patch.object(p,'validate_line_contract',return_value=[]):
            self.assertTrue(p.publication_errors({'packet':{}},timing,{'packet':{}},{'packet':{}}))

    def test_release_guard_does_not_treat_rejected_attempt_as_selected(self):
        timing={'validation_errors':[],'uncertain_occurrence_ids':[], 'refinements':[{'kind':'single','occurrence_id':'occ-064','start':912.322,'candidate_measurements':[912.322],'validation_errors':[], 'attempts':[{'start':905.822,'validation_errors':['uncertain'],'uncertainty_note':'cut off','response':{'packet':CUT_RESPONSES[0]}},{'start':912.322,'validation_errors':[],'uncertainty_note':'','response':{'packet':{'occurrence_id':'occ-064','start':6.5,'uncertainty':'','onset_at_clip_start':False}}}]}]}
        with patch.object(p,'validate_ids',return_value=[]),patch.object(p,'validate_line_contract',return_value=[]):
            self.assertFalse(p.publication_errors({'packet':{}},timing,{'packet':{}},{'packet':{}}))

    def test_uncertain_plus_one_uncorroborated_clear_response_is_not_consensus(self):
        uncertain={'occurrence_id':'occ-064','start':10.0,'uncertainty':'masked initial syllable','onset_at_clip_start':False}
        clear={**uncertain,'uncertainty':''}
        result,_=self.run_packets([uncertain,clear])
        self.assertTrue(result['validation_errors'])

    def test_legacy_cache_is_rejected_without_dispatch(self):
        timing={'publication_status':'review-required','validation_errors':[],'refinements':[{'kind':'single','occurrence_id':'occ-064','start':905.822,'validation_errors':[],'attempts':[{'start':905.822,'validation_errors':[],'uncertainty_note':'cut off','response':{'packet':CUT_RESPONSES[0]}}]}]}
        with patch.object(p,'read_packet',return_value=timing),patch.object(p.gemini,'call') as call:
            with self.assertRaisesRegex(RuntimeError,'cached timing'):
                p.align(Path('song'),{'packet':{}},Path('dummy.m4a'),argparse.Namespace(force=False))
            call.assert_not_called()

    def test_release_guard_allows_valid_report_superseding_cut_off(self):
        old={'kind':'single','occurrence_id':'occ-064','start':905.822,'validation_errors':[], 'attempts':[{'start':905.822,'validation_errors':[],'uncertainty_note':'cut off','response':{'packet':CUT_RESPONSES[0]}}]}
        new={'kind':'single','occurrence_id':'occ-064','start':912.322,'candidate_measurements':[912.322],'validation_errors':[], 'attempts':[{'start':912.322,'validation_errors':[],'uncertainty_note':'','response':{'packet':{'start':6.5,'uncertainty':'','onset_at_clip_start':False}}}]}
        timing={'sequence':[{'occurrence_id':'occ-064','start':912.322}],'validation_errors':[],'refinements':[old,new]}
        with patch.object(p,'validate_ids',return_value=[]),patch.object(p,'validate_line_contract',return_value=[]):
            self.assertFalse(p.publication_errors({'packet':{}},timing,{'packet':{}},{'packet':{}}))
            timing['sequence'][0]['start']=905.822
            self.assertTrue(p.publication_errors({'packet':{}},timing,{'packet':{}},{'packet':{}}))

    def test_legacy_same_report_old_uncertain_attempt_does_not_poison_clear_winner(self):
        old={'start':905.822,'validation_errors':[],'uncertainty_note':'cut off','response':{'packet':CUT_RESPONSES[0]}}
        clear={'start':912.322,'validation_errors':[],'uncertainty_note':'','response':{'packet':{'start':6.5,'uncertainty':'','onset_at_clip_start':False}}}
        timing={'sequence':[{'occurrence_id':'occ-064','start':912.322}],'refinements':[{'kind':'single','occurrence_id':'occ-064','start':912.322,'candidate_measurements':[912.322],'validation_errors':[],'attempts':[old,clear]}]}
        self.assertFalse(p.timing_uncertainty_errors(timing))
        timing['refinements'][0]['candidate_measurements']=[920.0]
        self.assertTrue(p.timing_uncertainty_errors(timing))

    def test_numeric_string_zero_cannot_bypass_boundary_evidence(self):
        packet={'occurrence_id':'occ-064','start':'0','uncertainty':''}
        result,_=self.run_packets([packet,packet],candidate=0,lower=None,upper=None)
        self.assertTrue(result['validation_errors'])

    def test_unused_historical_uncertainty_does_not_poison_selected_sequence(self):
        timing={'sequence':[{'occurrence_id':'occ-065','start':920.0}], 'refinements':[{'kind':'single','occurrence_id':'occ-064','start':905.822,'validation_errors':[],'attempts':[{'start':905.822,'validation_errors':[],'response':{'packet':CUT_RESPONSES[0]}}]}]}
        self.assertFalse(p.timing_uncertainty_errors(timing))

    def test_malformed_uncertainty_is_not_a_clear_sentinel(self):
        for value in [False,None,0,[],{}]:
            packet={'occurrence_id':'occ-064','start':6.5,'uncertainty':value,'onset_at_clip_start':False}
            result,_=self.run_packets([packet,packet])
            self.assertTrue(result['validation_errors'])

    def test_align_clears_coarse_uncertainty_only_after_complete_clear_refinement(self):
        occurrence={'occurrence_id':'occ-064'}
        for final_errors in [[],['unresolved first syllable']]:
            with self.subTest(errors=final_errors), tempfile.TemporaryDirectory() as td:
                opts=argparse.Namespace(force=False,model='google/gemini-3.7-flash',timeout=600)
                sequence=[{'occurrence_id':'occ-064','start':0.5}]
                with patch.object(p,'read_packet',return_value=None),patch.object(p,'display_occurrences',return_value=[occurrence]),patch.object(p.gemini,'duration_seconds',return_value=10),patch.object(p,'canonical_timing_audio',return_value=Path('audio.m4a')),patch.object(p.gemini,'key',return_value='dummy'),patch.object(p.gemini,'call',return_value={'packet':{}}),patch.object(p,'timing_sequence_from_response',return_value=(sequence,[],['occ-064'])),patch.object(p,'refine_all_starts',return_value=(sequence,[],final_errors)):
                    result=p.align(Path(td),{'packet':{'verified_lines':[{'id':'line'}]}},Path('audio.m4a'),opts)
                self.assertEqual(result['uncertain_occurrence_ids'],['occ-064'] if final_errors else [])
                self.assertEqual(result['publication_status'],'blocked' if final_errors else 'review-required')

    def test_release_guard_rejects_explicit_uncertain_occurrence_ids(self):
        with patch.object(p,'validate_ids',return_value=[]),patch.object(p,'validate_line_contract',return_value=[]):
            self.assertTrue(p.publication_errors({'packet':{}},{'uncertain_occurrence_ids':['occ-064']},{'packet':{}},{'packet':{}}))

if __name__=='__main__':unittest.main()

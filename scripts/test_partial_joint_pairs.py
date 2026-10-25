"""Saved real packets test recovery, not new model/acoustic accuracy."""
import copy
import json
import hashlib
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
import unittest

import bhakti_pipeline as p

DATA = json.loads((Path(__file__).parent / 'fixtures/tav-partial-timing.json').read_text())

class PartialPairTests(unittest.TestCase):
    def report(self, group):
        return copy.deepcopy(next(x['report'] for x in DATA['reports'] if x['report']['region']['index'] == group))

    def recover(self, report, **kwargs):
        return p.joint_pair_evidence(report, expected_region=report['region'],
            expected_fingerprint=report['input_fingerprint'], duration=DATA['duration_seconds'], **kwargs)

    def test_actual_all_six_groups_exact_population_and_no_mutation(self):
        good = {0:[3,4,5,6,7,8], 1:[10,11,12,13], 2:[16,17],
                3:[21,22,23,24,25,26], 4:[27,28,29,30,32], 5:[33,34,35,36]}
        held = {0:[], 1:[9,14], 2:[15], 3:[], 4:[31], 5:[37,38]}
        total=[]
        for group in range(6):
            report=self.report(group);original=copy.deepcopy(report)
            result=self.recover(report,allow_partial_rows=True)
            with self.subTest(group=group):
                self.assertEqual([r['timing_id'] for r in result['agreed']], [f'occ-{i:03}-r01' for i in good[group]])
                self.assertEqual(result['held_timing_ids'],[f'occ-{i:03}-r01' for i in held[group]])
                self.assertEqual(report,original)
            total += result['agreed']
        self.assertEqual(len(total),27)
        fourth=self.recover(self.report(4),allow_partial_rows=True)
        self.assertEqual(fourth['agreed'][-1]['start'],231.75)
        self.assertEqual(fourth['agreed'][-1]['measurements'],[231.9,231.6])

    def test_strict_default_keeps_whole_invalid_packet_hold(self):
        for group in (1,4):
            with self.subTest(group=group),self.assertRaises(ValueError):self.recover(self.report(group))

    def test_structure_or_source_binding_failure_never_recovers(self):
        for kind in ('missing','duplicate','reordered','wrong_clip','fingerprint'):
            r=self.report(1);rows=r['passes'][1]['response']['packet']['starts']
            if kind=='missing':rows.pop()
            elif kind=='duplicate':rows[1]['timing_id']=rows[0]['timing_id']
            elif kind=='reordered':rows[0],rows[1]=rows[1],rows[0]
            elif kind=='wrong_clip':r['passes'][1]['region']['clip_start']+=1
            else:r['input_fingerprint']='altered'
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                p.joint_pair_evidence(r,expected_region=self.report(1)['region'],
                    expected_fingerprint=self.report(1)['input_fingerprint'],duration=DATA['duration_seconds'],allow_partial_rows=True)

    def test_invalid_individual_row_is_held_without_suppressing_valid_neighbors(self):
        for change in ({'start':float('nan')},{'start':True},{'start':-1},{'start':70},
                       {'uncertainty':'initial syllable is masked'}):
            r=self.report(0);r['passes'][0]['response']['packet']['starts'][2].update(change)
            result=self.recover(r,allow_partial_rows=True)
            with self.subTest(change=change):
                self.assertEqual(result['held_timing_ids'],['occ-005-r01'])
                self.assertEqual([x['timing_id'] for x in result['agreed']],
                                 ['occ-003-r01','occ-004-r01','occ-006-r01','occ-007-r01','occ-008-r01'])

    def test_individually_agreeing_but_order_ambiguous_pairs_both_held(self):
        r=self.report(0)
        # Absolute pairs30/30.2 and30.1/30.1 agree, but second hearing reverses order.
        r['passes'][0]['response']['packet']['starts'][0]['start']=20
        r['passes'][0]['response']['packet']['starts'][1]['start']=20.1
        r['passes'][1]['response']['packet']['starts'][0]['start']=30.2
        r['passes'][1]['response']['packet']['starts'][1]['start']=30.1
        result=self.recover(r,allow_partial_rows=True)
        self.assertEqual(result['held_timing_ids'],['occ-003-r01','occ-004-r01'])
        self.assertEqual([x['timing_id'] for x in result['agreed']],['occ-005-r01','occ-006-r01','occ-007-r01','occ-008-r01'])

    def test_actual_selected_evidence_opt_in_and_final_coverage_still_required(self):
        r=self.report(1)
        item={'region':r['region'],'input_fingerprint':r['input_fingerprint'],'report':r,
              'select_timing_ids':['occ-010-r01','occ-011-r01','occ-012-r01','occ-013-r01'],
              'allow_partial_rows':True}
        def selected():
            return p.selected_joint_pairs([item],DATA['ordered_occurrences'],DATA['duration_seconds'],
                                          DATA['audio_sha256'],DATA['source_identity'])
        pairs=selected();self.assertEqual(len(pairs),4)
        with self.assertRaises(ValueError):p.assemble_joint_pair_evidence(DATA['ordered_occurrences'],pairs,DATA['duration_seconds'])
        item['select_timing_ids'].append('occ-014-r01')
        with self.assertRaises(ValueError):selected()
        item['select_timing_ids'].pop();item['allow_partial_rows']='yes'
        with self.assertRaises(ValueError):selected()

    def test_nonboolean_opt_in_rejected_before_report_access(self):
        for value in (None,0,1,'true',[],{}):
            with self.subTest(value=value),self.assertRaises(ValueError):
                p.joint_pair_evidence(None,expected_region=None,expected_fingerprint='',
                                     duration=311.201,allow_partial_rows=value)

    def test_actual_continuation_loader_preserves_opt_in_in_durable_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);audio=root/'audio.m4a';audio.write_bytes(b'identity-only-no-provider')
            audio_hash=hashlib.sha256(audio.read_bytes()).hexdigest()
            r=self.report(1);r['input_fingerprint']=p.joint_region_fingerprint(
                audio_hash,r['region'],DATA['duration_seconds'],DATA['source_identity'])
            saved=root/'saved.json';saved.write_text(json.dumps(r))
            ids=['occ-010-r01','occ-011-r01','occ-012-r01','occ-013-r01']
            all_ids=[x['timing_id'] for x in p.expanded_timing_targets(DATA['ordered_occurrences'])]
            remaining=[i for i in all_ids if i not in ids]
            self.assertEqual(len(remaining),39)
            pending={'index':99,'clip_start':0.,'clip_end':DATA['duration_seconds'],
                     'target_indices':list(range(len(DATA['ordered_occurrences']))),
                     'target_occurrences':DATA['ordered_occurrences'],
                     'preceding_context':None,'following_context':None,'target_timing_ids':remaining}
            plan={'version':1,'audio_sha256':audio_hash,'source_identity':DATA['source_identity'],
                  'ordered_occurrences':DATA['ordered_occurrences'],'duration_seconds':DATA['duration_seconds'],
                  'retained':[{'path':str(saved),'sha256':hashlib.sha256(saved.read_bytes()).hexdigest(),
                     'region':r['region'],'input_fingerprint':r['input_fingerprint'],'select_timing_ids':ids}],
                  'pending':[{'region':pending,'select_timing_ids':remaining}]}
            path=root/'plan.json'
            def options():
                path.write_text(json.dumps(plan))
                return SimpleNamespace(timing_joint_continuation={'path':str(path),
                    'sha256':hashlib.sha256(path.read_bytes()).hexdigest()},timing_source_identity=DATA['source_identity'])
            with patch.object(p,'run_joint_timing_unit',side_effect=RuntimeError('pending checkpoint')) as run:
                with self.assertRaises(ValueError):
                    p.align_joint_continuation(root,audio,DATA['ordered_occurrences'],DATA['duration_seconds'],options())
                run.assert_not_called()
                plan['retained'][0]['allow_partial_rows']=True
                with self.assertRaisesRegex(RuntimeError,'pending checkpoint'):
                    p.align_joint_continuation(root,audio,DATA['ordered_occurrences'],DATA['duration_seconds'],options())
                run.assert_called_once()
            receipts=list(root.rglob('retained.json'));self.assertEqual(len(receipts),1)
            receipt=json.loads(receipts[0].read_text())
            self.assertIs(receipt['evidence'][0]['allow_partial_rows'],True)
            self.assertEqual([x['timing_id'] for x in receipt['pairs']],ids)

if __name__=='__main__':unittest.main()

"""Partial joint evidence keeps only already agreeing exact source measurements."""
import copy,json,sys,unittest
from pathlib import Path
import bhakti_pipeline as p
FIXTURES=Path(__file__).resolve().parent/'fixtures/joint_timing'
BAD=FIXTURES/'partial.json'
GOOD=FIXTURES/'accepted.json'
SCOPE=FIXTURES/'scope.json'


class JointPairRetention(unittest.TestCase):
    def setUp(self):
        self.bad=json.loads(BAD.read_text());self.good=json.loads(GOOD.read_text())
        self.region=copy.deepcopy(self.bad['region']);self.fingerprint=self.bad['input_fingerprint']
    def extract(self,report=None):
        return p.joint_pair_evidence(report or self.bad,expected_region=self.region,
            expected_fingerprint=self.fingerprint,duration=922.721)
    def test_actual_pro_nineteen_pairs_preserved_one_held_no_candidate_mutation(self):
        original=copy.deepcopy(self.bad);result=self.extract()
        self.assertEqual(result['held_timing_ids'],['occ-017-r01'])
        expected=[x['timing_id'] for x in self.bad['passes'][0]['validation']['starts'] if x['timing_id']!='occ-017-r01']
        self.assertEqual([x['timing_id'] for x in result['agreed']],expected)
        self.assertEqual(len(result['agreed']),19)
        self.assertNotIn('occ-017-r01',[x['timing_id'] for x in result['agreed']])
        self.assertEqual(next(x for x in result['agreed'] if x['timing_id']=='occ-017-r02')['start'],305.45)
        self.assertEqual(self.bad,original)
        self.assertEqual(self.bad['starts'],[]) # The original region still failed.
    def test_accepted_first_region_sixteen_pairs_unchanged(self):
        result=p.joint_pair_evidence(self.good,expected_region=self.good['region'],
            expected_fingerprint=self.good['input_fingerprint'],duration=922.721)
        self.assertEqual(result['held_timing_ids'],[])
        self.assertEqual([{k:x[k] for k in ('timing_id','start')} for x in result['agreed']],self.good['expanded_starts'])
        self.assertEqual(len(result['agreed']),16)
    def test_changed_fingerprint_source_order_or_clip_rejects(self):
        for mode in ['fingerprint','source','order','clip']:
            report=copy.deepcopy(self.bad)
            if mode=='fingerprint':report['input_fingerprint']='0'*64
            elif mode=='source':report['region']['target_occurrences'][0]['source_text']+=' अन्य'
            elif mode=='order':report['passes'][1]['region']['target_occurrences'].reverse()
            else:report['passes'][1]['region']['clip_start']+=1
            with self.subTest(mode=mode),self.assertRaises(ValueError):self.extract(report)
    def test_missing_duplicate_reordered_uncertain_nonfinite_response_has_no_partial_acceptance(self):
        for mode in ['missing','duplicate','reordered','uncertain','nan','outside']:
            report=copy.deepcopy(self.bad);rows=report['passes'][0]['response']['packet']['starts']
            if mode=='missing':rows.pop()
            elif mode=='duplicate':rows[1]=copy.deepcopy(rows[0])
            elif mode=='reordered':rows[0],rows[1]=rows[1],rows[0]
            elif mode=='uncertain':rows[0]['uncertainty']='initial consonant masked'
            elif mode=='nan':rows[0]['start']=float('nan')
            else:rows[0]['start']=10000
            with self.subTest(mode=mode),self.assertRaises(ValueError):self.extract(report)
    def test_current_half_second_rule_not_widened_or_flash_substituted(self):
        self.assertEqual(self.extract()['held_timing_ids'],['occ-017-r01'])
        # There is deliberately no "preferred model" or new tolerance parameter.
        with self.assertRaises(TypeError):p.joint_pair_evidence(self.bad,expected_region=self.region,
            expected_fingerprint=self.fingerprint,duration=922.721,tolerance=.6)
    def test_actual_lookalike_couplet_across_regions_is_not_safe_to_retain(self):
        first=p.joint_pair_evidence(self.good,expected_region=self.good['region'],
            expected_fingerprint=self.good['input_fingerprint'],duration=922.721)['agreed']
        second=self.extract()['agreed']
        self.assertEqual(next(x['start'] for x in first if x['timing_id']=='occ-013-r01'),273.2)
        self.assertEqual(next(x['start'] for x in second if x['timing_id']=='occ-015-r01'),273.2)
        self.assertLess(next(x['start'] for x in second if x['timing_id']=='occ-015-r01'),
                        next(x['start'] for x in first if x['timing_id']=='occ-014-r01'))
        # Full-order checks reject the apparent agreement even before later regions exist.
        subset=self.good['region']['target_occurrences']+self.bad['region']['target_occurrences'][:2]
        pairs=first+[x for x in second if x['timing_id'] in ('occ-015-r01','occ-016-r01')]
        with self.assertRaisesRegex(ValueError,'non-increasing'):
            p.assemble_joint_pair_evidence(subset,pairs,922.721)

    def test_final_order_requires_every_repeat_once_and_rejects_changed_source(self):
        scope=json.loads(SCOPE.read_text())
        occurrences=scope['ordered_occurrences']
        first=p.joint_pair_evidence(self.good,expected_region=self.good['region'],expected_fingerprint=self.good['input_fingerprint'],duration=922.721)['agreed']
        second=[x for x in self.extract()['agreed'] if x['timing_id'] not in ('occ-015-r01','occ-016-r01')]
        # Synthetic measurements are only an assembly fixture; never a proposed audio result.
        expanded=p.expanded_timing_targets(occurrences)
        by_id={x['timing_id']:copy.deepcopy(x) for x in expanded}
        new=[{**by_id[tid],'start':point} for tid,point in [('occ-015-r01',286.),('occ-016-r01',292.),('occ-017-r01',298.8)]]
        third=[{**row,'start':600+index*10} for index,row in enumerate(p.expanded_timing_targets(scope['third_region']['target_occurrences']))]
        complete=first+second+new+third
        result=p.assemble_joint_pair_evidence(occurrences,complete,922.721)
        self.assertEqual(len(result['sequence']),51);self.assertEqual(len(result['expanded_starts']),59)
        self.assertEqual(next(x for x in result['expanded_starts'] if x['timing_id']=='occ-017-r02')['start'],305.45)
        for mode in ['missing','duplicate','wrongsource','nonincreasing']:
            changed=copy.deepcopy(complete)
            if mode=='missing':changed.pop()
            elif mode=='duplicate':changed.append(copy.deepcopy(changed[0]))
            elif mode=='wrongsource':changed[0]['source_text']+=' अन्य'
            else:changed[0]['start']=500
            with self.subTest(mode=mode),self.assertRaises(ValueError):p.assemble_joint_pair_evidence(occurrences,changed,922.721)

if __name__=='__main__':unittest.main()

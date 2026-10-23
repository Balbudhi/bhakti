"""Long source ownership: exact accepted overlap mapping, never coarse timestamps."""
import copy,unittest
import bhakti_library_source_pass as source
import bhakti_pipeline as pipeline
import test_source_adoption_design as fixtures


def long_fixture(split_repeat=False):
    f=fixtures.SourceDeltaContractTests()
    reader,plan,observed=f.split_observations()
    for interval in reader['SONG_TIMINGS']:
        interval['start']*=30;interval['end']*=30
    # Scale exact accepted acoustic cores/clips to a 20-minute recording.
    for unit in plan['units']:
        for key in ('clip_start','clip_end','core_start','core_end'):
            if key in unit:unit[key]*=30
    for item in observed['unit_results']:
        unit=item['unit'];seg=item['result']['segment_audits'][0]['segment']
        for key in ('clip_start','clip_end','core_start','core_end'):
            unit[key]*=30;seg[key]*=30
    if split_repeat:
        observed['unit_results'][0]['result']['segment_audits'][0]['audit']['packet']=fixtures.packet(['A','B'])
        observed['unit_results'][1]['result']['segment_audits'][0]['audit']['packet']=fixtures.packet(['B','B','C','D'])
    for item in observed['unit_results']:item['result_digest']=source.digest(item['result'])
    delta=source.reconcile_source_observations(reader,plan,observed)
    if delta['status']!='proposed':raise AssertionError(delta)
    return reader,delta,observed

class LongSourceOwnershipDesignTests(unittest.TestCase):
    def plan(self,reader,delta):
        return source.plan_source_timing(reader,delta,None,audio_sha256='a'*64,trim={},duration_seconds=1200.)
    def target_ids(self,region):
        # Explicit partial repeat ownership is necessary only across units;
        # ordinary callers keep the complete canonical target population.
        return region.get('target_timing_ids') or [r['timing_id'] for r in pipeline.expanded_timing_targets(region['target_occurrences'])]
    def test_long_missing_prior_partitions_by_accepted_source_units_without_omission_or_duplication(self):
        reader,delta,observed=long_fixture();result=self.plan(reader,delta)
        self.assertEqual(result['retained_starts'],{})
        self.assertEqual(len(result['regions']),2)
        self.assertEqual([self.target_ids(r) for r in result['regions']],
                         [['occ-000-r01','occ-001-r01','occ-002-r01'],['occ-003-r01']])
        for region in result['regions']:
            self.assertLessEqual(region['clip_end']-region['clip_start'],900.)
        self.assertEqual([(r['clip_start'],r['clip_end']) for r in result['regions']],[(0.,900.),(300.,1200.)])
    def test_repeat_block_crossing_source_units_keeps_global_repeat_identity(self):
        reader,delta,observed=long_fixture(split_repeat=True);result=self.plan(reader,delta)
        self.assertEqual([self.target_ids(r) for r in result['regions']],
            [['occ-000-r01','occ-001-r01'],['occ-001-r02','occ-002-r01','occ-003-r01']])
        # Both units refer to the same actual displayed block, preserving its
        # two audited performances. Do not renumber repeat two to repeat one.
        self.assertEqual([r['repeats'] for r in result['ordered_occurrences']],[1,2,1,1])
    def test_changed_or_incomplete_source_unit_ownership_is_not_replaced_by_uniform_slices(self):
        reader,delta,_=long_fixture()
        self.assertIn('source_unit_coverage',delta,'reconciliation must preserve accepted source unit ownership')
        for defect in ('gap','duplicate','outside_clip'):
            changed=copy.deepcopy(delta)
            units=changed['source_unit_coverage']
            if defect=='gap':units[-1]['expanded_indices']=[]
            elif defect=='duplicate':units[-1]['expanded_indices']=[0,*units[-1]['expanded_indices']]
            else:units[-1]['clip_end']=1300.
            with self.subTest(defect=defect),self.assertRaises(ValueError):self.plan(reader,changed)
    def test_no_accepted_long_ownership_holds_before_creating_an_unbounded_question(self):
        reader,delta,_=long_fixture();delta.pop('source_unit_coverage',None)
        with self.assertRaisesRegex(ValueError,'ownership|bounded|source unit'):self.plan(reader,delta)

if __name__=='__main__':unittest.main()

"""Narrow extension tests for the EXISTING source/timing planner.

The sample witness below is an explicitly accepted deterministic precondition;
real media production of that witness is tested separately. Source confirmation
is similarly accepted fixture evidence, not a fabricated linguistic claim.
"""
import copy
import hashlib
import json
import unittest
import bhakti_pipeline as p
import bhakti_library_source_pass as source


def fixture():
    lines={key:{'source':native,'roman':roman,'english':english} for key,native,roman,english in [
        ('A','सूचना','sūcanā','An unrelated announcement.'),('B','राम','rāma','Rāma.'),
        ('C','नाम','nāma','The name.'),('D','सूचना','sūcanā','A different unrelated announcement.')]}
    reader={'SONG_META':{},'SONG_LINES':lines,
        'SONG_SEQUENCE':[{'ref':key,'section':'spoken' if key in 'ABD' else 'verse','repeats':1} for key in lines],
        'SONG_TIMINGS':[{'start':2.+10*i,'end':12.+10*i if i<3 else 40.} for i in range(4)]}
    draft=source.source_draft(reader);old=p.display_occurrences({'verified_lines':draft['lines'],'performance_order':draft['performance_order']})
    before={'time_axis':'native-presentation','version':2,'audio_sha256':'a'*64,'source_identity':{'trim':{}},'ordered_occurrences':old}
    prior={'source_identity':before,'input_fingerprint':hashlib.sha256(json.dumps(before,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest(),
        'ordered_occurrences':old,'duration_seconds':40.,'refinements':[
        {'grid':grid,'index':0,'clip_start':0.,'clip_end':40.,'cache_key':{'targets':copy.deepcopy(old)},
         'response':{'packet':{'starts':[{'occurrence_id':r['occurrence_id'],'start':2.+i*10} for i,r in enumerate(old)],'uncertain_occurrence_ids':[]}}}
        for grid in ['first','independent']]}
    rebuilt={'verified_lines':[r for r in draft['lines'] if r['id'] in ['B','C']],
        'performance_order':[r for r in draft['performance_order'] if r['line_id'] in ['B','C']], 'uncertainties':[]}
    trim={'application_version':2,'status':'applied','trim_start':5.1,'trim_end':29.3}
    delta={'status':'proposed','before_identity':{'audio_sha256':'b'*64,'trim_sha256':source.digest(trim),
        'reader_source_sha256':source.reader_source_identity(reader)},'rebuilt':rebuilt,
        'occurrence_lineage':[{'old_index':0,'new_index':None},{'old_index':1,'new_index':0},
                             {'old_index':2,'new_index':1},{'old_index':3,'new_index':None}],
        'reused_line_ids':['B','C'],'fresh_line_ids':[],'removed_line_ids':['A','D']}
    measurement={'version':1,'status':'verified','source_sha256':'a'*64,'output_sha256':'b'*64,
        'decoded_source_offset_seconds':5.125,'timeline_source_offset_seconds':5.375,
        'source_first_frame_pts':.25,'output_first_frame_pts':0.,'offset_error_seconds':1/48000,
        'verified_output_interval':{'start':.6,'end':24.2},
        'sample_windows':[{'source_start':v,'output_start':v-5.125,'samples':48000,'unique':True,'offset_samples':246000} for v in [6.,15.,27.]]}
    transform={'version':1,'kind':'boundary-timebase','status':'verified',
        'before':{'audio_sha256':'a'*64,'trim':{},'duration_seconds':40.},
        'after':{'audio_sha256':'b'*64,'trim':trim,'duration_seconds':24.2},
        'requested_interval':{'start':5.1,'end':29.3},
        'native':{'audio.m4a':{'before':{'sha256':'a'*64},'after':{'sha256':'b'*64},'measurement':measurement}},
        # Explicit accepted pure-fixture clock premise, not something inferred
        # by the validator from sample correspondence or a requested cut cue.
        'timing_basis':{'status':'verified','axis':'native-presentation',
            'before':{'audio_sha256':'a'*64,'time_axis':'native-presentation'},
            'after':{'audio_sha256':'b'*64,'time_axis':'native-presentation'}}}
    return reader,delta,prior,transform,trim


class HistoricalBoundaryTiming(unittest.TestCase):
    def plan(self,reader,delta,prior,transform,trim):
        operation=getattr(source,'plan_source_timing',None)
        self.assertTrue(callable(operation),'accepted source timing planner is not integrated')
        snapshot=copy.deepcopy((reader,delta,prior,transform,trim))
        result=operation(reader,delta,prior,audio_sha256='b'*64,trim=trim,duration_seconds=24.2,audio_transform=transform)
        self.assertEqual((reader,delta,prior,transform,trim),snapshot)
        return result

    def test_both_edge_removals_preserve_attached_spoken_occurrence_and_measured_interior_starts(self):
        values=fixture();reader,delta,prior,transform,trim=values
        result=self.plan(*values)
        self.assertEqual(result['retained_starts'],{'occ-000':6.625,'occ-001':16.625})
        self.assertEqual(result['regions'],[])
        self.assertEqual([r['ref'] for r in result['ordered_occurrences']],['B','C'])
        self.assertEqual(result['ordered_occurrences'][0]['section'],'spoken')
        self.assertEqual(reader['SONG_LINES']['B']['english'],'Rāma.')
        sequence,errors,uncertain=p.timing_sequence_from_response(result['ordered_occurrences'],
            {'starts':[{'occurrence_id':k,'start':v} for k,v in result['retained_starts'].items()],
             'uncertain_occurrence_ids':[]},24.2)
        self.assertEqual(errors,[]);self.assertEqual(uncertain,[])
        self.assertEqual([(r['start'],r['end']) for r in sequence],[(6.625,16.625),(16.625,24.2)])

    def test_uncorroborated_retained_row_routes_only_its_existing_timing_unit(self):
        values=list(fixture());values[2]['refinements'][1]['response']['packet']['uncertain_occurrence_ids']=['occ-002']
        result=self.plan(*values)
        self.assertEqual(result['retained_starts'],{'occ-000':6.625})
        self.assertEqual([r['occurrence_id'] for region in result['regions'] for r in region['target_occurrences']],['occ-001'])
        self.assertEqual(result['regions'][0]['retained_anchor_starts'],{'occ-000':6.625})

    def test_changed_audio_identity_or_packet_only_witness_is_not_a_timing_rebind(self):
        for mutation in ('wrong_before','wrong_after','pending','packet_only'):
            with self.subTest(mutation=mutation):
                values=list(fixture());transform=values[3]
                if mutation=='wrong_before':transform['before']['audio_sha256']='c'*64
                if mutation=='wrong_after':transform['after']['audio_sha256']='c'*64
                if mutation=='pending':transform['status']='pending'
                if mutation=='packet_only':
                    witness=transform['native']['audio.m4a']['measurement'];witness.pop('sample_windows');witness.pop('decoded_source_offset_seconds');witness.pop('timeline_source_offset_seconds');witness['packet_source_offset']=5.375
                with self.assertRaises(ValueError):self.plan(*values)

    def test_uncertain_source_membership_never_becomes_authorized_by_good_timebase(self):
        values=list(fixture());values[1]['status']='unresolved';values[1]['issues']=[{'detail':'attached spoken edge unclear'}]
        with self.assertRaises(ValueError):self.plan(*values)

    def test_absent_or_contradictory_legacy_clock_cannot_reuse_native_pts_offset(self):
        for mode in ('absent','canonical-without-origin','different-after-axis'):
            with self.subTest(mode=mode):
                values=list(fixture());identity=values[2]['source_identity']
                if mode=='absent':identity.pop('time_axis')
                if mode=='canonical-without-origin':identity['time_axis']='model-canonical'
                if mode=='different-after-axis':values[3]['timing_basis']['after']['time_axis']='decoded-samples'
                values[2]['input_fingerprint']=hashlib.sha256(json.dumps(identity,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
                with self.assertRaisesRegex(ValueError,'(?i)(clock|axis|origin|timebase)'):
                    self.plan(*values)

    def test_decoder_initialization_prefix_routes_affected_onset_without_losing_good_interior(self):
        values=list(fixture())
        values[3]['native']['audio.m4a']['measurement']['verified_output_interval']['start']=7.
        result=self.plan(*values)
        self.assertEqual(result['retained_starts'],{'occ-001':16.625})
        self.assertEqual([r['occurrence_id'] for region in result['regions'] for r in region['target_occurrences']],['occ-000'])

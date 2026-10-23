"""Design regressions for actual source-adoption align caller (not implemented).

Real audio files, FFmpeg, align, joint measurement validator, router and disk.
Only provider responses are synthetic; these prove routing/evidence behavior,
not auditory accuracy. Source receipt is a synthetic already-approved fixture.
"""
import argparse,copy,hashlib,json,re,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import audit_bhakti_contract as contract
import bhakti_pipeline as pipeline
import bhakti_library_source_pass as source
import bhakti_model_routes as routes
from test_source_timing_lineage_design import timing_fixture
from test_generic_source_caller import make_audio,js,write_json

class SourceTimingCallerDesignTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.song=self.root/'song';self.song.mkdir()
        self.audio=self.song/'audio.m4a';make_audio(self.audio,40)
        self.calls=[];self.points={};self.uncertain=False;self.wrong_flash=False
        self.addCleanup(patch.stopall)
        patch.object(pipeline.gemini,'key',return_value='fixture-not-a-key').start()
        patch.object(pipeline.gemini,'call',side_effect=self.provider).start()
    def setup_source(self,heard):
        self.reader,self.delta,self.prior,_=timing_fixture(['A','B','C','D'],heard)
        self.duration=pipeline.gemini.duration_seconds(self.audio)
        self.assertEqual(self.duration,40.)
        audio_hash=source.file_hash(self.audio);self.delta['before_identity']['audio_sha256']=audio_hash
        self.prior['source_identity']['audio_sha256']=audio_hash
        self.prior['input_fingerprint']=hashlib.sha256(json.dumps(self.prior['source_identity'],ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
        archive=self.song/'.transcription/source-pass-original';archive.mkdir(parents=True)
        js(archive/'data.js',self.reader);self.reader=contract.load_data(archive/'data.js')
        write_json(archive/'03-timing.json',self.prior)
        self.target=self.song/'.transcription/pipeline/03-timing.json';write_json(self.target,self.prior)
        self.old_bytes=self.target.read_bytes()
        # Synthetic accepted source route retains real durable router structure;
        # no paid source hearing or human authorization is implied by fixtures.
        route_dir=self.root/'source-routes'
        routes.run_unit(route_dir,'fixture:accepted-source','a'*64,lambda ctx:{'source':'fixture'},lambda value:[],
            deadline_at=time.time()+120,base_model=pipeline.MODEL,pro_model=routes.PRO_MODEL)
        state=next(route_dir.rglob('route-state.json'))
        receipt={'version':1,'status':'accepted-source','original_reader_digest':source.digest(self.reader),
            'before_identity':self.delta['before_identity'],'delta':self.delta,'delta_digest':source.digest(self.delta),
            'approved_source_order_digest':source.digest(self.delta['rebuilt']),
            'evidence_files':{str(p):source.file_hash(p) for p in (state,state.parent/'accepted-result.json')}}
        path=self.root/'accepted-source-delta.json';write_json(path,receipt)
        self.declaration={'path':str(path),'sha256':source.file_hash(path),
            'original_reader':{'path':str(archive/'data.js'),'sha256':source.file_hash(archive/'data.js')},
            'prior_timing':{'path':str(archive/'03-timing.json'),'sha256':source.file_hash(archive/'03-timing.json')}}
        self.options=argparse.Namespace(model=pipeline.MODEL,pro_model=routes.PRO_MODEL,force=False,
            timeout=30,refresh_timing=False,timing_deadline_at=time.time()+120,
            timing_source_adoption=self.declaration)
        self.audited={'packet':copy.deepcopy(self.delta['rebuilt'])}
    def provider(self,model,key,prompt,**kwargs):
        self.assertEqual(kwargs['schema_name'],'bhakti_joint_starts',
                         'changed source must use the scoped consumer, never restart a full recording pass')
        expanded=json.JSONDecoder().raw_decode(prompt.split('EXACT ORDERED TIMING TARGETS: ',1)[1])[0]
        bounds=re.search(r'SOURCE CLIP: ([0-9.]+)–([0-9.]+)',prompt)
        clip,end=map(float,bounds.groups())
        self.calls.append((model,[r['timing_id'] for r in expanded],clip))
        self.assertTrue({row['timing_id'] for row in expanded} <= set(self.points),
                        'align asked to remeasure unrelated retained performances')
        starts=[]
        for row in expanded:
            value=self.points[row['timing_id']]
            if self.wrong_flash and model==self.options.model:
                value=11.75
                self.assertLess(clip,value);self.assertLess(value,end)
                self.assertLess(value,12., 'wrong onset must violate retained preceding anchor')
            starts.append({'timing_id':row['timing_id'],'start':value-clip,
                'uncertainty':'masked first syllable' if self.uncertain else '',
                'onset_at_clip_start':value==clip})
        return {'packet':{'starts':starts},'resolved_model':model}
    def invoke(self):return pipeline.align(self.song,self.audited,self.audio,self.options)
    def test_inserted_returning_refrain_uses_local_scope_and_remaps_later_starts(self):
        self.setup_source(['A','B','A','C','D']);self.points={'occ-002-r01':17.}
        result=self.invoke()
        self.assertEqual([r['start'] for r in result['sequence']],[2.,12.,17.,22.,32.])
        self.assertEqual([ids for _,ids,_ in self.calls],[['occ-002-r01']]*2)
        self.assertEqual(result['validation_errors'],[])
        count=len(self.calls);self.assertEqual(self.invoke(),result);self.assertEqual(len(self.calls),count)
    def test_deletion_rebuilds_ends_from_surviving_starts_without_audio_dispatch(self):
        self.setup_source(['A','C','D']);result=self.invoke()
        self.assertEqual(self.calls,[])
        self.assertEqual([(r['start'],r['end']) for r in result['sequence']],[(2.,22.),(22.,32.),(32.,40.)])
    def test_agreeing_wrong_refrain_is_rejected_inside_route_and_only_region_escalates(self):
        self.setup_source(['A','B','A','C','D']);self.points={'occ-002-r01':17.};self.wrong_flash=True
        result=self.invoke()
        self.assertEqual([r['start'] for r in result['sequence']],[2.,12.,17.,22.,32.])
        self.assertEqual([model for model,_,_ in self.calls],[self.options.model]*2+[self.options.pro_model]*2)
        states=[json.loads(p.read_text()) for p in (self.song/'.transcription/pipeline/joint-timing').rglob('route-state.json')]
        self.assertEqual(len(states),1);self.assertEqual(len(states[0]['attempts']),2)
        self.assertEqual([ids for _,ids,_ in self.calls],[['occ-002-r01']]*4)
    def test_focused_uncertainty_holds_without_overwrite_or_provider_replay(self):
        self.setup_source(['A','B','X','C','D']);self.points={'occ-002-r01':17.};self.uncertain=True
        with self.assertRaises(routes.UnitUnresolved):self.invoke()
        self.assertEqual(len(self.calls),4);self.assertEqual(self.target.read_bytes(),self.old_bytes)
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('unresolved route must not repay')):
            with self.assertRaises(routes.UnitUnresolved):self.invoke()
        self.assertEqual(self.target.read_bytes(),self.old_bytes)
    def test_interruption_between_independent_regions_reuses_first_and_preserves_other_starts(self):
        self.setup_source(['A','X','B','C','X','D']);self.points={'occ-001-r01':7.,'occ-004-r01':27.}
        real_measure=pipeline.run_joint_timing_unit
        def interruption(song,audio,region,*args,**kwargs):
            if region['target_occurrences'][0]['occurrence_id']=='occ-004':raise KeyboardInterrupt('between units')
            return real_measure(song,audio,region,*args,**kwargs)
        with patch.object(pipeline,'run_joint_timing_unit',side_effect=interruption):
            with self.assertRaises(KeyboardInterrupt):self.invoke()
        self.assertEqual(len(self.calls),2);self.assertEqual(self.target.read_bytes(),self.old_bytes)
        result=self.invoke()
        self.assertEqual([r['start'] for r in result['sequence']],[2.,7.,12.,22.,27.,32.])
        self.assertEqual([ids for _,ids,_ in self.calls],[['occ-001-r01']]*2+[['occ-004-r01']]*2)
    def test_single_or_uncertain_prior_measurement_is_not_reused_as_proof(self):
        self.setup_source(['A','B','X','C','D'])
        self.prior['refinements'][1]['response']['packet']['uncertain_occurrence_ids']=['occ-001']
        archived=Path(self.declaration['prior_timing']['path']);write_json(archived,self.prior)
        self.declaration['prior_timing']['sha256']=source.file_hash(archived)
        self.points={'occ-001-r01':12.,'occ-002-r01':17.}
        result=self.invoke()
        self.assertEqual([ids for _,ids,_ in self.calls],[['occ-001-r01','occ-002-r01']]*2)
        self.assertEqual([r['start'] for r in result['sequence']],[2.,12.,17.,22.,32.])
    def test_success_cache_revalidates_raw_timing_candidate_without_dispatch(self):
        self.setup_source(['A','B','A','C','D']);self.points={'occ-002-r01':17.}
        self.invoke();accepted_bytes=self.target.read_bytes()
        candidate=next((self.song/'.transcription/pipeline/joint-timing').rglob('flash/candidate.json'))
        value=json.loads(candidate.read_text());value['tampered']=True;write_json(candidate,value)
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('corrupt timing route must not repay')) as call:
            with self.assertRaises((ValueError,RuntimeError,routes.RunFatal)):self.invoke()
            call.assert_not_called()
        self.assertEqual(self.target.read_bytes(),accepted_bytes)

    def test_archived_timing_tampering_is_detected_before_dispatch(self):
        self.setup_source(['A','B','X','C','D'])
        archived=Path(self.declaration['prior_timing']['path']);archived.write_text('{}')
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('input drift must not dispatch')) as call:
            with self.assertRaises((ValueError,RuntimeError)):self.invoke()
            call.assert_not_called()
        self.assertEqual(self.target.read_bytes(),self.old_bytes)

if __name__=='__main__':unittest.main()

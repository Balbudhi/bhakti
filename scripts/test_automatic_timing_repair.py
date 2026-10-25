"""Causal regressions; fixture numbers are old evidence, not an audio oracle."""
import argparse
import copy
import json
import inspect
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import bhakti_pipeline as p

FIXTURE = json.loads((Path(__file__).parent/'fixtures/satgur-timing.json').read_text())

class TimingRepairTests(unittest.TestCase):
    def setUp(self):
        self.t = copy.deepcopy(FIXTURE['timing'])
        self.a = copy.deepcopy(FIXTURE['audited'])
        self.occ = self.t['ordered_occurrences']
        self.duration = self.t['duration_seconds']

    def test_deterministic_routing_does_not_corroborate_single_audio_call(self):
        # Actual wrong acceptance pattern of occ045: hint672.670, one response672.190.
        target = self.occ[45]
        clear = {'occurrence_id':target['occurrence_id'], 'start':6.42,
                 'uncertainty':'','onset_at_clip_start':False}
        doubtful = {**clear,'uncertainty':'cannot distinguish adjacent identical phrase'}
        opts = argparse.Namespace(model='google/gemini-3.7-flash',timeout=600)
        with tempfile.TemporaryDirectory() as td, patch.object(p.subprocess,'run'), patch.object(p.gemini,'key',return_value='dummy'), patch.object(p.gemini,'call',side_effect=[{'packet':clear},{'packet':doubtful}]) as call:
            result = p.refine_single_start(Path('audio'),self.occ,45,[672.67],self.duration,opts,Path(td),lower_bound=671.77,upper_bound=701.1,**({'candidate_is_evidence':False} if 'candidate_is_evidence' in inspect.signature(p.refine_single_start).parameters else {}))
        self.assertEqual(call.call_count,2)
        self.assertTrue(result['validation_errors'])
        self.assertIs(result['candidate_is_evidence'],False)

    def test_routing_only_two_clear_audio_measurements_can_agree(self):
        packets = [{'packet':{'occurrence_id':'occ-045','start':s,'uncertainty':'','onset_at_clip_start':False}} for s in [6.42,6.52]]
        with tempfile.TemporaryDirectory() as td, patch.object(p.subprocess,'run'), patch.object(p.gemini,'key',return_value='dummy'), patch.object(p.gemini,'call',side_effect=packets) as call:
            r=p.refine_single_start(Path('audio'),self.occ,45,[672.67],self.duration,argparse.Namespace(model='flash',timeout=600),Path(td),lower_bound=671.77,upper_bound=701.1,**({'candidate_is_evidence':False} if 'candidate_is_evidence' in inspect.signature(p.refine_single_start).parameters else {}))
        self.assertEqual(call.call_count,2)
        self.assertFalse(r['validation_errors'])
        self.assertAlmostEqual(r['start'],672.24,places=3)

    def test_actual_satgur_repair_joins_repeated_ending_and_preserves_prefix(self):
        plan=p.plan_joint_timing_regions(self.occ,self.t['coarse_sequence'],self.a,self.duration,self.t['refinements'])
        targets=[x['occurrence_id'] for r in plan['regions'] for x in r['target_occurrences']]
        self.assertEqual(targets,[f'occ-{i:03d}' for i in range(39,66)])
        self.assertEqual(len(plan['regions']),1)
        region=plan['regions'][0]
        self.assertLess(region['clip_start'],587.77) # distinct preceding lyric must be heard
        self.assertEqual(region['clip_end'],self.duration)
        self.assertEqual(region['preceding_context']['occurrence_id'],'occ-038')
        retained=plan['retained_starts']
        self.assertEqual(set(retained),{f'occ-{i:03d}' for i in range(39)})
        self.assertEqual(retained['occ-038'],587.77)
        self.assertEqual(retained['occ-010'],101.19)
        self.assertEqual(retained['occ-026'],362.383)
        self.assertNotIn('occ-045',retained)
        self.assertNotIn('occ-064',retained)
        # Original failed evidence stays byte-for-byte data equivalent.
        self.assertEqual(self.t,FIXTURE['timing'])

    def test_fresh_long_regions_use_full_audited_clip_not_uniform_crop(self):
        plan=p.plan_joint_timing_regions(self.occ,self.t['coarse_sequence'],self.a,self.duration,[])
        self.assertEqual(len(plan['regions']),3)
        for region,audit in zip(plan['regions'],self.a['segment_audits']):
            self.assertEqual(region['clip_start'],audit['segment']['clip_start'])
            self.assertEqual(region['clip_end'],audit['segment']['clip_end'])
        ids=[o['occurrence_id'] for r in plan['regions'] for o in r['target_occurrences']]
        self.assertEqual(ids,[o['occurrence_id'] for o in self.occ])

    def region(self):
        return {'clip_start':580.0,'clip_end':self.duration,'target_occurrences':self.occ[39:],
                'preceding_context':self.occ[38], 'following_context':None}

    def test_repeat_expansion_retains_embedded_double_and_exact_source(self):
        expanded=p.expanded_timing_targets(self.occ[39:])
        self.assertEqual(len(expanded),43)
        self.assertEqual(expanded[0]['source_text'],self.occ[39]['source_text'])
        self.assertEqual(sum(x['occurrence_id']=='occ-039' for x in expanded),1)
        self.assertEqual(sum(x['occurrence_id']=='occ-065' for x in expanded),8)
        self.assertEqual(len({x['timing_id'] for x in expanded}),43)

    def packets(self):
        # Synthetic increasing numbers solely test protocol, not proposed Satgur timestamps.
        return {'starts':[{'timing_id':x['timing_id'],'start':10+i*7.5,'uncertainty':'','onset_at_clip_start':False}
                         for i,x in enumerate(p.expanded_timing_targets(self.occ[39:]))]}

    def test_joint_pair_accepts_clear_agreement_without_changing_display_order(self):
        a=self.packets(); b=copy.deepcopy(a)
        for row in b['starts']:row['start']+=0.2
        result=p.joint_timing_consensus(self.region(),a,b,self.duration)
        self.assertFalse(result['validation_errors'])
        self.assertEqual([x['occurrence_id'] for x in result['starts']],[x['occurrence_id'] for x in self.occ[39:]])
        self.assertEqual(result['starts'][0]['start'],590.1)
        self.assertEqual(len(result['starts']),27)

    def test_joint_pair_rejects_uncertainty_even_when_two_numbers_agree(self):
        for note in ['cut off at start of clip','perhaps later repetition',False]:
            a=self.packets(); a['starts'][-1]['uncertainty']=note
            result=p.joint_timing_consensus(self.region(),a,copy.deepcopy(a),self.duration)
            self.assertTrue(result['validation_errors'])
            self.assertFalse(result['starts'])

    def test_joint_pair_rejects_order_missing_and_disagreement(self):
        for mode in ['swap','missing','disagreement']:
            a=self.packets(); b=copy.deepcopy(a)
            if mode=='swap':b['starts'][0],b['starts'][1]=b['starts'][1],b['starts'][0]
            elif mode=='missing':b['starts'].pop()
            else:b['starts'][10]['start']+=1
            r=p.joint_timing_consensus(self.region(),a,b,self.duration)
            self.assertTrue(r['validation_errors'],mode)
            self.assertFalse(r['starts'])

    def test_joint_pass_rejects_out_of_clip_duration_and_nonfinite_start(self):
        for point in [-1,378,self.duration,float('inf'),float('nan'),True]:
            a=self.packets(); a['starts'][-1]['start']=point
            r=p.validate_joint_timing_pass(self.region(),a,self.duration)
            self.assertTrue(r['validation_errors'],repr(point))
        a=self.packets(); region=self.region(); region['clip_end']=self.duration+10
        self.assertTrue(p.validate_joint_timing_pass(region,a,self.duration)['validation_errors'])

    def test_joint_zero_requires_explicit_complete_onset_but_clear_zero_allowed(self):
        for flag in [False,1,'true',None]:
            a=self.packets(); a['starts'][0].update(start=0,onset_at_clip_start=flag)
            self.assertTrue(p.validate_joint_timing_pass(self.region(),a,self.duration)['validation_errors'])
        a=self.packets(); a['starts'][0].update(start=0,onset_at_clip_start=True)
        self.assertFalse(p.validate_joint_timing_pass(self.region(),a,self.duration)['validation_errors'])

    def test_rehna_two_raw_clear_starts_survive_coarse_distance_veto(self):
        evidence=json.loads((Path(__file__).parent/'fixtures/rehna-timing.json').read_text())
        timing=evidence['timing']
        retained=p.retained_timing_measurements(timing['ordered_occurrences'],
                    [evidence['verification'],evidence['dispute']],timing['duration_seconds'])
        self.assertEqual(retained['occ-017'],518.325)
        self.assertNotEqual(retained['occ-017'],538.29)
        self.assertEqual(evidence['verification']['starts'][0]['occurrence_id'],'occ-018')
        self.assertIn('chunk start[0] is invalid',evidence['verification']['validation_errors'][0])

    def test_full_song_timing_does_not_accept_bool_as_zero_or_one(self):
        r={'starts':[{'occurrence_id':'occ-000','start':False}],'uncertain_occurrence_ids':[]}
        _,errors,_=p.timing_sequence_from_response(self.occ[:1],r,self.duration)
        self.assertTrue(errors)


class RoutedTimingTests(unittest.TestCase):
    """Exercise the real durable route; only external audio/model calls are fake."""
    def setUp(self):
        import bhakti_model_routes
        self.routes=bhakti_model_routes
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.audio=self.root/'audio.m4a';self.audio.write_bytes(b'fixture-audio-content')
        self.opts=argparse.Namespace(model=self.routes.FLASH_MODEL,pro_model=self.routes.PRO_MODEL,
                                    timeout=600,timing_deadline_at=time.time()+2400,force=False)
        self.occ=copy.deepcopy(FIXTURE['timing']['ordered_occurrences'][:3])
        self.region={'index':0,'clip_start':0.0,'clip_end':50.0,'target_occurrences':self.occ,
                     'preceding_context':None,'following_context':None}
        self.identity={'trim':{'applied':False}}

    def packet(self,uncertain=False):
        return {'packet':{'starts':[{'timing_id':x['timing_id'],'start':5+i*10,
                'uncertainty':'masked syllable' if uncertain and i==0 else '', 'onset_at_clip_start':False}
                for i,x in enumerate(p.expanded_timing_targets(self.occ))]}}

    def invoke(self):
        return p.run_joint_timing_unit(self.root,self.audio,self.region,50.0,self.opts,self.identity)

    def test_actual_route_requires_two_clear_calls_then_zero_call_resume(self):
        with patch.object(p.subprocess,'run'),patch.object(p.gemini,'key',return_value='dummy'),patch.object(p.gemini,'call',side_effect=lambda *a,**kw:self.packet()) as call:
            first=self.invoke();second=self.invoke()
        self.assertEqual(first,second)
        self.assertEqual(call.call_count,2)
        for item in call.call_args_list:
            self.assertEqual(item.args[0],self.routes.FLASH_MODEL)
            self.assertEqual(item.kwargs['max_completion_tokens'],65536)
            self.assertEqual(item.kwargs['reasoning_effort'],'high')
            self.assertIn('deadline_at',item.kwargs)
            self.assertIn('unit_context',item.kwargs)
            self.assertLessEqual(item.kwargs['timeout'],600)
        states=list(self.root.rglob('route-state.json'));self.assertEqual(len(states),1)
        state=json.loads(states[0].read_text());self.assertEqual(state['status'],'accepted')
        self.assertEqual(len(state['attempts']),1)
        self.assertNotIn('coarse_source_start',call.call_args_list[1].args[2])
        self.assertNotRegex(call.call_args_list[1].args[2],r'"start"\s*:\s*(5|15|25)(?:\.0)?[,}]')
        self.assertNotEqual(call.call_args_list[0].kwargs['audio'],call.call_args_list[1].kwargs['audio'])
        self.assertNotEqual(call.call_args_list[0].args[2],call.call_args_list[1].args[2])

    def test_explicit_completion_cap_binds_both_hearings_and_cache(self):
        self.region['max_completion_tokens']=4096
        with patch.object(p.subprocess,'run'),patch.object(p.gemini,'key',return_value='dummy'),patch.object(p.gemini,'call',side_effect=lambda *a,**kw:self.packet()) as call:
            first=self.invoke()
            self.assertEqual(self.invoke(),first)
            self.assertEqual(call.call_count,2)
            self.region['max_completion_tokens']=2048
            second=self.invoke()
        self.assertEqual([item.kwargs['max_completion_tokens'] for item in call.call_args_list],[4096,4096,2048,2048])
        self.assertNotEqual(first['input_fingerprint'],second['input_fingerprint'])
        import hashlib
        self.assertEqual(second['input_fingerprint'],p.joint_region_fingerprint(
            hashlib.sha256(self.audio.read_bytes()).hexdigest(),self.region,50.0,self.identity))

    def test_invalid_completion_cap_fails_before_audio_or_route_work(self):
        for cap in (True,None,0,-1,1.5,65537,'4096'):
            self.region['max_completion_tokens']=cap
            with self.subTest(cap=cap),patch.object(p,'timing_input_identity',side_effect=AssertionError('invalid cap reached audio identity')):
                with self.assertRaises(ValueError):self.invoke()
        self.assertFalse(list(self.root.rglob('route-state.json')))

    def test_explicit_reasoning_binds_both_hearings_and_cache(self):
        with patch.object(p.subprocess,'run'),patch.object(p.gemini,'key',return_value='dummy'),patch.object(p.gemini,'call',side_effect=lambda *a,**kw:self.packet()) as call:
            original=self.invoke()
            self.region['reasoning_effort']='medium'
            revised=self.invoke()
            self.assertEqual(self.invoke(),revised)
        self.assertEqual([item.kwargs['reasoning_effort'] for item in call.call_args_list],['high','high','medium','medium'])
        self.assertNotEqual(original['input_fingerprint'],revised['input_fingerprint'])
        self.assertEqual(len(list(self.root.rglob('accepted-result.json'))),2)

    def test_invalid_reasoning_fails_before_audio_or_route_work(self):
        for effort in (True,None,'','minimal','medium ',[],{}):
            self.region['reasoning_effort']=effort
            with self.subTest(effort=effort),patch.object(p,'timing_input_identity',side_effect=AssertionError('invalid reasoning reached audio identity')):
                with self.assertRaises(ValueError):self.invoke()
        self.assertFalse(list(self.root.rglob('route-state.json')))

    def test_real_route_quality_failure_gets_one_new_pro_pair_then_stops(self):
        def reply(model,*args,**kwargs):return self.packet(uncertain=model==self.routes.FLASH_MODEL)
        with patch.object(p.subprocess,'run'),patch.object(p.gemini,'key',return_value='dummy'),patch.object(p.gemini,'call',side_effect=reply) as call:
            result=self.invoke()
        self.assertFalse(result['validation_errors'])
        self.assertEqual([x.args[0] for x in call.call_args_list],[self.routes.FLASH_MODEL]*2+[self.routes.PRO_MODEL]*2)
        states=list(self.root.rglob('route-state.json'));state=json.loads(states[0].read_text())
        self.assertEqual([x['status'] for x in state['attempts']],['quality-failed','accepted'])
        self.assertEqual(len(list(self.root.rglob('candidate.json'))),2)

    def test_pro_disagreement_is_not_forced_or_retried_on_resume(self):
        original=self.root/'.transcription/pipeline/03-timing.json'
        original.parent.mkdir(parents=True);original.write_bytes(b'original retained held evidence')
        with patch.object(p.subprocess,'run'),patch.object(p.gemini,'key',return_value='dummy'),patch.object(p.gemini,'call',side_effect=lambda *a,**kw:self.packet(uncertain=True)) as call:
            with self.assertRaises(self.routes.UnitUnresolved):self.invoke()
            with self.assertRaises(self.routes.UnitUnresolved):self.invoke()
        self.assertEqual(call.call_count,4)
        state=json.loads(next(self.root.rglob('route-state.json')).read_text())
        self.assertEqual(state['status'],'unresolved')
        self.assertEqual(original.read_bytes(),b'original retained held evidence')

    def audited(self):
        return {'packet':{'verified_lines':list({x['ref']:{'id':x['ref'],'source_text':x['source_text'],'roman':x['roman'],'kind':x['section']} for x in reversed(self.occ)}.values()),
                'performance_order':[{'line_id':x['ref']} for x in self.occ for _ in range(x['repeats'])]}}

    def test_actual_align_holds_without_replacing_existing_03(self):
        original=self.root/'.transcription/pipeline/03-timing.json'
        original.parent.mkdir(parents=True)
        before=json.dumps({'publication_status':'blocked','ordered_occurrences':[]}).encode()
        original.write_bytes(before)
        with patch.object(p.subprocess,'run'),patch.object(p.gemini,'duration_seconds',return_value=50.0),patch.object(p,'canonical_timing_audio',return_value=self.audio),patch.object(p.gemini,'key',return_value='dummy'),patch.object(p.gemini,'call',side_effect=lambda *a,**kw:self.packet(uncertain=True)) as call:
            with self.assertRaises(self.routes.UnitUnresolved):p.align(self.root,self.audited(),self.audio,self.opts)
        self.assertEqual(call.call_count,4)
        self.assertEqual(original.read_bytes(),before)
        self.assertEqual(len(list(original.parent.glob('timing-history/*.json'))),1)

    def test_actual_align_flagged_legacy_uncertainty_reaches_repair(self):
        original=self.root/'.transcription/pipeline/03-timing.json';original.parent.mkdir(parents=True)
        old={'publication_status':'review-required','ordered_occurrences':self.occ,
             'sequence':[{'occurrence_id':'occ-000','start':0.0}], 'uncertain_occurrence_ids':['occ-000']}
        original.write_text(json.dumps(old))
        with patch.object(p.subprocess,'run'),patch.object(p.gemini,'duration_seconds',return_value=50.0),patch.object(p,'canonical_timing_audio',return_value=self.audio),patch.object(p.gemini,'key',return_value='dummy'),patch.object(p.gemini,'call',side_effect=lambda *a,**kw:self.packet()) as call:
            result=p.align(self.root,self.audited(),self.audio,self.opts)
        self.assertFalse(result['validation_errors'])
        self.assertEqual(call.call_count,2)
        self.assertEqual(result['uncertain_occurrence_ids'],[])
        self.assertEqual(len(list(original.parent.glob('timing-history/*.json'))),1)

    def test_actual_align_global_conflict_preserves03_and_saves_failed_candidate(self):
        original=self.root/'.transcription/pipeline/03-timing.json';original.parent.mkdir(parents=True)
        before=json.dumps({'publication_status':'blocked','ordered_occurrences':[]}).encode();original.write_bytes(before)
        with patch.object(p.gemini,'duration_seconds',return_value=50.0),patch.object(p,'canonical_timing_audio',return_value=self.audio),patch.object(p,'align_long_segments',return_value=([],[],['non-increasing cross-region starts'])),patch.object(p.gemini,'call') as call:
            result=p.align(self.root,self.audited(),self.audio,self.opts)
        self.assertEqual(result['publication_status'],'blocked')
        self.assertEqual(original.read_bytes(),before)
        candidates=list(original.parent.glob('timing-candidates/*.json'))
        self.assertEqual(len(candidates),1)
        self.assertEqual(json.loads(candidates[0].read_text())['validation_errors'],['non-increasing cross-region starts'])
        call.assert_not_called()

    def test_actual_align_exact_cache_reuses_but_same_ids_changed_source_invalidates(self):
        with patch.object(p.subprocess,'run'),patch.object(p.gemini,'duration_seconds',return_value=50.0),patch.object(p,'canonical_timing_audio',return_value=self.audio),patch.object(p.gemini,'key',return_value='dummy'),patch.object(p.gemini,'call',side_effect=lambda *a,**kw:self.packet()) as call:
            first=p.align(self.root,self.audited(),self.audio,self.opts)
            self.assertEqual(p.align(self.root,self.audited(),self.audio,self.opts),first)
            self.assertEqual(call.call_count,2)
            self.occ[0]['source_text']+=' ਵਾਹਿਗੁਰੂ'
            second=p.align(self.root,self.audited(),self.audio,self.opts)
        self.assertEqual(call.call_count,4)
        self.assertNotEqual(first['input_fingerprint'],second['input_fingerprint'])
        self.assertEqual(second['ordered_occurrences'][0]['source_text'],self.occ[0]['source_text'])

    def test_audio_trim_and_same_id_source_changes_invalidate_accepted_route(self):
        with patch.object(p.subprocess,'run'),patch.object(p.gemini,'key',return_value='dummy'),patch.object(p.gemini,'call',side_effect=lambda *a,**kw:self.packet()) as call:
            self.invoke()
            self.audio.write_bytes(b'different-actual-audio');self.invoke()
            self.identity['trim']={'applied':True,'trim_start':2.0};self.invoke()
            self.occ[0]['source_text']+=' ਵਾਹਿਗੁਰੂ';self.invoke()
            self.occ[1]['repeats']=3;self.invoke()
        self.assertEqual(call.call_count,10)
        self.assertEqual(len(list(self.root.rglob('route-state.json'))),5)


class TargetedCachedTimingTests(unittest.TestCase):
    def setUp(self):
        import hashlib
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.audio=self.root/'audio.m4a';self.audio.write_bytes(b'reviewed fixture bytes')
        self.t=copy.deepcopy(json.loads((Path(__file__).parent/'fixtures/rehna-timing.json').read_text())['timing'])
        self.path=self.root/'.transcription/pipeline/03-timing.json';self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps(self.t,ensure_ascii=False));self.old=self.path.read_bytes()
        self.opts=argparse.Namespace(model='google/gemini-3.7-flash',timeout=600,force=False,
            timing_deadline_at=time.time()+2400,timing_repair_occurrence_ids=['occ-017'],
            timing_legacy_evidence_identity={'audio_sha256':hashlib.sha256(self.audio.read_bytes()).hexdigest(),
                'timing_sha256':hashlib.sha256(self.old).hexdigest(),'trim':{}})
        self.a={'packet':{'verified_lines':list({x['ref']:{'id':x['ref'],'source_text':x['source_text'],'roman':x['roman'],'kind':x['section']} for x in self.t['ordered_occurrences']}.values()),
            'performance_order':[{'line_id':x['ref']} for x in self.t['ordered_occurrences'] for _ in range(x['repeats'])]}}
    def test_actual_rehna_all_cached_evidence_repairs_only_target_without_dispatch(self):
        with patch.object(p.gemini,'duration_seconds',return_value=self.t['duration_seconds']),patch.object(p.gemini,'call') as call,patch.object(p,'canonical_timing_audio',side_effect=AssertionError('targeted cached repair must not rerun audio')) as convert:
            result=p.align(self.root,self.a,self.audio,self.opts)
        call.assert_not_called();convert.assert_not_called()
        self.assertFalse(result['validation_errors'])
        self.assertEqual(result['sequence'][17]['start'],518.325)
        for before,after in zip(self.t['sequence'],result['sequence']):
            self.assertEqual({k:v for k,v in before.items() if k not in {'start','end'}},{k:v for k,v in after.items() if k not in {'start','end'}})
            if before['occurrence_id']!='occ-017':self.assertEqual(before['start'],after['start'])
        self.assertEqual(result['sequence'][16]['end'],518.325)
        self.assertEqual(result['ordered_occurrences'],self.t['ordered_occurrences'])
        self.assertEqual(result['repair_scope']['target_occurrence_ids'],['occ-017'])
        self.assertEqual(len(result['repair_scope']['retained_baseline_occurrence_ids']),23)
        archived=list(self.path.parent.glob('timing-history/*.json'));self.assertEqual(len(archived),1)
        self.assertEqual(archived[0].read_bytes(),self.old)
    def test_targeted_baseline_cannot_use_unbound_old_audio(self):
        self.opts.timing_legacy_evidence_identity['audio_sha256']='wrong'
        with patch.object(p.gemini,'duration_seconds',return_value=self.t['duration_seconds']),patch.object(p.gemini,'call') as call,patch.object(p,'canonical_timing_audio',side_effect=AssertionError('targeted cached repair must not rerun audio')):
            with self.assertRaisesRegex(RuntimeError,'bound'):p.align(self.root,self.a,self.audio,self.opts)
        call.assert_not_called();self.assertEqual(self.path.read_bytes(),self.old)
    def test_duplicate_cached_window_is_not_independent_agreement(self):
        import hashlib
        window=json.loads((Path(__file__).parent/'fixtures/rehna-timing.json').read_text())['verification']
        self.t['refinements']=[window,copy.deepcopy(window)]
        self.path.write_text(json.dumps(self.t));self.old=self.path.read_bytes()
        self.opts.timing_legacy_evidence_identity['timing_sha256']=hashlib.sha256(self.old).hexdigest()
        with patch.object(p.gemini,'duration_seconds',return_value=self.t['duration_seconds']),patch.object(p.gemini,'call') as call:
            with self.assertRaisesRegex(RuntimeError,'independent'):p.align(self.root,self.a,self.audio,self.opts)
        call.assert_not_called();self.assertEqual(self.path.read_bytes(),self.old)
    def test_one_cached_window_is_insufficient_for_targeted_first_syllable_repair(self):
        import hashlib
        self.t['refinements']=[json.loads((Path(__file__).parent/'fixtures/rehna-timing.json').read_text())['verification']]
        self.path.write_text(json.dumps(self.t));self.old=self.path.read_bytes()
        self.opts.timing_legacy_evidence_identity['timing_sha256']=hashlib.sha256(self.old).hexdigest()
        with patch.object(p.gemini,'duration_seconds',return_value=self.t['duration_seconds']),patch.object(p.gemini,'call') as call,patch.object(p,'canonical_timing_audio',side_effect=AssertionError('targeted cached repair must not rerun audio')):
            with self.assertRaisesRegex(RuntimeError,'independent'):p.align(self.root,self.a,self.audio,self.opts)
        call.assert_not_called();self.assertEqual(self.path.read_bytes(),self.old)

if __name__=='__main__':unittest.main()

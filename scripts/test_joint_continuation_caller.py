"""Real storage/router restart, with synthetic timing measurements instead of API calls."""
import argparse,copy,hashlib,json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import bhakti_pipeline as p
import bhakti_model_routes as routes
from test_joint_pair_retention import BAD,GOOD,SCOPE


class JointContinuationCaller(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.song=self.root/'song';self.song.mkdir()
        self.scope=json.loads(SCOPE.read_text());self.occ=self.scope['ordered_occurrences'];self.audio=self.root/'canonical.m4a'
        self.audio.write_bytes(b'unit-test canonical audio; no audio processing is invoked')
        self.scope['canonical_audio_sha256']=hashlib.sha256(self.audio.read_bytes()).hexdigest()
        self.plan={'version':1,'audio_sha256':self.scope['canonical_audio_sha256'],'source_identity':self.scope['source_identity'],
            'ordered_occurrences':self.occ,'duration_seconds':922.721,'retained':[],
            'pending':[{'region':self.scope['focused_region'],'select_timing_ids':self.scope['focused_select_only']},
                       {'region':self.scope['third_region'],'select_timing_ids':[x['timing_id'] for x in p.expanded_timing_targets(self.scope['third_region']['target_occurrences'])]}]}
        for path,ids in [(GOOD,self.scope['retained_region1_timing_ids']),(BAD,self.scope['retained_region2_timing_ids'])]:
            report=json.loads(path.read_text())
            # Only fixture identity is rebound to test bytes; saved timing measurements remain exact.
            report['input_fingerprint']=p.joint_region_fingerprint(self.scope['canonical_audio_sha256'],report['region'],922.721,self.scope['source_identity'])
            path=self.root/path.name;path.write_text(json.dumps(report,ensure_ascii=False)+'\n')
            self.plan['retained'].append({'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'region':report['region'],'input_fingerprint':report['input_fingerprint'],'select_timing_ids':ids})
        self.plan_path=self.root/'plan.json';self.save_plan()
        old=self.song/'.transcription/pipeline/03-timing.json';old.parent.mkdir(parents=True);old.write_text('{"old":"untouched"}\n');self.old=old
        self.executions=[];self.interrupt_third=False;self.failed_focus=False
    def save_plan(self):
        self.plan_path.write_text(json.dumps(self.plan,ensure_ascii=False,indent=2)+'\n')
        self.options=argparse.Namespace(model='google/gemini-3.7-flash',pro_model='google/gemini-3.1-pro-preview',
            force=False,timeout=60,timing_deadline_at=time.time()+300,timing_source_identity=self.scope['source_identity'],
            timing_joint_continuation={'path':str(self.plan_path),'sha256':hashlib.sha256(self.plan_path.read_bytes()).hexdigest()})
    def fake_measure(self,song,audio,region,duration,options,source_identity):
        focused=region['target_occurrences'][0]['occurrence_id']=='occ-015'
        if not focused and self.interrupt_third:
            self.interrupt_third=False;raise KeyboardInterrupt('simulated stop after focused accepted cache')
        identity=p.timing_input_identity(audio,region['target_occurrences'],source_identity);identity.update(region=region,duration=duration)
        fingerprint=hashlib.sha256(json.dumps(identity,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
        def execute(ctx):
            self.executions.append(('focus' if focused else 'third',ctx.model))
            targets=p.expanded_timing_targets(region['target_occurrences']);passes=[]
            for index in range(2):
                selected={**region,'clip_start':max(0.,region['clip_start']-10*index)};starts=[]
                for pos,target in enumerate(targets):
                    point=({'occ-015-r01':286.,'occ-016-r01':292.,'occ-017-r01':298.8,'occ-017-r02':305.8}[target['timing_id']] if focused else 600+pos*10)
                    if focused and self.failed_focus and pos==0:point+=index
                    starts.append({'timing_id':target['timing_id'],'start':point-selected['clip_start'],'uncertainty':'','onset_at_clip_start':False})
                response={'packet':{'starts':starts}};passes.append({'region':selected,'response':response,'validation':p.validate_joint_timing_pass(selected,response['packet'],duration)})
            return {**p.joint_consensus_from_measurements(region,[x['validation'] for x in passes]),'kind':'joint','region':region,
                    'passes':passes,'input_fingerprint':fingerprint,'resolved_model':ctx.model}
        return routes.run_unit(song/'.transcription/pipeline/joint-timing',
            f"timing:{region['target_occurrences'][0]['occurrence_id']}:{region['target_occurrences'][-1]['occurrence_id']}",fingerprint,
            execute,lambda result:[{'kind':'timing_disagreement','detail':e} for e in result['validation_errors']],deadline_at=options.timing_deadline_at)
    def invoke(self):
        return p.align_long_segments(self.song,self.audio,{},self.occ,[],922.721,self.options)
    def test_interrupted_caller_persists_retained_pairs_and_restarts_without_remeasuring_accepted_scope(self):
        self.interrupt_third=True
        with patch.object(p,'run_joint_timing_unit',side_effect=self.fake_measure),patch.object(p.gemini,'call',side_effect=AssertionError('API forbidden')):
            with self.assertRaises(KeyboardInterrupt):self.invoke()
            receipts=list((self.song/'.transcription/pipeline/joint-continuations').glob('*/retained.json'))
            self.assertEqual(len(receipts),1);receipt=json.loads(receipts[0].read_text())
            self.assertEqual(len(receipt['pairs']),33)
            self.assertNotIn('occ-015-r01',[r['timing_id'] for r in receipt['pairs']])
            before=receipts[0].read_bytes();sequence,reports,errors=self.invoke()
            self.assertEqual(receipts[0].read_bytes(),before)
        self.assertEqual(self.executions,[('focus','google/gemini-3.7-flash'),('third','google/gemini-3.7-flash')])
        self.assertEqual(len(sequence),51);self.assertEqual(errors,[])
        self.assertEqual(reports[0]['kind'],'joint-selection')
        self.assertEqual(next(x['start'] for x in reports[0]['expanded_starts'] if x['timing_id']=='occ-017-r02'),305.45)
        timing={'duration_seconds':922.721,'ordered_occurrences':self.occ,'source_identity':self.scope['source_identity'],
                'sequence':sequence,'refinements':reports,'uncertain_occurrence_ids':[]}
        self.assertEqual(p.timing_uncertainty_errors(timing),[])
        corrupted=copy.deepcopy(timing);corrupted['sequence'][17]['start']+=.1
        self.assertTrue(p.timing_uncertainty_errors(corrupted))
        self.assertEqual(self.old.read_text(),'{"old":"untouched"}\n')
    def test_failed_focused_pair_keeps_original_and_retained_cache_blocked_without_third_dispatch(self):
        self.failed_focus=True
        with patch.object(p,'run_joint_timing_unit',side_effect=self.fake_measure),patch.object(p.gemini,'call',side_effect=AssertionError('API forbidden')):
            with self.assertRaises(routes.UnitUnresolved):self.invoke()
            with self.assertRaises(routes.UnitUnresolved):self.invoke()
        self.assertEqual([x[0] for x in self.executions],['focus','focus']) # one Flash, one Pro, no replay
        self.assertTrue(list((self.song/'.transcription/pipeline/joint-continuations').glob('*/retained.json')))
        self.assertEqual(self.old.read_text(),'{"old":"untouched"}\n')
    def test_locally_agreeing_cross_region_lookalike_is_rejected_before_spending(self):
        # Reproduce the superseded one-target plan: its local pairs agree but
        # region2 selects the earlier breath-couplet performance.
        self.plan['retained'][1]['select_timing_ids'][:0]=['occ-015-r01','occ-016-r01']
        self.plan['pending'][0]['select_timing_ids']=['occ-017-r01']
        self.save_plan()
        with patch.object(p,'run_joint_timing_unit') as run:
            with self.assertRaisesRegex(ValueError,'retained.*non-increasing'):
                self.invoke()
            run.assert_not_called()

    def test_changed_plan_hash_or_retained_packet_rejects_before_any_dispatch(self):
        self.plan['retained'][1]['sha256']='0'*64;self.save_plan()
        with patch.object(p,'run_joint_timing_unit') as run:
            with self.assertRaises(ValueError):self.invoke()
            run.assert_not_called()
        self.plan_path.write_text('{}')
        with patch.object(p,'run_joint_timing_unit') as run:
            with self.assertRaises(ValueError):self.invoke()
            run.assert_not_called()

if __name__=='__main__':unittest.main()

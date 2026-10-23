"""Joined missing-source→timing→generation, synthetic providers and real audio/storage.

Only the source/semantic answers are fixtures. Timings are prescribed software
inputs, not an acoustic quality claim; actual align/FFmpeg/router are exercised.
"""
import copy,json,re,shutil,time,unittest
from pathlib import Path
from unittest.mock import patch
import bhakti_pipeline as pipeline
import bhakti_library_source_pass as source
import bhakti_model_routes as routes
from test_source_bootstrap_design import EmptySourceCallerTests
from test_long_source_bootstrap_design import SEGMENTS,segment_packet
from test_generic_source_caller import make_audio,write_json
from test_source_caller import fresh
from test_sense_decisions import decisions_for

REAL_ALIGN=pipeline.align

class EmptyJoinedTests(unittest.TestCase):
    setUp=EmptySourceCallerTests.setUp
    invoke=EmptySourceCallerTests.invoke
    align=EmptySourceCallerTests.align
    library_row=EmptySourceCallerTests.library_row
    def semantics(self,song,plan,metadata,options,route,deadline):
        self.fresh_targets.append(copy.deepcopy(plan['new_target_ids']))
        result=fresh(plan);decisions=decisions_for(plan['lines'],metadata['languages'])
        meanings={row['id']:{'मन':'Mind','तन':'Body','राम':'Rāma','नाम':'Name'}[row['source_text']] for row in plan['lines']}
        for row in result['glosses']['packet']['glosses']:
            row['sense_decisions']=decisions[row['id']];row['word_glosses'][0]['gloss']=('the divine name invoked' if meanings[row['id']]=='Rāma' else meanings[row['id']].lower())
            row['semantic_frame']={key:'Names '+meanings[row['id']] for key in pipeline.SEMANTIC_FRAME_FIELDS}
            row['grammar_note']='Noun.'
        for row in result['translations']['packet']['translations']:
            row['literal_english']=meanings[row['id']];row['segments']=[{'text':meanings[row['id']],'word_indices':[0]}]
        return result
    def provider(self,model,key,prompt,**kwargs):
        schema=kwargs.get('schema_name')
        if schema!='bhakti_joint_starts':
            if schema not in ('bhakti_segment_transcript','bhakti_segment_audit'):
                return EmptySourceCallerTests.provider(self,model,key,prompt,**kwargs)
            if schema=='bhakti_segment_transcript':
                index=int(re.search(r'This is segment (\d+)',prompt).group(1));packet=segment_packet(index)
            else:
                packet=json.JSONDecoder().raw_decode(prompt.split('FIRST TRANSCRIPT:\n',1)[1].lstrip())[0]
                index=int(packet['lines'][0]['id'][1])
            self.calls.append((schema,index,model))
            return {'packet':packet,'resolved_model':model}
        targets=json.JSONDecoder().raw_decode(prompt.split('EXACT ORDERED TIMING TARGETS: ',1)[1])[0]
        left,right=map(float,re.search(r'SOURCE CLIP: ([0-9.]+)–([0-9.]+)',prompt).groups())
        self.assertLessEqual(right-left,900)
        self.assertLessEqual(pipeline.gemini.duration_seconds(kwargs['audio']),900.1)
        self.timing_calls.append((model,[row['timing_id'] for row in targets],left,right))
        starts=[]
        for row in targets:
            point=self.points[row['timing_id']]
            self.assertLess(left,point);self.assertLess(point,right)
            starts.append({'timing_id':row['timing_id'],'start':point-left,'onset_at_clip_start':False,'uncertainty':''})
        return {'packet':{'starts':starts},'resolved_model':model}
    def actual_timing(self):
        self.timing.side_effect=REAL_ALIGN;self.timing_calls=[]
        self.points={'occ-000-r01':.5,'occ-001-r01':2.5}
    def long_recording(self):
        self.actual_timing()
        make_audio(self.song/'audio-long.m4a',1200)
        (self.song/'audio.m4a').write_bytes((self.song/'audio-long.m4a').read_bytes())
        (self.song/'audio-long.m4a').unlink()
        shutil.copy2(self.song/'audio.m4a',self.workspace/'songs'/self.slug/'audio.m4a')
        self.duration=1200.;self.deadline=time.time()+300;self.options.unit_deadline_at=self.deadline
        patch.object(pipeline,'adaptive_audio_segments',return_value=copy.deepcopy(SEGMENTS)).start()
        self.points={'occ-000-r01':2.,'occ-001-r01':400.,'occ-002-r01':600.,'occ-003-r01':1000.}
    def test_short_empty_source_reaches_actual_timing_and_resumes_without_any_provider(self):
        self.actual_timing();result=self.invoke()
        self.assertEqual(result['status'],'accepted',result)
        self.assertEqual(self.calls,[('transcript',self.options.model),('audit',self.options.model)])
        self.assertEqual([row[1] for row in self.timing_calls],[['occ-000-r01','occ-001-r01']]*2)
        self.assertEqual([row['start'] for row in result['reader']['SONG_TIMINGS']],[.5,2.5])
        self.assertFalse(pipeline.timing_uncertainty_errors(result['evidence']['timing']))
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('accepted bootstrap cannot repay')):
            self.assertEqual(self.invoke(),result)
    def test_accepted_bootstrap_revalidates_source_raw_candidate_without_provider(self):
        self.actual_timing();result=self.invoke();self.assertEqual(result['status'],'accepted',result)
        artifact=json.loads((self.workspace/'songs'/self.slug/'.transcription/pipeline/02-transcript-audit.json').read_text())
        state=Path(artifact['_source_route']['state_path'])
        candidate=state.parent/'flash/candidate.json';value=json.loads(candidate.read_text());value['tampered']=True;write_json(candidate,value)
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('corrupt bootstrap cannot repay')) as call:
            try:
                held=self.invoke();self.assertEqual(held['status'],'unresolved');self.assertFalse(held['publicationEligible'])
            except routes.RunFatal:
                pass
            call.assert_not_called()
    def test_workspace_trim_drift_holds_before_source_dispatch(self):
        write_json(self.workspace/'songs'/self.slug/'.transcription/trim-applied.json',{'start':1.,'end':3.})
        result=self.invoke();self.assertEqual(result['status'],'unresolved',result)
        self.assertEqual(self.calls,[]);self.semantic.assert_not_called();self.timing.assert_not_called()
    def test_long_bootstrap_uses_audited_occurrence_ownership_for_bounded_real_timing(self):
        self.long_recording();result=self.invoke();self.assertEqual(result['status'],'accepted',result)
        self.assertCountEqual(self.calls,[('bhakti_segment_transcript',0,self.options.model),('bhakti_segment_transcript',1,self.options.model),
            ('bhakti_segment_audit',0,self.options.model),('bhakti_segment_audit',1,self.options.model)])
        self.assertEqual([row[1] for row in self.timing_calls],
            [['occ-000-r01','occ-001-r01','occ-002-r01']]*2+[['occ-003-r01']]*2)
        self.assertEqual([row['start'] for row in result['reader']['SONG_TIMINGS']],[2.,400.,600.,1000.])
        delta=result['evidence']['plan']['adopted_delta'];units=delta['source_unit_coverage']
        self.assertEqual([row['expanded_indices'] for row in units],[[0,1,2],[3]])
        self.assertEqual([row['clip_start'] for row in units],[0.,540.])
        self.assertFalse(pipeline.timing_uncertainty_errors(result['evidence']['timing']))
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('completed long bootstrap cannot repay')):
            self.assertEqual(self.invoke(),result)
    def test_long_ownership_requires_contiguous_recording_coverage_before_timing(self):
        self.long_recording();segments=copy.deepcopy(SEGMENTS);segments[1]['core_start']=601.
        with patch.object(pipeline,'adaptive_audio_segments',return_value=segments):
            result=self.invoke()
        self.assertEqual(result['status'],'unresolved');self.assertFalse(result['publicationEligible'])
        self.assertEqual(self.timing_calls,[]);self.semantic.assert_not_called()
        self.assertEqual((self.workspace/'songs'/self.slug/'data.js').read_bytes(),self.original)

if __name__=='__main__':unittest.main()

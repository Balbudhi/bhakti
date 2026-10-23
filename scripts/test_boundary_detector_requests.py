"""Proposed real detector caller tests. Network transport/router execution mocked,
but FFmpeg, input files, detector cache and caller request assembly are real.
No evidence here claims model classification or router correctness.
"""
import argparse
import re
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock
import bhakti_model_routes as routes
import bhakti_pipeline as pipeline
from test_boundary_application import create_audio


class BoundaryDetectorRequests(unittest.TestCase):
    def detector_fixture(self, song, audio_duration=30.):
        create_audio(song, duration=audio_duration)
        calls=[]; route_calls=[]
        options=argparse.Namespace(model=pipeline.MODEL,pro_model=routes.PRO_MODEL,timeout=20,force=False,
                                   boundary_deadline_at=time.time()+90)
        def routed(state_dir,unit_id,fingerprint,execute,validate,**kwargs):
            route_calls.append({'unit_id':unit_id,'fingerprint':fingerprint,**kwargs})
            attempt_dir=Path(state_dir)/'test-attempt';attempt_dir.mkdir(parents=True,exist_ok=True)
            context={'unit_id':unit_id,'test_transport_context':True}
            ctx=SimpleNamespace(model=kwargs["base_model"],attempt_dir=attempt_dir,unit_id=unit_id,
                deadline_at=options.boundary_deadline_at,call_timeout_seconds=20,
                transport_context=context)
            result=execute(ctx)
            issues=validate(result)
            if issues:
                raise routes.UnitUnresolved(unit_id,'fixture quality failure',issues,attempt_dir/'state.json')
            return result
        def response(model,key,prompt,**kwargs):
            calls.append({'model':model,'prompt':prompt,**kwargs})
            edge='start' if 'start' in kwargs.get('schema_name','') else 'end'
            original_duration=pipeline.gemini.duration_seconds(pipeline.preferred_listener_audio(song))
            length=min(75.,original_duration)
            match=re.search(r"absolute source seconds ([0-9.]+)–([0-9.]+)",prompt)
            clip_start=float(match.group(1)) if match else 0.
            mode=getattr(self,'mode','keep')
            cut=2. if edge=='start' else 28.
            packet={'edge':edge,'decision':'keep','boundary':0. if edge=='start' else original_duration-clip_start,
                'outside_type':'music','relationship':'attached_to_work','confidence':'high',
                'reason':'Independent fixture: attached musical performance.',
                'retained_evidence':'Music continues as part of the target rendition.','excluded_evidence':''}
            if mode in {'crop','disagree','uncertain'}:
                packet.update(decision='trim',relationship='unrelated',boundary=cut-clip_start,
                              excluded_evidence='Unrelated separately announced recording.')
            if mode=='uncertain':packet.update(relationship='uncertain',confidence='low')
            if mode=='disagree' and 'verify' in kwargs.get('schema_name',''):
                packet['boundary']-=2.
            return {'packet':packet}

        return options,calls,route_calls,routed,response

    def test_matching_source_reuses_evidence_but_changed_bytes_require_new_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            song=Path(tmp);options,calls,route_calls,routed,response=self.detector_fixture(song)
            source={'source_file':'local.m4a','title':'Local fixture'}
            with mock.patch.object(routes,'run_unit',side_effect=routed), \
                 mock.patch.object(pipeline.gemini,'key',return_value='test-not-a-secret'), \
                 mock.patch.object(pipeline.gemini,'call',side_effect=response):
                first=pipeline.detect_youtube_trim(song,source,options)
                self.assertEqual(first['boundary_contract_version'],2)
                count=len(calls);self.assertGreater(count,0)
                second=pipeline.detect_youtube_trim(song,source,options)
                self.assertEqual(len(calls),count)
                self.assertEqual(first,second)
                audio=pipeline.preferred_listener_audio(song)
                audio.write_bytes(audio.read_bytes()+b'changed source bytes')
                pipeline.detect_youtube_trim(song,source,options)
                self.assertGreater(len(calls),count)

    def test_real_edge_requests_forward_bounded_route_and_preserve_membership_question(self):
        with tempfile.TemporaryDirectory() as tmp:
            song=Path(tmp);options,calls,route_calls,routed,response=self.detector_fixture(song)
            with mock.patch.object(routes,'run_unit',side_effect=routed), \
                 mock.patch.object(pipeline.gemini,'key',return_value='test-not-a-secret'), \
                 mock.patch.object(pipeline.gemini,'call',side_effect=response):
                result=pipeline.detect_youtube_trim(song,{'source_file':'local.m4a','title':'Fixture'},options)
            self.assertEqual(result['status'],'reviewed')
            self.assertTrue(route_calls)
            for route in route_calls:
                self.assertLessEqual(route['deadline_at'],options.boundary_deadline_at)
            for call in calls:
                self.assertTrue(call['unit_context'])
                self.assertLessEqual(call['deadline_at'],options.boundary_deadline_at)
                self.assertLessEqual(call['max_completion_tokens'],4096)
                schema=call['response_schema']['properties']
                self.assertIn('relationship',schema)
                self.assertIn('retained_evidence',schema)
                self.assertIn('excluded_evidence',schema)
                # The prompt must not infer unrelatedness from speech/music alone.
                self.assertIn('invocation',call['prompt'].lower())
                self.assertIn('unrelated',call['prompt'].lower())
                self.assertIn('spoken',call['prompt'].lower())
                self.assertIn('fade',call['prompt'].lower())

    def test_unrelated_both_edges_receive_independent_focused_verification(self):
        self.mode='crop'
        with tempfile.TemporaryDirectory() as tmp:
            song=Path(tmp);options,calls,route_calls,routed,response=self.detector_fixture(song)
            with mock.patch.object(routes,'run_unit',side_effect=routed), \
                 mock.patch.object(pipeline.gemini,'key',return_value='test-not-a-secret'), \
                 mock.patch.object(pipeline.gemini,'call',side_effect=response):
                result=pipeline.detect_youtube_trim(song,{'title':'Fixture'},options)
            self.assertEqual((result['trim_start'],result['trim_end']),(2.,28.))
            self.assertEqual(len(calls),4)
            for edge in ('start','end'):
                self.assertIn('verification',result[edge])
                verifier=next(c for c in calls if edge in c['schema_name'] and 'verify' in c['schema_name'])
                self.assertNotIn('previous boundary',verifier['prompt'].lower())

    def test_disagreement_or_uncertainty_is_not_published_as_keep(self):
        for mode in ('disagree','uncertain'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                self.mode=mode
                song=Path(tmp);options,calls,route_calls,routed,response=self.detector_fixture(song)
                with mock.patch.object(routes,'run_unit',side_effect=routed), \
                     mock.patch.object(pipeline.gemini,'key',return_value='test-not-a-secret'), \
                     mock.patch.object(pipeline.gemini,'call',side_effect=response):
                    with self.assertRaises(routes.UnitUnresolved):
                        pipeline.detect_youtube_trim(song,{'title':'Fixture'},options)
                self.assertLessEqual(len(calls),4)
                saved=pipeline.read_packet(song/'.transcription'/'trim-review.json') or {}
                self.assertNotEqual(saved.get('status'),'reviewed')

    def test_changed_prompt_identity_invalidates_cached_model_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            song=Path(tmp);options,calls,route_calls,routed,response=self.detector_fixture(song)
            with mock.patch.object(routes,'run_unit',side_effect=routed), \
                 mock.patch.object(pipeline.gemini,'key',return_value='test-not-a-secret'), \
                 mock.patch.object(pipeline.gemini,'call',side_effect=response):
                pipeline.detect_youtube_trim(song,{'title':'Fixture'},options);count=len(calls)
                with mock.patch.object(pipeline,'EDGE_BOUNDARY_INSTRUCTIONS',pipeline.EDGE_BOUNDARY_INSTRUCTIONS+' Revised edge question.'):
                    pipeline.detect_youtube_trim(song,{'title':'Fixture'},options)
                self.assertGreater(len(calls),count)

    def test_resume_after_application_reuses_original_axis_and_hash(self):
        self.mode='crop'
        with tempfile.TemporaryDirectory() as tmp:
            song=Path(tmp);options,calls,route_calls,routed,response=self.detector_fixture(song)
            with mock.patch.object(routes,'run_unit',side_effect=routed), \
                 mock.patch.object(pipeline.gemini,'key',return_value='test-not-a-secret'), \
                 mock.patch.object(pipeline.gemini,'call',side_effect=response):
                first=pipeline.detect_youtube_trim(song,{'title':'Fixture'},options)
                pipeline.apply_lossless_trim(song,first);count=len(calls)
                second=pipeline.detect_youtube_trim(song,{'title':'Fixture'},options)
                self.assertEqual(second,first)
                self.assertEqual(len(calls),count)
                self.assertGreater(second['duration'],pipeline.gemini.duration_seconds(pipeline.preferred_listener_audio(song)))

    def test_long_recording_keep_endpoint_is_explicitly_clip_relative(self):
        with tempfile.TemporaryDirectory() as tmp:
            song=Path(tmp);options,calls,route_calls,routed,response=self.detector_fixture(song,audio_duration=120.)
            with mock.patch.object(routes,'run_unit',side_effect=routed), \
                 mock.patch.object(pipeline.gemini,'key',return_value='test-not-a-secret'), \
                 mock.patch.object(pipeline.gemini,'call',side_effect=response):
                result=pipeline.detect_youtube_trim(song,{'title':'Fixture'},options)
            end=next(c for c in calls if 'end' in c['schema_name'])
            self.assertIn('Keep endpoint relative to this clip: 75.000 seconds.',end['prompt'])
            self.assertEqual(result['trim_end'],result['duration'])

    def test_economy_intake_uses_synchronous_base_model_for_audio_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            song=Path(tmp);options,calls,route_calls,routed,response=self.detector_fixture(song)
            options.model += ':batch'
            with mock.patch.object(routes,'run_unit',side_effect=routed), \
                 mock.patch.object(pipeline.gemini,'key',return_value='test-not-a-secret'), \
                 mock.patch.object(pipeline.gemini,'call',side_effect=response):
                pipeline.detect_youtube_trim(song,{'title':'Fixture'},options)
            self.assertTrue(calls)
            self.assertEqual({r['base_model'] for r in route_calls},{pipeline.MODEL})
            self.assertEqual({r['model'] for r in calls},{pipeline.MODEL})

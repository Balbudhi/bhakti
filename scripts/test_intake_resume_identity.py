"""Actual main regressions for independently found allowance/reset defects."""
import contextlib
import json
import os
import unittest
from unittest import mock
from pathlib import Path
import test_intake_run_prerequisites as helpers
import bhakti_pipeline as p


class IntakeResumeIdentity(unittest.TestCase):
    setUp=helpers.IntakeRunPrerequisites.setUp
    tearDown=helpers.IntakeRunPrerequisites.tearDown
    invoke=helpers.IntakeRunPrerequisites.invoke
    worker=helpers.IntakeRunPrerequisites.worker
    # Only these new regressions are selected in the review command; the base
    # test helper retains actual main/parse_args and actual ledger writes.
    def test_missing_ledger_holds_without_recreating_allowance(self):
        self.assertEqual(self.invoke(),0)
        ledger=Path(self.calls[-1]['ledger']);run=ledger.parent/'run.json';before=run.read_bytes()
        ledger.unlink();n=len(self.calls)
        self.assertEqual(self.invoke(),1)
        self.assertEqual(len(self.calls),n);self.assertFalse(ledger.exists());self.assertEqual(run.read_bytes(),before)

    def test_matching_limits_replacement_and_same_nonce_rollback_hold(self):
        self.assertEqual(self.invoke(),0)
        ledger=Path(self.calls[-1]['ledger']);original=json.loads(ledger.read_text());n=len(self.calls)
        for replacement in (
            {k:v for k,v in original.items() if k in ('version','budget_usd','max_calls','deadline_at','blocked')},
            dict(original),
        ):
            with self.subTest(keys=sorted(replacement)):
                replacement['requests']=[];ledger.write_text(json.dumps(replacement));before=ledger.read_bytes()
                self.assertEqual(self.invoke(),1)
                self.assertEqual(len(self.calls),n);self.assertEqual(ledger.read_bytes(),before)

    def test_legitimate_appended_request_remains_resumable(self):
        self.assertEqual(self.invoke(),0)
        ledger=Path(self.calls[-1]['ledger']);budget=self.calls[-1]['budget']
        with p.gemini._locked_run_ledger(ledger,budget) as record:
            record['requests'].append({'id':'cooperating-caller','status':'parsed','reservation_usd':.03,'reported_cost_usd':.02})
        prefix=json.loads(ledger.read_text())['requests']
        self.assertEqual(self.invoke(),0)
        self.assertEqual(json.loads(ledger.read_text())['requests'][:len(prefix)],prefix)

    def test_lower_call_limit_at_lock_acquisition_is_not_widened(self):
        ledger=self.root/'.transcription'/'external.json';ledger.parent.mkdir(parents=True)
        ledger.write_text(json.dumps({'version':1,'budget_usd':.4,'max_calls':9,'blocked':False,'requests':[]}))
        original_lock=p.gemini._locked_run_ledger
        @contextlib.contextmanager
        def changed(path,budget):
            record=json.loads(path.read_text());record['max_calls']=3;path.write_text(json.dumps(record))
            with original_lock(path,budget) as record:yield record
        with mock.patch.dict(os.environ,{'BHAKTI_API_RUN_LEDGER':str(ledger),'BHAKTI_API_RUN_BUDGET_USD':'.4'}), \
             mock.patch.object(p.gemini,'_locked_run_ledger',side_effect=changed):
            self.assertEqual(self.invoke(),1)
        self.assertEqual(self.calls,[]);self.assertEqual(json.loads(ledger.read_text())['max_calls'],3)

    def test_canonical_youtube_aliases_share_one_original_allowance(self):
        for source in ('https://youtu.be/abcdefghijk','https://www.youtube.com/watch?v=abcdefghijk'):
            self.input=source
            self.assertEqual(self.invoke(),0)
        self.assertEqual(self.calls[0]['ledger'],self.calls[1]['ledger'])
        self.assertEqual(self.calls[0]['deadline'],self.calls[1]['deadline'])
        self.assertEqual(len(json.loads(Path(self.calls[0]['ledger']).read_text())['requests']),2)

    def test_existing_textual_query_input_is_supported(self):
        self.input='Kabir song official artist'
        self.assertEqual(self.invoke(),0)
        self.assertEqual(len(self.calls),1)

    def test_owned_source_identity_uses_preserved_original_after_real_trim(self):
        from test_boundary_application import create_audio,accepted_crop
        song=self.root/'songs'/'song-0';song.mkdir(parents=True);create_audio(song)
        self.input=song/'audio.m4a'
        original=self.input.read_bytes()
        def first_worker(job,options):
            result=self.worker(job,options)
            p.apply_lossless_trim(song,accepted_crop(song))
            return result
        self.assertEqual(self.invoke(worker=first_worker),0)
        self.assertNotEqual(self.input.read_bytes(),original)
        self.assertEqual(self.invoke(),0)
        self.assertEqual(self.calls[0]['ledger'],self.calls[1]['ledger'])
        archive=song/'.transcription'/'original-audio'/'audio.m4a';archive.write_bytes(b'tamper')
        n=len(self.calls);ledger=Path(self.calls[-1]['ledger']);before=ledger.read_bytes()
        self.assertEqual(self.invoke(),1)
        self.assertEqual(len(self.calls),n);self.assertEqual(ledger.read_bytes(),before)

    def test_coordinator_exception_retains_charged_prefix_for_resume(self):
        def interrupted(options,jobs):
            self.worker(jobs[0],options)
            raise RuntimeError('fixture coordinator interruption after settled charge')
        with mock.patch.object(p,'_execute_intake_jobs',side_effect=interrupted):
            self.assertEqual(self.invoke(),1)
        ledger=Path(self.calls[-1]['ledger']);original=json.loads(ledger.read_text());n=len(self.calls)
        replacement=dict(original);replacement['requests']=[];ledger.write_text(json.dumps(replacement))
        self.assertEqual(self.invoke(),1)
        self.assertEqual(len(self.calls),n)
        ledger.write_text(json.dumps(original))
        self.assertEqual(self.invoke(),0)
        self.assertEqual(json.loads(ledger.read_text())['requests'][0],original['requests'][0])

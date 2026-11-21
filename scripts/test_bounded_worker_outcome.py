"""Real child-process failure classification; only a localhost server is used."""
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

# Private review overlay, then the existing real HTTP fixture and dependencies.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.append(str(Path(os.environ.get('BHAKTI_TEST_PIPELINE_ROOT', Path(__file__).resolve().parents[1])) / 'scripts'))
import process_song_gemini as client
import bhakti_model_routes as routes
from test_bounded_gemini_transport import BoundedTransportTests


class WorkerOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = BoundedTransportTests('test_success_saves_exact_raw_and_usage_without_credentials')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_worker_nonzero_preserves_unknown_outcome_and_never_replays(self):
        # Real request reaches the local server, but the child dies before saving
        # or acknowledging the response. Deliberately hostile stderr must not leak.
        original = client._BOUNDED_HTTP_WORKER
        needle = "    path = Path(job['response_path'])"
        self.assertEqual(original.count(needle), 1)
        worker = original.replace(needle, """    sys.stderr.write('private-worker-secret ' + repr(job['headers']) + 'x' * 10000 + '\\n')
    sys.stderr.write('ssl.SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] private-worker-secret\\n')
    sys.stderr.write('urllib.error.URLError: [Errno 54] https://user:private-worker-secret@example.test/\\n')
    sys.exit(7)
""" + needle)
        statuses = []
        update = client._bounded_update
        def record(*args, **kwargs):
            statuses.append(kwargs.get('status'))
            return update(*args, **kwargs)
        with patch.object(client, '_BOUNDED_HTTP_WORKER', worker), patch.object(client, '_bounded_update', side_effect=record):
            with self.assertRaises(RuntimeError) as caught:
                self.fixture.call()
        ledger = self.fixture.ledger()
        row = ledger['requests'][0]
        self.assertEqual(row['status'], 'unknown-outcome')
        self.assertEqual(statuses, ['unknown-outcome'])
        self.assertEqual(row['error'], 'HTTP worker exited without a confirmed response')
        self.assertTrue(row['worker_terminated'])
        diagnostics = row['worker_failure']
        self.assertEqual(diagnostics['returncode'], 7)
        self.assertGreater(diagnostics['stderr_bytes'], 10000)
        self.assertTrue(diagnostics['stderr_redacted'])
        self.assertLessEqual(len(diagnostics['stderr_summary']), 512)
        self.assertIn('SSLCertVerificationError', diagnostics['stderr_summary'])
        self.assertIn('URLError', diagnostics['stderr_summary'])
        self.assertIn('Errno 54', diagnostics['stderr_summary'])
        self.assertIn('CERTIFICATE_VERIFY_FAILED', diagnostics['stderr_summary'])
        self.assertNotIn('example.test', diagnostics['stderr_summary'])
        self.assertTrue(ledger['blocked'])
        self.assertGreater(row['reservation_usd'], 0)
        self.assertNotIn('reported_cost_usd', row)
        self.assertNotIn('http_status', row)
        self.assertFalse(Path(row['response_path']).exists())
        self.assertIn('without a confirmed response', str(caught.exception))
        self.assertNotIn('deadline', str(caught.exception))
        with self.assertRaises(ProcessLookupError):
            os.kill(row['worker_pid'], 0)
        with self.assertRaisesRegex(RuntimeError, 'blocked'):
            self.fixture.call('must not be replayed')
        self.assertEqual(len(self.fixture.requests), 1)
        self.assertEqual(len(self.fixture.ledger()['requests']), 1)
        persisted = '\n'.join(p.read_text() for p in self.fixture.root.rglob('*.json'))
        for secret in ('private-worker-secret', 'test-secret-never-persist'):
            self.assertNotIn(secret, persisted)
            self.assertNotIn(secret, str(caught.exception))

    def test_successful_http_invalid_body_is_a_different_known_failure(self):
        self.fixture.response = []  # valid HTTP acknowledgement, invalid response shape
        with self.assertRaises(RuntimeError):
            self.fixture.call()
        row = self.fixture.ledger()['requests'][0]
        self.assertEqual(row['http_status'], 200)
        self.assertTrue(Path(row['response_path']).exists())
        self.assertNotEqual(row['status'], 'unknown-outcome')
        self.assertTrue(self.fixture.ledger()['blocked'])
        self.assertEqual(len(self.fixture.requests), 1)

    def test_scoped_worker_failure_keeps_reservation_and_diagnostics_without_replay(self):
        needle = "    path = Path(job['response_path'])"
        worker = client._BOUNDED_HTTP_WORKER.replace(needle, """    sys.stderr.write('ConnectionResetError: [Errno 54] test-secret-never-persist')
    sys.exit(9)
""" + needle)
        def execute(ctx):
            return client.call(ctx.model, 'test-secret-never-persist', 'fixture', audio=None,
                timeout=3, max_completion_tokens=512, deadline_at=ctx.deadline_at,
                unit_context=ctx.transport_context)
        with patch.object(client, '_BOUNDED_HTTP_WORKER', worker):
            for _ in range(2):
                with self.assertRaises(routes.UnitUnresolved):
                    routes.run_unit(self.fixture.root/'route', 'timing:fixture', 'a'*64,
                        execute, lambda value: [], deadline_at=time.time()+20,
                        base_model=routes.FLASH_MODEL, pro_model=routes.FLASH_MODEL)
        ledger=self.fixture.ledger();row=ledger['requests'][0]
        self.assertFalse(ledger['blocked'])
        self.assertEqual(row['status'], 'unknown-outcome')
        self.assertGreater(row['reservation_usd'], 0)
        self.assertNotIn('reported_cost_usd', row)
        self.assertEqual(row['worker_failure']['returncode'], 9)
        self.assertIn('ConnectionResetError', row['worker_failure']['stderr_summary'])
        self.assertEqual(len(ledger['blocked_attempts']), 1)
        self.assertEqual(len(ledger['requests']), 1)
        self.assertEqual(len(self.fixture.requests), 1)
        for path in self.fixture.root.rglob('*.json'):
            self.assertNotIn('test-secret-never-persist', path.read_text())


if __name__ == '__main__':
    unittest.main()

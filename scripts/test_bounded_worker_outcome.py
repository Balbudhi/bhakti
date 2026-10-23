"""Real child-process failure classification; only a localhost server is used."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

# Private review overlay, then the existing real HTTP fixture and dependencies.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.append(str(Path(os.environ.get('BHAKTI_TEST_PIPELINE_ROOT', Path(__file__).resolve().parents[1])) / 'scripts'))
import process_song_gemini as client
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
        worker = original.replace(needle, """    sys.stderr.write('private-worker-secret ' + repr(job['headers']))
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


if __name__ == '__main__':
    unittest.main()

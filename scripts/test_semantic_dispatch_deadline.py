"""Real local transport boundaries; no paid/network provider calls."""
import threading
import time
import unittest
from unittest.mock import patch
from test_bounded_gemini_transport import BoundedTransportTests
import process_song_gemini as client


class AbsoluteDeadlineTests(BoundedTransportTests):
    def deadline_call(self, seconds=.04, timeout=2):
        return client.call(client.GEMINI_MODEL, 'test-secret-never-persist', 'fixture',
                           audio=None, timeout=timeout, max_completion_tokens=512,
                           deadline_at=time.time()+seconds)

    def test_real_semaphore_wait_cannot_dispatch_after_absolute_deadline(self):
        slot = threading.BoundedSemaphore(1); slot.acquire()
        release = threading.Timer(.12, slot.release); release.start(); self.addCleanup(release.join)
        with patch.object(client, '_API_SLOTS', slot):
            with self.assertRaisesRegex(RuntimeError, 'deadline'): self.deadline_call()
        self.assertEqual(self.requests, [])
        self.assertFalse((self.root / 'ledger.json').exists(), 'expired queue wait cannot reserve a new request')

    def test_scheduler_stagger_cannot_dispatch_after_absolute_deadline(self):
        with patch.object(client, '_wait_for_api_start', side_effect=lambda: time.sleep(.08)):
            with self.assertRaisesRegex(RuntimeError, 'deadline'): self.deadline_call()
        self.assertEqual(self.requests, [])
        self.assertFalse((self.root / 'ledger.json').exists())

    def test_deadline_rechecked_after_reservation_before_popen(self):
        original = client._private_json
        def wait_after_request_record(path, value):
            original(path, value)
            if path.name.endswith('.request.json'): time.sleep(.08)
        with patch.object(client, '_private_json', side_effect=wait_after_request_record), \
             patch.object(client.subprocess, 'Popen', wraps=client.subprocess.Popen) as popen:
            with self.assertRaisesRegex(RuntimeError, 'deadline|invalid'):
                self.deadline_call()
        popen.assert_not_called()
        self.assertEqual(self.requests, [])
        self.assertTrue(self.ledger()['blocked'])

    def test_worker_wait_uses_remaining_absolute_lifetime(self):
        self.keepalive = True
        with patch.object(client, '_wait_for_api_start', side_effect=lambda: time.sleep(.08)):
            started = time.monotonic()
            with self.assertRaisesRegex(RuntimeError, 'deadline'):
                self.deadline_call(seconds=1.5, timeout=5)
            elapsed = time.monotonic()-started
        self.assertLess(elapsed, 2.1, 'worker must stop near its absolute1.5s deadline, not original5s')
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(self.ledger()['blocked'])


if __name__ == '__main__': unittest.main()

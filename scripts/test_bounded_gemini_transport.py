"""Real local HTTP tests: no credentials or paid provider requests."""
import concurrent.futures
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import process_song_gemini as client


class BoundedTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.requests = []
        self.response = {"model": client.GEMINI_MODEL, "provider": "local fixture",
                         "choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}],
                         "usage": {"cost": 0.00001}}
        self.keepalive = False
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                outer.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.end_headers()
                if outer.keepalive:
                    try:
                        for _ in range(400):
                            self.wfile.write(b" ")
                            self.wfile.flush()
                            time.sleep(.025)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                else:
                    self.wfile.write(json.dumps(outer.response).encode())

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.env = patch.dict(os.environ, {"BHAKTI_GEMINI_PROVIDER": "openrouter",
                             "BHAKTI_API_RUN_LEDGER": str(self.root / "ledger.json"),
                             "BHAKTI_API_RUN_BUDGET_USD": "0.01"})
        self.env.start(); self.addCleanup(self.env.stop)
        self.url = patch.object(client, "API_URL", f"http://127.0.0.1:{self.server.server_port}/")
        self.url.start(); self.addCleanup(self.url.stop)
        self.wait = patch.object(client, "_wait_for_api_start")
        self.wait.start(); self.addCleanup(self.wait.stop)

    def call(self, prompt="fixture", timeout=3):
        return client.call(client.GEMINI_MODEL, "test-secret-never-persist", prompt, audio=None,
                           timeout=timeout, max_completion_tokens=512, max_attempts=6)

    def ledger(self):
        return json.loads((self.root / "ledger.json").read_text())

    def test_success_saves_exact_raw_and_usage_without_credentials(self):
        result = self.call()
        self.assertTrue(result["packet"]["ok"])
        ledger = self.ledger()
        row = ledger["requests"][0]
        self.assertEqual(row["status"], "parsed")
        self.assertEqual(row["reported_cost_usd"], .00001)
        self.assertEqual(json.loads(Path(row["response_path"]).read_text()), self.response)
        for path in self.root.rglob("*"):
            if path.is_file():
                self.assertNotIn("test-secret-never-persist", path.read_text())
        self.assertFalse(self.requests[0]["provider"]["allow_fallbacks"])

    def test_periodic_bytes_do_not_extend_hard_deadline_or_trigger_retry(self):
        self.keepalive = True
        started = time.monotonic()
        original = client._bounded_update
        def check_worker_stopped(*args, **kwargs):
            if kwargs.get("status") == "unknown-outcome":
                pid = self.ledger()["requests"][0]["worker_pid"]
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
            return original(*args, **kwargs)
        with patch.object(client, "_bounded_update", side_effect=check_worker_stopped):
            with self.assertRaisesRegex(RuntimeError, "wall deadline"):
                self.call(timeout=2)
        self.assertLess(time.monotonic() - started, 4)
        row = self.ledger()["requests"][0]
        self.assertEqual(row["status"], "unknown-outcome")
        self.assertNotIn("reported_cost_usd", row)
        with self.assertRaisesRegex(RuntimeError, "blocked"):
            self.call(prompt="pipeline fallback must not dispatch")
        self.assertEqual(len(self.requests), 1)

    def test_parse_failure_keeps_raw_cost_and_blocks_fallback_calls(self):
        self.response["choices"][0]["message"]["content"] = '{"unfinished":'
        with self.assertRaisesRegex(RuntimeError, "bounded.*invalid"):
            self.call()
        row = self.ledger()["requests"][0]
        self.assertEqual(row["status"], "invalid-response")
        self.assertEqual(row["reported_cost_usd"], .00001)
        self.assertTrue(Path(row["response_path"]).is_file())
        with self.assertRaisesRegex(RuntimeError, "blocked"):
            self.call()
        self.assertEqual(len(self.requests), 1)

    def test_nonobject_packet_blocks_ledger(self):
        self.response["choices"][0]["message"]["content"] = "[]"
        with self.assertRaisesRegex(RuntimeError, "bounded.*invalid"):
            self.call()
        self.assertTrue(self.ledger()["blocked"])
        self.assertEqual(self.ledger()["requests"][0]["status"], "invalid-response")
        with self.assertRaisesRegex(RuntimeError, "blocked"):
            self.call()
        self.assertEqual(len(self.requests), 1)

    def test_post_reservation_disk_failure_blocks_without_dispatch(self):
        original = client._private_json
        def fail_request(path, value):
            if path.name.endswith(".request.json"):
                raise OSError("fixture write failure")
            original(path, value)
        with patch.object(client, "_private_json", side_effect=fail_request):
            with self.assertRaisesRegex(RuntimeError, "bounded.*invalid"):
                self.call()
        self.assertTrue(self.ledger()["blocked"])
        with self.assertRaisesRegex(RuntimeError, "blocked"):
            self.call()
        self.assertEqual(self.requests, [])

    def test_success_finalization_failure_blocks_further_dispatch(self):
        original = client._bounded_update
        def fail_finalization(*args, **kwargs):
            if kwargs.get("status") == "parsed":
                raise OSError("fixture final ledger failure")
            return original(*args, **kwargs)
        with patch.object(client, "_bounded_update", side_effect=fail_finalization):
            with self.assertRaisesRegex(RuntimeError, "finalization failed"):
                self.call()
        self.assertTrue(self.ledger()["blocked"])
        with self.assertRaisesRegex(RuntimeError, "blocked"):
            self.call()
        self.assertEqual(len(self.requests), 1)

    def test_sibling_failure_between_reservation_and_launch_prevents_dispatch(self):
        original = client._private_json
        def sibling_failed(path, value):
            original(path, value)
            if path.name.endswith(".request.json"):
                with client._locked_run_ledger(self.root / "ledger.json", .01) as ledger:
                    ledger["blocked"] = True
        with patch.object(client, "_private_json", side_effect=sibling_failed):
            with self.assertRaisesRegex(RuntimeError, "bounded.*invalid"):
                self.call()
        self.assertEqual(self.requests, [])
        self.assertEqual(len(self.ledger()["requests"]), 1)

    def test_budget_is_reserved_before_any_network_request(self):
        with patch.dict(os.environ, {"BHAKTI_API_RUN_BUDGET_USD": "0.000001"}):
            with self.assertRaisesRegex(RuntimeError, "budget"):
                self.call()
        self.assertEqual(self.requests, [])

    def test_missing_cap_and_wrong_model_fail_before_network(self):
        for model, cap in [(client.GEMINI_MODEL, None), ("google/another-model", 512)]:
            with self.assertRaises(RuntimeError):
                client.call(model, "fixture", "fixture", audio=None, timeout=1,
                            max_completion_tokens=cap)
        self.assertEqual(self.requests, [])

    def test_concurrent_reservations_cannot_overspend(self):
        self.keepalive = True
        with patch.dict(os.environ, {"BHAKTI_API_RUN_BUDGET_USD": "0.004"}):
            def attempt(_):
                try:
                    self.call(timeout=2)
                except RuntimeError:
                    return
                self.fail("keepalive fixture must not complete")
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(attempt, range(2)))
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(len(self.ledger()["requests"]), 1)

    def test_two_processes_share_reservation_budget(self):
        self.keepalive = True
        source = """import sys
sys.path.insert(0, sys.argv[1])
import process_song_gemini as c
c.API_URL = sys.argv[2]
try:
 c.call(c.GEMINI_MODEL, 'fixture', 'fixture', audio=None, timeout=2, max_completion_tokens=512)
except RuntimeError:
 pass
"""
        environment = dict(os.environ, BHAKTI_API_RUN_BUDGET_USD="0.004")
        jobs = [subprocess.Popen([sys.executable, "-c", source, str(Path(client.__file__).parent), client.API_URL],
                                 env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        for job in jobs:
            stdout, stderr = job.communicate(timeout=8)
            self.assertEqual(job.returncode, 0, stderr)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(len(self.ledger()["requests"]), 1)


if __name__ == "__main__":
    unittest.main()

"""Forced AI Studio wire-size preflight; no HTTP, provider or child dispatch."""
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import process_song_gemini as client


LIMIT = 20_000_000


class ReservationReached(BaseException):
    """Stop at the first ledger access, before any reservation is written."""


class BoundedPayloadSizeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.ledger = self.root / 'ledger.json'
        env = patch.dict(os.environ, {
            'BHAKTI_GEMINI_PROVIDER': 'openrouter',
            'BHAKTI_API_RUN_LEDGER': str(self.ledger),
            'BHAKTI_API_RUN_BUDGET_USD': '10',
        })
        env.start()
        self.addCleanup(env.stop)

    def payload(self, size, *, prefix=''):
        payload = {'model': client.model_routes.FLASH_MODEL, 'max_tokens': 512,
                   'messages': [{'role': 'user', 'content': [
                       {'type': 'text', 'text': prefix},
                       {'type': 'input_audio', 'input_audio': {'data': '', 'format': 'mp3'}}]}]}
        priced = client.model_routes.model_pricing(payload['model'], 2048)
        forced = {'only': ['google-ai-studio'], 'order': ['google-ai-studio'],
                  'ignore': ['google-ai-studio/flex', 'google-ai-studio/priority'],
                  'allow_fallbacks': False, 'require_parameters': True,
                  'max_price': {key: priced[key] for key in ('prompt', 'completion')}}
        remaining = size - len(json.dumps({**payload, 'provider': forced}).encode('utf-8'))
        self.assertGreaterEqual(remaining, 0)
        payload['messages'][0]['content'][1]['input_audio']['data'] = 'A' * remaining
        return payload, forced

    def reject(self, payload):
        before = copy.deepcopy(payload)
        original_files = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        aborted = set(client._ABORTED_RUNS)
        with patch.object(client, '_locked_run_ledger', side_effect=ReservationReached) as ledger, \
                patch.object(client.subprocess, 'Popen') as process:
            with self.assertRaises(client.model_routes.UnitTransportFailure) as caught:
                client._bounded_call(payload, 'secret-sentinel', None, 5)
        self.assertEqual(caught.exception.category, 'request-too-large')
        self.assertIsNone(caught.exception.request_id)
        self.assertIn('20000000', str(caught.exception))
        self.assertIn('no request sent', str(caught.exception))
        self.assertNotIn('secret-sentinel', str(caught.exception))
        ledger.assert_not_called()
        process.assert_not_called()
        self.assertEqual(client._ABORTED_RUNS, aborted)
        self.assertEqual(payload, before)
        self.assertEqual({p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}, original_files)
        self.assertFalse((self.root / 'ledger-responses').exists())
        return caught.exception

    def test_exact_limit_is_allowed_to_reservation_boundary(self):
        payload, forced = self.payload(LIMIT, prefix='ਹਰਿ “name”')
        self.assertEqual(len(json.dumps({**payload, 'provider': forced}).encode()), LIMIT)
        with patch.object(client, '_locked_run_ledger', side_effect=ReservationReached) as ledger, \
                patch.object(client.subprocess, 'Popen') as process:
            with self.assertRaises(ReservationReached):
                client._bounded_call(payload, 'secret-sentinel', None, 5)
        ledger.assert_called_once()
        process.assert_not_called()
        self.assertFalse(self.ledger.exists())

    def test_one_byte_over_includes_forced_provider_overhead(self):
        payload, forced = self.payload(LIMIT + 1)
        self.assertLess(len(json.dumps(payload).encode()), LIMIT)
        self.assertEqual(len(json.dumps({**payload, 'provider': forced}).encode()), LIMIT + 1)
        error = self.reject(payload)
        self.assertIn(str(LIMIT + 1), str(error))

    def test_ascii_escaping_matches_worker_not_raw_utf8_estimate(self):
        payload, forced = self.payload(LIMIT + 1, prefix='ਹ' * 200)
        self.assertLess(len(json.dumps({**payload, 'provider': forced}, ensure_ascii=False).encode()), LIMIT)
        self.reject(payload)

    def test_existing_unknown_reservation_is_untouched(self):
        self.ledger.write_text(json.dumps({'version': 1, 'budget_usd': 10, 'blocked': False,
            'requests': [{'id': 'old', 'status': 'unknown-outcome', 'reservation_usd': .8}]}))
        payload, _ = self.payload(LIMIT + 1)
        self.reject(payload)

    def test_router_holds_only_oversized_unit_without_pro_or_global_abort(self):
        payload, _ = self.payload(LIMIT + 1)
        attempted = []
        def execute(context):
            attempted.append(context.model)
            client._bounded_call(payload, 'secret-sentinel', None, 5,
                                 unit_context=context.transport_context)
        with patch.object(client.subprocess, 'Popen', side_effect=AssertionError('unexpected child dispatch')) as process:
            with self.assertRaises(client.model_routes.UnitUnresolved) as caught:
                client.model_routes.run_unit(self.root / 'routes', 'oversize', 'a' * 64,
                    execute, lambda _: [], deadline_at=time.time() + 60)
        state = json.loads(caught.exception.state_path.read_text())
        self.assertEqual(state['reason'], 'request-too-large')
        self.assertEqual(len(state['attempts']), 1)
        self.assertEqual(attempted, [client.model_routes.FLASH_MODEL])
        self.assertIsNone(state['attempts'][0]['request_id'])
        process.assert_not_called()
        self.assertFalse(self.ledger.exists())
        self.assertNotIn(str(self.ledger.resolve()), client._ABORTED_RUNS)
        # A distinct unit can still execute under the same run allowance.
        result = client.model_routes.run_unit(self.root / 'routes', 'other', 'b' * 64,
            lambda _: {'ok': True}, lambda _: [], deadline_at=time.time() + 60)
        self.assertEqual(result, {'ok': True})

    def test_actual_worker_uses_default_ascii_json_serialization(self):
        payload = {'messages': [{'text': 'ਹਰਿ “name”\n'}], 'provider': {'only': ['google-ai-studio']}}
        job = {'url': 'https://invalid.example/', 'payload': payload, 'headers': {},
               'timeout': 1, 'response_path': str(self.root / 'response.json')}
        class Response:
            code = 200
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self): return b'{}'
        with patch.object(client.sys, 'stdin', io.StringIO(json.dumps(job))), \
                patch.object(client.sys, 'stdout', io.StringIO()), \
                patch.object(client.urllib.request, 'urlopen', return_value=Response()) as http:
            exec(client._BOUNDED_HTTP_WORKER, {})
        wire = http.call_args.args[0].data
        self.assertEqual(wire, json.dumps(payload).encode('utf-8'))
        self.assertNotEqual(wire, json.dumps(payload, ensure_ascii=False).encode('utf-8'))


if __name__ == '__main__':
    unittest.main()

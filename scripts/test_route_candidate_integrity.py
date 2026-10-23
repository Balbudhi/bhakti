"""Persist all returned candidate identities before quality validation; no API."""
import json
from pathlib import Path
import tempfile
import time
import unittest

import bhakti_model_routes as routes
from bhakti_semantic_repair import digest


class CandidateIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.deadline = time.time()+60
        self.candidates = []; self.seen_at_validation = []

    def execute(self, context):
        candidate = {'attempt_id': context.attempt_id, 'model': context.model,
                     'source': 'ठिकाना', 'semantic_assertion': 'observed current reader'}
        self.candidates.append((context, candidate))
        return candidate

    def validate(self, candidate):
        context = self.candidates[-1][0]
        state = json.loads(Path(context.transport_context['state_path']).read_text())
        record = next(r for r in state['attempts'] if r['attempt_id']==candidate['attempt_id'])
        self.seen_at_validation.append(record.get('candidate_sha256'))
        return ([{'kind':'invalid_review','detail':'malformed sibling audit row'}]
                if candidate['model']==routes.FLASH_MODEL else [])

    def run_unit(self, execute=None):
        return routes.run_unit(self.directory,'song:current-source-review','immutable-original-input',
            self.execute if execute is None else execute,self.validate,
            deadline_at=self.deadline,dependency_fingerprint='original-recording-policy')

    def test_unit_state_path_matches_real_identity_without_io_or_version_reset(self):
        expected = routes.unit_state_path(self.directory, 'song:current-source-review',
            'immutable-original-input', dependency_fingerprint='original-recording-policy')
        self.assertEqual(list(self.directory.iterdir()), [])
        self.run_unit()
        actual = Path(self.candidates[0][0].transport_context['state_path'])
        self.assertEqual(expected.resolve(), actual)
        state = json.loads(actual.read_text())
        self.assertEqual(state['version'], 1)
        changed = routes.unit_state_path(self.directory, 'song:current-source-review',
            'different-input', dependency_fingerprint='original-recording-policy')
        self.assertNotEqual(changed, expected)
        self.assertFalse(changed.exists())

    def test_quality_failed_candidate_hash_is_durable_before_validator_runs(self):
        accepted = self.run_unit()
        self.assertEqual(len(self.candidates),2)
        self.assertEqual(self.seen_at_validation,[digest(candidate) for _,candidate in self.candidates])
        state = json.loads(Path(self.candidates[0][0].transport_context['state_path']).read_text())
        self.assertEqual([r['status'] for r in state['attempts']],['quality-failed','accepted'])
        self.assertEqual(state['attempts'][0]['candidate_sha256'],digest(self.candidates[0][1]))
        self.assertEqual(accepted,self.candidates[1][1])

    def test_changed_failed_candidate_rejected_before_accepted_cache_reuse(self):
        self.run_unit()
        path = self.candidates[0][0].attempt_dir/'candidate.json'
        candidate = json.loads(path.read_text());candidate['semantic_assertion']='changed failed evidence'
        path.write_text(json.dumps(candidate))
        changed = path.read_bytes()
        def forbidden(context):
            self.fail('integrity failure must not reset spent attempts')
        with self.assertRaisesRegex(routes.RunFatal,'candidate.*(digest|identity)|digest.*candidate'):
            self.run_unit(forbidden)
        self.assertEqual(path.read_bytes(),changed)
        self.assertEqual(len(self.candidates),2)


if __name__=='__main__':unittest.main()

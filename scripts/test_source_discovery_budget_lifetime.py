"""A run owner's initialized quota cannot be recreated by later acquisition."""
from pathlib import Path
from types import SimpleNamespace
import unittest
import test_source_discovery as fixture

class SourceBudgetLifetime(unittest.TestCase):
    def setUp(self):
        self.case=fixture.SourceDiscoveryRequirements();self.case.setUp();self.addCleanup(self.case.doCleanups)
        c=self.case
        self.budget=c.discovery.configure_run_budget(c.root,c.budget['deadline_at'],
            SimpleNamespace(source_discovery_max_requests=1))

    def acquire(self,opener=None,budget=None):
        c=self.case
        return c.discovery.acquire_source_candidates(c.plan(),c.root/'cache',
            opener=opener or c.opener,run_budget=budget or self.budget)

    def test_counter_removed_between_calls_cannot_renew_one_request_allowance(self):
        c=self.case
        first=self.acquire();self.assertEqual(c.calls,['बजरंग'])
        self.assertTrue(any(gap['kind']=='source_discovery_budget' for gap in first['gaps']))
        Path(self.budget['path']).unlink()
        with self.assertRaisesRegex(ValueError,'budget.*missing|quota.*missing'):
            self.acquire()
        self.assertEqual(c.calls,['बजरंग']);self.assertFalse(Path(self.budget['path']).exists())

    def test_counter_removed_after_first_fetch_cannot_be_recreated_for_second_reservation(self):
        c=self.case
        def remove(url,timeout):
            value=c.opener(url,timeout);Path(self.budget['path']).unlink();return value
        with self.assertRaisesRegex(ValueError,'budget.*missing|quota.*missing'):
            self.acquire(opener=remove)
        self.assertEqual(c.calls,['बजरंग']);self.assertFalse(Path(self.budget['path']).exists())

    def test_acquisition_requires_owner_initialized_counter_before_any_fetch(self):
        budget={**self.budget,'path':self.case.root/'never-initialized.json'}
        with self.assertRaisesRegex(ValueError,'budget.*missing|quota.*missing'):
            self.acquire(budget=budget)
        self.assertEqual(self.case.calls,[]);self.assertFalse(Path(budget['path']).exists())

if __name__=='__main__':unittest.main()

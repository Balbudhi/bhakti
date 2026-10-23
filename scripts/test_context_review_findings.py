"""Real review/router/journal path; provider alone is mocked."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import test_review_findings_integration as fixture_helpers
from test_review_findings_integration import clean_review
import bhakti_library_pass as library
import bhakti_review_findings as findings
from bhakti_semantic_repair import digest

class ContextFindingsTests(unittest.TestCase):
    setUp = fixture_helpers.FindingIntegrationTests.setUp
    audit = fixture_helpers.FindingIntegrationTests.audit
    provider = fixture_helpers.FindingIntegrationTests.provider
    authorize = fixture_helpers.FindingIntegrationTests.authorize
    corrected_candidate = fixture_helpers.FindingIntegrationTests.corrected_candidate

    def observed_run(self, extra, *, early=False):
        self.fixture['reviews'] = copy.deepcopy(self.fixture['later_reviews'])
        if early:
            # Keep the real reporting row out of first child targets, then review
            # it clean in the last child. Actual source/gloss content is unchanged.
            key = extra['id']
            sequence = self.reader['SONG_SEQUENCE']
            self.reader['SONG_SEQUENCE'] = ([event for event in sequence if event['ref'] != key]
                + [event for event in sequence if event['ref'] == key])
            self.lines, self.glosses, self.translations = library.reader_evidence(self.reader)
            self.context.update(lines=self.lines, glosses=self.glosses, reader_digest=digest(self.reader))
        if not early:
            # The last outro-only request does not naturally include this verse.
            # Supply it as a real explicit dependency, rather than rely on the
            # former whole-song source dump to authorize unrelated response IDs.
            key = extra['id']
            self.options.semantic_distant_context = [{
                'source': copy.deepcopy(next(row for row in self.lines if row['id'] == key)),
                'gloss': copy.deepcopy(next(row for row in self.glosses if row['id'] == key)),
                'draft': copy.deepcopy(next(row for row in self.translations if row['id'] == key)),
            }]
        original = self.provider
        raw = []
        def provider(*args, **kwargs):
            response = original(*args, **kwargs)
            rows = response['packet']['reviews']
            if (len(rows) == 10) == early:
                self.assertNotIn(extra['id'], [row['id'] for row in rows])
                response['packet']['reviews'].append(copy.deepcopy(extra))
                raw.append(copy.deepcopy(response))
            return response
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), \
             patch.object(library.pipeline.gemini, 'call', side_effect=provider):
            result = self.audit()
            calls = len(self.calls)
            replay = self.audit()
        self.assertEqual(calls, 2)
        self.assertEqual(len(self.calls), calls)
        self.assertEqual(result, replay)
        self.assertEqual([row['id'] for row in result['reviews']], [row['id'] for row in self.lines])
        self.assertTrue(all(row['passes'] for row in result['reviews']))
        return result, raw[0]

    def assert_dependency(self, result, raw, extra, observed_kind):
        pending = findings.pending_findings(result['finding_snapshot'])
        self.assertEqual(len(pending), 1)
        item = pending[0]
        self.assertEqual(item['kind'], 'context_dependency')
        self.assertEqual(item['observed_kind'], observed_kind)
        self.assertEqual(item['row'], extra)
        scope = item['context_scope']
        self.assertNotIn(extra['id'], scope['target_ids'])
        self.assertIn(extra['id'], scope['context_ids'])
        self.assertEqual(scope['response_digest'], digest(raw))
        self.assertTrue(any(packet['response'] == raw for packet in result['context_review_packets']))
        with self.assertRaisesRegex(ValueError, 'pending|unresolved'):
            self.authorize(self.reader, result, None, result['finding_snapshot'])
        return item

    def test_late_context_defect_survives_clean_own_batch_and_replay(self):
        extra = next(copy.deepcopy(row) for row in self.fixture['reviews'] if row['issues'])
        result, raw = self.observed_run(extra)
        item = self.assert_dependency(result, raw, extra, 'defect')
        self.assertEqual(item['issue'], extra['issues'][0])
        # Context-only evidence cannot authorize an otherwise sensible target edit.
        with self.assertRaises(ValueError):
            self.authorize(self.corrected_candidate(), result, None,
                           result['finding_snapshot'], partial=True)
        snapshot = copy.deepcopy(result['finding_snapshot'])
        snapshot['reviews'][0]['artifact']['context_review_packets'][0]['target_ids'].append(extra['id'])
        with self.assertRaises(ValueError):
            findings.validate_snapshot(snapshot, **self.context)

    def test_early_context_choice_survives_later_clean_own_batch(self):
        extra = next(copy.deepcopy(row) for row in self.fixture['reviews']
                     if row['human_review_recommended'] and not row['issues'])
        result, raw = self.observed_run(extra, early=True)
        self.assert_dependency(result, raw, extra, 'open_choice')

    def test_passing_context_projects_without_finding_or_new_target(self):
        extra = clean_review('verse-3-line-2')
        result, _ = self.observed_run(extra)
        self.assertEqual(result['finding_snapshot']['findings'], [])
        self.assertEqual(result['issues'], [])

    def test_context_scope_and_duplicate_rows_fail_closed_without_fake_findings(self):
        extra = next(copy.deepcopy(row) for row in self.fixture['reviews'] if row['issues'])
        artifact = copy.deepcopy(self.artifact)
        artifact['reviews'] = copy.deepcopy(self.fixture['later_reviews'])
        artifact['issues'] = []
        scope = {'label': '0.1', 'target_ids': ['outro-instrumental'],
                 'context_ids': [line['id'] for line in self.lines],
                 'response': {'packet': {'reviews': [clean_review('outro-instrumental'), extra]}}}
        for changed in ('duplicate', 'unknown-scope', 'malformed-row'):
            with self.subTest(changed=changed):
                packet = copy.deepcopy(scope)
                if changed == 'duplicate': packet['response']['packet']['reviews'].append(extra)
                if changed == 'unknown-scope': packet['context_ids'].append('not-a-reader-line')
                if changed == 'malformed-row': packet['response']['packet']['reviews'][-1]['issues'] = None
                artifact['context_review_packets'] = [packet]
                result = findings.classify_review(artifact, **self.context)
                self.assertTrue(result['contract_errors'])
                self.assertEqual(result['findings'], [])

    def test_policy_invalidates_old_enclosing_review_cache(self):
        policy = library.pipeline.translation_policy_payload()
        self.assertEqual(policy.get('context_findings_contract'), 2)
        legacy = copy.deepcopy(policy); legacy.pop('context_findings_contract')
        self.assertNotEqual(digest(policy), digest(legacy))

if __name__ == '__main__': unittest.main()

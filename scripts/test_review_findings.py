"""Tests specified before implementation; real retained Rehna evidence, no API."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import bhakti_review_findings as findings
import bhakti_library_pass as library

FIXTURE = Path(__file__).resolve().parent / 'fixtures/review_findings/rehna-reviews.json'


class FindingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text())
        self.artifact = {k: copy.deepcopy(self.fixture[k]) for k in
                        ('reader_digest', 'dependency_fingerprint', 'attempt_id', 'reviews', 'issues')}
        self.context = {k: self.fixture[k] for k in ('reader_digest', 'dependency_fingerprint')}
        self.context.update(lines=self.fixture['source_lines'], glosses=self.fixture['gloss_rows'])
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'findings.json'

    def classify(self, artifact=None):
        return findings.classify_review(self.artifact if artifact is None else artifact, **self.context)

    def later_pass(self):
        return {**copy.deepcopy(self.artifact), 'attempt_id': 'independent-later-pro',
                'reviews': copy.deepcopy(self.fixture['later_reviews']), 'issues': []}

    def test_actual_population_keeps_one_defect_three_choices_seven_passing_observations(self):
        saved = copy.deepcopy((self.artifact, self.context))
        result = self.classify()
        self.assertEqual(result['contract_errors'], [])
        defects = [f for f in result['findings'] if f['kind'] == 'defect']
        choices = [f for f in result['findings'] if f['kind'] == 'open_choice']
        self.assertEqual(len(defects), 1)
        self.assertEqual(defects[0]['issue'], self.artifact['issues'][0])
        self.assertEqual(defects[0]['issue']['references'][0]['word_indices'], [2])
        self.assertEqual(defects[0]['issue']['target_line_ids'], ['verse-3-line-2'])
        self.assertEqual({f['line_id'] for f in choices}, {'refrain-1', 'refrain-2', 'verse-1-line-2'})
        self.assertEqual(len(result['observations']), 7)
        self.assertEqual((self.artifact, self.context), saved)
        self.assertEqual(len({f['finding_id'] for f in result['findings']}), 4)

    def test_duplicate_exact_typed_issue_keeps_raw_evidence_but_one_finding(self):
        artifact = copy.deepcopy(self.artifact)
        artifact['reviews'][-2]['issues'].append(copy.deepcopy(artifact['issues'][0]))
        artifact['issues'].append(copy.deepcopy(artifact['issues'][0]))
        classified = self.classify(artifact)
        self.assertEqual(classified['contract_errors'], [])
        self.assertEqual(len(classified['findings']), 4)
        self.assertEqual(len({f['finding_id'] for f in classified['findings']}), 4)
        snapshot = findings.record_review(self.path, artifact, **self.context)
        self.assertEqual(snapshot['reviews'][0]['artifact'], artifact)
        self.assertEqual(len(snapshot['reviews'][0]['artifact']['issues']), 2)
        self.assertEqual(len(snapshot['findings']), 4)

    def test_later_all_pass_does_not_erase_existing_defect_or_choices(self):
        first = findings.record_review(self.path, self.artifact, **self.context)
        second = findings.record_review(self.path, self.later_pass(), **self.context)
        self.assertEqual(findings.pending_findings(second), findings.pending_findings(first))
        self.assertEqual(len(findings.pending_findings(second)), 4)
        self.assertEqual(len(second['reviews']), 2)
        self.assertEqual(second['reviews'][0]['artifact'], self.artifact)
        self.assertEqual(second['reviews'][1]['artifact'], self.later_pass())

    def test_resume_exact_evidence_idempotent_no_finding_recreation(self):
        first = findings.record_review(self.path, self.artifact, **self.context)
        raw = self.path.read_bytes()
        second = findings.record_review(self.path, copy.deepcopy(self.artifact), **self.context)
        self.assertEqual(first, second)
        self.assertEqual(self.path.read_bytes(), raw)

    def test_unrelated_bad_row_cannot_discard_real_finding(self):
        self.artifact['reviews'][0]['passes'] = 'true'
        classified = self.classify()
        self.assertTrue(classified['contract_errors'])
        self.assertEqual(len([f for f in classified['findings'] if f['kind'] == 'defect']), 1)
        snapshot = findings.record_review(self.path, self.artifact, **self.context)
        self.assertEqual(len(findings.pending_findings(snapshot)), 4)
        self.assertTrue(snapshot['reviews'][0]['contract_errors'])

    def test_malformed_sibling_issue_does_not_throw_or_hide_valid_findings(self):
        artifact = copy.deepcopy(self.artifact)
        malformed = {'kind': []}
        artifact['reviews'][0].update(passes=False, issues=[malformed])
        artifact['issues'] = [malformed, *artifact['issues']]
        result = self.classify(artifact)
        self.assertTrue(result['contract_errors'])
        self.assertEqual(len(result['findings']), 4)

    def test_invalid_typed_reference_is_never_a_retained_defect(self):
        for field, value in [('source_quote', 'not performed'), ('word_indices', [999]), ('domain', 'source_tokens')]:
            with self.subTest(field=field):
                artifact = copy.deepcopy(self.artifact)
                artifact['reviews'][-2]['issues'][0]['references'][0][field] = value
                artifact['issues'] = copy.deepcopy(artifact['reviews'][-2]['issues'])
                result = self.classify(artifact)
                self.assertTrue(result['contract_errors'])
                self.assertFalse([f for f in result['findings'] if f['kind'] == 'defect'])

    def test_duplicate_row_cannot_supply_a_finding(self):
        self.artifact['reviews'].append(copy.deepcopy(self.artifact['reviews'][-2]))
        result = self.classify()
        self.assertTrue(result['contract_errors'])
        self.assertFalse([f for f in result['findings'] if f['kind'] == 'defect'])

    def test_issue_for_other_known_row_does_not_explain_reporting_row(self):
        artifact = copy.deepcopy(self.artifact)
        other = self.context['lines'][4]
        issue = artifact['reviews'][-2]['issues'][0]
        issue['target_line_ids'] = [other['id']]
        issue['references'] = [{'line_id': other['id'], 'domain': 'word_glosses',
                                'word_indices': [0], 'source_quote': other['source_text']}]
        artifact['issues'] = copy.deepcopy(artifact['reviews'][-2]['issues'])
        result = self.classify(artifact)
        self.assertTrue(result['contract_errors'])
        self.assertFalse([f for f in result['findings'] if f['kind'] == 'defect'])

    def test_existing_journal_rejects_new_self_consistent_reader_or_dependency(self):
        findings.record_review(self.path, self.artifact, **self.context)
        original = self.path.read_bytes()
        for key in ('reader_digest', 'dependency_fingerprint'):
            with self.subTest(key=key):
                artifact = self.later_pass()
                context = copy.deepcopy(self.context)
                artifact[key] = context[key] = 'new-self-consistent-identity'
                with self.assertRaises(ValueError):
                    findings.record_review(self.path, artifact, **context)
                self.assertEqual(self.path.read_bytes(), original)

    def test_existing_journal_rejects_changed_source_or_gloss_context(self):
        findings.record_review(self.path, self.artifact, **self.context)
        original = self.path.read_bytes()
        for target in ('lines', 'glosses'):
            with self.subTest(target=target):
                context = copy.deepcopy(self.context)
                if target == 'lines':
                    context['lines'][0]['source_text'] += ' changed'
                else:
                    context['glosses'][0]['word_glosses'][0]['gloss'] += ' changed'
                with self.assertRaises(ValueError):
                    findings.record_review(self.path, self.later_pass(), **context)
                self.assertEqual(self.path.read_bytes(), original)

    def test_journal_artifact_or_finding_tamper_rejected_without_rewriting(self):
        findings.record_review(self.path, self.artifact, **self.context)
        original = json.loads(self.path.read_text())
        for target in ('artifact', 'findings'):
            with self.subTest(target=target):
                modified = copy.deepcopy(original)
                if target == 'artifact':
                    modified['reviews'][0]['artifact']['reviews'][0]['material_choice'] = 'tampered'
                else:
                    modified['findings'].pop()
                self.path.write_text(json.dumps(modified, ensure_ascii=False))
                tampered_bytes = self.path.read_bytes()
                with self.assertRaises(ValueError):
                    findings.record_review(self.path, self.later_pass(), **self.context)
                self.assertEqual(self.path.read_bytes(), tampered_bytes)

    def test_classification_and_finding_ids_are_deterministic(self):
        first = self.classify()
        second = self.classify(copy.deepcopy(self.artifact))
        self.assertEqual(first, second)
        self.assertEqual([row['finding_id'] for row in first['findings']],
                         [row['finding_id'] for row in second['findings']])

    def test_same_attempt_changed_result_rejected_original_file_kept(self):
        findings.record_review(self.path, self.artifact, **self.context)
        original = self.path.read_bytes()
        different = self.later_pass(); different['attempt_id'] = self.artifact['attempt_id']
        with self.assertRaises(ValueError):
            findings.record_review(self.path, different, **self.context)
        self.assertEqual(self.path.read_bytes(), original)

    def test_stale_reader_or_dependency_rejects_before_adoption(self):
        for key in ('reader_digest', 'dependency_fingerprint'):
            with self.subTest(key=key):
                artifact = copy.deepcopy(self.artifact); artifact[key] = 'changed'
                with self.assertRaises(ValueError):
                    findings.record_review(self.path, artifact, **self.context)
                self.assertFalse(self.path.exists())

    def test_audit_acceptance_is_shape_not_publication_readiness(self):
        errors = library.current_review_errors(self.artifact, self.context['lines'], self.context['glosses'],
            self.context['reader_digest'], self.context['dependency_fingerprint'])
        self.assertEqual(errors, [])
        self.assertEqual(self.artifact['reviews'][-2]['human_review_recommended'], True)
        self.assertEqual(self.artifact['reviews'][-2]['passes'], False)
        self.assertEqual(len(self.classify()['findings']), 4)

    def test_recovered_response_shape_errors_remain_contract_errors(self):
        artifact = self.later_pass()
        artifact['response_contract_errors'] = ['provider returned an unknown context ID']
        classified = self.classify(artifact)
        self.assertTrue(classified['contract_errors'])
        self.assertEqual(classified['findings'], [])
        snapshot = findings.record_review(self.path, artifact, **self.context)
        self.assertTrue(snapshot['reviews'][0]['contract_errors'])
        self.assertEqual(snapshot['reviews'][0]['artifact'], artifact)

    def test_failed_fidelity_without_evidenced_issue_is_still_malformed(self):
        artifact = self.later_pass()
        artifact['reviews'][0]['imagery_preserved'] = False
        result = self.classify(artifact)
        self.assertTrue(result['contract_errors'])
        self.assertEqual(result['findings'], [])

    def test_truthy_flags_and_missing_choice_are_not_silently_accepted(self):
        for field, value in [('human_review_recommended', 'false'), ('agency_preserved', 1), ('material_choice', None)]:
            with self.subTest(field=field):
                artifact = self.later_pass(); artifact['reviews'][0][field] = value
                self.assertTrue(self.classify(artifact)['contract_errors'])
        artifact = self.later_pass()
        artifact['reviews'][0].update(human_review_recommended=True, material_choice='')
        self.assertTrue(self.classify(artifact)['contract_errors'])


if __name__ == '__main__':
    unittest.main()

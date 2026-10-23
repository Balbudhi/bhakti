"""Six exact retained artifacts + real FFprobe snapshots, captured before migration.

No source audio copied, provider calls or blanket acceptance. Classification
is a proposed read-only suboperation of inspect_historical_boundary.
"""
import copy
import json
from pathlib import Path
import unittest
from unittest import mock
import bhakti_pipeline as p

FIXTURES=json.loads((Path(__file__).parent/'fixtures/historical_boundary/legacy.json').read_text())

class HistoricalBoundaryLegacy(unittest.TestCase):
    def classify(self,row):
        operation=getattr(p,'classify_historical_boundary_evidence',None)
        self.assertTrue(callable(operation),'explicit legacy boundary classification is missing')
        before=copy.deepcopy(row)
        with mock.patch.object(p.gemini,'call',side_effect=AssertionError('inventory must not buy model calls')):
            result=operation(row)
        self.assertEqual(row,before)
        self.assertFalse(result['publicationEligible'])
        self.assertEqual(result['original_binding'],'unproven')
        return result

    def test_four_previously_shortened_masters_require_real_original_recovery(self):
        shortened={'akashi-zep-ghe-re-pakhara','anuraniya-thokada','arunachala-akshara-mana-malai','he-sadaguru-tume-mor-haatku-dhara'}
        for row in FIXTURES:
            if row['slug'] not in shortened:continue
            with self.subTest(slug=row['slug']):
                result=self.classify(row)
                self.assertEqual(result['status'],'needs-original-recovery')
                self.assertIn('original-audio-identity',result['remaining_obligations'])
                self.assertFalse(result['can_review_original_edges_now'])

    def test_two_full_duration_candidates_do_not_become_retroactive_request_proof(self):
        for row in FIXTURES:
            if row['slug'] not in {'benti-chaupai','shri-guru-prarthana'}:continue
            with self.subTest(slug=row['slug']):
                result=self.classify(row)
                self.assertEqual(result['status'],'needs-boundary-review')
                self.assertTrue(result['can_archive_current_master'])
                self.assertFalse(result['legacy_observation_reusable'])
                self.assertIn('boundary-source-binding',result['remaining_obligations'])

    def test_actual_conflicting_intervals_and_suppressed_outro_remain_explicit(self):
        by_slug={row['slug']:row for row in FIXTURES}
        expected={'akashi-zep-ghe-re-pakhara':'applied-end-differs',
                  'anuraniya-thokada':'unapplied-end-proposal',
                  'he-sadaguru-tume-mor-haatku-dhara':'applied-start-differs'}
        for slug,issue in expected.items():
            with self.subTest(slug=slug):self.assertIn(issue,self.classify(by_slug[slug])['conflicts'])

    def test_arunachala_preserves_owner_silence_record_without_certifying_logo_claim(self):
        row=next(row for row in FIXTURES if row['slug']=='arunachala-akshara-mana-malai')
        result=self.classify(row)
        self.assertEqual(result['retained_editorial_review'],row['artifacts']['trim-review.json']['editorial_review'])
        self.assertIn('verify-leading-silence-and-entire-prelude',result['remaining_obligations'])
        self.assertNotIn('whole-recording-transcription',result['remaining_obligations'])
        self.assertNotIn('retranslate',result['remaining_obligations'])

    def test_attached_narration_is_not_removed_by_type_or_old_high_confidence(self):
        for slug in ['he-sadaguru-tume-mor-haatku-dhara','shri-guru-prarthana']:
            row=next(row for row in FIXTURES if row['slug']==slug)
            result=self.classify(row)
            self.assertIn('establish-spoken-work-relationship',result['remaining_obligations'])
            self.assertNotIn('approved_interval',result)

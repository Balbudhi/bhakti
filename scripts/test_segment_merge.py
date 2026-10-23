"""Cached recording regressions for lossless transcript seam reconciliation."""
import copy
import json
import unittest
from pathlib import Path
import bhakti_pipeline as pipeline

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/patta_segment_merge.json').read_text())

def surfaces(packet):
    lines = {row['id']: row['source_text'] for row in packet['verified_lines']}
    return [lines[row['line_id']] for row in packet['performance_order']]

def segment(index, words, start, end):
    lines = [{'id': str(i), 'source_text': text, 'roman': text, 'kind': 'verse',
              'language': 'Hindi', 'partial': partial} for i, (text, partial) in enumerate(words)]
    return {'segment': {'index': index, 'clip_start': start, 'clip_end': end},
            'audit': {'packet': {'lines': lines, 'performance_order': [{'line_id': row['id']} for row in lines],
                                 'uncertainties': []}}}

class SegmentMergeTests(unittest.TestCase):
    def test_cached_patta_keeps_every_supported_occurrence(self):
        before = copy.deepcopy(FIXTURE['segments'])
        result = pipeline.merge_audited_segments(before)
        self.assertEqual(surfaces(result), FIXTURE['expected_source_order'])
        self.assertEqual(len(surfaces(result)), 59)
        self.assertEqual(surfaces(result).count('ऐसी बानी बोलिए'), 2)
        self.assertEqual(surfaces(result).count('दुख में सुमिरन सब करे'), 3)
        self.assertEqual(surfaces(result).count('पत्ता बोला'), 1)
        self.assertEqual(before, FIXTURE['segments'])

    def test_edge_fragment_replaced_only_by_matching_full_counterpart(self):
        data = [segment(0, [('earlier whole line', 'none'), ('beginning', 'trailing')], 0, 40),
                segment(1, [('beginning completed', 'none'), ('later whole line', 'none')], 20, 60)]
        self.assertEqual(surfaces(pipeline.merge_audited_segments(data)),
                         ['earlier whole line', 'beginning completed', 'later whole line'])

    def test_unmatched_partial_is_retained_with_a_hold(self):
        data = [segment(0, [('unmatched pickup', 'trailing')], 0, 40),
                segment(1, [('different later text', 'none')], 20, 60)]
        result = pipeline.merge_audited_segments(data)
        self.assertEqual(surfaces(result), ['unmatched pickup', 'different later text'])
        self.assertTrue(result['uncertainties'])

    def test_nonoverlapping_clips_never_deduplicate_same_words(self):
        data = [segment(0, [('identical refrain', 'none')], 0, 10),
                segment(1, [('identical refrain', 'none')], 10, 20)]
        self.assertEqual(surfaces(pipeline.merge_audited_segments(data)), ['identical refrain'] * 2)

    def test_internal_partial_survives(self):
        data = [segment(0, [('short pickup', 'trailing'), ('shared full line', 'none')], 0, 40),
                segment(1, [('shared full line', 'none'), ('new full line', 'none')], 20, 60)]
        self.assertEqual(surfaces(pipeline.merge_audited_segments(data)),
                         ['short pickup', 'shared full line', 'new full line'])

    def test_fuzzy_context_cannot_swallow_a_new_short_line(self):
        first = 'the first distinct long verse about the forest and river banks '
        last = 'the final distinct long verse about the mountain and silent sky '
        data = [segment(0, [(first, 'none'), (last, 'none')], 0, 40),
                segment(1, [(first, 'none'), ('xyz', 'none'), (last, 'none')], 20, 60)]
        result = pipeline.merge_audited_segments(data)
        self.assertIn('xyz', surfaces(result))
        self.assertTrue(result['uncertainties'])

    def test_fuzzy_unequal_units_cannot_borrow_a_new_short_line(self):
        first = 'the first distinct long verse about the forest and river banks'
        last = 'the final distinct long verse about the mountain and silent sky'
        data = [segment(0, [(first, 'none'), ('hari ' + last, 'none')], 0, 40),
                segment(1, [(first, 'none'), ('hari', 'none'), ('har ' + last, 'none')], 20, 60)]
        result = pipeline.merge_audited_segments(data)
        self.assertEqual(surfaces(result), [first, 'hari ' + last, first, 'hari', 'har ' + last])
        self.assertTrue(result['uncertainties'])
        # A genuine line split with the identical full text remains valid.
        data[1]['audit']['packet']['lines'][2]['source_text'] = last
        data[1]['audit']['packet']['lines'][2]['roman'] = last
        exact = pipeline.merge_audited_segments(data)
        self.assertEqual(surfaces(exact), [first, 'hari ' + last])
        self.assertEqual(exact['uncertainties'], [])

    def test_unknown_or_invalid_clip_bounds_preserve_every_occurrence(self):
        for invalid in ({}, {'clip_start': float('nan'), 'clip_end': 40},
                        {'clip_start': 0, 'clip_end': float('inf')},
                        {'clip_start': 50, 'clip_end': 40},
                        {'clip_start': -1, 'clip_end': 40}):
            with self.subTest(bounds=invalid):
                left = segment(0, [('same repeated line', 'none')], 0, 40)
                right = segment(1, [('same repeated line', 'none')], 20, 60)
                left['segment'] = {'index': 0, **invalid}
                result = pipeline.merge_audited_segments([left, right])
                self.assertEqual(surfaces(result), ['same repeated line'] * 2)
                self.assertTrue(result['uncertainties'])
                self.assertEqual(pipeline.audit_segment_merge_coverage([left, right], result)['status'], 'uncertain')

    def test_malformed_raw_identifiers_never_claim_coverage(self):
        valid = segment(0, [('a valid full line', 'none')], 0, 40)
        variants = []
        item = copy.deepcopy(valid)
        item['audit']['packet']['lines'].append(copy.deepcopy(item['audit']['packet']['lines'][0]))
        variants.append(item)
        item = copy.deepcopy(valid)
        item['audit']['packet']['performance_order'][0]['line_id'] = 'missing'
        variants.append(item)
        item = copy.deepcopy(valid)
        item['audit']['packet']['lines'][0]['source_text'] = '  '
        variants.append(item)
        item = copy.deepcopy(valid)
        item['audit']['packet']['lines'][0]['roman'] = ''
        variants.append(item)
        item = copy.deepcopy(valid)
        item['audit']['packet']['performance_order'] = []
        variants.append(item)
        for item in variants:
            with self.subTest(packet=item):
                with self.assertRaises(ValueError):
                    pipeline.merge_audited_segments([item])
                with self.assertRaises(ValueError):
                    pipeline.audit_segment_merge_coverage([item], {})

    def test_diacritic_fold_cannot_collapse_distinct_native_words(self):
        item = segment(0, [('मन', 'none'), ('मान', 'none')], 0, 40)
        item['audit']['packet']['lines'][0]['roman'] = 'man'
        item['audit']['packet']['lines'][1]['roman'] = 'mān'
        item['audit']['packet']['performance_order'].append({'line_id': '0'})
        result = pipeline.merge_audited_segments([item])
        self.assertEqual(surfaces(result), ['मन', 'मान', 'मन'])
        self.assertEqual(len(result['verified_lines']), 2)
        self.assertEqual(pipeline.audit_segment_merge_coverage([item], result)['status'], 'covered')

    def test_coverage_reports_historical_loss(self):
        expected = pipeline.merge_audited_segments(FIXTURE['segments'])
        historical = copy.deepcopy(expected)
        dropped = {'ऐसी बानी बोलिए', 'मन का आपा खोए', 'अपना तन शीतल करे', 'औरों को सुख देय'}
        ids = {row['id'] for row in historical['verified_lines'] if row['source_text'] in dropped}
        historical['performance_order'] = [row for row in historical['performance_order'] if row['line_id'] not in ids]
        report = pipeline.audit_segment_merge_coverage(FIXTURE['segments'], historical)
        self.assertEqual(report['status'], 'mismatch')
        missing = [row['line']['source_text'] for diff in report['differences'] for row in diff['expected_occurrences']]
        self.assertTrue(dropped.issubset(missing))
        self.assertEqual(pipeline.audit_segment_merge_coverage(FIXTURE['segments'], expected)['status'], 'covered')

if __name__ == '__main__':
    unittest.main()

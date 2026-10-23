"""Selective timing's next interface; no audio/model behavior is simulated as truth.

Uses the real source reconciler, display-occurrence consumer and existing
independent-measurement parser. Handwritten timing expectations distinguish
performance identity from positional IDs. No provider or filesystem mutation.
"""
import copy
import hashlib
import json
import unittest
import bhakti_library_source_pass as source
import bhakti_pipeline as pipeline
from test_source_adoption_design import fixture


def timing_fixture(old, heard):
    reader, plan, observed = fixture(old, heard)
    delta = source.reconcile_source_observations(reader, plan, observed)
    draft = source.source_draft(reader)
    packet = {'verified_lines':draft['lines'], 'performance_order':draft['performance_order']}
    old_occurrences = pipeline.display_occurrences(packet)
    # One authoritative synthetic display measurement at two seconds into each
    # old ten-second block, independently confirmed on two distinct grids.
    starts = {row['occurrence_id']:2. + i*10 for i,row in enumerate(old_occurrences)}
    duration = len(old) * 10.
    reports = [{'grid':grid, 'index':0, 'clip_start':0., 'clip_end':duration,
        'cache_key':{'targets':copy.deepcopy(old_occurrences)},
        'response':{'packet':{'starts':[{'occurrence_id':key,'start':value} for key,value in starts.items()],
                               'uncertain_occurrence_ids':[]}}} for grid in ('first','independent')]
    identity = {'version':2,'audio_sha256':'a'*64,'source_identity':{'trim':{}},
                'ordered_occurrences':old_occurrences}
    fingerprint = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()
    prior = {'input_fingerprint':fingerprint, 'source_identity':identity,
             'ordered_occurrences':old_occurrences,'duration_seconds':duration,'refinements':reports,
             'sequence':[{**row,'start':starts[row['occurrence_id']],
                          'end':2.+(i+1)*10 if i+1<len(old_occurrences) else duration}
                         for i,row in enumerate(old_occurrences)],
             'validation_errors':[], 'uncertain_occurrence_ids':[]}
    return reader, delta, prior, duration


class SourceTimingLineageDesignTests(unittest.TestCase):
    def plan(self, reader, delta, prior, duration, audio_sha256='a'*64, trim=None):
        operation = getattr(source, 'plan_source_timing', None)
        self.assertTrue(callable(operation), 'selective changed-source timing planner is missing')
        snapshot = copy.deepcopy((reader, delta, prior))
        result = operation(reader, delta, prior, audio_sha256=audio_sha256,
                           trim={} if trim is None else trim, duration_seconds=duration)
        self.assertEqual((reader, delta, prior), snapshot)
        return result

    def test_nochange_retains_all_independently_bound_starts_without_regions(self):
        reader, delta, prior, duration = timing_fixture(['A','B','C','D'], ['A','B','C','D'])
        self.assertEqual(pipeline.retained_timing_measurements(prior['ordered_occurrences'], prior['refinements'], duration, require_consensus=True),
                         {'occ-000':2.,'occ-001':12.,'occ-002':22.,'occ-003':32.})
        result = self.plan(reader, delta, prior, duration)
        self.assertEqual(result['retained_starts'], {'occ-000':2.,'occ-001':12.,'occ-002':22.,'occ-003':32.})
        self.assertEqual(result['regions'], [])

    def test_insertion_remaps_later_ids_and_targets_only_new_performance(self):
        reader, delta, prior, duration = timing_fixture(['A','B','C','D'], ['A','B','X','C','D'])
        result = self.plan(reader, delta, prior, duration)
        self.assertEqual(result['retained_starts'], {'occ-000':2.,'occ-001':12.,'occ-003':22.,'occ-004':32.})
        targets = [row['occurrence_id'] for region in result['regions'] for row in region['target_occurrences']]
        self.assertEqual(targets, ['occ-002'])
        region = result['regions'][0]
        self.assertEqual(region['preceding_context']['occurrence_id'], 'occ-001')
        self.assertEqual(region['following_context']['occurrence_id'], 'occ-003')
        self.assertLess(region['clip_start'],12.);self.assertGreater(region['clip_end'],22.)

    def test_deletion_reuses_surviving_occurrences_without_timing_removed_line(self):
        reader, delta, prior, duration = timing_fixture(['A','B','C','D'], ['A','C','D'])
        result = self.plan(reader, delta, prior, duration)
        self.assertEqual(result['retained_starts'], {'occ-000':2.,'occ-001':22.,'occ-002':32.})
        self.assertEqual(result['regions'], [])
        # The later timing assembler must derive ends from these retained/new
        # starts. It cannot keep old A's end at the deleted B's onset.

    def test_word_replacement_does_not_reuse_old_word_onset_as_evidence(self):
        reader, delta, prior, duration = timing_fixture(['A','B','C','D'], ['A','X','C','D'])
        result = self.plan(reader, delta, prior, duration)
        self.assertEqual(result['retained_starts'], {'occ-000':2.,'occ-002':22.,'occ-003':32.})
        self.assertEqual([row['occurrence_id'] for region in result['regions'] for row in region['target_occurrences']], ['occ-001'])

    def test_returning_refrain_receives_new_timing_not_earlier_same_text_start(self):
        reader, delta, prior, duration = timing_fixture(['A','B','C','D'], ['A','B','A','C','D'])
        result = self.plan(reader, delta, prior, duration)
        self.assertEqual(result['retained_starts'], {'occ-000':2.,'occ-001':12.,'occ-003':22.,'occ-004':32.})
        self.assertNotIn('occ-002', result['retained_starts'])
        self.assertEqual([row['occurrence_id'] for region in result['regions'] for row in region['target_occurrences']], ['occ-002'])

    def test_changed_audio_or_trim_never_retains_old_measurements(self):
        reader, delta, prior, duration = timing_fixture(['A','B','C','D'], ['A','B','X','C','D'])
        for arguments in ({'audio_sha256':'c'*64}, {'trim':{'offset_seconds':1.}}):
            with self.subTest(arguments=arguments):
                # A changed recording invalidates the source delta too; it is
                # an input hold, not permission for an unrequested fresh run.
                with self.assertRaises(ValueError):
                    self.plan(reader, delta, prior, duration, **arguments)

    def test_single_or_uncertain_old_measurement_does_not_become_retained_evidence(self):
        reader, delta, prior, duration = timing_fixture(['A','B','C','D'], ['A','B','X','C','D'])
        prior['refinements'][1]['response']['packet']['uncertain_occurrence_ids'] = ['occ-001']
        result = self.plan(reader, delta, prior, duration)
        self.assertNotIn('occ-001', result['retained_starts'])
        self.assertEqual(result['retained_starts']['occ-004'],32.)
        self.assertEqual({row['occurrence_id'] for region in result['regions'] for row in region['target_occurrences']}, {'occ-001','occ-002'})


if __name__ == '__main__':
    unittest.main()

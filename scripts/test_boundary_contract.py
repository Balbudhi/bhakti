"""Proposed new-format evidence contract; review before implementing it."""
import copy
import unittest
import bhakti_pipeline as pipeline
from test_boundary_regressions import edge_artifact


def witnessed_artifact():
    artifact = edge_artifact(end=990., outside_type='music')
    artifact['boundary_contract_version'] = 2
    artifact['source_audio'] = 'audio.m4a'
    artifact['source_sha256'] = 'c'*64
    for edge in ('start', 'end'):
        row = artifact[edge]
        row['clip_end'] = row['clip_start'] + 75.
        packet = row['response']['packet']
        packet['relationship'] = 'attached_to_work' if edge == 'start' else 'unrelated'
        packet['retained_evidence'] = 'The target recording is continuous through its natural fade.'
        packet['excluded_evidence'] = '' if edge == 'start' else 'A finished fade is followed by a separately introduced different song.'
    artifact['end']['verification'] = {
        'edge': 'end', 'clip_start': 980., 'clip_end': 1000.,
        'response': {'packet': {'edge':'end', 'decision':'trim', 'boundary':10.,
                               'outside_type':'music', 'relationship':'unrelated',
                               'confidence':'high', 'reason':'Independent transition evidence.',
                               'retained_evidence':'Original coda fades fully before transition.',
                               'excluded_evidence':'Separate introduced recording follows.'}}}
    return artifact


class BoundaryEvidenceContract(unittest.TestCase):
    def test_evidenced_independent_cut_is_accepted(self):
        result = pipeline.normalize_trim_artifact(witnessed_artifact())
        self.assertEqual(result['trim_end'], 990.)
        self.assertEqual(result['status'], 'reviewed')
        self.assertEqual(result['validation_errors'], [])

    def test_attached_spoken_or_musical_edge_is_kept(self):
        for kind in ('speech', 'music', 'invocation', 'instrumental_coda'):
            with self.subTest(kind=kind):
                packet = witnessed_artifact()
                end = packet['end']
                end.pop('verification')
                end['response']['packet'].update(decision='keep', boundary=75., outside_type=kind,
                                                 relationship='attached_to_work', excluded_evidence='')
                result = pipeline.normalize_trim_artifact(packet)
                self.assertEqual(result['trim_end'], 1000.)
                self.assertEqual(result['validation_errors'], [])

    def test_unverified_category_does_not_authorize_cut(self):
        packet = witnessed_artifact()
        packet['end'].pop('verification')
        self.assertTrue(pipeline.normalize_trim_artifact(packet)['validation_errors'])

    def test_relationship_disagreement_holds(self):
        packet = witnessed_artifact()
        packet['end']['verification']['response']['packet']['relationship'] = 'attached_to_work'
        self.assertTrue(pipeline.normalize_trim_artifact(packet)['validation_errors'])

    def test_boundary_disagreement_holds(self):
        packet = witnessed_artifact()
        packet['end']['verification']['response']['packet']['boundary'] = 8.
        self.assertTrue(pipeline.normalize_trim_artifact(packet)['validation_errors'])

    def test_small_boundary_disagreement_keeps_more_target_audio(self):
        packet = witnessed_artifact()
        packet['end']['verification']['response']['packet']['boundary'] = 10.1
        result = pipeline.normalize_trim_artifact(packet)
        self.assertEqual(result['trim_end'], 990.1)
        self.assertEqual(result['validation_errors'], [])

    def test_uncertain_relationship_holds_even_with_high_confidence(self):
        packet = witnessed_artifact()
        packet['end']['response']['packet']['relationship'] = 'uncertain'
        self.assertTrue(pipeline.normalize_trim_artifact(packet)['validation_errors'])

    def test_missing_boundary_evidence_holds(self):
        packet = witnessed_artifact()
        packet['end']['response']['packet']['retained_evidence'] = ''
        self.assertTrue(pipeline.normalize_trim_artifact(packet)['validation_errors'])

    def test_nonfinite_and_mismatched_edge_are_validation_failures(self):
        for value in (float('nan'), float('inf'), -1., 76.):
            packet = witnessed_artifact()
            packet['end']['response']['packet']['boundary'] = value
            self.assertTrue(pipeline.normalize_trim_artifact(packet)['validation_errors'])
        packet = witnessed_artifact()
        packet['end']['response']['packet']['edge'] = 'start'
        self.assertTrue(pipeline.normalize_trim_artifact(packet)['validation_errors'])

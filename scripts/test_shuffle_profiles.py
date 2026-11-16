"""Profile freshness gates: classifications never become playback eligibility."""
from __future__ import annotations
import copy
import hashlib
import json
import unittest
from pathlib import Path
import tempfile

import bhakti_shuffle_profiles as profiles


class ProfileContractTests(unittest.TestCase):
    def setUp(self):
        self.reader = {
            'SONG_META': {'title': 'Example', 'languages': ['Hindi'], 'subjectTags': ['Guru'],
                          'audioSources': [{'src': 'https://example.test/a.m4a', 'type': 'audio/mp4'}]},
            'SONG_LINES': {'a': {'source': 'मन', 'roman': 'man', 'sourceLanguage': 'hi',
                                'english': 'mind', 'words': [{'roman': 'man', 'gloss': 'mind'}],
                                'grammarNote': ''}},
            'SONG_SEQUENCE': [{'ref': 'a', 'section': 'verse', 'repeats': 1}],
            'SONG_TIMINGS': [{'start': 0, 'end': 12}],
        }
        self.taxonomy = {'schemaVersion': 1, 'vocabularyVersion': 1,
                         'concepts': [{'id': 'inner-search', 'facet': 'theme'}]}
        self.qualification = {'qualificationVersion': 1, 'fallbackKinds': ['human'], 'methods': {
            'semantic': {'id': 'semantic-independent', 'version': '1', 'model': 'fixture-model',
                         'evidenceRevision': 'fixture-1', 'qualified': True, 'fingerprint': 'f' * 64, 'languages': ['Hindi'], 'maxLines': 2, 'maxTextBytes': 10000},
            'audio': {'id': 'physical', 'version': 'physical-1', 'evidenceRevision': 'fixture-1', 'qualified': True,
                      'recipeFingerprints': ['c' * 64], 'codecs': ['aac'], 'sampleRates': [44100], 'maxChannels': 2, 'maxDurationSeconds': 60}}}
        self.media_hash = 'a' * 64
        self.record = {
            'slug': 'example',
            'semantic': {
                'inputHash': profiles.semantic_input_hash(self.reader, self.taxonomy),
                'assessment': 'reviewed', 'outcome': 'known',
                'method': {'id': 'semantic-independent', 'version': '1', 'model': 'fixture-model', 'fingerprint': 'f' * 64},
                'qualificationVersion': 1, 'evidenceRevision': 'fixture-1',
                'review': {'kind': 'independent-model', 'recordHash': 'b' * 64,
                           'extractionRequestIds': ['proposal-1'], 'reviewRequestIds': ['review-1'],
                           'coveredLineCount': 1},
                'features': {'themes': [{'id': 'inner-search', 'weight': 0.8}], 'actions': [], 'subjects': []},
            },
            'audio': {
                'inputHash': profiles.audio_input_hash(self.media_hash),
                'mediaSha256': self.media_hash, 'assessment': 'measured', 'outcome': 'known',
                'methodFingerprint': 'c' * 64,
                'method': {'id': 'physical', 'version': 'physical-1'},
                'qualificationVersion': 1, 'evidenceRevision': 'fixture-1',
                'domain': {'codec': 'aac', 'sampleRate': 44100, 'channels': 2, 'durationSeconds': 12},
                'physical': {'whole': {'integratedLufs': -18.0, 'truePeakDbfs': -1.0,
                                       'rmsDbfs': -22.0, 'centroidHz': 1000.0}, 'profiles': {}},
            },
        }

    def project(self, *, record=None, required=True, reader=None, media_hash=None):
        return profiles.project_song_profile(
            '12345678', 'example', reader or self.reader, self.taxonomy,
            media_hash or self.media_hash, self.record if record is None else record,
            required=required, qualification=self.qualification)

    def test_final_reader_content_and_taxonomy_are_dependencies(self):
        initial = profiles.semantic_input_hash(self.reader, self.taxonomy)
        for label, mutate in [
            ('source', lambda r: r['SONG_LINES']['a'].update(source='तन')),
            ('translation', lambda r: r['SONG_LINES']['a'].update(english='body')),
            ('gloss', lambda r: r['SONG_LINES']['a']['words'][0].update(gloss='body')),
            ('language', lambda r: r['SONG_LINES']['a'].update(sourceLanguage='pa')),
            ('repeat', lambda r: r['SONG_SEQUENCE'][0].update(repeats=2)),
            ('subject', lambda r: r['SONG_META'].update(subjectTags=['Rāma'])),
        ]:
            with self.subTest(label=label):
                changed = copy.deepcopy(self.reader); mutate(changed)
                self.assertNotEqual(initial, profiles.semantic_input_hash(changed, self.taxonomy))
        taxonomy = copy.deepcopy(self.taxonomy); taxonomy['concepts'][0]['definition'] = 'Different'
        self.assertNotEqual(initial, profiles.semantic_input_hash(self.reader, taxonomy))

    def test_presentation_url_and_onset_changes_do_not_require_semantic_calls(self):
        changed = copy.deepcopy(self.reader)
        changed['SONG_META'].update(title='New spelling', credit='New credit')
        changed['SONG_META']['audioSources'][0]['src'] = 'https://new.test/same-bytes.m4a'
        changed['SONG_TIMINGS'][0]['start'] = 1.0
        self.assertEqual(profiles.semantic_input_hash(self.reader, self.taxonomy),
                         profiles.semantic_input_hash(changed, self.taxonomy))
        self.assertEqual(self.project(reader=changed)['semantic']['status'], 'accepted')

    def test_unknown_requires_completed_review_not_failed_extraction(self):
        unknown = copy.deepcopy(self.record)
        unknown['semantic'].update(outcome='unknown', reason='No supported thematic assertion',
                                   features={'themes': [], 'actions': [], 'subjects': []})
        unknown['audio'].update(assessment='reviewed', outcome='unknown',
                                review={'kind': 'human', 'recordHash': 'd' * 64,
                                        'reason': 'Reviewed recording has no reliable rhythm estimate'})
        unknown['audio'].pop('physical')
        self.assertEqual(self.project(record=unknown)['audio']['status'], 'accepted')
        for state in ['pending', 'running', 'failed', 'triaged']:
            invalid = copy.deepcopy(unknown); invalid['audio']['assessment'] = state
            with self.subTest(state=state), self.assertRaisesRegex(ValueError, 'audio'):
                self.project(record=invalid)

    def test_new_missing_blocks_legacy_missing_is_neutral(self):
        with self.assertRaises(ValueError):
            self.project(record={})
        result = self.project(record={}, required=False)
        self.assertEqual(result['semantic']['status'], 'unavailable')
        self.assertEqual(result['audio']['status'], 'unavailable')
        self.assertEqual(set(result), {'semantic', 'audio'})

    def test_staleness_is_independent_and_never_projects_old_features(self):
        changed = copy.deepcopy(self.reader); changed['SONG_LINES']['a']['english'] = 'thought'
        with self.assertRaisesRegex(ValueError, 'semantic'):
            self.project(reader=changed)
        result = self.project(reader=changed, required=False)
        self.assertEqual(result['semantic']['status'], 'unavailable')
        self.assertEqual(result['audio']['status'], 'accepted')
        result = self.project(media_hash='e' * 64, required=False)
        self.assertEqual(result['semantic']['status'], 'accepted')
        self.assertEqual(result['audio']['status'], 'unavailable')
        with self.assertRaisesRegex(ValueError, 'audio'):
            self.project(media_hash='e' * 64)

    def test_cross_song_invalid_values_and_self_review_rejected(self):
        wrong = copy.deepcopy(self.record); wrong['slug'] = 'another'
        with self.assertRaises(ValueError): self.project(record=wrong)
        for mutate in [
            lambda r: r['semantic']['review'].update(reviewRequestIds=['proposal-1']),
            lambda r: r['semantic']['features']['themes'][0].update(weight=float('nan')),
            lambda r: r['semantic']['features']['themes'][0].update(weight=-0.1),
            lambda r: r['semantic']['features']['themes'][0].update(weight=1.1),
            lambda r: r['semantic']['features']['themes'].append(dict(r['semantic']['features']['themes'][0])),
            lambda r: r['semantic']['features']['themes'][0].update(id='invented'),
            lambda r: r['audio']['physical']['whole'].update(centroidHz=float('inf')),
        ]:
            bad = copy.deepcopy(self.record); mutate(bad)
            with self.assertRaises(ValueError): self.project(record=bad)

    def test_method_and_input_outside_qualification_do_not_become_accepted(self):
        for mutate in [
            lambda r: r['semantic']['method'].update(version='2'),
            lambda r: r['semantic']['method'].update(model='untested-model'),
            lambda r: r['semantic'].update(evidenceRevision='invented'),
            lambda r: r['audio']['domain'].update(codec='untested-codec'),
            lambda r: r['audio'].update(methodFingerprint='e' * 64),
            lambda r: r['audio']['domain'].update(durationSeconds=120),
        ]:
            invalid = copy.deepcopy(self.record); mutate(invalid)
            with self.assertRaisesRegex(ValueError, 'qualif'):
                self.project(record=invalid)
        self.qualification['methods']['semantic']['languages'] = ['Punjabi']
        with self.assertRaisesRegex(ValueError, 'qualif'):
            self.project()
        self.assertEqual(self.project(required=False)['semantic']['status'], 'unavailable')

    def test_semantic_projection_contract_is_bound_independently_of_inference(self):
        fields = {'projectionVersion': 2, 'projectionFingerprint': '1' * 64}
        self.qualification['methods']['semantic'].update(fields)
        self.record['semantic']['method'].update(fields)
        self.assertEqual(self.project()['semantic']['status'], 'accepted')
        for change in ({'projectionVersion': 3}, {'projectionFingerprint': '2' * 64},
                       {'projectionFingerprint': None}):
            bad = copy.deepcopy(self.record)
            bad['semantic']['method'].update(change)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'qualification'):
                self.project(record=bad)
        self.qualification['methods']['semantic'].pop('projectionFingerprint')
        with self.assertRaisesRegex(ValueError, 'qualification'):
            self.project()

    def test_subject_roles_and_facet_mass_are_validated_at_adoption(self):
        self.taxonomy['entities'] = [{'id': 'guru'}]
        self.taxonomy['concepts'].append({'id': 'remembrance', 'facet': 'theme'})
        self.record['semantic']['inputHash'] = profiles.semantic_input_hash(self.reader, self.taxonomy)
        bad = copy.deepcopy(self.record)
        bad['semantic']['features']['subjects'] = [{'id': 'guru', 'role': 'composer', 'weight': 1.0}]
        with self.assertRaisesRegex(ValueError, 'role'):
            self.project(record=bad)
        bad = copy.deepcopy(self.record)
        bad['semantic']['features']['themes'].append({'id': 'remembrance', 'weight': 0.8})
        with self.assertRaisesRegex(ValueError, 'mass'):
            self.project(record=bad)

    def test_exact_audio_qualification_domain_excludes_unmeasured_channels_and_short_duration(self):
        rule = self.qualification['methods']['audio']
        rule.update(channels=[2], minDurationSeconds=12)
        self.assertEqual(self.project()['audio']['status'], 'accepted')
        for change in ({'channels': 1}, {'durationSeconds': 11.99}):
            bad = copy.deepcopy(self.record)
            bad['audio']['domain'].update(change)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'qualification'):
                self.project(record=bad)

    def test_missing_policy_never_disables_an_installed_feature(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'assets').mkdir()
            self.assertFalse(profiles.enabled(root))
            (root / 'assets/shuffle.js').write_text('window.BHAKTI_SHUFFLE = {};')
            with self.assertRaisesRegex(ValueError, 'policy'):
                profiles.enabled(root)

    def test_private_provenance_does_not_leak_into_runtime(self):
        self.record['semantic']['privateNotes'] = '/private/cache/secret-prompt'
        runtime = self.project()
        self.assertNotIn('private', json.dumps(runtime))
        self.assertNotIn('recordHash', json.dumps(runtime))
        self.assertEqual(runtime['semantic']['themes'], [{'id': 'inner-search', 'weight': 0.8}])

    def editorial_record(self, factor=0.25):
        record = copy.deepcopy(self.record)
        record['semantic']['editorialReview'] = {'kind': 'independent-assistant',
            'evidenceHash': '9' * 64, 'inputHash': record['semantic']['inputHash'],
            'baseFeaturesHash': profiles.digest(record['semantic']['features'])}
        record['semantic']['editorialAdjustments'] = [{'facet': 'themes', 'id': 'inner-search',
            'factor': factor, 'reason': 'Context supports only a minor theme', 'sourceLineIds': ['a']}]
        return record

    def test_editorial_reductions_preserve_base_evidence_and_never_renormalize(self):
        record = self.editorial_record(); before = copy.deepcopy(record)
        runtime = self.project(record=record)
        self.assertEqual(runtime['semantic']['themes'], [{'id': 'inner-search', 'weight': 0.2}])
        self.assertEqual(record, before)
        self.assertNotIn('editorial', json.dumps(runtime))
        excluded = self.project(record=self.editorial_record(0))
        self.assertEqual(excluded['semantic']['status'], 'accepted')
        self.assertEqual(excluded['semantic']['themes'], [])

    def test_editorial_overlay_rejects_unbound_or_invalid_corrections(self):
        for mutate in [
            lambda p: p['editorialReview'].update(inputHash='0' * 64),
            lambda p: p['editorialReview'].update(kind='human'),
            lambda p: p['editorialReview'].update(evidenceHash='short'),
            lambda p: p['editorialReview'].update(baseFeaturesHash='0' * 64),
            lambda p: p['editorialReview'].pop('baseFeaturesHash'),
            lambda p: p.pop('editorialReview'),
            lambda p: p.pop('editorialAdjustments'),
            lambda p: p['editorialAdjustments'][0].update(factor=-0.1),
            lambda p: p['editorialAdjustments'][0].update(factor=1.01),
            lambda p: p['editorialAdjustments'][0].update(factor=float('nan')),
            lambda p: p['editorialAdjustments'][0].update(factor=True),
            lambda p: p['editorialAdjustments'][0].update(reason=' '),
            lambda p: p['editorialAdjustments'][0].update(sourceLineIds=[]),
            lambda p: p['editorialAdjustments'][0].update(sourceLineIds=['missing']),
            lambda p: p['editorialAdjustments'][0].update(facet='actions'),
            lambda p: p['editorialAdjustments'][0].update(id='new-concept'),
            lambda p: p['editorialAdjustments'][0].update(role='worship_focus'),
            lambda p: p['editorialAdjustments'].append(dict(p['editorialAdjustments'][0])),
        ]:
            record = self.editorial_record(); mutate(record['semantic'])
            with self.subTest(record=record['semantic']), self.assertRaisesRegex(ValueError, 'editorial'):
                self.project(record=record)

    def test_editorial_subject_reduction_targets_exact_role_and_valid_base_only(self):
        self.taxonomy['entities'] = [{'id': 'guru'}]
        self.record['semantic']['inputHash'] = profiles.semantic_input_hash(self.reader, self.taxonomy)
        self.record['semantic']['features']['subjects'] = [
            {'id': 'guru', 'role': 'worship_focus', 'weight': 0.6},
            {'id': 'guru', 'role': 'narrative_subject', 'weight': 0.4}]
        record = self.editorial_record()
        record['semantic']['editorialAdjustments'] = [{'facet': 'subjects', 'id': 'guru',
            'role': 'narrative_subject', 'factor': 0, 'reason': 'No separate narrative role', 'sourceLineIds': ['a']}]
        self.assertEqual(self.project(record=record)['semantic']['subjects'],
            [{'id': 'guru', 'role': 'worship_focus', 'weight': 0.6}])
        record['semantic']['editorialAdjustments'][0]['role'] = 'composer'
        with self.assertRaisesRegex(ValueError, 'editorial'):
            self.project(record=record)
        record = self.editorial_record(0)
        record['semantic']['features']['themes'][0]['weight'] = 2
        with self.assertRaisesRegex(ValueError, 'weight'):
            self.project(record=record)

    def test_store_preserves_overlay_only_on_same_input_without_mutating_new_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'data').mkdir()
            queue_id = hashlib.blake2s(b'example', digest_size=4).hexdigest()
            for name, data in [(profiles.POLICY, {'schemaVersion': 1, 'legacySongs': {}, **self.qualification}),
                               (profiles.TAXONOMY, self.taxonomy),
                               (profiles.REVIEWS, {'schemaVersion': 1, 'profiles': {queue_id: self.editorial_record()}})]:
                (root / name).write_text(json.dumps(data))
            incoming = copy.deepcopy(self.record)
            profiles.store_reviewed_profile(root, 'example', self.reader, self.media_hash, incoming)
            stored = profiles.read_json(root / profiles.REVIEWS)['profiles'][queue_id]
            self.assertEqual(stored['semantic']['editorialAdjustments'], self.editorial_record()['semantic']['editorialAdjustments'])
            self.assertNotIn('editorialReview', incoming['semantic'])
            changed_base = copy.deepcopy(incoming)
            changed_base['semantic']['features']['themes'][0]['weight'] = 0.2
            with self.assertRaisesRegex(ValueError, 'editorial'):
                profiles.store_reviewed_profile(root, 'example', self.reader, self.media_hash, changed_base)
            self.assertEqual(profiles.read_json(root / profiles.REVIEWS)['profiles'][queue_id], stored)
            changed_reader = copy.deepcopy(self.reader)
            changed_reader['SONG_LINES']['a']['english'] = 'thought'
            incoming['semantic']['inputHash'] = profiles.semantic_input_hash(changed_reader, self.taxonomy)
            profiles.store_reviewed_profile(root, 'example', changed_reader, self.media_hash, incoming)
            stored = profiles.read_json(root / profiles.REVIEWS)['profiles'][queue_id]
            self.assertNotIn('editorialReview', stored['semantic'])
            self.assertNotIn('editorialAdjustments', stored['semantic'])


if __name__ == '__main__':
    unittest.main()

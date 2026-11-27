"""Actual reader generation and assembly boundaries, with no provider calls."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import bhakti_pipeline as pipeline
import bhakti_shuffle_profiles as profiles
from audit_bhakti_contract import load_data
import test_shuffle_profiles


class GenerationProfileGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); (self.root / 'data').mkdir()
        self.song = self.root / 'songs' / 'sample-song'; self.song.mkdir(parents=True)
        original = pipeline.ROOT
        for name in ['preserved_terms.json', 'editorial_baselines.json', 'source_credits.json']:
            (self.root / 'data' / name).write_bytes((original / 'data' / name).read_bytes())
        self.taxonomy = {'schemaVersion': 1, 'vocabularyVersion': 1, 'concepts': []}
        self.save('shuffle-taxonomy.json', self.taxonomy)
        fixture = test_shuffle_profiles.ProfileContractTests(); fixture.setUp()
        self.policy = {'schemaVersion': 1, 'legacySongs': {}, **fixture.qualification}
        self.save('shuffle-profile-policy.json', self.policy)
        self.save('shuffle-profile-reviews.json', {'schemaVersion': 1, 'profiles': {}})
        self.save('song_tag_overrides.json', {'version': 1, 'songs': {'sample-song': {
            'addTags': ['Guru'], 'evidence': [{'tag': 'Guru', 'source': 'साईं', 'reason': 'Reviewed fixture'}]}}})
        self.save('queue_numbers.json', {'schemaVersion': 1, 'numbers': {}})
        self.save('songs.js', 'window.BHAKTI_SONGS = [];')
        self.media_hash = 'a' * 64
        self.save('media.json', {'schemaVersion': 2, 'songs': {'sample-song': [
            {'src': 'https://example.test/song.m4a', 'type': 'audio/mp4', 'sha256': self.media_hash}]}})
        self.audited = {'packet': {'metadata': {'languages': ['Hindi']}, 'uncertainties': [], 'verified_lines': [
            {'id': 'line-one', 'source_text': 'साईं', 'roman': 'Sāīṃ', 'kind': 'refrain'}]}}
        self.timing = {'sequence': [{'ref': 'line-one', 'start': 1.25, 'end': 2.5}], 'validation_errors': []}
        self.glosses = {'packet': {'glosses': [{'id': 'line-one', 'word_glosses': [
            {'roman': 'Sāīṃ', 'gloss': 'holy master'}], 'grammar_note': '', 'uncertainty': ''}]}}
        self.translations = {'packet': {'translations': [{'id': 'line-one', 'literal_english': 'Sai.',
            'segments': [{'text': 'Sai', 'word_indices': [0]}, {'text': '.', 'word_indices': []}], 'uncertainty': ''}]}}
        self.job = {'slug': 'sample-song', 'source': 'unused', 'title': 'Sample Song',
                    'languages': ['Hindi'], 'subjectTags': []}
        packet_dir = self.song / '.transcription/pipeline'; packet_dir.mkdir(parents=True)
        (packet_dir / '05-translation.json').write_text(json.dumps(self.translations))
        self.queue_id = hashlib.blake2s(b'sample-song', digest_size=4).hexdigest()
        self.addCleanup(patch.stopall)
        patch.object(pipeline, 'ROOT', self.root).start()
        patch.object(pipeline, 'QUEUE_NUMBERS_PATH', self.root / 'data/queue_numbers.json').start()
        self.provider = patch.object(pipeline, 'complete_semantics', side_effect=AssertionError('No assessment API in generation')).start()

    def save(self, name, value):
        (self.root / 'data' / name).write_text(value if isinstance(value, str) else json.dumps(value))

    def generate(self, **kwargs):
        return pipeline.generate(self.song, self.job, {}, self.audited, self.timing,
                                 self.glosses, self.translations, write_catalogue_after=False, **kwargs)

    def approve_unknown(self, reader):
        record = {'slug': 'sample-song', 'semantic': {
            'inputHash': profiles.semantic_input_hash(reader, self.taxonomy), 'assessment': 'reviewed',
            'outcome': 'unknown', 'reason': 'No supported themes', 'method': {'id': 'semantic-independent', 'version': '1', 'model': 'fixture-model', 'fingerprint': 'f' * 64},
            'qualificationVersion': 1, 'evidenceRevision': 'fixture-1',
            'review': {'kind': 'independent-model', 'recordHash': 'b' * 64, 'extractionRequestIds': ['p1'],
                       'reviewRequestIds': ['r1'], 'coveredLineCount': 1},
            'features': {'themes': [], 'actions': [], 'subjects': []}},
            'audio': {'inputHash': profiles.audio_input_hash(self.media_hash), 'mediaSha256': self.media_hash,
                      'assessment': 'reviewed', 'outcome': 'unknown', 'methodFingerprint': 'c' * 64,
                      'qualificationVersion': 1, 'evidenceRevision': 'fixture-1',
                      'review': {'kind': 'human', 'recordHash': 'd' * 64, 'reason': 'No reliable descriptor'}}}
        self.save('shuffle-profile-reviews.json', {'schemaVersion': 1, 'profiles': {self.queue_id: record}})

    def test_prepare_contains_final_overrides_without_public_writes(self):
        self.assertEqual(pipeline.publication_errors(self.audited, self.timing, self.glosses, self.translations, expected_review_task_version=0), [])
        reader = self.generate(prepare_only=True)
        self.assertIn('Guru', reader['SONG_META']['subjectTags'])
        self.assertEqual(reader['SONG_LINES']['line-one']['words'][0]['gloss'], 'holy master')
        self.assertFalse((self.song / 'data.js').exists())
        self.assertFalse((self.song / 'index.html').exists())
        with self.assertRaisesRegex(ValueError, 'profile'):
            self.generate()
        self.approve_unknown(reader)
        self.generate()
        self.assertEqual(reader, load_data(self.song / 'data.js'))
        self.provider.assert_not_called()

    def test_generate_only_uses_real_cached_artifacts_and_missing_gate(self):
        import argparse
        packet_dir = self.song / '.transcription/pipeline'; packet_dir.mkdir(parents=True, exist_ok=True)
        for name, packet in [('02-transcript-audit.json', self.audited), ('03-timing.json', self.timing),
                             ('04-glosses.json', self.glosses), ('05-translation.json', self.translations)]:
            (packet_dir / name).write_text(json.dumps(packet))
        options = argparse.Namespace(generate_only=True, publish=False, workers=1)
        result = pipeline._execute_intake_jobs(options, [self.job])
        self.assertEqual(result, 1)
        self.assertFalse((self.song / 'data.js').exists())
        reader = self.generate(prepare_only=True); self.approve_unknown(reader)
        self.assertEqual(pipeline._execute_intake_jobs(options, [self.job]), 0)
        self.assertEqual(reader, load_data(self.song / 'data.js'))
        self.provider.assert_not_called()


class IntakeAssessmentTests(unittest.TestCase):
    setUp = GenerationProfileGateTests.setUp
    save = GenerationProfileGateTests.save
    generate = GenerationProfileGateTests.generate
    approve_unknown = GenerationProfileGateTests.approve_unknown
    def exercise_intake(self, *, mutate=False):
        import argparse
        import bhakti_shuffle_semantics as semantics
        import bhakti_shuffle_audio as audio
        from contextlib import ExitStack
        media_path = self.song / 'audio.m4a'; media_path.write_bytes(b'fixture retained listener bytes')
        self.media_hash = profiles.file_hash(media_path)
        self.save('media.json', {'schemaVersion': 2, 'songs': {'sample-song': [
            {'src': 'https://example.test/song.m4a', 'type': 'audio/mp4', 'sha256': self.media_hash}]}})
        rule = self.policy['methods']['semantic']
        rule.update(id='source-grounded-semantic-review', version=semantics.METHOD_VERSION,
                    model=semantics.MODEL, fingerprint=semantics.semantic_method_fingerprint(),
                    projectionVersion=semantics.PROJECTION_VERSION,
                    projectionFingerprint=semantics.projection_fingerprint())
        self.save('shuffle-profile-policy.json', self.policy)
        reader = self.generate(prepare_only=True)
        self.approve_unknown(reader)
        template = profiles.read_json(self.root / 'data/shuffle-profile-reviews.json')['profiles'][self.queue_id]
        template['semantic']['method'] = {key: rule[key] for key in
            ('id', 'version', 'model', 'fingerprint', 'projectionVersion', 'projectionFingerprint')}
        self.save('shuffle-profile-reviews.json', {'schemaVersion': 1, 'profiles': {}})
        seen = []
        def assess(actual, taxonomy, **kwargs):
            self.assertEqual(actual, reader)
            self.assertIn('Guru', actual['SONG_META']['subjectTags'])
            seen.append(actual)
            if mutate:
                (self.song / '.transcription/source.json').write_text('{"changed":true}')
            return {'recorded': True}
        options = argparse.Namespace(model=semantics.MODEL, force=False, source_witness_audit=False,
                                     refresh_timing=False, timeout=30, unit_deadline_at=9999999999)
        from bhakti_boundary_timebase import boundary_snapshot
        snapshot = boundary_snapshot(self.song, [media_path, self.song / '.transcription/source.json',
                                                 self.root / 'data/shuffle-profile-policy.json'])
        with ExitStack() as stack:
            measured = stack.enter_context(patch.object(audio, 'analyze_audio', return_value={'recorded': True}))
            stack.enter_context(patch.object(audio, 'audio_summary', return_value=template['audio']))
            assessed = stack.enter_context(patch.object(semantics, 'assess_semantics', side_effect=assess))
            stack.enter_context(patch.object(semantics, 'semantic_summary', return_value=template['semantic']))
            if mutate:
                with self.assertRaisesRegex(RuntimeError, 'snapshot changed'):
                    profiles.assess_song_profiles(self.root, self.job['slug'], reader, media_path, options, snapshot)
            else:
                result = profiles.assess_song_profiles(self.root, self.job['slug'], reader, media_path, options, snapshot)
                self.assertEqual(result['slug'], self.job['slug'])
            self.assertEqual(measured.call_count, 1)
            self.assertEqual(assessed.call_count, 1)
        registry = profiles.read_json(self.root / 'data/shuffle-profile-reviews.json')
        self.assertEqual(bool(registry['profiles']), not mutate)
        self.assertFalse((self.song / 'data.js').exists())

    def test_assessment_coordinator_adopts_final_reader_without_publication(self):
        self.exercise_intake()

    def test_assessment_coordinator_rejects_changed_inputs_before_adoption(self):
        self.exercise_intake(mutate=True)


class PublicationProfileTests(unittest.TestCase):
    setUp = GenerationProfileGateTests.setUp
    save = GenerationProfileGateTests.save
    generate = GenerationProfileGateTests.generate
    approve_unknown = GenerationProfileGateTests.approve_unknown

    def ready(self):
        reader = self.generate(prepare_only=True); self.approve_unknown(reader); self.generate()
        pipeline.write_catalogue()
        return profiles.load_catalogue(self.root)

    def assembly_ready(self):
        import assemble_public_site as assembly
        self.ready()
        (self.root / 'assets').mkdir()
        # Assembly now uses both production renderers to emit crawlable HTML.
        for name in ('library.js', 'song.js'):
            (self.root / 'assets' / name).write_bytes(
                (Path(__file__).resolve().parents[1] / 'assets' / name).read_bytes())
        for name in assembly.PUBLIC_ROOT_FILES:
            (self.root / name).write_text('fixture')

    def test_pair_revision_and_exact_reader_snapshot(self):
        loaded = self.ready()
        document = profiles.validate_public_profiles(self.root)
        self.assertEqual(document['revision'], loaded['BHAKTI_SHUFFLE_REVISION'])
        path = self.song / 'data.js'
        path.write_text(path.read_text().replace('Sample Song', 'New title'))
        with self.assertRaisesRegex(ValueError, 'snapshot|revision'):
            profiles.validate_public_profiles(self.root)
        pipeline.write_catalogue()
        repaired = profiles.validate_public_profiles(self.root)
        self.assertNotEqual(document['revision'], repaired['revision'])
        self.assertEqual(document['profiles'], repaired['profiles'])
        self.provider.assert_not_called()

    def test_missing_catalogue_member_and_mixed_revision_are_rejected(self):
        loaded = self.ready()
        with self.assertRaisesRegex(ValueError, 'population'):
            profiles.build_public_profiles(self.root, [])
        path = self.root / 'data/songs.js'
        path.write_text(path.read_text().replace(loaded['BHAKTI_SHUFFLE_REVISION'], '0' * 64))
        with self.assertRaisesRegex(ValueError, 'revision'):
            profiles.validate_public_profiles(self.root)

    def test_new_url_for_identical_manifest_bytes_reuses_assessments(self):
        self.ready()
        old = profiles.validate_public_profiles(self.root)
        path = self.song / 'data.js'
        path.write_text(path.read_text().replace('https://example.test/song.m4a', 'https://new.test/same.m4a'))
        manifest = profiles.read_json(self.root / 'data/media.json')
        manifest['songs']['sample-song'][0]['src'] = 'https://new.test/same.m4a'
        self.save('media.json', manifest)
        pipeline.write_catalogue()
        updated = profiles.validate_public_profiles(self.root)
        self.assertEqual(old['profiles'], updated['profiles'])
        self.assertNotEqual(old['revision'], updated['revision'])
        self.provider.assert_not_called()

    def test_new_listener_source_identity_not_title_or_duration(self):
        self.ready()
        manifest = profiles.read_json(self.root / 'data/media.json')
        manifest['songs']['sample-song'][0]['sha256'] = 'e' * 64
        self.save('media.json', manifest)
        with self.assertRaisesRegex(ValueError, 'audio'):
            pipeline.write_catalogue()

    def test_assembly_ships_projection_only_and_holds_previous_site(self):
        import assemble_public_site as assembly
        self.assembly_ready()
        assembly.assemble_public_site(self.root)
        self.assertTrue((self.root / '_site/data/shuffle-profiles.js').is_file())
        published_reader = (self.root / '_site/songs/sample-song/index.html').read_text()
        self.assertIn('class="line-source"', published_reader)
        self.assertIn('साईं', published_reader)
        self.assertFalse((self.root / '_site/data/shuffle-profile-reviews.json').exists())
        sentinel = self.root / '_site/retained'; sentinel.write_text('old valid site')
        path = self.song / 'data.js'
        path.write_text(path.read_text().replace('Sample Song', 'Changed after pairing'))
        with self.assertRaises(ValueError):
            assembly.assemble_public_site(self.root)
        self.assertEqual(sentinel.read_text(), 'old valid site')

    def test_assembly_rejects_writer_racing_after_real_profile_validation(self):
        import assemble_public_site as assembly
        self.assembly_ready()
        assembly.assemble_public_site(self.root)
        sentinel = self.root / '_site/retained'; sentinel.write_text('old valid site')
        validate = profiles.validate_public_profiles
        def changing_after_validation(*args, **kwargs):
            result = validate(*args, **kwargs)
            path = self.song / 'data.js'
            path.write_text(path.read_text().replace('Sample Song', 'Concurrent direct edit'))
            return result
        with patch.object(profiles, 'validate_public_profiles', side_effect=changing_after_validation):
            with self.assertRaisesRegex(RuntimeError, 'snapshot'):
                assembly.assemble_public_site(self.root)
        self.assertEqual(sentinel.read_text(), 'old valid site')

    def test_assembly_rejects_private_receipt_or_tag_evidence_race(self):
        import assemble_public_site as assembly
        self.assembly_ready()
        receipt = self.root / profiles.TEXT_REPAIRS
        receipt.write_text('{"version":1,"songs":{}}')
        assembly.assemble_public_site(self.root)
        self.assertFalse((self.root / '_site' / profiles.TEXT_REPAIRS).exists())
        self.assertFalse((self.root / '_site/data/song_tag_overrides.json').exists())
        sentinel = self.root / '_site/retained'; sentinel.write_text('old valid site')
        validate = profiles.validate_public_profiles
        for relative in (profiles.TEXT_REPAIRS, 'data/song_tag_overrides.json'):
            path = self.root / relative
            original = path.read_bytes()
            def change(*args, **kwargs):
                result = validate(*args, **kwargs)
                path.write_bytes(original + b'\n')
                return result
            with self.subTest(relative=relative), \
                 patch.object(profiles, 'validate_public_profiles', side_effect=change), \
                 self.assertRaisesRegex(RuntimeError, 'assessment inputs changed'):
                assembly.assemble_public_site(self.root)
            self.assertEqual(sentinel.read_text(), 'old valid site')
            path.write_bytes(original)

    def test_legacy_projection_does_not_allow_new_song_to_claim_legacy(self):
        self.save('shuffle-profile-policy.json', {'schemaVersion': 1, 'legacySongs': {self.queue_id: 'wrong-song'}})
        with self.assertRaisesRegex(ValueError, 'legacy'):
            self.generate()


if __name__ == '__main__': unittest.main()

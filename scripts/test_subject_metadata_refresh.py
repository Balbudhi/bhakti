"""A reviewed public-tag correction preserves the original model assessment.

Cases exercise the actual stored registry and publication consumer: unchanged
meaning permits reviewed additions/removals, while changes outside that narrow
boundary, stale evidence and guessed receipts cannot inherit accepted status.
"""
import copy
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import bhakti_shuffle_profiles as profiles
import test_shuffle_profiles


class SubjectMetadataRefreshTests(unittest.TestCase):
    def setUp(self):
        fixture = test_shuffle_profiles.ProfileContractTests(); fixture.setUp()
        self.reader = fixture.reader
        self.taxonomy = fixture.taxonomy
        self.record = fixture.record
        self.policy = {'schemaVersion': 1, 'legacySongs': {}, **fixture.qualification}
        self.media_hash = fixture.media_hash
        self.queue_id = hashlib.blake2s(b'example', digest_size=4).hexdigest()
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); (self.root / 'data').mkdir()
        self.registry = {'version': 1, 'songs': {'example': {
            'addTags': ['Kṛṣṇa'],
            'evidence': [{'tag': 'Kṛṣṇa', 'source': 'मन', 'reason': 'Reviewed test witness'}],
        }}}
        self.save(profiles.POLICY, self.policy)
        self.save(profiles.TAXONOMY, self.taxonomy)
        self.save('data/song_tag_overrides.json', self.registry)
        self.store(self.record)
        self.save('data/media.json', {'songs': {'example': [{
            'src': self.reader['SONG_META']['audioSources'][0]['src'], 'sha256': self.media_hash}]}})
        self.changed = copy.deepcopy(self.reader)
        self.changed['SONG_META']['subjectTags'] = ['Guru', 'Kṛṣṇa']

    def save(self, name, data):
        (self.root / name).write_text(json.dumps(data, ensure_ascii=False))

    def store(self, record):
        self.save(profiles.REVIEWS, {'schemaVersion': 1, 'profiles': {self.queue_id: record}})

    def revise(self, reader=None, record=None):
        result = copy.deepcopy(self.record if record is None else record)
        result['semantic']['subjectTagRevision'] = profiles.reviewed_subject_tag_revision(
            self.root, 'example', reader or self.changed, result, prior_tags=['Guru'])
        return result

    def project(self, record, reader=None):
        return profiles.project_song_profile(self.queue_id, 'example', reader or self.changed,
            self.taxonomy, self.media_hash, record, required=True, qualification=self.policy, root=self.root)

    def test_reviewed_tags_keep_original_model_audio_and_editorial_reductions(self):
        self.record['semantic']['editorialReview'] = {
            'kind': 'independent-assistant', 'inputHash': self.record['semantic']['inputHash'],
            'baseFeaturesHash': profiles.digest(self.record['semantic']['features']), 'evidenceHash': 'd' * 64}
        self.record['semantic']['editorialAdjustments'] = [{
            'facet': 'themes', 'id': 'inner-search', 'factor': .25,
            'reason': 'Review fixture reduction', 'sourceLineIds': ['a']}]
        self.store(self.record)
        before = copy.deepcopy(self.record)
        revised = self.revise()
        base = copy.deepcopy(revised); revision = base['semantic'].pop('subjectTagRevision')
        self.assertEqual(base, before)
        self.assertEqual(self.record, before)
        self.assertEqual(revision['originalInputHash'], before['semantic']['inputHash'])
        self.assertEqual(revision['priorTags'], ['Guru'])
        self.assertEqual(revision['evidenceHash'], profiles.digest(self.registry['songs']['example']))
        projected = self.project(revised)
        self.assertEqual(projected['semantic']['themes'], [{'id': 'inner-search', 'weight': .2}])
        self.assertEqual(projected['semantic']['subjects'], [])
        self.assertEqual(projected['audio']['status'], 'accepted')
        profiles.store_reviewed_profile(self.root, 'example', self.changed, self.media_hash, revised)
        self.assertEqual(profiles.read_json(self.root / profiles.REVIEWS)['profiles'][self.queue_id], revised)
        self.assertEqual(profiles.require_song_profile(self.root, 'example', self.changed), projected)
        song = self.root / 'songs/example'; song.mkdir(parents=True)
        (song / 'data.js').write_text('\n'.join('window.' + key + '=' + json.dumps(value) + ';'
                                                  for key, value in self.changed.items()))
        catalogue = [{'queueId': self.queue_id, 'slug': 'example'}]
        published = profiles.publish_catalogue(self.root, catalogue)
        self.assertEqual(published['profiles'][self.queue_id], projected)
        self.assertEqual(profiles.validate_public_profiles(self.root), published)

    def test_removal_requires_registry_and_preserves_exact_surviving_order(self):
        row = self.registry['songs']['example']; row['removeTags'] = ['Guru']
        row['evidence'].append({'operation': 'remove', 'tag': 'Guru', 'source': 'मन',
                                'reason': 'Complete source reviewed for removal'})
        self.save('data/song_tag_overrides.json', self.registry)
        self.changed['SONG_META']['subjectTags'] = ['Kṛṣṇa']
        self.assertEqual(self.project(self.revise())['semantic']['status'], 'accepted')

    def test_changed_meaning_and_unreviewed_tags_do_not_inherit_assessment(self):
        revised = self.revise()
        for label, mutate in [
            ('source', lambda r: r['SONG_LINES']['a'].update(source='तन')),
            ('gloss', lambda r: r['SONG_LINES']['a']['words'][0].update(gloss='body')),
            ('english', lambda r: r['SONG_LINES']['a'].update(english='body')),
            ('sequence', lambda r: r['SONG_SEQUENCE'].append(dict(r['SONG_SEQUENCE'][0]))),
            ('tag', lambda r: r['SONG_META']['subjectTags'].append('Śiva')),
        ]:
            changed = copy.deepcopy(self.changed); mutate(changed)
            with self.subTest(label=label):
                with self.assertRaises(ValueError): self.revise(reader=changed)
                with self.assertRaises(ValueError): self.project(revised, reader=changed)

    def test_revision_bindings_cannot_be_changed_or_omitted(self):
        revised = self.revise()
        for key, value in [('priorTags', ['Rāma']), ('originalInputHash', '0' * 64),
                           ('inputHash', '0' * 64), ('evidenceHash', '0' * 64), ('version', 2)]:
            bad = copy.deepcopy(revised); bad['semantic']['subjectTagRevision'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.project(bad)
        with self.assertRaises(ValueError):
            profiles.project_song_profile(self.queue_id, 'example', self.changed, self.taxonomy,
                self.media_hash, revised, required=True, qualification=self.policy)
        with self.assertRaises(ValueError): self.project(revised, reader=self.reader)

    def test_registry_change_is_detected_even_when_tags_still_match(self):
        revised = self.revise()
        self.registry['songs']['example']['evidence'][0]['reason'] = 'Changed review'
        self.save('data/song_tag_overrides.json', self.registry)
        with self.assertRaises(ValueError): self.project(revised)
        self.registry['songs']['example']['evidence'][0]['source'] = 'unperformed'
        self.save('data/song_tag_overrides.json', self.registry)
        with self.assertRaises(ValueError): self.revise()
        revised['semantic']['subjectTagRevision']['evidenceHash'] = profiles.digest(self.registry['songs']['example'])
        with self.assertRaises(ValueError): self.project(revised)

    def test_registry_re_review_replaces_amendment_without_rewriting_assessment(self):
        revised = self.revise(); self.store(revised)
        self.registry['songs']['example']['evidence'][0]['reason'] = 'Expanded source review'
        self.save('data/song_tag_overrides.json', self.registry)
        refreshed = self.revise(record=revised)
        before = copy.deepcopy(revised); before['semantic'].pop('subjectTagRevision')
        after = copy.deepcopy(refreshed); after['semantic'].pop('subjectTagRevision')
        self.assertEqual(after, before)
        self.assertNotEqual(refreshed['semantic']['subjectTagRevision']['evidenceHash'],
                            revised['semantic']['subjectTagRevision']['evidenceHash'])
        self.assertEqual(self.project(refreshed)['semantic']['status'], 'accepted')

    def test_constructor_rejects_unstored_model_record_and_unqualified_record(self):
        bad = copy.deepcopy(self.record); bad['semantic']['features']['themes'][0]['weight'] = .9
        with self.assertRaises(ValueError): self.revise(record=bad)
        bad = copy.deepcopy(self.record); bad['semantic']['method']['model'] = 'unqualified'
        self.store(bad)
        with self.assertRaises(ValueError): self.revise(record=bad)

    def test_existing_profiles_still_need_exact_hash_and_no_registry(self):
        (self.root / 'data/song_tag_overrides.json').unlink()
        self.assertEqual(self.project(self.record, reader=self.reader)['semantic']['status'], 'accepted')
        with self.assertRaises(ValueError): self.project(self.record)
        with self.assertRaises(ValueError): self.revise()

    def test_song_assess_reuses_valid_amendment_without_listener_or_provider(self):
        import bhakti_shuffle_audio as audio
        import bhakti_shuffle_semantics as semantics
        import song
        self.changed['SONG_META'].update(sourceStatus='reviewed', translationStatus='reviewed')
        revised = self.revise(); self.store(revised)
        folder = self.root / 'songs/example'; folder.mkdir(parents=True)
        (folder / 'data.js').write_text('\n'.join('window.' + key + '=' + json.dumps(value) + ';'
                                                  for key, value in self.changed.items()))
        with patch.dict('os.environ'), patch.object(song, 'ROOT', self.root), \
                patch.object(song, 'WORK', self.root / 'work'), \
                patch.object(song, 'listener', side_effect=AssertionError('No listener needed')) as listener, \
                patch.object(audio, 'analyze_audio', side_effect=AssertionError('No audio analysis')) as analyze, \
                patch.object(semantics, 'assess_semantics', side_effect=AssertionError('No paid assessment')) as assess:
            song.assess('example')
            self.assertEqual(profiles.read_json(self.root / profiles.REVIEWS)['profiles'][self.queue_id], revised)
            bad = copy.deepcopy(revised); bad['semantic']['subjectTagRevision']['evidenceHash'] = '0' * 64
            self.store(bad)
            with self.assertRaisesRegex(SystemExit, 'semantic'):
                song.assess('example')
            bad = copy.deepcopy(revised); bad['audio']['mediaSha256'] = '0' * 64
            self.store(bad)
            with self.assertRaisesRegex(SystemExit, 'audio'):
                song.assess('example')
            listener.assert_not_called(); analyze.assert_not_called(); assess.assert_not_called()

    def retag_fixture(self, slugs=('example',)):
        import bhakti_pipeline as pipeline
        import song
        stack = ExitStack(); self.addCleanup(stack.close)
        for module in (song, pipeline):
            stack.enter_context(patch.object(module, 'ROOT', self.root))
        stack.enter_context(patch.object(song, 'WORK', self.root / 'work'))
        stack.enter_context(patch.object(pipeline, 'QUEUE_NUMBERS_PATH', self.root / 'data/queue_numbers.json'))
        self.save('data/queue_numbers.json', {'schemaVersion': 1, 'numbers': {slug: i for i, slug in enumerate(slugs)}})
        self.save('data/translation-review-status.json', {'preserved': 'not a tag review'})
        reviews = {}; media = {}
        for slug in slugs:
            folder = self.root / 'songs' / slug; folder.mkdir(parents=True)
            (folder / 'data.js').write_text('// Keep this prelude.\n' + '\n'.join(
                'window.' + key + ' = ' + json.dumps(value, ensure_ascii=False, indent=2) + ';'
                for key, value in self.reader.items()) + '\n// Keep this ending.\n')
            (folder / 'index.html').write_text(pipeline.page_html(self.reader['SONG_META'], slug))
            record = copy.deepcopy(self.record); record['slug'] = slug
            reviews[hashlib.blake2s(slug.encode(), digest_size=4).hexdigest()] = record
            media[slug] = [{'src': self.reader['SONG_META']['audioSources'][0]['src'], 'sha256': self.media_hash}]
        self.save(profiles.REVIEWS, {'schemaVersion': 1, 'profiles': reviews})
        self.save('data/media.json', {'songs': media})
        pipeline.write_catalogue()
        return song

    def test_retag_preserves_other_bytes_and_reviews_and_is_idempotent(self):
        import bhakti_shuffle_semantics as semantics
        song = self.retag_fixture()
        reader_path = self.root / 'songs/example/data.js'
        page_path = reader_path.with_name('index.html')
        before_source, before_page = reader_path.read_text(), page_path.read_text()
        ledger = (self.root / 'data/translation-review-status.json').read_bytes()
        with patch.object(song, 'listener', side_effect=AssertionError('No listener')) as listener, \
                patch.object(semantics, 'assess_semantics', side_effect=AssertionError('No provider')) as assess:
            song.retag(['example'])
            current = profiles.parse_javascript_sources({'example': reader_path.read_text()})['example']
            self.assertEqual(current, self.changed)
            self.assertEqual(reader_path.read_text().split('window.SONG_LINES')[1],
                             before_source.split('window.SONG_LINES')[1])
            self.assertTrue(reader_path.read_text().startswith('// Keep this prelude.\n'))
            self.assertEqual([line for line in page_path.read_text().splitlines() if 'class="song-meta"' not in line],
                             [line for line in before_page.splitlines() if 'class="song-meta"' not in line])
            self.assertIn('Kṛṣṇa', page_path.read_text())
            self.assertEqual((self.root / 'data/translation-review-status.json').read_bytes(), ledger)
            stored = profiles.read_json(self.root / profiles.REVIEWS)['profiles'][self.queue_id]
            stored['semantic'].pop('subjectTagRevision')
            self.assertEqual(stored, self.record)
            profiles.validate_public_profiles(self.root)
            files = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
            song.retag(['example'])
            self.assertEqual({path: path.read_bytes() for path in files}, files)
            self.assertFalse((self.root / 'work').exists())
            listener.assert_not_called(); assess.assert_not_called()

    def test_retag_invalid_second_item_leaves_whole_batch_untouched(self):
        song = self.retag_fixture(('example', 'second'))
        self.registry['songs']['second'] = copy.deepcopy(self.registry['songs']['example'])
        self.registry['songs']['second']['evidence'][0]['source'] = 'not performed'
        self.save('data/song_tag_overrides.json', self.registry)
        files = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        with self.assertRaisesRegex(ValueError, 'not performed'):
            song.retag(['example', 'second'])
        self.assertEqual({path: path.read_bytes() for path in files}, files)

    def test_retag_detects_concurrent_reader_edit_before_writing_profiles(self):
        import bhakti_pipeline as pipeline
        song = self.retag_fixture()
        path = self.root / 'songs/example/data.js'
        external_edit = path.read_bytes() + b'\n// Concurrent owner edit.\n'
        originals = {file: file.read_bytes() for file in self.root.rglob('*') if file.is_file()}
        render = pipeline.page_html
        def edit_during_prepare(meta, slug):
            path.write_bytes(external_edit)
            return render(meta, slug)
        with patch.object(pipeline, 'page_html', side_effect=edit_during_prepare):
            with self.assertRaisesRegex(ValueError, 'inputs changed'):
                song.retag(['example'])
        self.assertEqual(path.read_bytes(), external_edit)
        self.assertEqual({file: file.read_bytes() for file in originals if file != path},
                         {file: data for file, data in originals.items() if file != path})

    def test_retag_stale_unselected_song_fails_before_any_write(self):
        song=self.retag_fixture(('example','second'))
        other=self.root/'songs/second/data.js'; original=other.read_bytes()
        other.write_text(other.read_text().replace('mind','body'))
        files={path:path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        with self.assertRaisesRegex(ValueError,'second.*semantic'):
            song.retag(['example'])
        self.assertEqual({path:path.read_bytes() for path in files},files)
        other.write_bytes(original)
        song.retag(['example'])
        profiles.validate_public_profiles(self.root)

    def test_retag_no_metadata_change_repairs_stale_public_pair(self):
        song=self.retag_fixture(); song.retag(['example'])
        reader=self.root/'songs/example/data.js'; before=reader.read_bytes()
        public=self.root/profiles.PUBLIC
        public.write_text('window.BHAKTI_SHUFFLE_PROFILES = {};\n')
        with self.assertRaises(ValueError): profiles.validate_public_profiles(self.root)
        song.retag(['example'])
        self.assertEqual(reader.read_bytes(),before)
        profiles.validate_public_profiles(self.root)

    def test_retag_write_failure_rolls_back_owned_outputs(self):
        song=self.retag_fixture()
        before={path:path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        atomic=profiles.atomic_text; written=[]
        def fail_once(path,content):
            if path.is_relative_to(self.root) and '.retag-' not in str(path):
                written.append(path)
                if len(written)==2: raise OSError('fixture write failure')
            return atomic(path,content)
        with patch.object(profiles,'atomic_text',side_effect=fail_once), \
             self.assertRaisesRegex(OSError,'fixture write failure'):
            song.retag(['example'])
        self.assertEqual({path:path.read_bytes() for path in before},before)


if __name__ == '__main__':
    unittest.main()

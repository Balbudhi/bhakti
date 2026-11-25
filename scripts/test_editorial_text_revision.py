"""Source-reviewed text amendments preserve, rather than impersonate, model evidence."""
import copy
import json
from unittest.mock import patch
import unittest

import bhakti_shuffle_profiles as profiles
import test_subject_metadata_refresh as subject_tests


class EditorialTextRevisionTests(unittest.TestCase):
    setUp = subject_tests.SubjectMetadataRefreshTests.setUp
    save = subject_tests.SubjectMetadataRefreshTests.save
    store = subject_tests.SubjectMetadataRefreshTests.store
    project = subject_tests.SubjectMetadataRefreshTests.project

    def receipt(self, before=None, after=None):
        before = before or self.reader
        after = after or self.changed
        return {'reviewer': {'kind': 'assistant-source-review',
                            'reason': 'Read source and corrected word meanings in context.'},
                'beforeLines': {'a': copy.deepcopy(before['SONG_LINES']['a'])},
                'afterLines': {'a': copy.deepcopy(after['SONG_LINES']['a'])},
                'lineEvidence': {'a': 'मन denotes the mind; revised gloss retains inward attention.'},
                'featureDispositions': [{'facet': 'themes', 'id': 'inner-search', 'disposition': 'retain',
                    'factor': 1, 'reason': 'The corrected mind line still supports the inward-search theme.',
                    'sourceLineIds': ['a']}]}

    def prepare(self, tagged=False):
        self.changed = copy.deepcopy(self.reader)
        if tagged:
            self.changed['SONG_META']['subjectTags'] = ['Guru', 'Kṛṣṇa']
            self.record['semantic']['subjectTagRevision'] = profiles.reviewed_subject_tag_revision(
                self.root, 'example', self.changed, self.record, prior_tags=['Guru'])
            self.store(self.record)
        self.changed['SONG_LINES']['a']['english'] = 'the mind'
        self.changed['SONG_LINES']['a']['sourceLanguage'] = 'sa'
        self.evidence = self.receipt()
        self.save_receipt()
        return self.revise()

    def save_receipt(self):
        self.save(profiles.TEXT_REPAIRS, {'version': 1, 'songs': {'example': self.evidence}})

    def revise(self):
        result = copy.deepcopy(self.record)
        result['semantic']['editorialTextRevision'] = profiles.reviewed_editorial_text_revision(
            self.root, 'example', self.changed, self.record)
        return result

    def test_preserves_original_model_audio_and_tag_receipts(self):
        revised = self.prepare(tagged=True)
        self.assertEqual(self.project(revised)['semantic']['themes'], self.record['semantic']['features']['themes'])
        unchanged = copy.deepcopy(revised)
        amendment = unchanged['semantic'].pop('editorialTextRevision')
        self.assertEqual(unchanged, self.record)
        self.assertEqual(amendment['priorLines'], self.reader['SONG_LINES'])
        self.assertNotEqual(amendment['inputHash'], revised['semantic']['inputHash'])
        self.store(revised)
        self.assertEqual(profiles.reviewed_subject_tag_revision(self.root,'example',self.changed,
                         revised,prior_tags=['Guru']),revised['semantic']['subjectTagRevision'])

    def test_empty_semantic_features_need_explicit_review_too(self):
        self.record['semantic'].update(features={'themes': [], 'actions': [], 'subjects': []},
                                       outcome='unknown',reason='No supported semantic features')
        self.store(self.record)
        self.changed=copy.deepcopy(self.reader)
        self.changed['SONG_LINES']['a']['english']='the mind'
        self.evidence=self.receipt(); self.evidence['featureDispositions']=[]; self.save_receipt()
        with self.assertRaisesRegex(ValueError,'empty semantic'): self.revise()
        self.evidence['emptyFeatureDisposition']='Correction does not resolve a supported classification.'
        self.save_receipt()
        self.assertEqual(self.project(self.revise())['semantic']['themes'],[])

    def test_unreviewed_mutations_fail_closed(self):
        revised = self.prepare(tagged=True)
        for mutate in [lambda r: r['SONG_LINES']['a'].update(english='body'),
                       lambda r: r['SONG_LINES']['a'].update(source='तन'),
                       lambda r: r['SONG_LINES']['a']['words'][0].update(gloss='body'),
                       lambda r: r['SONG_LINES']['a'].update(sourceLanguage='hi'),
                       lambda r: r['SONG_SEQUENCE'][0].update(repeats=2),
                       lambda r: r['SONG_META'].update(languages=['Sanskrit']),
                       lambda r: r['SONG_META'].update(subjectTags=['Rāma'])]:
            bad = copy.deepcopy(self.changed); mutate(bad)
            with self.assertRaises(ValueError): self.project(revised, bad)
        bad = copy.deepcopy(revised); bad['semantic']['features']['themes'][0]['weight'] = .9
        with self.assertRaises(ValueError): self.project(bad)
        bad = copy.deepcopy(revised); bad['audio']['mediaSha256'] = 'd'*64
        with self.assertRaises(ValueError): self.project(bad)

    def test_evidence_and_reconstructed_original_cannot_be_rehashed_away(self):
        revised = self.prepare()
        self.evidence['beforeLines']['a']['english'] = 'not the model input'
        self.save_receipt()
        revised['semantic']['editorialTextRevision']['evidenceHash'] = profiles.digest(self.evidence)
        revised['semantic']['editorialTextRevision']['priorLines'] = self.evidence['beforeLines']
        with self.assertRaisesRegex(ValueError, 'original|assessed'): self.project(revised)

    def test_every_feature_needs_explicit_source_bound_disposition(self):
        self.prepare()
        for dispositions in [[], [{'facet': 'themes','id':'inner-search','factor':1}],
                             [dict(self.evidence['featureDispositions'][0],factor=1.1)],
                             [dict(self.evidence['featureDispositions'][0],sourceLineIds=['missing'])],
                             [dict(self.evidence['featureDispositions'][0],reason='')],
                             self.evidence['featureDispositions']*2]:
            original=copy.deepcopy(self.evidence)
            self.evidence['featureDispositions']=dispositions; self.save_receipt()
            with self.assertRaises(ValueError): self.revise()
            self.evidence=original

    def test_only_reviewed_reductions_are_applied_to_public_projection(self):
        self.prepare()
        self.evidence['featureDispositions'][0].update(disposition='reduce',factor=.25)
        self.save_receipt(); revised=self.revise()
        self.assertEqual(self.project(revised)['semantic']['themes'][0]['weight'], .2)
        self.assertEqual(revised['semantic']['features']['themes'][0]['weight'], .8)

    def test_text_reduction_multiplies_existing_editorial_reduction(self):
        self.record['semantic']['editorialReview'] = {
            'kind':'independent-assistant','inputHash':self.record['semantic']['inputHash'],
            'baseFeaturesHash':profiles.digest(self.record['semantic']['features']),'evidenceHash':'d'*64}
        self.record['semantic']['editorialAdjustments'] = [{'facet':'themes','id':'inner-search',
            'factor':.5,'reason':'Existing independent reduction','sourceLineIds':['a']}]
        self.store(self.record); self.prepare()
        self.evidence['featureDispositions'][0].update(disposition='reduce',factor=.25)
        self.save_receipt()
        self.assertAlmostEqual(self.project(self.revise())['semantic']['themes'][0]['weight'],.1)
        self.record['semantic']['editorialAdjustments'][0]['factor']=0
        self.store(self.record)
        self.assertEqual(self.project(self.revise())['semantic']['themes'],[])

    def test_missing_stale_or_fake_evidence_rejected(self):
        revised=self.prepare()
        self.evidence['reviewer']['kind']='human'; self.save_receipt()
        with self.assertRaises(ValueError): self.revise()
        self.evidence['reviewer']['kind']='assistant-source-review'; self.save_receipt()
        self.evidence['lineEvidence']['a']='Changed source basis'; self.save_receipt()
        with self.assertRaises(ValueError): self.project(revised)
        (self.root/profiles.TEXT_REPAIRS).unlink()
        with self.assertRaises(ValueError): self.project(revised)

    def test_unused_and_unchanged_definitions_rejected(self):
        self.prepare()
        for key,line in [('unused', self.reader['SONG_LINES']['a']), ('a', self.changed['SONG_LINES']['a'])]:
            original=copy.deepcopy(self.evidence)
            self.evidence['beforeLines'][key]=copy.deepcopy(line)
            self.evidence['afterLines'][key]=copy.deepcopy(line)
            self.evidence['lineEvidence'][key]='Claimed review'; self.save_receipt()
            with self.assertRaises(ValueError): self.revise()
            self.evidence=original

    def test_assess_valid_text_amendment_never_calls_provider_or_listener(self):
        import song
        revised=self.prepare(); self.store(revised)
        folder=self.root/'songs/example'; folder.mkdir(parents=True)
        source='\n'.join('window.'+key+' = '+json.dumps(value,ensure_ascii=False)+';' for key,value in self.changed.items())
        (folder/'data.js').write_text(source)
        with patch.object(song,'ROOT',self.root), patch.object(song,'WORK',self.root/'work'), \
             patch.object(song,'listener',side_effect=AssertionError('listener forbidden')), \
             patch('bhakti_shuffle_semantics.assess_semantics',side_effect=AssertionError('provider forbidden')), \
             patch('bhakti_shuffle_audio.analyze_audio',side_effect=AssertionError('audio forbidden')):
            song.assess('example')
            self.evidence['lineEvidence']['a']='Stale receipt'; self.save_receipt()
            with self.assertRaises(SystemExit): song.assess('example')
        self.assertFalse((self.root/'work').exists())

    def write_reader(self):
        folder=self.root/'songs/example'; folder.mkdir(parents=True,exist_ok=True)
        path=folder/'data.js'
        path.write_text('\n'.join('window.'+key+' = '+json.dumps(value,ensure_ascii=False)+';'
                                  for key,value in self.changed.items()))
        return path

    def test_batch_refresh_is_atomic_on_validation_and_idempotent(self):
        import refresh_reviewed_text_profiles as command
        self.prepare(); source=self.write_reader(); before_source=source.read_bytes()
        before=(self.root/profiles.REVIEWS).read_bytes()
        with self.assertRaises((ValueError,FileNotFoundError)):
            command.refresh(self.root,['example','missing'],apply=True)
        self.assertEqual((self.root/profiles.REVIEWS).read_bytes(),before)
        command.refresh(self.root,['example'])
        self.assertEqual((self.root/profiles.REVIEWS).read_bytes(),before)
        command.refresh(self.root,['example'],apply=True)
        updated=(self.root/profiles.REVIEWS).read_bytes()
        command.refresh(self.root,['example'],apply=True)
        self.assertEqual((self.root/profiles.REVIEWS).read_bytes(),updated)
        self.assertEqual(source.read_bytes(),before_source)
        self.assertEqual(set(self.root.rglob('*.js')),{source})

    def test_batch_refresh_rejects_concurrent_owner_edit(self):
        import refresh_reviewed_text_profiles as command
        self.prepare(); source=self.write_reader()
        before=(self.root/profiles.REVIEWS).read_bytes()
        original=profiles.reviewed_editorial_text_revision
        def edit(*args,**kwargs):
            result=original(*args,**kwargs)
            source.write_text(source.read_text()+'\n// concurrent owner change\n')
            return result
        with patch.object(profiles,'reviewed_editorial_text_revision',side_effect=edit), \
             self.assertRaisesRegex(ValueError,'changed during preparation'):
            command.refresh(self.root,['example'],apply=True)
        self.assertEqual((self.root/profiles.REVIEWS).read_bytes(),before)
        self.assertIn('concurrent owner change',source.read_text())

    def test_retag_corrected_reader_preserves_text_and_original_assessment(self):
        revised = self.prepare()
        original = copy.deepcopy(self.record)
        self.reader = copy.deepcopy(self.changed)
        self.record = revised
        song = subject_tests.SubjectMetadataRefreshTests.retag_fixture(self)
        path = self.root / 'songs/example/data.js'
        text_suffix = path.read_text().split('window.SONG_LINES')[1]
        receipt = (self.root / profiles.TEXT_REPAIRS).read_bytes()
        song.retag(['example'])
        current = profiles.parse_javascript_sources({'example': path.read_text()})['example']
        self.assertEqual(current['SONG_META']['subjectTags'], ['Guru', 'Kṛṣṇa'])
        self.assertEqual(current['SONG_LINES'], self.reader['SONG_LINES'])
        self.assertEqual(path.read_text().split('window.SONG_LINES')[1], text_suffix)
        stored = profiles.read_json(self.root / profiles.REVIEWS)['profiles'][self.queue_id]
        unchanged = copy.deepcopy(stored)
        unchanged['semantic'].pop('editorialTextRevision')
        unchanged['semantic'].pop('subjectTagRevision')
        self.assertEqual(unchanged, original)
        self.assertEqual((self.root / profiles.TEXT_REPAIRS).read_bytes(), receipt)
        profiles.validate_public_profiles(self.root)
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        song.retag(['example'])
        self.assertEqual({p: p.read_bytes() for p in before}, before)

        # Reversing a reviewed addition returns to original tags, not original text.
        self.registry['songs']['example'] = {'addTags': [], 'removeTags': ['Kṛṣṇa'],
            'evidence': [{'operation': 'remove', 'tag': 'Kṛṣṇa', 'source': 'मन',
                          'reason': 'Contextual incidental-reference exclusion'}]}
        self.save('data/song_tag_overrides.json', self.registry)
        song.retag(['example'])
        current = profiles.parse_javascript_sources({'example': path.read_text()})['example']
        self.assertEqual(current['SONG_META']['subjectTags'], ['Guru'])
        self.assertEqual(current['SONG_LINES'], self.reader['SONG_LINES'])
        stored = profiles.read_json(self.root / profiles.REVIEWS)['profiles'][self.queue_id]
        self.assertNotIn('subjectTagRevision', stored['semantic'])
        profiles.validate_public_profiles(self.root)

    def test_retag_text_receipt_rejects_unreviewed_changes(self):
        revised = self.prepare()
        self.store(revised)
        current = copy.deepcopy(self.changed)
        current['SONG_META']['subjectTags'] = ['Guru', 'Kṛṣṇa']
        for field, value in [('english', 'unreviewed'), ('source', 'तन')]:
            bad = copy.deepcopy(current)
            bad['SONG_LINES']['a'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                profiles.reviewed_retag_semantic(self.root, 'example', bad, revised,
                                                 prior_tags=['Guru'])
        self.evidence['lineEvidence']['a'] = 'Changed since approval'
        self.save_receipt()
        with self.assertRaises(ValueError):
            profiles.reviewed_retag_semantic(self.root, 'example', current, revised,
                                             prior_tags=['Guru'])

    def test_retag_witness_uses_reviewed_corrected_source(self):
        self.prepare()
        self.changed['SONG_LINES']['a']['source'] = 'चित्त'
        self.evidence = self.receipt()
        self.save_receipt()
        revised = self.revise()
        self.store(revised)
        self.registry['songs']['example']['evidence'][0]['source'] = 'चित्त'
        self.save('data/song_tag_overrides.json', self.registry)
        current = copy.deepcopy(self.changed)
        current['SONG_META']['subjectTags'] = ['Guru', 'Kṛṣṇa']
        amended = copy.deepcopy(revised)
        amended['semantic'] = profiles.reviewed_retag_semantic(
            self.root, 'example', current, revised, prior_tags=['Guru'])
        self.assertEqual(self.project(amended, current)['semantic']['status'], 'accepted')
        self.assertEqual(amended['semantic']['inputHash'], self.record['semantic']['inputHash'])
        self.registry['songs']['example']['evidence'][0]['source'] = 'मन'
        self.save('data/song_tag_overrides.json', self.registry)
        with self.assertRaisesRegex(ValueError, 'evidence changed|not performed'):
            profiles.reviewed_retag_semantic(self.root, 'example', current, revised,
                                             prior_tags=['Guru'])

    def test_retag_replaces_existing_combined_tag_amendment(self):
        revised = self.prepare(tagged=True)
        self.store(revised)
        self.registry['songs']['example'] = {'addTags': ['Śiva'], 'removeTags': ['Kṛṣṇa'],
            'evidence': [{'operation': op, 'tag': tag, 'source': 'मन',
                          'reason': 'Revised contextual classification'}
                         for op, tag in [('add', 'Śiva'), ('remove', 'Kṛṣṇa')]]}
        self.save('data/song_tag_overrides.json', self.registry)
        current = copy.deepcopy(self.changed)
        current['SONG_META']['subjectTags'] = ['Guru', 'Śiva']
        amended = copy.deepcopy(revised)
        amended['semantic'] = profiles.reviewed_retag_semantic(
            self.root, 'example', current, revised, prior_tags=['Guru'])
        self.assertEqual(self.project(amended, current)['semantic']['status'], 'accepted')
        self.assertEqual(amended['semantic']['subjectTagRevision']['priorTags'], ['Guru'])
        self.assertEqual(amended['semantic']['editorialTextRevision']['evidenceHash'],
                         revised['semantic']['editorialTextRevision']['evidenceHash'])
        self.assertEqual(amended['audio'], revised['audio'])


if __name__ == '__main__': unittest.main()

"""Reviewed tags follow exact performed text across regenerated line IDs."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import audit_bhakti_contract as audit
import tag_taxonomy as tags


class ReviewedSubjectTagTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'data').mkdir()
        self.registry = {'version': 1, 'songs': {'reviewed': {
            'addTags': ['Guru', 'Viṣṇu'],
            'evidence': [
                {'tag': 'Guru', 'lineId': 'old-id', 'source': 'गुरु का शब्द', 'reason': 'Teacher reference'},
                {'tag': 'Viṣṇu', 'source': 'हरि नाम', 'reason': 'Devotional name reference'},
            ],
        }}}
        self.lines = {'new-id': {'source': 'गुरु का शब्द'}, 'hari': {'source': 'हरि नाम'}}
        self.sequence = [{'ref': 'new-id'}, {'ref': 'hari'}, {'ref': 'new-id'}]
        self.save()

    def save(self) -> None:
        (self.root / 'data' / 'song_tag_overrides.json').write_text(json.dumps(self.registry))

    def apply(self, meta: dict, slug: str = 'reviewed') -> None:
        tags.apply_reviewed_subject_tags(meta, slug, self.lines, self.sequence, root=self.root)

    def test_renumbered_lines_use_exact_performed_source_and_append_once(self) -> None:
        meta = {'subjectTags': ['Nirguṇa', 'Guru'], 'writer': 'Do not change'}
        self.apply(meta)
        self.apply(meta)
        self.assertEqual(meta, {'subjectTags': ['Nirguṇa', 'Guru', 'Viṣṇu'], 'writer': 'Do not change'})

    def test_changed_source_fails_before_mutating_metadata(self) -> None:
        meta = {'subjectTags': ['Nirguṇa']}
        self.lines['hari']['source'] = 'हरी नाम'
        with self.assertRaisesRegex(ValueError, 'reviewed.*Viṣṇu'):
            self.apply(meta)
        self.assertEqual(meta, {'subjectTags': ['Nirguṇa']})

    def test_stored_but_unperformed_source_does_not_authorize_tag(self) -> None:
        self.sequence = [{'ref': 'new-id'}]
        with self.assertRaisesRegex(ValueError, 'Viṣṇu'):
            self.apply({'subjectTags': []})

    def test_metadata_author_or_roman_cannot_replace_source_evidence(self) -> None:
        self.lines['hari'] = {'source': '', 'roman': 'hari nāma'}
        with self.assertRaises(ValueError):
            self.apply({'subjectTags': [], 'writer': 'Hari'})

    def test_unregistered_song_remains_unchanged(self) -> None:
        meta = {'subjectTags': ['Rāma']}
        self.apply(meta, 'other')
        self.assertEqual(meta, {'subjectTags': ['Rāma']})

    def test_malformed_or_missing_registry_fails_closed(self) -> None:
        original = copy.deepcopy(self.registry)
        mutations = [None, {'version': 2, 'songs': {}}, {'version': 1, 'songs': []}]
        for field, value in [('addTags', []), ('addTags', ['Guru', 'Guru']),
                             ('evidence', []), ('evidence', [{'tag': 'Guru', 'source': '', 'reason': 'x'}])]:
            broken = copy.deepcopy(original)
            broken['songs']['reviewed'][field] = value
            mutations.append(broken)
        for broken in mutations:
            self.registry = broken
            self.save()
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                self.apply({'subjectTags': []}, 'other')
        (self.root / 'data' / 'song_tag_overrides.json').unlink()
        with self.assertRaises(ValueError):
            self.apply({'subjectTags': []})

    def test_duplicate_json_keys_and_uncovered_tags_are_rejected(self) -> None:
        path = self.root / 'data' / 'song_tag_overrides.json'
        path.write_text('{"version":1,"songs":{},"songs":{}}')
        with self.assertRaises(ValueError):
            self.apply({'subjectTags': []})
        self.registry['songs']['reviewed']['evidence'].pop()
        self.save()
        with self.assertRaises(ValueError):
            self.apply({'subjectTags': []})

    def test_unknown_performance_reference_is_rejected(self) -> None:
        self.sequence.append({'ref': 'missing'})
        with self.assertRaises(ValueError):
            self.apply({'subjectTags': []})

    def removal_record(self) -> None:
        record = self.registry['songs']['reviewed']
        record['removeTags'] = ['Rāma']
        record['evidence'].append({'operation': 'remove', 'tag': 'Rāma',
            'source': 'रमा लक्ष्मी', 'reason': 'Ramā names the goddess in this performed context.'})
        self.lines['goddess'] = {'source': 'रमा लक्ष्मी'}
        self.sequence.append({'ref': 'goddess'})
        self.save()

    def test_removal_precedes_append_and_both_actions_are_idempotent(self) -> None:
        self.removal_record()
        meta = {'subjectTags': ['Rāma', 'Śakti', 'Guru']}
        self.apply(meta)
        self.apply(meta)
        self.assertEqual(meta['subjectTags'], ['Śakti', 'Guru', 'Viṣṇu'])

    def test_stale_removal_evidence_prevents_every_mutation(self) -> None:
        self.removal_record()
        meta = {'subjectTags': ['Rāma', 'Śakti']}
        self.lines['goddess']['source'] = 'Changed source'
        with self.assertRaisesRegex(ValueError, 'Rāma.*evidence changed'):
            self.apply(meta)
        self.assertEqual(meta['subjectTags'], ['Rāma', 'Śakti'])

    def test_removal_requires_explicit_action_and_complete_evidence(self) -> None:
        self.removal_record()
        record = self.registry['songs']['reviewed']
        del record['evidence'][-1]['operation']
        self.save()
        with self.assertRaises(ValueError):
            self.apply({'subjectTags': ['Rāma']})
        record['evidence'][-1]['operation'] = 'remove'
        record['addTags'].append('Rāma')
        self.save()
        with self.assertRaises(ValueError):
            self.apply({'subjectTags': ['Rāma']})

    def test_removal_only_record_is_supported(self) -> None:
        self.removal_record()
        record = self.registry['songs']['reviewed']
        record['addTags'] = []
        record['evidence'] = record['evidence'][-1:]
        self.save()
        meta = {'subjectTags': ['Rāma', 'Śakti']}
        self.apply(meta)
        self.assertEqual(meta['subjectTags'], ['Śakti'])

    def test_contract_respects_semantic_removal_and_reports_stale_witness(self) -> None:
        self.removal_record()
        for ref, romans, meanings in (
            ('new-id', ['guru', 'kā', 'śabda'], ['spiritual teacher', 'of', 'Word']),
            ('hari', ['hari', 'nāma'], ['the Divine', 'Name']),
            ('goddess', ['ramā', 'lakṣmī'], ['goddess of prosperity', 'goddess of abundance']),
        ):
            self.lines[ref].update(roman=' '.join(romans),
                words=[{'roman': roman, 'gloss': meaning} for roman, meaning in zip(romans, meanings)],
                sourceWords=[{'text': token, 'wordIndices': [i]} for i, token in enumerate(self.lines[ref]['source'].split())],
                english=' '.join('{'+str(i)+':'+meaning+'}' for i, meaning in enumerate(meanings)))
        for entry in self.sequence:
            entry.update(section='verse', repeats=1)
        meta = {'subjectTags': ['Śakti'], 'languages': ['Hindi'], 'title': 'Example',
                'credit': '', 'writer': '', 'singer': '', 'composer': '',
                'timingStatus': 'start-only-reviewed', 'translationStatus': 'reviewed', 'sourceStatus': 'reviewed'}
        self.apply(meta)
        data = {'SONG_META': meta, 'SONG_LINES': self.lines,
                'SONG_SEQUENCE': self.sequence,
                'SONG_TIMINGS': [{'start': i, 'end': i + 1} for i in range(len(self.sequence))]}
        path = self.root / 'reviewed'
        path.mkdir()
        (path / 'data.js').touch()
        with patch.object(audit, 'load_data', return_value=data), patch.object(audit, 'ROOT', self.root):
            problems = audit.audit_song(path)['problems']
            self.assertEqual(problems, [])
            self.lines['goddess']['source'] = 'Changed source'
            problems = audit.audit_song(path)['problems']
            self.assertTrue(any('Rāma evidence changed' in p for p in problems), problems)


if __name__ == '__main__':
    unittest.main()

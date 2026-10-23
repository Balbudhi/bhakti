"""Behavioral contracts for the selective caller; approved before implementation."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import bhakti_library_pass as library
import apply_translation_style_review as writer


def write_js(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join('window.' + key + ' = ' + json.dumps(value, ensure_ascii=False) + ';'
                              for key, value in payload.items()))


def reader():
    return {'SONG_META': {'title': 'Example', 'credit': 'Singer', 'writer': '', 'singer': 'Singer',
                         'composer': '', 'languages': ['Hindi'], 'subjectTags': [],
                         'sourceStatus': 'reviewed', 'timingStatus': 'start-only-reviewed',
                         'translationStatus': 'gloss-derived literal'},
            'SONG_LINES': {'one': {'source': 'मन', 'roman': 'mana', 'english': '{0:mind}',
                                  'words': [{'roman': 'mana', 'gloss': 'mind'}],
                                  'sourceWords': [{'text': 'मन', 'wordIndices': [0]}]}},
            'SONG_SEQUENCE': [{'ref': 'one', 'section': 'verse', 'repeats': 1}],
            'SONG_TIMINGS': [{'start': 1, 'end': 5}]}


class SelectivePassTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.root = self.base / 'repo'; self.root.mkdir()
        self.state = self.base / 'state'; self.catalogue = []
        for args in [('init', '-q'), ('config', 'user.name', 'Test'),
                     ('config', 'user.email', 'test@example.invalid')]: self.git(*args)
        (self.root / '.gitignore').write_text('.transcription/\nsongs/*/audio.*\n')
        (self.root / 'data').mkdir()
        (self.root / 'data/editorial_baselines.json').write_text('{"version":1,"songs":{}}')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args]).decode().strip()

    def add_song(self, slug, singer='Singer'):
        data = reader(); data['SONG_META']['singer'] = singer
        directory = self.root / 'songs' / slug
        write_js(directory / 'data.js', data)
        (directory / 'index.html').write_text('<title>Example</title>')
        (directory / 'audio.webm').write_bytes(b'fixture native audio')
        private = directory / '.transcription'; private.mkdir()
        (private / 'source.json').write_text(json.dumps({'source_url': 'https://www.youtube.com/watch?v=abcdefghijk'}))
        self.catalogue.append({'slug': slug, 'title': 'Example', 'singer': singer, 'writer': '',
                               'languageTags': ['Hindi'], 'subjectTags': []})
        return data

    def commit(self):
        write_js(self.root / 'data/songs.js', {'BHAKTI_SONGS': self.catalogue})
        self.git('add', '.'); self.git('commit', '-qm', 'published fixtures')

    def inventory(self):
        return library.build_inventory(self.root, catalogue_ref='HEAD', state_dir=self.state)

    def test_actual_dry_cli_uses_committed_population_and_never_calls_or_writes_inputs(self):
        self.add_song('published'); self.commit(); self.add_song('unpublished')
        write_js(self.root / 'data/songs.js', {'BHAKTI_SONGS': self.catalogue})
        before = {p.relative_to(self.root).as_posix(): p.read_bytes()
                  for p in self.root.rglob('*') if p.is_file() and '.git' not in p.parts}
        with patch.object(library.pipeline.gemini, 'call', side_effect=AssertionError('dry pass called model')):
            self.assertEqual(library.main(['--root', str(self.root), '--state-dir', str(self.state)]), 0)
        report = json.loads((self.state / 'inventory.json').read_text())
        self.assertEqual([r['slug'] for r in report['songs']], ['published'])
        self.assertEqual(before, {p.relative_to(self.root).as_posix(): p.read_bytes()
                                 for p in self.root.rglob('*') if p.is_file() and '.git' not in p.parts})
        self.assertTrue(report['songs'][0]['audio'][0]['sha256'])
        self.assertNotEqual(report['songs'][0]['state'], 'untouched-valid')

    def test_legacy_missing_hash_and_frame_are_review_gaps_not_linguistic_defects(self):
        self.add_song('legacy'); self.commit()
        row = self.inventory()['songs'][0]
        self.assertEqual(row['state'], 'review-needed')
        self.assertTrue(row['evidenceGaps'])
        self.assertFalse(row['defects'])
        self.assertNotIn('transcript', row['plannedStages'])
        self.assertNotIn('gloss', row['plannedStages'])
        self.assertIn('semantic-review', row['plannedStages'])

    def test_audio_content_change_invalidates_fingerprint_even_same_length(self):
        self.add_song('song'); self.commit()
        before = self.inventory()['songs'][0]['fingerprints']
        (self.root / 'songs/song/audio.webm').write_bytes(b'fixture NATIVE audio')
        after = self.inventory()['songs'][0]['fingerprints']
        self.assertNotEqual(before['audio'], after['audio'])
        self.assertEqual(before['text'], after['text'])

    def test_gloss_change_keeps_audio_and_timing_dependencies(self):
        data = self.add_song('song'); self.commit()
        before = self.inventory()['songs'][0]['fingerprints']
        data['SONG_LINES']['one']['words'][0]['gloss'] = 'the mind'
        write_js(self.root / 'songs/song/data.js', data)
        row = self.inventory()['songs'][0]
        self.assertEqual(before['audio'], row['fingerprints']['audio'])
        self.assertEqual(before['timing'], row['fingerprints']['timing'])
        self.assertNotEqual(before['gloss'], row['fingerprints']['gloss'])
        self.assertTrue(row['workingReaderChanged'])
        self.assertFalse(row['dispatchEligible'])

    def test_exact_owner_baseline_is_protected_even_when_other_evidence_missing(self):
        self.add_song('koi-hor-nahi')
        registry = {'version': 1, 'songs': {'koi-hor-nahi': {
            'policy': 'preserve_english', 'reason': 'owner reference',
            'plainEnglishByLine': {'one': 'mind'},
            'englishSha256': hashlib.sha256(json.dumps({'one': 'mind'}, ensure_ascii=False,
                sort_keys=True, separators=(',', ':')).encode()).hexdigest()}}}
        (self.root / 'data').mkdir(exist_ok=True)
        (self.root / 'data/editorial_baselines.json').write_text(json.dumps(registry))
        self.commit(); row = self.inventory()['songs'][0]
        self.assertEqual(row['state'], 'protected')
        self.assertFalse(row['dispatchEligible'])
        self.assertEqual(row['plannedStages'], [])

    def test_repair_requires_confirmed_targets_and_preserves_every_other_object(self):
        before = reader(); before['SONG_LINES']['two'] = copy.deepcopy(before['SONG_LINES']['one'])
        after = copy.deepcopy(before); after['SONG_LINES']['one']['english'] = '{0:the mind}'
        with self.assertRaisesRegex(ValueError, 'confirmed'):
            library.assert_targeted_change(before, after, confirmed_changes={})
        library.assert_targeted_change(before, after, confirmed_changes={'one': ['english']})
        after['SONG_LINES']['two']['grammarNote'] = 'unrequested metadata polish'
        with self.assertRaisesRegex(ValueError, 'two'):
            library.assert_targeted_change(before, after, confirmed_changes={'one': ['english']})
        after = copy.deepcopy(before); after['SONG_TIMINGS'][0]['start'] = 2
        with self.assertRaisesRegex(ValueError, 'SONG_TIMINGS'):
            library.assert_targeted_change(before, after, confirmed_changes={'one': ['english']})

    def test_existing_writer_uses_explicit_private_root_and_keeps_owner_guard(self):
        data = self.add_song('song'); self.commit()
        original = (self.root / 'songs/song/data.js').read_bytes()
        candidate_root = self.base / 'candidate'
        (candidate_root / 'songs/song').mkdir(parents=True)
        (candidate_root / 'data').mkdir()
        (candidate_root / 'data/editorial_baselines.json').write_text('{"version":1,"songs":{}}')
        writer.write_reader('song', data, root=candidate_root)
        self.assertEqual(library.prepare.load_javascript((candidate_root / 'songs/song/data.js').read_bytes()), data)
        self.assertEqual((self.root / 'songs/song/data.js').read_bytes(), original)


if __name__ == '__main__': unittest.main()

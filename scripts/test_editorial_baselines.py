"""Saved owner English survives generated output and linkage-only edits."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import editorial_baselines as baselines


class EditorialBaselineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'data').mkdir()
        self.registry = {'version': 1, 'songs': {'owner-song': {
            'policy': 'preserve_english', 'reason': 'Owner reference',
            'englishSha256': 'a' * 64,
            'plainEnglishByLine': {'a': 'My breath will abandon me.', 'b': 'Mother!'},
        }}}
        self.save()

    def save(self) -> None:
        (self.root / 'data' / 'editorial_baselines.json').write_text(json.dumps(self.registry))

    def lines(self) -> dict:
        return {'a': {'english': '{0:My breath }{1:will abandon me.}'},
                'b': {'english': '{0:Mother!}'}}

    def test_browser_valid_index_spaces_preserve_visible_english(self) -> None:
        self.assertEqual(baselines.plain_english("{ 0, 1 :O Mother}"), "O Mother")

    def test_linkage_changes_and_reordering_do_not_change_english(self) -> None:
        lines = {'b': {'english': 'Mother!'},
                 'a': {'english': '{1:My }{2,3:breath will }{0:abandon me.}'}}
        baselines.assert_english_preserved('owner-song', lines, root=self.root)

    def test_changed_text_is_blocked_even_if_current_reader_was_rewritten(self) -> None:
        directory = self.root / 'songs' / 'owner-song'
        directory.mkdir(parents=True)
        changed = self.lines()
        changed['a']['english'] = '{0:I will breathe my last.}'
        (directory / 'data.js').write_text('window.SONG_LINES = ' + json.dumps(changed) + ';')
        with self.assertRaisesRegex(RuntimeError, 'owner-song.*a'):
            baselines.assert_english_preserved('owner-song', changed, root=self.root)

    def test_missing_extra_and_malformed_lines_are_blocked(self) -> None:
        cases = [ {'a': self.lines()['a']},
                  {**self.lines(), 'c': {'english': 'Added'}},
                  {**self.lines(), 'a': {'english': None}},
                  {**self.lines(), 'a': {'english': '{bad:My breath will abandon me.}'}} ]
        for lines in cases:
            with self.subTest(lines=lines), self.assertRaises(RuntimeError):
                baselines.assert_english_preserved('owner-song', lines, root=self.root)

    def test_unregistered_song_is_not_locked(self) -> None:
        baselines.assert_english_preserved('other-song', {'x': {'english': 'New'}}, root=self.root)

    def test_invalid_registry_fails_even_for_unregistered_song(self) -> None:
        malformed = [None, {'version': 2, 'songs': {}},
                     {'version': 1, 'songs': []},
                     {'version': 1, 'songs': {'x': {'policy': 'other'}}},
                     {'version': 1, 'songs': {'x': {'policy': 'preserve_english',
                       'englishSha256': 'a' * 64, 'plainEnglishByLine': {'x': 3}}}}]
        for value in malformed:
            self.registry = value
            self.save()
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                baselines.assert_english_preserved('other-song', {}, root=self.root)
        (self.root / 'data' / 'editorial_baselines.json').write_text('{broken')
        with self.assertRaises(RuntimeError):
            baselines.assert_english_preserved('other-song', {}, root=self.root)
        (self.root / 'data' / 'editorial_baselines.json').unlink()
        with self.assertRaises(RuntimeError):
            baselines.assert_english_preserved('other-song', {}, root=self.root)

    def test_style_writer_blocks_before_touching_file(self) -> None:
        import apply_translation_style_review as style
        directory = self.root / 'songs' / 'owner-song'
        directory.mkdir(parents=True)
        target = directory / 'data.js'
        target.write_text('original bytes')
        data = {'SONG_META': {}, 'SONG_LINES': self.lines(), 'SONG_SEQUENCE': [], 'SONG_TIMINGS': []}
        data['SONG_LINES']['a']['english'] = 'Changed'
        with patch.object(style, 'ROOT', self.root), self.assertRaises(RuntimeError):
            style.write_reader('owner-song', data)
        self.assertEqual(target.read_text(), 'original bytes')
        data['SONG_LINES'] = self.lines()
        with patch.object(style, 'ROOT', self.root):
            style.write_reader('owner-song', data)
        self.assertIn('My breath', target.read_text())

    def test_style_review_cannot_report_changed_owner_english_ready(self) -> None:
        import apply_translation_style_review as style
        directory = self.root / 'songs' / 'owner-song'
        directory.mkdir(parents=True)
        data = {'SONG_META': {}, 'SONG_LINES': self.lines(), 'SONG_SEQUENCE': [], 'SONG_TIMINGS': []}
        for line in data['SONG_LINES'].values():
            line['words'] = [{'roman': 'x'}, {'roman': 'y'}]
        with patch.object(style, 'ROOT', self.root):
            style.write_reader('owner-song', data)
        target = directory / 'data.js'
        original = target.read_bytes()
        review_dir = directory / '.transcription' / 'translation-style-audit'
        review_dir.mkdir(parents=True)
        review = {'reviews': [
            {'id': line_id, 'change_needed': True, 'uncertainty': '',
             'revised_english': text, 'segments': [{'text': text, 'word_indices': [0]}]}
            for line_id, text in [('a', 'I will breathe my last.'), ('b', 'Mother!')]
        ]}
        (review_dir / 'review.json').write_text(json.dumps(review))
        for apply in [False, True]:
            with self.subTest(apply=apply), patch.object(style, 'ROOT', self.root):
                with self.assertRaisesRegex(RuntimeError, 'owner-song:a'):
                    style.run_slug('owner-song', apply=apply)
            self.assertEqual(target.read_bytes(), original)

    def test_duplicate_registry_keys_are_rejected(self) -> None:
        (self.root / 'data' / 'editorial_baselines.json').write_text(
            '{"version":1,"songs":{},"songs":{}}'
        )
        with self.assertRaisesRegex(RuntimeError, 'duplicate key'):
            baselines.assert_english_preserved('other-song', {}, root=self.root)


if __name__ == '__main__':
    unittest.main()

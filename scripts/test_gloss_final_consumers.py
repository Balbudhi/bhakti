"""Real final reader consumers must not manufacture a reviewed word meaning."""
import json
import unittest

import bhakti_pipeline as pipeline
import rebuild_public_readers as rebuild
import test_bhakti_pipeline as pipeline_fixtures


class FinalGlossConsumerTests(unittest.TestCase):
    setUp = pipeline_fixtures.PipelineTests.setUp
    tearDown = pipeline_fixtures.PipelineTests.tearDown

    def fixture(self, gloss):
        song = self.root / 'songs' / 'context-test'; song.mkdir(exist_ok=True)
        audited = {'packet': {'metadata': {'languages': ['Hindi']}, 'uncertainties': [],
            'verified_lines': [{'id': 'l1', 'source_text': 'माधव', 'roman': 'Mādhava', 'kind': 'verse'}]}}
        timing = {'sequence': [{'ref': 'l1', 'start': 1, 'end': 2}], 'validation_errors': []}
        glosses = {'packet': {'glosses': [{'id': 'l1', 'word_glosses': [
            {'roman': 'Mādhava', 'gloss': gloss}], 'grammar_note': '', 'uncertainty': ''}]}}
        translations = {'packet': {'translations': [{'id': 'l1', 'literal_english': 'Mādhava',
            'segments': [{'text': 'Mādhava', 'word_indices': [0]}], 'uncertainty': ''}]}}
        job = {'slug': 'context-test', 'source': 'unused', 'title': 'Context test', 'languages': ['Hindi']}
        packet_dir = song / '.transcription/pipeline'; packet_dir.mkdir(parents=True, exist_ok=True)
        (packet_dir / '05-translation.json').write_text(json.dumps(translations))
        return song, job, audited, timing, glosses, translations

    def prepare(self, gloss):
        song, job, audited, timing, glosses, translations = self.fixture(gloss)
        return pipeline.generate(song, job, {}, audited, timing, glosses, translations,
                                 prepare_only=True, write_catalogue_after=False)

    def test_real_generation_rejects_bare_name_before_writing(self):
        with self.assertRaisesRegex(ValueError, 'unresolved self-referential gloss'):
            self.prepare('Madhava')
        self.assertFalse((self.root / 'songs/context-test/data.js').exists())

    def test_real_generation_preserves_both_reviewed_roles_and_english(self):
        for explanation in ("the poet's signature-name", 'Kṛṣṇa, the cowherd beside the Yamunā',
                            'Mādhava is a name of Kṛṣṇa in this scene'):
            with self.subTest(explanation=explanation):
                reader = self.prepare(explanation)
                self.assertEqual(reader['SONG_LINES']['l1']['words'][0]['gloss'], explanation)
                self.assertEqual(reader['SONG_LINES']['l1']['english'], '{0:Mādhava}')

    def test_actual_rebuild_rejects_bare_name_without_changing_reader(self):
        reader = self.prepare('Kṛṣṇa, the cowherd beside the Yamunā')
        reader['SONG_LINES']['l1']['words'][0]['gloss'] = 'Madhava'
        song = self.root / 'songs/context-test'; path = song/'data.js'
        path.write_text(rebuild.data_javascript(reader)); before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'unresolved self-referential gloss'):
            rebuild.rebuild(song)
        self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__': unittest.main()

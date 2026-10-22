"""Generation must suppress printed metre labels without deleting lyrics."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bhakti_pipeline as pipeline
from audit_bhakti_contract import load_data


class MetrePrefixTests(unittest.TestCase):
    def generate_line(self, source, roman, words, segments):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            line = {"id": "line-1", "source_text": source, "roman": roman, "kind": "verse"}
            with patch.object(pipeline, "publication_errors", return_value=[]):
                pipeline.generate(directory, {"slug": "test-metre", "languages": ["Awadhi"]}, {},
                    {"packet": {"verified_lines": [line]}},
                    {"sequence": [{"ref": "line-1", "start": 0, "end": 5}]},
                    {"packet": {"glosses": [{"id": "line-1", "word_glosses": words}]}},
                    {"packet": {"translations": [{"id": "line-1", "segments": segments}]}},
                    write_catalogue_after=False)
            return load_data(directory / "data.js")["SONG_LINES"]["line-1"]

    def test_combined_dohā_marker_preserves_lexical_word_and_shared_english_index(self):
        for source, roman, gloss, text in (
            ("दो.=रामु", "dō.=rāmu", "dohā marker + Rāma", "Rāma "),
            ("दो0=उभय", "dō0=ubhaya", "dohā tag + in both; either", "in either "),
            ("दो0=सरनागत", "dō0=saranāgata", "dohā: one who has come for refuge", "one seeking refuge "),
        ):
            with self.subTest(roman=roman):
                result = self.generate_line(source + " प्रभु", roman + " prabhu",
                    [{"roman": roman, "gloss": gloss}, {"roman": "prabhu", "gloss": "master"}],
                    [{"text": "Doha. ", "word_indices": [0]}, {"text": text, "word_indices": [0]},
                     {"text": "master", "word_indices": [1]}])
                self.assertEqual(result["words"][0]["roman"], roman.split("=")[1])
                self.assertEqual(result["english"], "{0:" + text + "}{1:master}")
                self.assertEqual(result["sourceWords"][0]["wordIndices"], [0])
                self.assertNotIn("dohā", result["words"][0]["gloss"].lower())
                if roman == "dō.=rāmu":
                    self.assertEqual(result["words"][0]["gloss"],
                                     "hero of the Rāmāyaṇa and Viṣṇu’s avatāra")

    def test_standalone_metre_marker_is_removed_and_lexical_index_remapped(self):
        for source, roman, gloss, label in (
            ("दो.", "dō.", "dohā marker", "Dohā: "),
            ("छं.", "chaṃ.", "meter tag; chhand indicator", "Chhand. "),
            ("सो.", "sō.", "sorathā marker", "Sorathā. "),
        ):
            with self.subTest(roman=roman):
                result = self.generate_line(source + " प्रभु", roman + " prabhu",
                    [{"roman": roman, "gloss": gloss}, {"roman": "prabhu", "gloss": "master"}],
                    [{"text": label, "word_indices": [0]}, {"text": "master", "word_indices": [1]}])
                self.assertEqual(result["words"], [{"roman": "prabhu", "gloss": "master"}])
                self.assertEqual(result["english"], "{0:master}")

    def test_lettered_verse_suffixes_do_not_render_as_lyric_words(self):
        for letter, roman_letter, english_letter in (("क", "ka", "a"), ("ख", "kha", "b")):
            result = self.generate_line("प्रभु ॥ ३९(" + letter + ") ॥", "prabhu. 39(" + roman_letter + ").",
                [{"roman": "prabhu.", "gloss": "master"},
                 {"roman": "39(" + roman_letter + ").", "gloss": "doha marker"}],
                [{"text": "master. ", "word_indices": [0]}, {"text": "|| 39" + english_letter + " ||", "word_indices": [1]}])
            self.assertEqual(result["source"], "प्रभु")
            self.assertEqual(result["roman"], "prabhu.")
            self.assertEqual(result["words"], [{"roman": "prabhu.", "gloss": "master"}])
            self.assertEqual(result["english"], "{0:master.}")

    def test_lexical_parentheses_are_not_structural_markers(self):
        source = "प्रभु (राम)"
        self.assertEqual(pipeline.display_source_without_verse_marker(source), source)
        self.assertEqual(pipeline.display_roman_without_verse_marker("prabhu (rāma)", source), "prabhu (rāma)")
        self.assertEqual(pipeline.strip_terminal_verse_marker_english("master (Rāma)"), "master (Rāma)")


if __name__ == "__main__":
    unittest.main()

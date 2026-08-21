#!/usr/bin/env python3

import unittest
from pathlib import Path

import audit_bhakti_contract
import source_word_map


ROOT = Path(__file__).resolve().parents[1]


class SourceWordMapTests(unittest.TestCase):
    def test_whitespace_preserving_phrase_maps_each_source_word(self) -> None:
        words = [{"roman": "Zarā"}, {"roman": "to"}, {"roman": "itnā"}, {"roman": "batā do"}, {"roman": "Sāīṃ"}]
        mapped = source_word_map.build_source_words("ज़रा तो इतना बता दो साईं", words)
        self.assertEqual([item["text"] for item in mapped], ["ज़रा", "तो", "इतना", "बता", "दो", "साईं"])
        self.assertEqual(mapped[3]["wordIndices"], [3])
        self.assertEqual(mapped[4]["wordIndices"], [3])

    def test_source_compound_can_link_multiple_roman_words(self) -> None:
        words = [{"roman": "Yā"}, {"roman": "devī"}, {"roman": "sarvabhūteṣu"},
                 {"roman": "dayā"}, {"roman": "rūpeṇa"}, {"roman": "saṃsthitā"}]
        mapped = source_word_map.build_source_words("या देवी सर्वभूतेषु दया-रूपेण संस्थिता", words)
        compound = next(item for item in mapped if item["text"] == "दया-रूपेण")
        self.assertEqual(compound["wordIndices"], [3, 4])

    def test_kannada_agglutination_links_each_morpheme_gloss(self) -> None:
        words = [{"roman": "Tanu"}, {"roman": "karagada"}, {"roman": "varalli"},
                 {"roman": "majjana"}, {"roman": "vanolleyayyā"}, {"roman": "nīnu"}]
        mapped = source_word_map.build_source_words("ತನು ಕರಗದವರಲ್ಲಿ ಮಜ್ಜನವನೊಲ್ಲೆಯಯ್ಯಾ ನೀನು", words)
        self.assertEqual(mapped[1], {"text": "ಕರಗದವರಲ್ಲಿ", "wordIndices": [1, 2]})
        self.assertEqual(mapped[2], {"text": "ಮಜ್ಜನವನೊಲ್ಲೆಯಯ್ಯಾ", "wordIndices": [3, 4]})

    def test_tamil_compound_maps_to_reviewed_roman_units(self) -> None:
        words = [{"roman": "muṭiyaṭi"}, {"roman": "kāṇā"}, {"roman": "muṭi"}, {"roman": "viṭuttu"}]
        mapped = source_word_map.build_source_words("முடியடி காணா முடி விடுத்து", words)
        self.assertEqual(mapped[0], {"text": "முடியடி", "wordIndices": [0]})
        self.assertEqual(mapped[-1], {"text": "விடுத்து", "wordIndices": [3]})

    def test_every_published_source_mapping_is_reproducible(self) -> None:
        for path in sorted((ROOT / "songs").glob("*/data.js")):
            data = audit_bhakti_contract.load_data(path)
            for line_id, line in data["SONG_LINES"].items():
                with self.subTest(song=path.parent.name, line=line_id):
                    expected = source_word_map.build_source_words(line.get("source", ""), line.get("words", []))
                    self.assertEqual(line.get("sourceWords"), expected)


if __name__ == "__main__":
    unittest.main()

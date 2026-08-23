#!/usr/bin/env python3

import unittest

import normalize_embedded_repeats as repeats


class NormalizeEmbeddedRepeatsTests(unittest.TestCase):
    def test_exact_multiword_phrase_becomes_a_sequence_repeat(self) -> None:
        page = {
            "SONG_LINES": {
                "refrain": {
                    "source": "राम नाम राम नाम",
                    "sourceWords": [
                        {"text": "राम", "wordIndices": [0]},
                        {"text": "नाम", "wordIndices": [1]},
                        {"text": "राम", "wordIndices": [2]},
                        {"text": "नाम", "wordIndices": [3]},
                    ],
                    "roman": "Rām nām Rām nām",
                    "english": "{0:Rāma }{1:name, }{2:Rāma }{3:name}",
                    "words": [
                        {"roman": "Rām", "gloss": "Rāma"},
                        {"roman": "nām", "gloss": "name"},
                        {"roman": "Rām", "gloss": "Rāma"},
                        {"roman": "nām", "gloss": "name"},
                    ],
                }
            },
            "SONG_SEQUENCE": [{"ref": "refrain", "repeats": 1}],
        }
        self.assertEqual(repeats.normalize_page(page), 1)
        line = page["SONG_LINES"]["refrain"]
        self.assertEqual(line["source"], "राम नाम")
        self.assertEqual(line["roman"], "Rām nām")
        self.assertEqual(line["english"], "{0:Rāma }{1:name, }")
        self.assertEqual(len(line["words"]), 2)
        self.assertEqual(page["SONG_SEQUENCE"][0]["repeats"], 2)

    def test_one_word_chant_is_not_rewritten(self) -> None:
        self.assertEqual(
            repeats.repeat_factor([{"roman": "Rām"}, {"roman": "Rām"}]),
            1,
        )


if __name__ == "__main__":
    unittest.main()

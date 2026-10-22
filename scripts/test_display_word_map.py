#!/usr/bin/env python3
"""Hidden structural markers must not become phantom lyric-word links."""

import copy
import re
import unittest

from display_word_map import clean_display_word_map


def visible_english(value):
    return re.sub(r"\{[\d,\s]+:([^}]*)\}", r"\1", value)


class DisplayWordMapTests(unittest.TestCase):
    def test_absent_numeric_marker_is_removed_from_mixed_links_without_changing_text(self):
        line = {"source": "मोहि बिश्राम", "roman": "mohi biśrāma",
                "words": [{"roman": "mohi", "gloss": "for me"},
                          {"roman": "biśrāma", "gloss": "rest"},
                          {"roman": "2.", "gloss": "couplet two"}],
                "sourceWords": [{"text": "मोहि", "wordIndices": [0]},
                                {"text": "बिश्राम", "wordIndices": [1, 2]}],
                "english": "{1:rest }{0,2:for me}", "grammarNote": "unchanged"}
        original = copy.deepcopy(line)
        cleaned, report = clean_display_word_map(line)
        self.assertEqual(cleaned["words"], original["words"][:2])
        self.assertEqual(cleaned["sourceWords"][-1]["wordIndices"], [1])
        self.assertEqual(cleaned["english"], "{1:rest }{0:for me}")
        self.assertEqual(report, {"removedWordIndices": [2], "unlinkedEnglish": []})
        self.assertEqual(visible_english(cleaned["english"]), visible_english(original["english"]))
        self.assertEqual(line, original)
        self.assertEqual(clean_display_word_map(cleaned), (cleaned, {"removedWordIndices": [], "unlinkedEnglish": []}))

    def test_empty_metrical_marker_shifts_indices_but_retains_english_as_unlinked(self):
        line = {"source": "चिक्करहिं दिग्गज", "roman": "cikkarahiṃ diggaja",
                "words": [{"roman": "", "gloss": "meter tag; chhand indicator"},
                          {"roman": "cikkarahiṃ", "gloss": "trumpet"},
                          {"roman": "diggaja", "gloss": "world-elephants"}],
                "sourceWords": [{"text": "चिक्करहिं", "wordIndices": [0, 1]},
                                {"text": "दिग्गज", "wordIndices": [2]}],
                "english": "{0:Chhand. }{2:The world-elephants}{1: trumpet}"}
        cleaned, report = clean_display_word_map(line)
        self.assertEqual(cleaned["english"], "Chhand. {1:The world-elephants}{0: trumpet}")
        self.assertEqual(cleaned["sourceWords"], [{"text": "चिक्करहिं", "wordIndices": [0]},
                                                  {"text": "दिग्गज", "wordIndices": [1]}])
        self.assertEqual(report["unlinkedEnglish"], ["Chhand. "])

    def test_visible_numbers_and_lexical_digits_are_not_removed(self):
        for source, roman, word in (("१ राम", "1 rāma", "1"),
                                    ("एक राम", "1 rāma", "1"),
                                    ("१ राम", "eka rāma", "1"),
                                    ("राम", "rāma2", "rāma2")):
            line = {"source": source, "roman": roman, "words": [{"roman": word, "gloss": "meaning"}],
                    "sourceWords": [], "english": "{0:one}"}
            with self.subTest(source=source, roman=roman):
                self.assertEqual(clean_display_word_map(line)[0], line)

    def test_missing_lexical_evidence_is_never_guessed(self):
        line = {"source": "मन", "roman": "mana", "words": [{"roman": "", "gloss": "mind"}],
                "sourceWords": [{"text": "मन", "wordIndices": [0]}], "english": "{0:mind}"}
        self.assertEqual(clean_display_word_map(line)[0], line)
        line["words"][0] = {"roman": "2", "gloss": "verse number"}
        with self.assertRaisesRegex(ValueError, "source token"):
            clean_display_word_map(line)

    def test_unicode_verse_number_is_structural_but_bad_english_index_is_rejected(self):
        line = {"source": "राम", "roman": "rāma", "words": [
            {"roman": "rāma", "gloss": "Rāma"}, {"roman": "॥२॥", "gloss": "verse two"}],
            "sourceWords": [{"text": "राम", "wordIndices": [0]}], "english": "{0:Rāma}"}
        self.assertEqual(clean_display_word_map(line)[1]["removedWordIndices"], [1])
        line["english"] = "{2:Rāma}"
        with self.assertRaisesRegex(ValueError, "outside the original word map"):
            clean_display_word_map(line)


if __name__ == "__main__":
    unittest.main()

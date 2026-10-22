"""Every displayed lyric letter needs a gloss, including compound components."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import audit_bhakti_contract as audit


class RomanWordCoverageTests(unittest.TestCase):
    def test_missing_leading_lyric_is_rejected_even_when_existing_links_are_valid(self):
        data = {"SONG_META": {"title": "Example", "credit": "", "writer": "", "singer": "",
                "composer": "", "languages": ["Awadhi"], "subjectTags": ["Rāma"],
                "timingStatus": "start-only-reviewed", "translationStatus": "reviewed", "sourceStatus": "reviewed"},
                "SONG_LINES": {"line": {"source": "रामु प्रभु", "roman": "rāmu prabhu",
                    "english": "{0:master}", "words": [{"roman": "prabhu", "gloss": "master"}],
                    "sourceWords": [{"text": "रामु", "wordIndices": [0]}, {"text": "प्रभु", "wordIndices": [0]}]}},
                "SONG_SEQUENCE": [{"ref": "line", "section": "verse", "repeats": 1}],
                "SONG_TIMINGS": [{"start": 0, "end": 1}]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "data.js").touch()
            with patch.object(audit, "load_data", return_value=data):
                problems = audit.audit_song(path)["problems"]
        self.assertTrue(any("IAST has letters without a word gloss" in problem for problem in problems), problems)

    def test_legitimate_compound_parts_punctuation_and_combining_marks_are_covered(self):
        for roman, tokens in (("karagadavaralli", ["karagada", "varalli"]),
                              ("pautramakalmaṣam |", ["pautram", "akalmaṣam"]),
                              ("tū̃ sam̐hālē ॥", ["tū̃", "sam̐hālē"])):
            self.assertEqual(audit.uncovered_roman_spans(roman, [{"roman": token} for token in tokens]), [])

    def test_missing_middle_and_final_letters_are_detected(self):
        self.assertEqual(audit.uncovered_roman_spans("rāmu prabhu rāmu", [{"roman": "rāmu"}, {"roman": "prabhu"}]), [" rāmu"])
        self.assertEqual(audit.uncovered_roman_spans("rāmu prabhu rāmu", [{"roman": "rāmu"}, {"roman": "rāmu"}]), [" prabhu "])


if __name__ == "__main__":
    unittest.main()

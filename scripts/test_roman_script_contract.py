#!/usr/bin/env python3
"""Roman text must stay in the Latin layer without losing IAST marks."""

import json
import tempfile
import unittest
from pathlib import Path

import audit_bhakti_contract


class RomanScriptContractTests(unittest.TestCase):
    def audit_roman(self, roman: str) -> list[str]:
        # Use the public data.js reader, including a matching word token: the
        # historical defect passed substring linkage checks because both were bad.
        data = {
            "SONG_META": {
                "title": "Example", "credit": "", "writer": "", "singer": "",
                "composer": "", "languages": ["Punjabi"], "subjectTags": [],
                "timingStatus": "start-only-reviewed", "translationStatus": "reviewed",
                "sourceStatus": "reviewed",
            },
            "SONG_LINES": {"line": {
                "source": "ਜਪਾਵੈ", "roman": roman, "english": "{0:causes to chant}",
                "words": [{"roman": roman, "gloss": "causes to chant"}],
                "sourceWords": [{"text": "ਜਪਾਵੈ", "wordIndices": [0]}],
            }},
            "SONG_SEQUENCE": [{"ref": "line", "section": "verse", "repeats": 1}],
            "SONG_TIMINGS": [{"start": 0, "end": 1}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "data.js").write_text("\n".join(
                f"window.{key} = {json.dumps(value, ensure_ascii=False)};"
                for key, value in data.items()
            ), encoding="utf-8")
            return audit_bhakti_contract.audit_song(path)["problems"]

    def test_matching_mixed_script_word_does_not_escape_the_audit(self) -> None:
        for roman in ("japਾਵai", "tere तेरे", "abatāradhାରī", "rāмa"):
            with self.subTest(roman=roman):
                problems = self.audit_roman(roman)
                self.assertTrue(any("non-Latin" in problem for problem in problems), problems)

    def test_iast_combining_marks_and_transliteration_punctuation_remain_valid(self) -> None:
        for roman in ("japāvai", "tū̃", "sam̐hālē", "jī'o", "ʻadam", "japāvai ॥", "japāvai ||"):
            with self.subTest(roman=roman):
                self.assertEqual(self.audit_roman(roman), [])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import apply_translation_style_review as script


def write_reader(path: Path, english: str) -> None:
    data = {
        "SONG_META": {"title": "T", "credit": "C", "languages": ["Hindi"], "subjectTags": [],
                       "timingStatus": "start-only-reviewed", "translationStatus": "gloss-derived literal",
                       "sourceStatus": "reviewed"},
        "SONG_LINES": {"line-1": {"source": "सा", "sourceLanguage": "hi", "roman": "sā",
                                    "english": english, "words": [{"roman": "sā", "gloss": "Sai"}],
                                    "grammarNote": ""}},
        "SONG_SEQUENCE": [{"ref": "line-1", "section": "verse", "repeats": 1}],
        "SONG_TIMINGS": [{"start": 0.0, "end": 1.0}],
    }
    content = ("window.SONG_META = " + json.dumps(data["SONG_META"], ensure_ascii=False, indent=2) + ";\n\n" +
               "window.SONG_LINES = " + json.dumps(data["SONG_LINES"], ensure_ascii=False, indent=2) + ";\n\n" +
               "window.SONG_SEQUENCE = " + json.dumps(data["SONG_SEQUENCE"], ensure_ascii=False, indent=2) + ";\n\n" +
               "window.SONG_TIMINGS = " + json.dumps(data["SONG_TIMINGS"], ensure_ascii=False, indent=2) + ";\n")
    path.write_text(content, encoding="utf-8")


class ApplyTranslationStyleReviewTests(unittest.TestCase):
    def test_apply_review_rewrites_only_changed_lines(self) -> None:
        reader = {
            "SONG_LINES": {
                "line-1": {"english": "{0:Sai.}"},
                "line-2": {"english": "{0:Stay.}"},
            }
        }
        review = {
            "reviews": [
                {"id": "line-1", "revised_english": "Sai!", "segments": [{"text": "Sai!", "word_indices": [0]}],
                 "change_needed": True, "issue_type": "none", "reason": "", "uncertainty": ""},
                {"id": "line-2", "revised_english": "Stay.", "segments": [{"text": "Stay.", "word_indices": [0]}],
                 "change_needed": False, "issue_type": "none", "reason": "", "uncertainty": ""},
            ]
        }
        updated, changed = script.apply_review(reader, review)
        self.assertEqual(changed, 1)
        self.assertEqual(updated["SONG_LINES"]["line-1"]["english"], "{0:Sai!}")
        self.assertEqual(updated["SONG_LINES"]["line-2"]["english"], "{0:Stay.}")

    def test_run_slug_applies_review_from_disk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            song_dir = root / "songs" / "demo"
            song_dir.mkdir(parents=True)
            write_reader(song_dir / "data.js", "{0:Sai.}")
            review_dir = song_dir / ".transcription" / "translation-style-audit"
            review_dir.mkdir(parents=True)
            review = {
                "reviews": [
                    {"id": "line-1", "revised_english": "Sai!", "segments": [{"text": "Sai!", "word_indices": [0]}],
                     "change_needed": True, "issue_type": "punctuation", "reason": "test", "uncertainty": ""}
                ]
            }
            (review_dir / "review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            with mock.patch.object(script, "ROOT", root):
                result = script.run_slug("demo", apply=True)
                self.assertEqual(result["changed_lines"], 1)
                output = script.load_reader("demo")
                self.assertEqual(output["SONG_LINES"]["line-1"]["english"], "{0:Sai!}")

    def test_preserved_term_flattening_is_rejected(self) -> None:
        reader = {
            "SONG_LINES": {
                "line-1": {
                    "source": "माया",
                    "roman": "māyā",
                    "english": "{0:māyā}",
                    "words": [{"roman": "māyā", "gloss": "worldly appearance", "concept_key": "maya",
                               "preserve_in_english": True}],
                    "grammarNote": "",
                }
            }
        }
        review = {
            "reviews": [
                {"id": "line-1", "revised_english": "illusion", "segments": [{"text": "illusion", "word_indices": [0]}],
                 "change_needed": True, "issue_type": "unsupported_embellishment", "reason": "", "uncertainty": "none"}
            ]
        }
        errors = script.validate_review("demo", reader, review)
        self.assertIn("demo:line-1 would drop preserved term māyā", errors)


if __name__ == "__main__":
    unittest.main()

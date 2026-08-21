#!/usr/bin/env python3

from __future__ import annotations

import unittest

import audit_translation_style as style


class AuditTranslationStylePromptTests(unittest.TestCase):
    def test_prompt_explicitly_protects_resultant_state_and_agency(self) -> None:
        rendered = style.prompt("demo", [{"id": "line", "source_text": "", "roman": "", "current_english": "",
                                          "word_glosses": [], "grammar_note": ""}], [])
        self.assertIn("my breath will abandon me", rendered)
        self.assertIn("from the inside", rendered)
        self.assertIn("Preserve suffered or resultant states as states", rendered)
        self.assertIn("do not replace it merely because another grammatical parse is possible", rendered)

    def test_review_max_completion_tokens_scales_with_batch_size(self) -> None:
        self.assertEqual(style.review_max_completion_tokens([{}]), 4096)
        self.assertEqual(style.review_max_completion_tokens([{}] * 20), 7680)
        self.assertEqual(style.review_max_completion_tokens([{}] * 80), 16384)

    def test_normalize_segments_repairs_em_dash_spacing(self) -> None:
        segments = [
            {"text": " O Mother —", "word_indices": [0]},
            {"text": "O Mother,", "word_indices": [1]},
            {"text": " take hold of", "word_indices": [2]},
        ]
        fixed = style.normalize_segments(segments)
        self.assertEqual(fixed[0]["text"], " O Mother — ")
        self.assertEqual(fixed[1]["text"], "O Mother,")

        segments = [
            {"text": "fear", "word_indices": [0]},
            {"text": " —aarti to ", "word_indices": [1]},
        ]
        fixed = style.normalize_segments(segments)
        self.assertEqual(fixed[1]["text"], "—aarti to ")

        segments = [
            {"text": "O Mother", "word_indices": [0]},
            {"text": "— ", "word_indices": []},
            {"text": "O Mother,", "word_indices": [1]},
        ]
        fixed = style.normalize_segments(segments)
        self.assertEqual(fixed[1]["text"], " — ")

        segments = [
            {"text": "O Lord— ", "word_indices": [0]},
            {"text": "aarti ", "word_indices": [1]},
        ]
        fixed = style.normalize_segments(segments)
        self.assertEqual(fixed[0]["text"], "O Lord—")


if __name__ == "__main__":
    unittest.main()

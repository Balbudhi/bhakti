#!/usr/bin/env python3
"""Tests for the secondary-text witness layer (no network required)."""

from __future__ import annotations

import unittest

import source_witness


class SourceWitnessTests(unittest.TestCase):
    def test_pustak_parser_excludes_page_chrome_and_commentary(self) -> None:
        html = '''<div id="freeread">
          सभी कष्टों की पीड़ा से निवारण का मूल मंत्र<br>
          <p>सिंधु-तरन, सिय-सोच-हरन, रबि-बालबरन-तनु ।<br>भुज बिसाल, मूरति कराल कालहुको काल जनु ।।</p>
          <p>भावार्थ - यह व्याख्या गीत का पाठ नहीं है।</p>
        </div><div id="dynaJs">'''
        self.assertEqual(source_witness._extract_pustak_page(html), [
            "सिंधु-तरन, सिय-सोच-हरन, रबि-बालबरन-तनु ।",
            "भुज बिसाल, मूरति कराल कालहुको काल जनु ।",
        ])

    def test_witness_prompt_requires_audio_to_control_variants(self) -> None:
        witness = {"witness": {
            "title": "Hanumān Bāhuk",
            "verification_status": "public-working-witness",
            "comparison_policy": "Audio is authoritative for this recording."
        }, "lines": [{"page": 2, "text": "गहन-दहन-निरदहन-लंक नि:संक, बंक-भुव ।"}]}
        context = source_witness.prompt_context(witness, [{"source_text": "गहन दहन निरदहन लंक निहसंक बंक भुअ"}])
        self.assertIn("Audio is authoritative", context)
        self.assertIn("preserve the performance", context)
        self.assertIn("नि:संक", context)

    def test_unmatched_witness_never_becomes_prompt_evidence(self) -> None:
        witness = {"witness": {}, "lines": [{"page": 2, "text": "बिलकुल अलग पाठ"}]}
        self.assertEqual(source_witness.prompt_context(witness, [{"source_text": "हनुमान की जय"}]), "")


if __name__ == "__main__":
    unittest.main()

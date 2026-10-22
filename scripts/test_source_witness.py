#!/usr/bin/env python3
"""Tests for the secondary-text witness layer (no network required)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import source_witness


class SourceWitnessTests(unittest.TestCase):
    def test_srigranth_parser_keeps_only_visible_gurmukhi_source(self) -> None:
        document = '''<script>ਗਲਤ</script>
        <font face="AnmolUniPr"><a title="invented interpretation">ਗਗਨ </a>
        <a>ਮੈ </a>ਥਾਲੁ ॥੧॥</font><br>
        <font color="#008080">गगन मै थालु</font>
        <font face="TAHOMA">Gagan mai thaal</font>
        <font face="TAHOMA">The sky is a plate.</font>
        <font face="AnmolUniPr">ਸਮੑਾਲੇ&nbsp;॥</font>
        <div>ਅਨੁਵਾਦ</div>'''
        self.assertEqual(source_witness._extract_srigranth_gurmukhi(document), [
            "ਗਗਨ ਮੈ ਥਾਲੁ ॥੧॥", "ਸਮੑਾਲੇ ॥",
        ])

    def test_srigranth_acquisition_keeps_page_provenance_and_rejects_empty_source(self) -> None:
        record = {"pages": [6, 9]}
        with patch.object(source_witness, "_fetch", side_effect=[
            '<font face="AnmolUniPr">ਸੋ ਦਰੁ ਕੇਹਾ ॥</font>',
            '<font face="AnmolUniPr">ਸੋ ਦਰੁ ਤੇਰਾ ਕੇਹਾ ॥</font>',
        ]):
            pages, lines = source_witness._acquire_srigranth_pages(record)
        self.assertEqual([row["page"] for row in lines], [6, 9])
        self.assertTrue(lines[1]["url"].endswith("Param=9"))
        self.assertEqual([row["line_count"] for row in pages], [1, 1])
        with patch.object(source_witness, "_fetch", return_value="<p>Unavailable</p>"):
            with self.assertRaisesRegex(RuntimeError, "no Gurmukhi source"):
                source_witness._acquire_srigranth_pages({"pages": [6]})

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

    def test_pdf_range_extractor_keeps_only_the_configured_verse_text(self) -> None:
        text = """भूमिका
गाइये गणपति जगवंदन । शंकर सुवन भवानीनंदन ।
सिद्धि सदन गजवदन विनायक ।
प्रश्न: इस कविता का सार लिखिए।
अतिरिक्त गद्य"""
        self.assertEqual(source_witness._extract_pdf_text_range(text, "गाइये गणपति", "प्रश्न:"), [
            "गाइये गणपति जगवंदन ।",
            "शंकर सुवन भवानीनंदन ।",
            "सिद्धि सदन गजवदन विनायक ।",
        ])

    def test_html_pre_range_extractor_keeps_the_source_poem_without_metadata(self) -> None:
        document = '''<pre class="stotra" id="content">भूमिका
जामवंत के बचन सुहाए।
सुनि हनुमंत हृदय अति भाए ॥
दोहा सकल सुमंगल दायक रघुनायक गुन गान।</pre>
        <pre class="inf">% Text title metadata</pre>'''
        self.assertEqual(source_witness._extract_html_pre_text_range(
            document, "जामवंत के बचन सुहाए", "दोहा सकल सुमंगल दायक रघुनायक गुन गान。"
        ), [])
        self.assertEqual(source_witness._extract_html_pre_text_range(
            document, "जामवंत के बचन सुहाए", "दोहा सकल सुमंगल दायक रघुनायक गुन गान।"
        ), ["जामवंत के बचन सुहाए।", "सुनि हनुमंत हृदय अति भाए ॥", "दोहा सकल सुमंगल दायक रघुनायक गुन गान।"])


if __name__ == "__main__":
    unittest.main()

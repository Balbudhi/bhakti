#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

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

    def test_together_gpt_oss_reserves_reasoning_and_final_output(self) -> None:
        with mock.patch.object(style.gemini, 'provider_name', return_value='together'):
            self.assertEqual(style.review_max_completion_tokens([{}], model='openai/gpt-oss-120b'), 16384)
            self.assertEqual(style.review_max_completion_tokens([{}] * 20, model='openai/gpt-oss-20b'), 16384)
            self.assertEqual(style.review_max_completion_tokens([{}], model='Qwen/Qwen3.5-9B'), 4096)
        with mock.patch.object(style.gemini, 'provider_name', return_value='openrouter'):
            self.assertEqual(style.review_max_completion_tokens([{}], model='openai/gpt-oss-120b'), 4096)

    def test_other_providers_and_models_keep_existing_completion_limits(self) -> None:
        for provider, model in [('google', 'google/gemini-3.7-flash'),
                                ('together', 'google/gemini-3.7-flash'),
                                ('openrouter', 'google/gemini-3.8-flash')]:
            with self.subTest(provider=provider, model=model), \
                    mock.patch.object(style.gemini, 'provider_name', return_value=provider):
                self.assertEqual(style.review_max_completion_tokens([{}] * 18, model=model), 6912)
                self.assertEqual(style.review_max_completion_tokens([{}] * 30, model=model), 11520)

    def test_gemini_request_accommodates_saved_high_reasoning_outputs_and_reuses_cache(self) -> None:
        # Successful saved 3.7 audits: Yeh Garv (18 lines, 20,338 completion
        # tokens) and Kakad batch 7 (30 lines, 24,447). Exercise run_slug so a
        # helper-only fix that is not passed to the actual request also fails.
        for count, historical_completion in [(18, 20338), (30, 24447)]:
            with self.subTest(lines=count), tempfile.TemporaryDirectory() as temporary:
                reader = {'SONG_META': {'languages': ['Hindi']}, 'SONG_LINES': {
                    f'line-{index}': {'source': 'एक', 'roman': 'eka',
                                     'english': '{0:One}', 'words': [{'roman': 'eka', 'gloss': 'one'}]}
                    for index in range(count)}}
                reviews = [{'id': line_id, 'revised_english': 'One',
                            'segments': [{'text': 'One', 'word_indices': [0]}],
                            'change_needed': False, 'issue_type': '', 'reason': '', 'uncertainty': ''}
                           for line_id in reader['SONG_LINES']]
                options = argparse.Namespace(model='google/gemini-3.7-flash', batch_size=30,
                                             force=False, timeout=600)
                with mock.patch.object(style, 'ROOT', Path(temporary)), \
                        mock.patch.object(style, 'load_reader', return_value=reader), \
                        mock.patch.object(style.gemini, 'provider_name', return_value='openrouter'), \
                        mock.patch.object(style.gemini, 'key', return_value='test-placeholder'), \
                        mock.patch.object(style.gemini, 'call', return_value={
                            'packet': {'reviews': reviews}, 'usage': {'cost': 0.01}}) as request:
                    style.run_slug('fixture', options)
                    request.assert_called_once()
                    kwargs = request.call_args.kwargs
                    self.assertEqual(kwargs['reasoning_effort'], 'high')
                    self.assertIsNone(kwargs['audio'])
                    self.assertGreater(kwargs['max_completion_tokens'], historical_completion)
                    self.assertEqual(kwargs['max_completion_tokens'], 32768)
                    cache_path = (Path(temporary) / 'songs/fixture/.transcription/'
                                  'translation-style-audit/batch-000.json')
                    saved = json.loads(cache_path.read_text())
                    self.assertEqual(saved['validation_errors'], [])
                    self.assertEqual(len(saved['response']['packet']['reviews']), count)
                    style.run_slug('fixture', options)
                    request.assert_called_once()

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

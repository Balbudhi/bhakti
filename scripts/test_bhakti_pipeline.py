#!/usr/bin/env python3
"""Deterministic integration tests for the one-command Bhakti pipeline."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bhakti_pipeline as pipeline


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bhakti-pipeline-test-")
        self.root = Path(self.temp.name)
        self.original_root = pipeline.ROOT
        registry = (self.original_root / "data" / "preserved_terms.json").read_text(encoding="utf-8")
        pipeline.ROOT = self.root
        (self.root / "songs").mkdir()
        (self.root / "data").mkdir()
        (self.root / "data" / "songs.js").write_text("window.BHAKTI_SONGS = [];\n", encoding="utf-8")
        (self.root / "data" / "preserved_terms.json").write_text(registry, encoding="utf-8")

    def tearDown(self) -> None:
        pipeline.ROOT = self.original_root
        self.temp.cleanup()

    def test_local_mp3_is_transcoded_to_real_m4a(self) -> None:
        source = self.root / "input.mp3"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2",
            "-c:a", "libmp3lame", str(source),
        ], check=True)
        song, _ = pipeline.intake({"slug": "local-test", "source": str(source)}, force=False)
        format_name = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=format_name", "-of", "default=nokey=1:noprint_wrappers=1",
            str(song / "audio.m4a"),
        ], check=True, capture_output=True, text=True).stdout
        self.assertIn("mp4", format_name)

    def test_generation_uses_roles_and_canonical_reader_contract(self) -> None:
        song = self.root / "songs" / "sample-song"
        song.mkdir()
        audited = {"packet": {"metadata": {"languages": ["Hindi"]}, "uncertainties": [], "verified_lines": [
            {"id": "line-one", "source_text": "साईं", "roman": "Sāīṃ", "kind": "refrain"}
        ]}}
        timing = {"sequence": [{"ref": "line-one", "start": 1.25, "end": 2.5}], "validation_errors": []}
        glosses = {"packet": {"glosses": [{"id": "line-one", "word_glosses": [{"roman": "Sāīṃ", "gloss": "Sai"}], "grammar_note": "", "uncertainty": ""}]}}
        translations = {"packet": {"translations": [{"id": "line-one", "literal_english": "Sai.", "segments": [{"text": "Sai", "word_indices": [0]}, {"text": ".", "word_indices": []}], "uncertainty": ""}]}}
        job = {"slug": "sample-song", "source": "unused", "title": "Sample Song", "writer": "Writer", "singer": "Singer",
               "languages": ["Hindi"], "subjectTags": ["Śirḍī Sāī"], "searchAliases": ["Shirdi Sai Baba"]}
        pipeline.generate(song, job, {}, audited, timing, glosses, translations)
        page = (song / "index.html").read_text(encoding="utf-8")
        data = (song / "data.js").read_text(encoding="utf-8")
        self.assertIn("Writer · Singer", (self.root / "data" / "songs.js").read_text(encoding="utf-8"))
        self.assertIn("<p class=\"song-credit\">Singer</p>", page)
        self.assertIn('"sourceLanguage": "hi"', data)
        self.assertIn('"section": "refrain"', data)
        self.assertIn('"searchAliases"', data)
        self.assertIn("Shirdi Sai Baba", (self.root / "data" / "songs.js").read_text(encoding="utf-8"))
        self.assertIn("manifest.webmanifest", page)

    def test_publication_gate_rejects_uncertainty(self) -> None:
        audited = {"packet": {"verified_lines": [], "uncertainties": ["unclear word"]}}
        timing = {"sequence": [], "validation_errors": []}
        glosses = {"packet": {"glosses": []}}
        translations = {"packet": {"translations": []}}
        self.assertIn("audited transcription has unresolved uncertainties",
                      pipeline.publication_errors(audited, timing, glosses, translations))

    def test_publication_gate_rejects_translation_fidelity_loss(self) -> None:
        lines = [{"id": "line", "source_text": "साँस", "roman": "sāṁs"}]
        audited = {"packet": {"verified_lines": lines, "uncertainties": []}}
        timing = {"sequence": [], "validation_errors": []}
        glosses = {"packet": {"glosses": [{"id": "line", "word_glosses": [
            {"roman": "sāṁs", "gloss": "breath"}], "grammar_note": "", "uncertainty": ""}]}}
        translations = {"packet": {"translations": [{"id": "line", "literal_english": "I die.",
            "segments": [{"text": "I die.", "word_indices": [0]}],
            "fidelity": {"agency_and_image_preserved": False, "all_meaning_accounted_for": True,
                         "unsupported_additions": [], "notes": "agency changed"}, "uncertainty": ""}]}}
        errors = pipeline.publication_errors(audited, timing, glosses, translations)
        self.assertIn("line translation does not preserve agency or imagery", errors)

    def test_semantic_frame_is_required_by_new_gloss_contract(self) -> None:
        lines = [{"id": "line", "roman": "sāṁs", "source_text": "साँस"}]
        rows = [{"id": "line", "word_glosses": [{"roman": "sāṁs", "gloss": "breath"}]}]
        self.assertIn("line lacks a complete semantic frame", pipeline.gloss_contract_errors(lines, rows))

    def test_independent_translation_review_can_block_poetic_choice(self) -> None:
        lines = [{"id": "line", "source_text": "", "roman": "sāṁs"}]
        glosses = [{"id": "line", "word_glosses": [{"roman": "sāṁs", "gloss": "breath"}]}]
        translations = [{"id": "line", "literal_english": "My breath leaves me.",
                         "segments": [{"text": "My breath leaves me.", "word_indices": [0]}],
                         "independent_review": {"passes": True, "human_review_recommended": True,
                                                "agency_preserved": True, "imagery_preserved": True,
                                                "all_meaning_accounted_for": True,
                                                "unsupported_additions": [], "material_choice": "agency",
                                                "reason": "two defensible readings"}}]
        errors = pipeline.validate_line_contract(lines, glosses, translations)
        self.assertIn("line independent review requires a human poetic choice", errors)

    def test_translation_contract_requires_every_source_word_link(self) -> None:
        lines = [{"id": "line", "source_text": "मन उदास", "roman": "mana udāsa"}]
        glosses = [{"id": "line", "word_glosses": [
            {"roman": "mana", "gloss": "heart"}, {"roman": "udāsa", "gloss": "despondent"}]}]
        translations = [{"id": "line", "literal_english": "The heart is despondent.",
                         "segments": [{"text": "The heart is despondent.", "word_indices": [1]}]}]
        errors = pipeline.validate_line_contract(lines, glosses, translations)
        self.assertIn("line English segments omit source word indices [0]", errors)

    def test_curated_maya_must_remain_in_english(self) -> None:
        registry = pipeline.preserved_term_registry()["terms"]
        self.assertEqual(registry["maya"]["iast"], "māyā")
        self.assertIn("illusion", registry["maya"]["forbiddenFlattenings"])
        lines = [{"id": "line", "source_text": "माया", "roman": "māyā"}]
        glosses = [{"id": "line", "word_glosses": [{"roman": "māyā", "gloss": "worldly appearance",
                                                       "concept_key": "maya", "preserve_in_english": True}]}]
        translations = [{"id": "line", "literal_english": "illusion",
                         "segments": [{"text": "illusion", "word_indices": [0]}]}]
        errors = pipeline.validate_line_contract(lines, glosses, translations)
        self.assertIn("line must preserve māyā in English", errors)

    def test_display_occurrences_compress_only_adjacent_repeats(self) -> None:
        packet = {"verified_lines": [
            {"id": "a", "source_text": "अ", "roman": "A", "kind": "refrain"},
            {"id": "b", "source_text": "ब", "roman": "B", "kind": "verse"},
        ], "performance_order": [
            {"line_id": "a"}, {"line_id": "a"}, {"line_id": "b"}, {"line_id": "a"}
        ]}
        occurrences = pipeline.display_occurrences(packet)
        self.assertEqual([item["occurrence_id"] for item in occurrences], ["occ-000", "occ-001", "occ-002"])
        self.assertEqual([(item["ref"], item["repeats"]) for item in occurrences], [("a", 2), ("b", 1), ("a", 1)])

    def test_compress_adjacent_reader_entries_merges_sequence_and_timings(self) -> None:
        sequence = [
            {"ref": "a", "section": "refrain", "repeats": 1},
            {"ref": "a", "section": "refrain", "repeats": 1},
            {"ref": "b", "section": "verse", "repeats": 2},
            {"ref": "b", "section": "spoken", "repeats": 1},
        ]
        timings = [
            {"start": 1.0, "end": 2.0},
            {"start": 2.0, "end": 3.5},
            {"start": 3.5, "end": 7.0},
            {"start": 7.0, "end": 8.0},
        ]
        merged_sequence, merged_timings, merged = pipeline.compress_adjacent_reader_entries(sequence, timings)
        self.assertEqual(merged, 1)
        self.assertEqual(merged_sequence, [
            {"ref": "a", "section": "refrain", "repeats": 2},
            {"ref": "b", "section": "verse", "repeats": 2},
            {"ref": "b", "section": "spoken", "repeats": 1},
        ])
        self.assertEqual(merged_timings, [
            {"start": 1.0, "end": 3.5},
            {"start": 3.5, "end": 7.0},
            {"start": 7.0, "end": 8.0},
        ])

    def test_start_only_response_derives_intervals_and_blocks_reordering(self) -> None:
        occurrences = [
            {"occurrence_id": "occ-000", "ref": "a", "section": "refrain", "repeats": 2},
            {"occurrence_id": "occ-001", "ref": "b", "section": "verse", "repeats": 1},
        ]
        sequence, errors, uncertain = pipeline.timing_sequence_from_response(
            occurrences,
            {"starts": [{"occurrence_id": "occ-000", "start": 3.25},
                        {"occurrence_id": "occ-001", "start": 11.5}], "uncertain_occurrence_ids": []},
            20.0,
        )
        self.assertEqual(errors, [])
        self.assertEqual(uncertain, [])
        self.assertEqual(sequence[0]["end"], 11.5)
        self.assertEqual(sequence[1]["end"], 20.0)
        _, errors, _ = pipeline.timing_sequence_from_response(
            occurrences,
            {"starts": [{"occurrence_id": "occ-001", "start": 3.25},
                        {"occurrence_id": "occ-000", "start": 11.5}], "uncertain_occurrence_ids": []},
            20.0,
        )
        self.assertTrue(any("order differs" in error for error in errors))

    def test_uncertainty_is_repairable_not_fatal(self) -> None:
        occurrences = [
            {"occurrence_id": "occ-000", "ref": "a", "section": "refrain", "repeats": 1},
            {"occurrence_id": "occ-001", "ref": "b", "section": "verse", "repeats": 1},
        ]
        sequence, errors, uncertain = pipeline.timing_sequence_from_response(
            occurrences,
            {"starts": [{"occurrence_id": "occ-000", "start": 1.0},
                        {"occurrence_id": "occ-001", "start": 4.0}],
             "uncertain_occurrence_ids": ["occ-001"]},
            10.0,
        )
        self.assertEqual(errors, [])
        self.assertEqual(uncertain, ["occ-001"])
        self.assertEqual(len(sequence), 2)

    def test_bounded_verification_grid_covers_every_occurrence_once(self) -> None:
        occurrences = [{"occurrence_id": f"occ-{index:03d}", "ref": str(index)} for index in range(4)]
        coarse = [{"start": start} for start in (10.0, 50.0, 100.0, 170.0)]
        chunks = pipeline.build_timing_chunks(occurrences, coarse, 200.0)
        coverage = {occurrence["occurrence_id"]: 0 for occurrence in occurrences}
        for chunk in chunks:
            for target in chunk["target_occurrences"]:
                coverage[target["occurrence_id"]] += 1
        self.assertEqual(set(chunk["grid"] for chunk in chunks), {"verification"})
        self.assertEqual(set(coverage.values()), {1})

    def test_consensus_requires_two_close_measurements(self) -> None:
        self.assertEqual(pipeline.consensus_value([10.1, 10.3, 14.0]), 10.2)
        self.assertIsNone(pipeline.consensus_value([10.0]))
        self.assertIsNone(pipeline.consensus_value([10.0, 11.0]))

    def test_adaptive_segments_choose_energy_valleys_with_overlap(self) -> None:
        frames = [(float(second), -10.0) for second in range(0, 1001)]
        frames[330] = (330.0, -40.0)
        frames[640] = (640.0, -35.0)
        with mock.patch.object(pipeline.gemini, "duration_seconds", return_value=1000.0), \
             mock.patch.object(pipeline, "rms_frames", return_value=frames):
            segments = pipeline.adaptive_audio_segments(Path("unused.m4a"))
        self.assertEqual(segments[0]["core_end"], 330.25)
        self.assertEqual(segments[1]["core_end"], 640.25)
        self.assertEqual(segments[1]["clip_start"], 315.25)
        self.assertEqual(segments[1]["clip_end"], 655.25)

    def test_listener_audio_prefers_preserved_best_stream(self) -> None:
        song = self.root / "songs" / "audio-choice"
        song.mkdir()
        (song / "audio.m4a").touch()
        (song / "audio.webm").touch()
        self.assertEqual(pipeline.preferred_listener_audio(song).name, "audio.webm")

    def test_lossless_trim_shortens_audio_without_changing_codec(self) -> None:
        song = self.root / "songs" / "trim-test"
        (song / ".transcription").mkdir(parents=True)
        audio = song / "audio.m4a"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=10", "-c:a", "aac", str(audio)], check=True)
        pipeline.apply_lossless_trim(song, {"duration": 10.0, "trim_start": 2.0, "trim_end": 8.0,
                                             "validation_errors": []})
        self.assertLess(pipeline.gemini.duration_seconds(audio), 6.2)
        codec = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                                "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1", str(audio)],
                               check=True, capture_output=True, text=True).stdout.strip()
        self.assertEqual(codec, "aac")

    def test_batch_rejects_non_string_search_aliases(self) -> None:
        manifest = self.root / "batch.json"
        manifest.write_text(json.dumps({"songs": [{"slug": "sample", "source": "unused", "searchAliases": "Shirdi Sai"}]}),
                            encoding="utf-8")
        options = type("Options", (), {"song": [], "batch": manifest})()
        with self.assertRaisesRegex(SystemExit, "searchAliases.*list of strings"):
            pipeline.normalise_jobs(options)

    def test_segmented_english_preserves_word_spacing_and_punctuation(self) -> None:
        rendered = pipeline.segment_english([
            {"text": "Take", "word_indices": [2]},
            {"text": "flight", "word_indices": [1]},
            {"text": "into the sky", "word_indices": [0]},
            {"text": ",", "word_indices": []},
            {"text": "O bird", "word_indices": [3, 4]},
            {"text": ".", "word_indices": []},
        ], "")
        self.assertEqual(rendered, "{2:Take}{1: flight}{0: into the sky},{3,4: O bird}.")
        self.assertEqual(
            pipeline.segment_english([
                {"text": "O Lord—", "word_indices": [0]},
                {"text": " aarti", "word_indices": [1]},
            ], ""),
            "{0:O Lord—}{1:aarti}",
        )
        self.assertEqual(
            pipeline.segment_english([
                {"text": "fear", "word_indices": [0]},
                {"text": "—aarti to ", "word_indices": [1]},
                {"text": "Sai", "word_indices": [2]},
            ], ""),
            "{0:fear}{1:—aarti to }{2:Sai}",
        )
        self.assertEqual(
            pipeline.segment_english([
                {"text": "Ganu ", "word_indices": [0]},
                {"text": "says", "word_indices": [1]},
            ], ""),
            "{0:Ganu }{1:says}",
        )
        self.assertEqual(
            pipeline.segment_english([
                {"text": 'Ganu says, "', "word_indices": [0]},
                {"text": "Baba", "word_indices": [1]},
            ], ""),
            '{0:Ganu says, "}{1:Baba}',
        )
        self.assertEqual(
            pipeline.segment_english([
                {"text": "Sai", "word_indices": [0]},
                {"text": "’s name", "word_indices": [1]},
                {"text": "…", "word_indices": []},
            ], ""),
            "{0:Sai}{1:’s name}…",
        )

    def test_display_title_and_language_use_reviewed_forms(self) -> None:
        lines = [{"roman": "ākāśī jhepa ghe re pākharā"}]
        self.assertEqual(pipeline.reviewed_display_title("Akashi Zep Ghe Re Pakhara", lines),
                         "Ākāśī Jhepa Ghe Re Pākharā")
        self.assertEqual(pipeline.normalized_language("mr"), "Marathi")

    def test_long_timing_segments_cover_each_occurrence_once(self) -> None:
        occurrences = [{"occurrence_id": f"occ-{index:03d}", "ref": str(index)} for index in range(4)]
        coarse = [{"start": start, "segment_index": segment}
                  for start, segment in ((10.0, 0), (90.0, 0), (110.0, 1), (190.0, 1))]
        audited = {"segment_audits": [
            {"segment": {"index": 0, "core_start": 0.0, "core_end": 100.0,
                         "clip_start": 0.0, "clip_end": 115.0}},
            {"segment": {"index": 1, "core_start": 100.0, "core_end": 200.0,
                         "clip_start": 85.0, "clip_end": 200.0}},
        ]}
        chunks = pipeline.build_long_timing_chunks(audited, occurrences, coarse, 200.0)
        self.assertEqual([len(chunk["target_occurrences"]) for chunk in chunks], [2, 2])
        ids = [target["occurrence_id"] for chunk in chunks for target in chunk["target_occurrences"]]
        self.assertEqual(ids, [item["occurrence_id"] for item in occurrences])

    def test_long_merge_drops_internal_overlap_fragments(self) -> None:
        def segment(index: int, lines: list[dict[str, str]]) -> dict:
            return {"segment": {"index": index}, "audit": {"packet": {
                "lines": lines,
                "performance_order": [{"line_id": line["id"]} for line in lines],
                "uncertainties": [],
            }}}
        merged = pipeline.merge_audited_segments([
            segment(0, [
                {"id": "a", "source_text": "पूर्व", "roman": "pūrva", "language": "Sanskrit", "partial": "none"},
                {"id": "cut", "source_text": "नमामीश्वरं…", "roman": "namāmīśvaram…", "language": "Sanskrit", "partial": "trailing"},
            ]),
            segment(1, [
                {"id": "full", "source_text": "नमामीश्वरं सद्गुरुं साईनाथम्", "roman": "namāmīśvaraṃ sadguruṃ sāyinātham", "language": "Sanskrit", "partial": "none"},
            ]),
        ])
        self.assertEqual([line["source_text"] for line in merged["verified_lines"]],
                         ["पूर्व", "नमामीश्वरं सद्गुरुं साईनाथम्"])


if __name__ == "__main__":
    unittest.main()

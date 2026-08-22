#!/usr/bin/env python3
"""Deterministic integration tests for the one-command Bhakti pipeline."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import intake_bhakti_youtube as intake
import bhakti_pipeline as pipeline


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bhakti-pipeline-test-")
        self.root = Path(self.temp.name)
        self.original_root = pipeline.ROOT
        registry = (self.original_root / "data" / "preserved_terms.json").read_text(encoding="utf-8")
        source_credits = (self.original_root / "data" / "source_credits.json").read_text(encoding="utf-8")
        pipeline.ROOT = self.root
        (self.root / "songs").mkdir()
        (self.root / "data").mkdir()
        (self.root / "data" / "songs.js").write_text("window.BHAKTI_SONGS = [];\n", encoding="utf-8")
        (self.root / "data" / "preserved_terms.json").write_text(registry, encoding="utf-8")
        (self.root / "data" / "source_credits.json").write_text(source_credits, encoding="utf-8")

    def tearDown(self) -> None:
        pipeline.ROOT = self.original_root
        self.temp.cleanup()

    def test_local_mp3_is_transcoded_to_real_m4a(self) -> None:
        source = self.root / "input.mp3"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2",
            "-c:a", "libmp3lame", str(source),
        ], check=True)
        source_url = "https://www.youtube.com/watch?v=AAAAAAAAAAA"
        song, evidence = pipeline.intake(
            {"slug": "local-test", "source": str(source), "sourceUrl": source_url}, force=False
        )
        format_name = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=format_name", "-of", "default=nokey=1:noprint_wrappers=1",
            str(song / "audio.m4a"),
        ], check=True, capture_output=True, text=True).stdout
        self.assertIn("mp4", format_name)
        self.assertEqual(evidence["source_url"], source_url)

    def test_intake_resumes_an_empty_private_scaffold(self) -> None:
        source = self.root / "input.m4a"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.1",
            "-c:a", "aac", str(source),
        ], check=True)
        (self.root / "songs" / "resume-test" / ".transcription").mkdir(parents=True)
        song, _evidence = pipeline.intake({"slug": "resume-test", "source": str(source)}, force=False)
        self.assertEqual(song.name, "resume-test")
        self.assertTrue((song / "audio.m4a").is_file())

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
        self.assertIn('<dt>Poet</dt><dd>Writer</dd>', page)
        self.assertIn('<dt>Singer</dt><dd>Singer</dd>', page)
        self.assertIn('<span class="song-tag subject-tag">Śirḍī Sāī</span>', page)
        self.assertNotIn('class="song-attrib"', page)
        self.assertIn('"sourceLanguage": "hi"', data)
        self.assertIn('"gloss": "holy master"', data)
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

    def test_long_transcript_cache_contract_is_versioned(self) -> None:
        self.assertGreaterEqual(pipeline.LONG_TRANSCRIPT_CONTRACT_VERSION, 1)

    def test_historical_spoken_intro_evidence_is_repaired_without_an_api_call(self) -> None:
        artifact = {
            "duration": 100.0,
            "start": {"response": {"packet": {
                "decision": "trim", "boundary": 8.25, "outside_type": "spoken_intro", "confidence": "high"
            }}},
            "end": {"clip_start": 25.0, "response": {"packet": {
                "decision": "keep", "boundary": 75.0, "outside_type": "none", "confidence": "high"
            }}},
            "trim_start": 0.0, "trim_end": 100.0, "validation_errors": []
        }
        normalized = pipeline.normalize_trim_artifact(artifact)
        self.assertEqual(normalized["trim_start"], 8.25)
        self.assertEqual(normalized["trim_end"], 100.0)
        self.assertEqual(normalized["validation_errors"], [])

    def test_post_song_film_dialogue_is_a_valid_trim_target(self) -> None:
        artifact = {
            "duration": 69.081,
            "start": {"response": {"packet": {
                "decision": "keep", "boundary": 0.0, "outside_type": "none", "confidence": "high"
            }}},
            "end": {"clip_start": 0.0, "response": {"packet": {
                "decision": "trim", "boundary": 63.3, "outside_type": "post_song_film_dialogue", "confidence": "high"
            }}},
            "trim_start": 0.0, "trim_end": 69.081, "validation_errors": []
        }
        normalized = pipeline.normalize_trim_artifact(artifact)
        self.assertEqual(normalized["trim_start"], 0.0)
        self.assertEqual(normalized["trim_end"], 63.3)
        self.assertEqual(normalized["validation_errors"], [])

    def test_punctuation_only_glosses_are_not_public_words(self) -> None:
        rows = [{"id": "line", "word_glosses": [
            {"roman": "hanumāna", "gloss": "Hanuman"},
            {"roman": "॥", "gloss": "double danda"},
        ]}]
        cleaned = pipeline.clean_gloss_rows(rows)
        self.assertEqual([word["roman"] for word in cleaned[0]["word_glosses"]], ["hanumāna"])

    def test_gloss_surfaces_follow_audited_roman_tokens(self) -> None:
        lines = [{"id": "line", "roman": "mana ko agama tana"}]
        rows = [{"id": "line", "word_glosses": [
            {"roman": "man", "gloss": "mind"}, {"roman": "ko", "gloss": "to"},
            {"roman": "agam", "gloss": "inaccessible"}, {"roman": "tan", "gloss": "body"},
        ]}]
        normalized = pipeline.normalize_gloss_rows(lines, rows)
        self.assertEqual([word["roman"] for word in normalized[0]["word_glosses"]],
                         ["mana", "ko", "agama", "tana"])

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

    def test_does_not_merge_adjacent_near_refrains_with_a_real_terminal_variation(self) -> None:
        sequence = [
            {"ref": "hari-bhajana-ko-mana-le", "section": "refrain", "repeats": 3},
            {"ref": "hari-bhajana-ko-mana-re", "section": "refrain", "repeats": 2},
        ]
        timings = [{"start": 1.0, "end": 10.0}, {"start": 10.0, "end": 16.0}]
        merged_sequence, merged_timings, merged = pipeline.compress_adjacent_reader_entries(sequence, timings)
        self.assertEqual(merged, 0)
        self.assertEqual(merged_sequence, sequence)
        self.assertEqual(merged_timings, timings)

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

    def test_uniform_coarse_sequence_routes_a_failed_full_timing_pass(self) -> None:
        occurrences = [
            {"occurrence_id": "occ-000", "ref": "a", "section": "verse", "repeats": 1},
            {"occurrence_id": "occ-001", "ref": "b", "section": "refrain", "repeats": 2},
        ]
        sequence = pipeline.uniform_coarse_sequence(occurrences, 10.0)
        self.assertEqual([entry["start"] for entry in sequence], [2.5, 7.5])
        self.assertEqual([entry["repeats"] for entry in sequence], [1, 2])

    def test_fallback_grid_routes_without_voting_and_keeps_valid_partial_window_starts(self) -> None:
        occurrences = [
            {"occurrence_id": "occ-000", "ref": "a", "section": "verse", "repeats": 1},
            {"occurrence_id": "occ-001", "ref": "b", "section": "refrain", "repeats": 1},
        ]
        coarse = pipeline.uniform_coarse_sequence(occurrences, 10.0)

        def timing_report(_audio, _occurrences, chunk, _options, _destination, _cache_path, **_kwargs):
            second_pass = chunk["grid"] == "dispute-verification"
            return {
                "index": chunk["index"],
                "starts": [
                    {"occurrence_id": "occ-000", "start": 1.1 if second_pass else 1.0},
                    {"occurrence_id": "occ-001", "start": 8.1 if second_pass else 8.0},
                ],
                # A malformed sibling entry must not erase valid starts.
                "validation_errors": ["one sibling onset was malformed"] if not second_pass else [],
            }

        with mock.patch.object(pipeline, "refine_timing_chunk", side_effect=timing_report):
            sequence, _evidence, errors = pipeline.refine_all_starts(
                Path("unused.m4a"), occurrences, coarse, 10.0, mock.Mock(model="test", timeout=1),
                coarse_is_evidence=False, max_coarse_delta=10.0,
            )
        self.assertEqual(errors, [])
        self.assertEqual([entry["start"] for entry in sequence], [1.05, 8.05])
        self.assertNotIn(2.5, [entry["start"] for entry in sequence])

    def test_new_timing_evidence_can_agree_with_the_existing_verifier(self) -> None:
        # Coarse and window disagree, but one narrow check agreeing with either
        # is already the required second independent measurement.
        self.assertTrue(pipeline.corroborated_by_existing(317.66, [318.6, 317.48]))
        self.assertFalse(pipeline.corroborated_by_existing(320.0, [318.6, 317.48]))

    def test_disputed_starts_can_share_one_timing_region(self) -> None:
        values = {9: [164.7, 163.7], 13: [231.2, 230.4], 18: [285.0, 283.85]}
        groups = {}
        for index, measurements in values.items():
            groups.setdefault(int(pipeline.median(measurements) // 120.0), []).append(index)
        self.assertEqual(groups, {1: [9, 13], 2: [18]})

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

    def test_listener_audio_prefers_clean_higher_bitrate_audio_over_mp3_with_artwork_stream(self) -> None:
        song = self.root / "songs" / "cover-art-choice"
        song.mkdir()
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.1",
            "-c:a", "aac", "-b:a", "192k", str(song / "audio.m4a"),
        ], check=True)
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.1",
            "-c:a", "libmp3lame", "-b:a", "96k", str(song / "audio.mp3"),
        ], check=True)
        self.assertEqual(pipeline.preferred_listener_audio(song).name, "audio.m4a")

    def test_published_audio_uses_release_manifest_without_losing_local_development_fallback(self) -> None:
        song = self.root / "songs" / "release-audio"
        song.mkdir()
        (song / "audio.m4a").touch()
        self.assertEqual(pipeline.published_audio_sources(song), [
            {"src": "audio.m4a", "type": "audio/mp4"},
        ])
        remote = [{"src": "https://github.com/example/release-audio.m4a", "type": "audio/mp4"}]
        (self.root / "data" / "media.json").write_text(
            json.dumps({"songs": {"release-audio": remote}}), encoding="utf-8"
        )
        self.assertEqual(pipeline.published_audio_sources(song), remote)

    def test_language_hold_detects_sanskrit_from_first_pass_metadata(self) -> None:
        self.assertTrue(pipeline.is_sanskrit_first_pass({"packet": {"metadata": {"languages": ["sa"]}}}))
        self.assertFalse(pipeline.is_sanskrit_first_pass({"packet": {"metadata": {"languages": ["Hindi", "Marathi"]}}}))

    def test_language_hold_retains_transcript_without_generating_a_reader(self) -> None:
        song = self.root / "songs" / "held-song"
        (song / ".transcription" / "pipeline").mkdir(parents=True)
        raw = {"packet": {"metadata": {"languages": ["Sanskrit"]}}, "usage": {"cost": 0.01}}
        packet = pipeline.language_hold_packet(song, {"source_file": "held.m4a"}, raw, 0.0)
        saved = json.loads((song / ".transcription" / "pipeline" / "song-packet.json").read_text(encoding="utf-8"))
        self.assertEqual(packet["publication_status"], "held-language")
        self.assertEqual(saved["transcript"], raw)
        self.assertFalse((song / "data.js").exists())

    def test_intake_normalizes_music_watch_urls_to_canonical_webpage_url(self) -> None:
        metadata = {"webpage_url": "https://www.youtube.com/watch?v=Xw0yC-5bK_I", "id": "Xw0yC-5bK_I"}
        source_url = intake.canonical_source_url(metadata, "https://music.youtube.com/watch?v=Xw0yC-5bK_I")
        self.assertEqual(source_url, "https://www.youtube.com/watch?v=Xw0yC-5bK_I")

    def test_intake_filters_non_audio_files_from_download_listing(self) -> None:
        song = self.root / "songs" / "intake-audio-choice"
        song.mkdir()
        (song / "audio.webm").touch()
        (song / "audio.jpg").touch()
        (song / "audio.part").touch()
        self.assertEqual([path.name for path in intake.downloaded_audio_files(song)], ["audio.webm"])

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

    def test_source_credit_override_is_evidence_backed(self) -> None:
        value = pipeline.source_credit_override({"id": "aLWFJaF9HsU"})
        self.assertEqual(value["writer"], "Tulsīdās")
        self.assertEqual(value["singer"], "Sarita Joshi")
        self.assertEqual(value["subjectTags"], ["Hanumān"])
        self.assertTrue(value["keepOriginal"])

    def test_pinned_source_skips_secondary_official_audio_resolution(self) -> None:
        job = {"slug": "pinned", "source": "https://youtu.be/aLWFJaF9HsU", "_keep_original": True,
               "_source_metadata": {"id": "aLWFJaF9HsU", "title": "Hanuman Bahuk", "duration": 10}}
        with mock.patch.object(pipeline.ytmusic, "resolve_reference") as resolve, \
             mock.patch.object(pipeline.subprocess, "run", side_effect=RuntimeError("stop after resolution")):
            with self.assertRaisesRegex(RuntimeError, "stop after resolution"):
                pipeline.intake(job, force=False)
        resolve.assert_not_called()

    def test_media_metadata_surfaces_extractor_diagnostics(self) -> None:
        failed = subprocess.CompletedProcess(["yt-dlp"], 1, stdout="", stderr="challenge solver missing")
        with mock.patch.object(pipeline.subprocess, "run", return_value=failed):
            with self.assertRaisesRegex(RuntimeError, "challenge solver missing"):
                pipeline.media_metadata("https://example.com/song")

    def test_preflight_blocks_when_shared_openrouter_credits_are_exhausted(self) -> None:
        options = type("Options", (), {"generate_only": False, "timeout": 300.0})()
        with mock.patch.object(pipeline.gemini, "key", return_value="unused"), \
             mock.patch.object(
                 pipeline.gemini,
                 "openrouter_account_status",
                 return_value={"total_credits": 10.0, "total_usage": 10.0, "credits_exhausted": True},
             ):
            reason = pipeline.preflight_blocked_reason(options)
        self.assertIn("OpenRouter credits are exhausted", reason)

    def test_preflight_probe_failure_does_not_block_processing(self) -> None:
        options = type("Options", (), {"generate_only": False, "timeout": 300.0})()
        with mock.patch.object(pipeline.gemini, "key", return_value="unused"), \
             mock.patch.object(pipeline.gemini, "openrouter_account_status", side_effect=OSError("offline")):
            self.assertIsNone(pipeline.preflight_blocked_reason(options))

    def test_batch_result_uses_discounted_batch_usage(self) -> None:
        batch = {"usage": {"cost": 0.25, "prompt_tokens": 10}, "results": [{
            "custom_id": "one",
            "response": {"status_code": 200, "body": {
                "model": "google/gemini-3.7-flash", "choices": [],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            }},
        }]}
        result = pipeline.gemini.extract_batch_result(batch, "one")
        self.assertEqual(result["usage"]["cost"], 0.25)
        self.assertEqual(result["usage"]["completion_tokens"], 20)
        self.assertEqual(pipeline.gemini.batch_base_model("google/gemini-3.7-flash:batch"),
                         "google/gemini-3.7-flash")
        self.assertEqual(pipeline.economy_model("google/gemini-3.7-flash"),
                         "google/gemini-3.7-flash:batch")

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
                {"text": "this verse is sung: '", "word_indices": [0]},
                {"text": "The Maruts ", "word_indices": [1]},
            ], ""),
            "{0:this verse is sung: '}{1:The Maruts }",
        )
        self.assertEqual(
            pipeline.segment_english([
                {"text": "Sai", "word_indices": [0]},
                {"text": "’s name", "word_indices": [1]},
                {"text": "…", "word_indices": []},
            ], ""),
            "{0:Sai}{1:’s name}…",
        )
        self.assertEqual(
            pipeline.segment_english([
                {"text": "O Mother —", "word_indices": [0]},
                {"text": " O Mother,", "word_indices": [1]},
            ], ""),
            "{0:O Mother —}{1: O Mother,}",
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

    def test_long_merge_recognises_a_split_suffix_as_overlap(self) -> None:
        left = [{"source_text": "पूर्व पंक्ति। गरजहिं तरजहिं सहज असंका। मानहु ग्रसन चहत हहिं लंका।"}]
        right = [
            {"source_text": "गरजहिं तरजहिं सहज असंका"},
            {"source_text": "मानहु ग्रसन चहत हहिं लंका"},
        ]
        self.assertEqual(pipeline.balanced_overlap(left, right), (1, 2, 1.0))

    def test_long_merge_matches_the_same_line_across_indic_scripts(self) -> None:
        left = [{
            "source_text": "سانسوں کی مالا پہ سمروں میں پی کا نام",
            "roman": "Sā̃sō̃ kī mālā pe simrū̃ maĩ pī kā nām",
        }]
        right = [{
            "source_text": "साँसों की माला पे सिमरूँ मैं पी का नाम",
            "roman": "Sā̃sō̃ kī mālā pe simrū̃ maĩ pī kā nām",
        }]
        self.assertEqual(pipeline.balanced_overlap(left, right), (1, 1, 1.0))

    def test_long_coarse_sequence_routes_retained_only_occurrences(self) -> None:
        def line(identifier: str, roman: str) -> dict:
            return {"id": identifier, "source_text": roman, "roman": roman,
                    "kind": "verse", "partial": "none"}

        retained = [line("a", "first verse"), line("extra", "inserted refrain"), line("b", "last verse")]
        segment_lines = [retained[0], retained[2]]
        audited = {"packet": {
            "verified_lines": retained,
            "performance_order": [{"line_id": item["id"]} for item in retained],
        }, "segment_audits": [{
            "segment": {"index": 0, "core_start": 0.0, "core_end": 30.0,
                        "clip_start": 0.0, "clip_end": 30.0},
            "audit": {"packet": {
                "lines": segment_lines,
                "performance_order": [{"line_id": item["id"]} for item in segment_lines],
            }},
        }]}
        occurrences = pipeline.display_occurrences(audited["packet"])
        coarse = pipeline.long_coarse_sequence(audited, occurrences, 30.0)
        self.assertEqual(len(coarse), 3)
        self.assertEqual([entry["routing_only"] for entry in coarse], [False, True, False])
        self.assertLess(coarse[0]["start"], coarse[1]["start"])
        self.assertLess(coarse[1]["start"], coarse[2]["start"])

    def test_long_coarse_alignment_tolerates_a_reviewed_nasal_variant(self) -> None:
        occurrences = [{"roman": "Sāṅsoṅ kī mālā pe simrūṅ maiṅ pī kā nām"}]
        rebuilt = [{"line": {"roman": "Sām̐sōṁ kī mālā pē simarūm̐ maim̐ pī kā nāma"}}]
        self.assertEqual(pipeline.align_long_coarse_entries(occurrences, rebuilt), [(0, 0)])

    def test_routing_only_long_timing_child_uses_its_full_parent_clip(self) -> None:
        occurrences = [{"occurrence_id": f"occ-{index:03d}", "ref": str(index), "section": "verse"}
                       for index in range(3)]
        coarse = [
            {"start": 10.0, "routing_only": False},
            {"start": 20.0, "routing_only": True},
            {"start": 30.0, "routing_only": False},
        ]
        parent = {"index": 4, "clip_start": 0.0, "clip_end": 100.0,
                  "target_indices": [0, 1, 2]}
        child = pipeline.build_long_timing_subchunks(parent, occurrences, coarse)[0]
        self.assertTrue(child["routing_only"])
        self.assertEqual(child["grid"], "long-segment-routing")
        self.assertEqual((child["clip_start"], child["clip_end"]), (0.0, 100.0))

    def test_reconcile_segment_seams_removes_only_a_false_script_warning(self) -> None:
        def segment(index: int, source_text: str, roman: str) -> dict:
            line = {"id": f"line-{index}", "source_text": source_text, "roman": roman}
            return {"segment": {"index": index}, "audit": {"packet": {
                "lines": [line], "performance_order": [{"line_id": line["id"]}],
            }}}

        audits = [
            segment(0, "سانسوں کی مالا پہ سمروں میں پی کا نام", "Sā̃sō̃ kī mālā pe simrū̃ maĩ pī kā nām"),
            segment(1, "साँसों की माला पे सिमरूँ मैं पी का नाम", "Sā̃sō̃ kī mālā pe simrū̃ maĩ pī kā nām"),
        ]
        self.assertEqual(
            pipeline.reconcile_segment_seam_uncertainties(
                audits, ["humanly reviewed uncertainty", "segment seam 0/1 overlap score is only 0.000"]),
            ["humanly reviewed uncertainty"],
        )

    def test_hydrate_pipeline_artifacts_backfills_missing_stage_files(self) -> None:
        packet_dir = self.root / "songs" / "hydrated-song" / ".transcription" / "pipeline"
        packet_dir.mkdir(parents=True)
        packet = {
            "transcript": {"packet": {"lines": []}},
            "audit": {"packet": {"verified_lines": []}},
            "timing": {"sequence": [], "validation_errors": []},
            "glosses": {"packet": {"glosses": []}},
            "translation": {"packet": {"translations": []}},
        }
        pipeline.write_json(packet_dir / "song-packet.json", packet)
        pipeline.hydrate_pipeline_artifacts(packet_dir)
        self.assertTrue((packet_dir / "01-transcript.json").is_file())
        self.assertTrue((packet_dir / "02-transcript-audit.json").is_file())
        self.assertTrue((packet_dir / "03-timing.json").is_file())
        self.assertTrue((packet_dir / "04-glosses.json").is_file())
        self.assertTrue((packet_dir / "05-translation.json").is_file())


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Search contract: performed evidence, spelling, contextual leads, real JS input."""

import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import search_song_subjects as search


def reader(lines, tags=()):
    return {
        "SONG_META": {"title": "Example", "writer": "Krishna", "subjectTags": list(tags)},
        "SONG_LINES": {str(i): line for i, line in enumerate(lines)},
        "SONG_SEQUENCE": [{"ref": str(i), "section": "verse"} for i in range(len(lines))],
    }


class SongSubjectSearchTests(unittest.TestCase):
    def test_search_all_lyric_fields_and_strip_english_links(self):
        data = reader([{"source": "ਬਨਵਾਰੀ", "roman": "Banvārī",
                        "english": "{0:the flute }{1:player}",
                        "words": [{"roman": "Banvārī", "gloss": "Kṛṣṇa, forest garland wearer"}]}])
        for query, field in [("ਬਨਵਾਰੀ", "source"), ("banvari", "roman"),
                             ("flute player", "english"), ("Krishna", "words[0].gloss"),
                             ("krsna", "words[0].gloss")]:
            with self.subTest(query=query):
                hits = search.search_reader("song", data, query)
                self.assertEqual(len(hits), 1)
                self.assertIn(field, [match["field"] for match in hits[0]["matches"]])
        self.assertEqual(search.search_reader("song", data, "writer"), [])

    def test_performed_scope_context_and_no_metadata_matches(self):
        data = reader([{"roman": "before"}, {"roman": "Mādhav"}, {"roman": "after"}])
        data["SONG_LINES"]["unused"] = {"roman": "Govardhan Hanuman"}
        data["SONG_LINES"]["music"] = {"english": "flute"}
        data["SONG_SEQUENCE"].extend([
            {"ref": "music", "section": "instrumental"},
            {"ref": "1", "section": "refrain"},
        ])
        hit = search.search_reader("song", data, "madhav", context=1)[0]
        self.assertEqual(hit["lineId"], "1")
        self.assertEqual([line["lineId"] for line in hit["context"]], ["0", "1", "2"])
        self.assertEqual(search.search_reader("song", data, "Krishna"), [])
        self.assertEqual(search.search_reader("song", data, "Govardhan"), [])
        self.assertEqual(search.search_reader("song", data, "flute"), [])
        self.assertEqual(len(search.search_reader("song", data, "madhav")), 1)
        self.assertNotIn("Hanumān", {hit["candidateTag"] for hit in search.screen_reader("song", data)})

    def test_signal_names_scripts_and_symbols_are_review_leads(self):
        cases = [
            ("Banvārī Mādhav Murārī", "Kṛṣṇa", "epithet"),
            ("Nīl kaṇṭh", "Śiva", "epithet"),
            ("Nārāyaṇ", "Viṣṇu", "epithet"),
            ("कृष्ण", "Kṛṣṇa", "name"),
            ("ਕ੍ਰਿਸ਼ਨ", "Kṛṣṇa", "name"),
            ("ಕೃಷ್ಣ", "Kṛṣṇa", "name"),
            ("flute peacock feather", "Kṛṣṇa", "symbol"),
            ("Govardhan", "Kṛṣṇa", "narrative"),
            ("blue throat", "Śiva", "symbol"),
        ]
        for text, tag, kind in cases:
            with self.subTest(text=text):
                data = reader([{"source": text, "roman": text, "english": text}])
                before = copy.deepcopy(data)
                hits = search.screen_reader("song", data)
                self.assertTrue(any(hit["candidateTag"] == tag and hit["kind"] == kind for hit in hits))
                self.assertTrue(all(hit["requiresReview"] for hit in hits))
                self.assertEqual(data, before)

    def test_ambiguous_symbols_do_not_classify_and_existing_tags_are_excluded(self):
        data = reader([{"english": "The village boy plays a flute."}])
        hits = search.screen_reader("song", data)
        self.assertEqual({hit["candidateTag"] for hit in hits}, {"Kṛṣṇa"})
        self.assertTrue(all(hit["requiresReview"] for hit in hits))
        self.assertEqual(data["SONG_META"]["subjectTags"], [])
        data["SONG_META"]["subjectTags"] = ["Kṛṣṇa"]
        self.assertEqual(search.screen_reader("song", data), [])
        self.assertEqual(search.screen_reader("song", reader([{"roman": "Kali yuga sāīṁ"}])), [])
        self.assertEqual(search.search_reader("song", reader([{"roman": "ramble"}]), "Rāma"), [])

    def test_missing_performed_reference_fails_instead_of_incomplete_success(self):
        data = reader([])
        data["SONG_SEQUENCE"] = [{"ref": "missing", "section": "verse"}]
        with self.assertRaisesRegex(ValueError, "missing"):
            search.screen_reader("broken", data)

    def test_actual_prabh_reader_exposes_all_requested_epithets(self):
        root = Path(__file__).resolve().parents[1]
        readers = search.load_readers(root, slugs=["prabh-ju-to-kah-laj-hamari"])
        data = readers["prabh-ju-to-kah-laj-hamari"]
        for query in ["Banvari", "Madhav", "Murari", "Nil kanth", "Narayan"]:
            self.assertTrue(search.search_reader("prabh", data, query), query)
        # Tags may already have been repaired; remove them only in this copy to
        # verify the real performed text still triggers the omission screen.
        data["SONG_META"]["subjectTags"] = []
        self.assertTrue({"Kṛṣṇa", "Śiva", "Viṣṇu"}.issubset(
            {hit["candidateTag"] for hit in search.screen_reader("prabh", data)}))

    def test_check_requires_reasoned_dismissal_bound_to_full_performed_meaning(self):
        data = reader([{"english": "The village boy plays a flute.", "source": "one"},
                       {"source": "two", "english": "Another contextual line."}])
        registry = {"schemaVersion": 1, "decisions": {}}
        result = search.check_candidates({"song": data}, registry)
        self.assertFalse(result["passed"])
        self.assertEqual(result["candidateGroups"], 1)
        decision = {"decision": "dismiss", "inputHash": search.subject_input_hash(data, "Kṛṣṇa"),
                    "reason": "The passage describes a village musician, not a divine addressee."}
        registry["decisions"]["song"] = {"Kṛṣṇa": decision}
        self.assertTrue(search.check_candidates({"song": data}, registry)["passed"])
        for field, value in [("source", "changed"), ("roman", "new words"),
                             ("english", "new context"), ("words", [{"roman": "x", "gloss": "new sense"}])]:
            changed = copy.deepcopy(data)
            changed["SONG_LINES"]["1"][field] = value
            result = search.check_candidates({"song": changed}, registry)
            self.assertFalse(result["passed"], field)
            self.assertIn("stale", result["unresolved"][0]["problem"])
        decision["reason"] = " "
        self.assertFalse(search.check_candidates({"song": data}, registry)["passed"])
        # A real addition resolves the finding without a dismissal record.
        data["SONG_META"]["subjectTags"] = ["Kṛṣṇa"]
        self.assertTrue(search.check_candidates({"song": data}, registry)["passed"])

    def test_hash_ignores_metadata_and_timing_but_binds_the_candidate_identity(self):
        data = reader([{"source": "source", "english": "{0:flute}"}])
        original = search.subject_input_hash(data, "Kṛṣṇa")
        data["SONG_META"]["subjectTags"] = ["Kṛṣṇa"]
        data["SONG_TIMINGS"] = [{"start": 1}]
        data["SONG_LINES"]["0"]["english"] = "flute"
        self.assertEqual(search.subject_input_hash(data, "Kṛṣṇa"), original)
        self.assertNotEqual(search.subject_input_hash(data, "Śiva"), original)

    def test_check_cli_fails_missing_registry_and_passes_valid_disposition(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "songs" / "song"
            directory.mkdir(parents=True)
            data = reader([{"english": "a flute"}])
            (directory / "data.js").write_text("\n".join(
                f"window.{key} = {json.dumps(value)};" for key, value in data.items()))
            command = ["python3", str(Path(search.__file__)), "--root", str(root), "--check", "--json"]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(json.loads(result.stdout)["passed"])
            (root / "data").mkdir()
            (root / "data" / "subject-tag-review.json").write_text(json.dumps({
                "schemaVersion": 1, "decisions": {"song": {"Kṛṣṇa": {
                    "decision": "dismiss", "inputHash": search.subject_input_hash(data, "Kṛṣṇa"),
                    "reason": "An ordinary instrument in this passage."}}}}))
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["passed"])

    def test_complete_json_cli_scan_reads_real_js_and_never_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for slug, text in [("a", "Govardhan"), ("b", "Nīl kaṇṭh")]:
                directory = root / "songs" / slug
                directory.mkdir(parents=True)
                data = reader([{"roman": text}])
                (directory / "data.js").write_text("\n".join(
                    f"window.{key} = {json.dumps(value, ensure_ascii=False)};"
                    for key, value in data.items()))
            before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
            command = ["python3", str(Path(search.__file__)), "--root", str(root), "--json"]
            result = subprocess.run([*command, "--candidates"], capture_output=True, text=True, check=True)
            report = json.loads(result.stdout)
            self.assertEqual(report["songsScanned"], 2)
            self.assertEqual(report["performedLinesScanned"], 2)
            self.assertEqual({hit["slug"] for hit in report["results"]}, {"a", "b"})
            result = subprocess.run([*command, "govardhan"], capture_output=True, text=True, check=True)
            self.assertEqual([hit["slug"] for hit in json.loads(result.stdout)["results"]], ["a"])
            self.assertEqual(before, {path: path.read_bytes() for path in root.rglob("*") if path.is_file()})


if __name__ == "__main__":
    unittest.main()

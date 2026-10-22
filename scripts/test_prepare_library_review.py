#!/usr/bin/env python3
"""Exercise the published universe, repair routing, and editorial locks on disk."""

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import prepare_library_review as prepare


def write_js(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"window.{key} = {json.dumps(value, ensure_ascii=False)};"
                              for key, value in values.items()), encoding="utf-8")


def reader():
    return {
        "SONG_META": {"title": "Example", "credit": "Singer", "writer": "", "singer": "Singer",
                      "composer": "", "languages": ["Hindi"], "subjectTags": [],
                      "sourceStatus": "reviewed", "timingStatus": "start-only-reviewed",
                      "translationStatus": "gloss-derived literal"},
        "SONG_LINES": {"line": {"source": "मन", "roman": "mana", "english": "{0:mind}",
                                "words": [{"roman": "mana", "gloss": "mind"}],
                                "sourceWords": [{"text": "मन", "wordIndices": [0]}]}},
        "SONG_SEQUENCE": [{"ref": "line", "section": "verse", "repeats": 2}],
        "SONG_TIMINGS": [{"start": 1, "end": 5}],
    }


class LibraryReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        (self.root / ".gitignore").write_text(".transcription/\nsongs/*/audio.*\n")
        self.catalogue = []

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def add_song(self, slug, *, writer="", tags=None, data=None):
        data = copy.deepcopy(data or reader())
        data["SONG_META"].update(writer=writer, subjectTags=tags or [])
        self.catalogue.append({"slug": slug, "title": "Example", "writer": writer,
                               "singer": "Singer", "languageTags": ["Hindi"],
                               "subjectTags": tags or []})
        folder = self.root / "songs" / slug
        write_js(folder / "data.js", data)
        (folder / "index.html").write_text("<title>Example</title>")
        return data

    def commit(self):
        write_js(self.root / "data/songs.js", {"BHAKTI_SONGS": self.catalogue})
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")

    def evidence(self, slug, data, *, declared=False):
        folder = self.root / "songs" / slug
        (folder / "audio.m4a").write_bytes(b"local audio fixture")
        private = folder / ".transcription"
        (private / "pipeline").mkdir(parents=True, exist_ok=True)
        source = {"source_url": "https://www.youtube.com/watch?v=abcdefghijk"}
        if declared:
            source["providedTranslation"] = ""
        audit = {"packet": {"verified_lines": [{"id": "line", "source_text": "मन", "roman": "mana"}],
                            "uncertainties": []}}
        translation = {"packet": {"translations": [{"id": "line", "literal_english": "mind"}]}}
        timing = {"sequence": [{**data["SONG_SEQUENCE"][0], **data["SONG_TIMINGS"][0]}],
                  "validation_errors": [], "uncertain_occurrence_ids": []}
        for path, value in {
            "source.json": source, "pipeline/02-transcript-audit.json": audit,
            "pipeline/03-timing.json": timing, "pipeline/05-translation.json": translation,
            "pipeline/song-packet.json": {"source": source, "audit": audit, "translation": translation,
                                           "timing": timing},
        }.items():
            (private / path).write_text(json.dumps(value, ensure_ascii=False))

    def test_committed_catalogue_is_the_universe_and_priorities_are_deterministic(self):
        self.add_song("ordinary")
        self.add_song("kabir", writer="Kabīr")
        self.add_song("gurbani", tags=["Gurbāṇī"])
        self.commit()
        self.add_song("unpublished")
        write_js(self.root / "data/songs.js", {"BHAKTI_SONGS": self.catalogue})
        result = prepare.build_inventory(self.root)
        self.assertEqual([row["slug"] for row in result["songs"]], ["gurbani", "kabir", "ordinary"])
        self.assertEqual(result["counts"]["songs"], 3)
        self.assertEqual(result["counts"]["uniqueLines"], 3)
        self.assertEqual(result["counts"]["displayOccurrences"], 3)
        self.assertEqual(result["counts"]["performedOccurrences"], 6)
        self.assertEqual(result, prepare.build_inventory(self.root))
        self.assertTrue(all(row["reviewNeeded"] for row in result["songs"]))

    def test_locks_unknown_status_and_consistent_generated_provenance_control_export(self):
        for slug in ["locked", "unknown", "generated"]:
            data = self.add_song(slug)
            self.evidence(slug, data, declared=slug != "unknown")
        self.commit()
        locks = self.root / "data/editorial_baselines.json"
        locks.write_text(json.dumps({"version": 1, "songs": {"locked": {
            "policy": "preserve_english", "reason": "owner baseline", "englishSha256": "baseline-hash"}}}))
        result = prepare.build_inventory(self.root)
        by_slug = {row["slug"]: row for row in result["songs"]}
        self.assertEqual(by_slug["locked"]["translationLock"]["status"], "preserve_english")
        self.assertEqual(by_slug["unknown"]["translationLock"]["status"], "unknown")
        self.assertEqual(by_slug["generated"]["translationLock"]["status"], "confirmed_unlocked")
        self.assertEqual([job["slug"] for job in result["pipelineManifest"]["songs"]], ["generated"])
        self.assertTrue(by_slug["unknown"]["manifestHoldReasons"])
        self.assertEqual(by_slug["generated"]["route"], "text-only")
        self.assertFalse(result["pipelineManifest"]["audioQualified"])

    def test_defects_and_dirty_inputs_are_reported_without_mutation(self):
        data = self.add_song("broken")
        self.evidence("broken", data, declared=True)
        self.commit()
        data["SONG_LINES"]["line"]["roman"] = "maनa"
        data["SONG_LINES"]["line"]["english"] = "{oops:mind}"
        path = self.root / "songs/broken/data.js"
        write_js(path, data)
        before = path.read_bytes()
        result = prepare.build_inventory(self.root)
        row = result["songs"][0]
        self.assertTrue(row["readerChangedSinceCatalogueRevision"])
        self.assertEqual(row["route"], "audio-first")
        self.assertTrue(any("non-Latin" in reason for reason in row["mechanicalDefects"]))
        self.assertTrue(any("malformed" in reason for reason in row["mechanicalDefects"]))
        self.assertEqual(result["pipelineManifest"]["songs"], [])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(row["translationLock"]["status"], "unknown")

    def test_duplicate_catalogue_entries_fail_instead_of_disappearing(self):
        self.add_song("same")
        self.catalogue.append(dict(self.catalogue[0]))
        self.commit()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            prepare.build_inventory(self.root)

    def test_public_no_human_flag_alone_does_not_unlock_and_webm_only_cannot_resume(self):
        data = reader()
        data["SONG_META"]["humanTranslation"] = False
        self.add_song("metadata-only", data=data)
        self.evidence("metadata-only", data)
        generated = self.add_song("webm-only")
        self.evidence("webm-only", generated, declared=True)
        folder = self.root / "songs/webm-only"
        (folder / "audio.m4a").rename(folder / "audio.webm")
        self.commit()
        result = prepare.build_inventory(self.root)
        by_slug = {row["slug"]: row for row in result["songs"]}
        self.assertEqual(by_slug["metadata-only"]["translationLock"]["status"], "unknown")
        self.assertTrue(any("audio.m4a" in reason for reason in by_slug["webm-only"]["manifestHoldReasons"]))
        self.assertEqual(result["pipelineManifest"]["songs"], [])

    def test_missing_reader_and_invalid_evidence_are_accounted_and_output_is_private(self):
        self.add_song("missing")
        self.add_song("bad-evidence")
        self.commit()
        (self.root / "songs/missing/data.js").unlink()
        evidence = self.root / "songs/bad-evidence/.transcription/source.json"
        evidence.parent.mkdir(parents=True)
        evidence.write_text("{broken")
        result = prepare.build_inventory(self.root)
        self.assertEqual(len(result["songs"]), 2)
        self.assertTrue(all(row["mechanicalDefects"] for row in result["songs"]))
        with self.assertRaisesRegex(ValueError, "private"):
            prepare.write_inventory(self.root, self.root / "data", result)
        output = self.root / ".transcription/library-review"
        prepare.write_inventory(self.root, output, result)
        self.assertEqual(json.loads((output / "inventory.json").read_text()), result)

    def test_malformed_occurrences_with_declared_provenance_do_not_abort_inventory(self):
        self.add_song("valid")
        cases = {"bad-sequence": ("SONG_SEQUENCE", ["invalid occurrence"]),
                 "bad-timing": ("SONG_TIMINGS", ["invalid timing"]),
                 "null-sequence": ("SONG_SEQUENCE", None),
                 "object-timing": ("SONG_TIMINGS", {"start": 1})}
        for slug, (field, value) in cases.items():
            data = self.add_song(slug)
            self.evidence(slug, data, declared=True)
            data[field] = value
            write_js(self.root / "songs" / slug / "data.js", data)
        self.commit()
        result = prepare.build_inventory(self.root)
        self.assertEqual(len(result["songs"]), len(cases) + 1)
        by_slug = {row["slug"]: row for row in result["songs"]}
        for slug in cases:
            with self.subTest(slug=slug):
                self.assertEqual(by_slug[slug]["translationLock"]["status"], "unknown")
                self.assertTrue(by_slug[slug]["mechanicalDefects"])
                self.assertTrue(by_slug[slug]["manifestHoldReasons"])
        self.assertEqual(result["pipelineManifest"]["songs"], [])
        self.assertIn("OpenRouter", result["pipelineManifest"]["executionGate"])
        self.assertIsNone(by_slug["null-sequence"]["counts"]["performedOccurrences"])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Regression checks for public devotional-English quality."""

from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BANNED = (
    "cast a glance of mercy",
    "begging satchel",
    "hem of Your dress",
)


def load_lines(path: Path) -> dict:
    script = """const fs=require('fs'),vm=require('vm');const c={window:{}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),c,{filename:process.argv[1]});
process.stdout.write(JSON.stringify(c.window.SONG_LINES||{}));"""
    return json.loads(subprocess.run(
        ["node", "-e", script, str(path)], check=True, capture_output=True, text=True
    ).stdout)


def plain(value: str) -> str:
    return re.sub(r"\{[^:{}]*:([^{}]*)\}", r"\1", value)


class TranslationStyleTests(unittest.TestCase):
    def test_public_english_has_no_known_machine_calques(self) -> None:
        failures = []
        for path in sorted((ROOT / "songs").glob("*/data.js")):
            for line_id, line in load_lines(path).items():
                english = plain(str(line.get("english", "")))
                for phrase in BANNED:
                    if phrase.casefold() in english.casefold():
                        failures.append(f"{path.parent.name}/{line_id}: {phrase}")
                if re.search(r"\s{2,}|\s+[,.!?;:]", english):
                    failures.append(f"{path.parent.name}/{line_id}: malformed spacing")
        self.assertEqual(failures, [])

    def test_mercy_phrasing_and_user_translation_are_preserved(self) -> None:
        morning = load_lines(ROOT / "songs" / "morning-aarti" / "data.js")
        self.assertEqual(plain(morning["line-030"]["english"]), "O Sai, look upon me with mercy,")
        self.assertEqual(plain(morning["line-037"]["english"]), "Look upon me with mercy.")
        thanu = load_lines(ROOT / "songs" / "thanu-karagadavaralli" / "data.js")
        self.assertIn("cupped hands", plain(thanu["karasthala"]["english"]))
        koi = load_lines(ROOT / "songs" / "koi-hor-nahi" / "data.js")
        self.assertEqual(plain(koi["v1a"]["english"]), "My breath is going to abandon me.")
        jhoothe = load_lines(ROOT / "songs" / "jhoothe-jag-ne" / "data.js")
        self.assertIn("from the inside", plain(jhoothe["refrain_b"]["english"]))
        zara = load_lines(ROOT / "songs" / "zara-to-itana-bata-do-sai" / "data.js")
        self.assertIn("causing to take hold", plain(zara["refrain_2"]["english"]))


if __name__ == "__main__":
    unittest.main()

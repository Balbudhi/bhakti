#!/usr/bin/env python3
"""Migrate reviewed public `jīva` occurrences to the curated preserved term."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
JIVA_FORMS = {"jīva", "jiva", "jīvā", "jīvahi", "jivahi"}
ENGLISH: dict[str, dict[str, str]] = {
    "akashi-zep-ghe-re-pakhara": {
        "ka-jiva-bicara-hoi-bavara": "{0:why}{2: does the poor}{1: jīva}{3: become}{4: bewildered?}"},
    "dhoop-aarti": {"line-002": "{0:giver of peace }{1:to the jīva,}"},
    "doi-kar-teka-hei-matha": {
        "line-19-adhi-vyadhi": "{0:From mental distress, }{1:bodily illness, }{3:and the burning afflictions }{2:of worldly existence, }{4,7:ferry }{5:these inert }{6:jīvas across!}",
        "line-71-pancha-prana-jiva": "{0:With the five} {1:vital breaths} {3,4:and the feeling} {2:of my jīva,} {5:I wave} {6:the arati lamp.}"},
    "ghana-ghamand-nabh-garajat-ghora": {
        "antara-5b": "{0:as though }{2:māyā }{3:clung }{1:to the embodied jīva.}",
        "antara-7b": "{0:becomes }{1:still, }{2:as does }{3:the jīva }{5:upon attaining }{4:Hari.}"},
    "hanuman-bahuk": {
        "line-113": "{4:Beholding }{3:the ocean }{2:of disease, }{1:the monkeys }{0:of joy }{5:have lost heart; }{6:the jīva, }{7,8:like Jāmbavān, }{11:has immense }{9:reliance }{10:on you.}",
        "line-148": "{0:Goddesses, }{1:gods, }{2:demons, }{3:humans, }{4:sages, }{5:Siddhas, }{6:Nagas—}{10:all }{9:the jīvas }{7:small }{8:and great, }{11:conscious }{12:and unconscious that }{13:are—}",
        "line-198": "{8,9:Rama is the maker of }{0:māyā, }{1,2,3:jīva, Time, }{4,5:karma, }{6,7:and innate nature; }{10,11:the Vedas declare this, }{12,13,14:contemplate it as truth in the mind.}"},
    "kakad-aarti": {
        "line-073": "{0,1,2:Aarti to Sai Baba,}{5: O Lord}{4: who bestows bliss}{3: upon the jīva!}",
        "line-074": "{0,1,2:In the dust of your feet,}{3,4: grant}{5: repose}{6: to the jīva!}",
        "line-075": "{0:Repose}{1: to the jīva;}{2: aarti}{3,4: to Sai Baba!}",
        "line-097": "{2:O Lord, }{1:bestower of bliss }{0:upon the jīva!}"},
    "madhyahna-aarti": {"line-009": "{0:Aarti to }{1:Sai Baba, }{2:the bestower of bliss }{3:upon the jīva,}"},
    "shree-sai-aarti": {
        "line-refrain-1": "{0:Wave-offering of light to }{1:Sai }{2:Baba, }{5:O divine Lord }{4:who bestows joy }{3:upon the jīva,}",
        "line-refrain-2": "{2:In }{1:the dust }{0:of your feet, }{3,4:grant }{5:resting solace }{6:to the jīva, }{7:resting solace }{8:to the jīva.}"}
}


def load(path: Path) -> dict[str, Any]:
    script = "global.window={};require(process.argv[1]);process.stdout.write(JSON.stringify(window));"
    output = subprocess.run(["node", "-e", script, str(path)], check=True, capture_output=True, text=True).stdout
    return json.loads(output)


def write(path: Path, page: dict[str, Any]) -> None:
    path.write_text(
        "window.SONG_META = " + json.dumps(page["SONG_META"], ensure_ascii=False, indent=2) + ";\n\n" +
        "window.SONG_LINES = " + json.dumps(page["SONG_LINES"], ensure_ascii=False, indent=2) + ";\n\n" +
        "window.SONG_SEQUENCE = " + json.dumps(page["SONG_SEQUENCE"], ensure_ascii=False, indent=2) + ";\n\n" +
        "window.SONG_TIMINGS = " + json.dumps(page["SONG_TIMINGS"], ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8")


def normalized(value: str) -> str:
    return re.sub(r"[^a-zāīūṛṝḷṅñṭḍṇśṣḥ]", "", value.casefold())


def main() -> int:
    changed = []
    for slug, replacements in ENGLISH.items():
        path = ROOT / "songs" / slug / "data.js"
        page = load(path)
        for line_id, english in replacements.items():
            line = page["SONG_LINES"][line_id]
            line["english"] = english
            for word in line.get("words", []):
                if normalized(str(word.get("roman", ""))) in JIVA_FORMS:
                    word["gloss"] = "individual living being; embodied self"
                    word["concept_key"] = "jiva"
                    word["preserve_in_english"] = True
        write(path, page)
        changed.append(slug)
    print(json.dumps({"changed": changed, "lines": sum(len(rows) for rows in ENGLISH.values())}, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())

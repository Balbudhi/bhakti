#!/usr/bin/env python3
"""Replace high-confidence deity/name placeholder glosses with identities.

Only exact, unambiguous forms are automated. Everything else remains in the
placeholder review queue for source/grammar-specific treatment.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GLOSSES = {
    "rāma": "Viṣṇu's avatāra; husband of Sītā",
    "rām": "Viṣṇu's avatāra; husband of Sītā",
    "śāradā": "goddess of speech, learning, and inspired expression",
    "śiva": "the auspicious one; deity of transformation",
    "śiv": "the auspicious one; deity of transformation",
    "śaṅkara": "Śiva as the auspicious maker of good",
    "śaṅkar": "Śiva as the auspicious maker of good",
    "sītā": "Rāma's consort",
    "gaṇeśa": "elephant-headed remover of obstacles",
    "viṣṇu": "deity who preserves cosmic order",
    "lakṣmī": "goddess of flourishing and fortune",
    "rāvana": "king of Laṅkā and Rāma's adversary",
    "puṇḍalīka": "devotee associated with Viṭṭhala",
    "śirḍī": "town associated with Sāī Bābā",
    "īśvara": "the Lord; supreme ruler",
    "sarasvatī": "she who possesses flowing waters; Vedic goddess of speech, learning, and inspired expression",
    "sāībābā": "revered saint of Śirḍī",
    "gaṇēśa": "elephant-headed remover of obstacles",
    "vināyaka": "guide/remover of obstacles; epithet of Gaṇeśa",
    "nām": "sacred invocation; devotional recitation",
    "tukā": "Marathi poet-saint; signature-name of Tukārām",
    "tukārām": "Marathi poet-saint and author of abhanga verse",
    "nārada": "sage and divine minstrel",
    "rādhā": "Kṛṣṇa's beloved and devotee",
    "rādhikā": "Kṛṣṇa's beloved and devotee",
    "pārvatī": "Śiva's consort; mountain-born goddess",
    "brahmā": "creator deity of the cosmic triad",
    "brahma": "creator deity of the cosmic triad",
    "vaiṣṇo": "mountain goddess worshipped at Katra",
    "śraddhā": "faith; trusting devotional commitment",
    "prārabdha": "already-begun karma bearing its present result",
    "prahlāda": "devotee saved by Narasiṃha",
    "bharata": "Rāma's brother and devoted ruler of Ayodhyā",
    "kaikeyī": "Rāma's stepmother, queen of Ayodhyā",
    "daśarath": "king of Ayodhyā; father of Rāma",
    "ayodhyā": "Rāma's royal city",
    "garuḍa": "eagle mount of Viṣṇu",
    "allā": "Arabic name for God",
    "allāha": "Arabic name for God",
    "lakṣmaṇa": "Rāma's younger brother",
    "añjanā": "mother of Hanumān",
    "āratī": "ritual waving of light before a deity; the hymn sung with it",
    "nanda": "Kṛṣṇa's foster-father",
    "banamālī": "wearer of a forest-flower garland; epithet of Kṛṣṇa",
    "vanamālī": "wearer of a forest-flower garland; epithet of Kṛṣṇa",
    "kali": "the age of strife",
    "cakora": "moon-loving partridge of Sanskrit poetic imagery",
    "cātaka": "bird traditionally imagined as thirsting only for rain",
    "rāmanārāyaṇa": "Viṣṇu in the form of Rāma",
    "mīrā": "poet-saint devoted to Kṛṣṇa",
    "meera": "poet-saint devoted to Kṛṣṇa",
    "yamunā": "sacred river associated with Kṛṣṇa's Braj",
    "timi": "large sea-creature; whale or great fish",
    "akampana": "Rākṣasa warrior; literally “unshaken”",
    "pūtanā": "demoness slain by the infant Kṛṣṇa",
    "rāhu": "eclipse-causing asura who seizes sun and moon",
    "gaṇśa": "lord of the gaṇas (attendant hosts); elephant-headed remover of obstacles",
    "kālī": "the dark one; fierce form of the Goddess",
    "kailāśa": "Mount Kailāśa, Śiva's Himalayan abode",
    "vaidhī": "daughter of Videha; epithet of Sītā",
    "braja": "Kṛṣṇa's pastoral homeland",
    "vraja": "Kṛṣṇa's pastoral homeland",
    "tāṇḍava": "vigorous dance, especially Śiva's cosmic dance",
    "mūlādhāra": "“root support”; yogic centre at the base of the spine",
    "bhairavī": "fierce feminine form or consort of Bhairava",
    "nandighoṣa": "Jagannātha's chariot",
    "rāginī": "melodic mode; traditionally the feminine counterpart of a rāga",
    "śyām": "the dark-hued one; epithet of Kṛṣṇa",
    "dhrupad": "North Indian classical vocal genre",
    "tulasīdāsa": "poet of the Rāmcaritmānas",
    "rahīm": "Hindi poet and devotee ʿAbd al-Raḥīm Khān-i-Khānān",
    "aśoka": "the “sorrowless” aśoka tree; setting of Sītā's captivity",
    "asoka": "the “sorrowless” aśoka tree; setting of Sītā's captivity",
    "suṣena": "physician summoned to treat Lakṣmaṇa",
    "droṇa": "mountain of the life-restoring herb",
    "ahirāvana": "underworld demon defeated by Hanumān",
    "girijā": "“mountain-born”; epithet of Pārvatī",
}
PLACEHOLDERS = {"proper name", "proper name or untranslated term", "untranslated term"}


def canonical(value: str) -> str:
    value = value.casefold()
    return re.sub(r"[^a-zāīūṛṝḷṅñṭḍṇśṣḥ]", "", value)


def load(path: Path) -> dict:
    script = "global.window={};require(process.argv[1]);process.stdout.write(JSON.stringify(window));"
    output = subprocess.run(["node", "-e", script, str(path)], check=True, capture_output=True, text=True).stdout
    return json.loads(output)


def write(path: Path, page: dict) -> None:
    path.write_text(
        "window.SONG_META = " + json.dumps(page["SONG_META"], ensure_ascii=False, indent=2) + ";\n\n" +
        "window.SONG_LINES = " + json.dumps(page["SONG_LINES"], ensure_ascii=False, indent=2) + ";\n\n" +
        "window.SONG_SEQUENCE = " + json.dumps(page["SONG_SEQUENCE"], ensure_ascii=False, indent=2) + ";\n\n" +
        "window.SONG_TIMINGS = " + json.dumps(page["SONG_TIMINGS"], ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")


def main() -> int:
    changed = {}
    for song in sorted((ROOT / "songs").iterdir()):
        path = song / "data.js"
        if not path.is_file():
            continue
        page = load(path)
        count = 0
        for line in page.get("SONG_LINES", {}).values():
            for word in line.get("words", []):
                replacement = GLOSSES.get(canonical(str(word.get("roman") or "")))
                if replacement:
                    word["gloss"] = replacement
                    count += 1
        if count:
            write(path, page)
            changed[song.name] = count
    print(json.dumps({"songs": changed, "count": sum(changed.values())}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())

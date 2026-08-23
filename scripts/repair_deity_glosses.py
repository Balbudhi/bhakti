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
    # Recurrent Sanskrit devotional titles.  These are deliberately short
    # song-page cards: explain the word and its established referent without
    # pretending that the surrounding vernacular line has received a formal
    # grammatical parse.  See docs/SANSKRIT_POPUP_REVIEW.md.
    "datta": "“the given one”; Dattātreya, revered teacher-deity",
    "dattā": "“the given one”; Dattātreya, revered teacher-deity",
    "bhavānī": "she who belongs to Bhava (Śiva); epithet of Pārvatī",
    "gaurī": "the radiant/fair one; epithet of Pārvatī",
    "ḍamarū": "small hourglass drum associated with Śiva",
    "damarū": "small hourglass drum associated with Śiva",
    "avadhūta": "one who has shaken off worldly ties; liberated ascetic",
    "digambara": "sky-clad; one whose garment is the sky/directions",
    "digambarā": "sky-clad; one whose garment is the sky/directions",
    "pāṇḍuraṅga": "the pale/white-hued one; Viṭṭhala of Paṇḍharpur",
    "durgā": "the difficult-to-reach, protective one; form of the Goddess",
    "gaṅgā": "the sacred Ganges river, personified as a goddess",
    "gopāḷā": "protector of cows; epithet of Kṛṣṇa",
    "gopāla": "protector of cows; epithet of Kṛṣṇa",
    "rādhē": "Rādhā, beloved of Kṛṣṇa; vocative form",
    "bhagavatī": "the blessed/powerful one; title of the Goddess",
    "brahmāṇī": "Brahmā’s śakti; feminine manifestation of creative power",
    "rudrāṇī": "Rudra’s śakti; epithet of Pārvatī",
    "mahādeva": "the great god; epithet of Śiva",
    "mahādev": "the great god; epithet of Śiva",
    "keśarī": "Keśarī, Hanumān’s father",
    # Exact remaining public hover forms.  These are identities or ordinary
    # meanings, never a fallback label that leaves the listener guessing.
    "siv": "Śiva, “the auspicious one”; deity of transformation",
    "siva": "Śiva, “the auspicious one”; deity of transformation",
    "mahādēv": "mahā, “great” + deva, “god”; epithet of Śiva",
    "purandara": "Purandaradāsa, “servant of Purandara”; Kannada composer-poet devoted to Viṭṭhala",
    "ved": "Vedas; sacred knowledge texts",
    "darbha": "sacred kuśa grass used in ritual",
    "sugrīva": "su, “good” + grīva, “neck”; monkey king and Rāma’s ally",
    "nīla": "“dark-blue one”; monkey commander who helps build Rāma’s bridge",
    "nala": "“reed”; monkey commander who helps build Rāma’s bridge",
    "gada": "monkey warrior named Gada",
    "dadhimukha": "dadhi, “curd” + mukha, “face”; guardian of Sugrīva’s honey grove",
    "nisaṭha": "monkey warrior named Nisaṭha",
    "saṭha": "monkey warrior named Saṭha",
    "maheśa": "mahā, “great” + īśa, “lord”; epithet of Śiva",
    "gōpāl": "go, “cow” + pāla, “protector”; epithet of Kṛṣṇa",
    "gōvind": "go, “cow” + √vid, “find/know”; finder of cows, epithet of Kṛṣṇa",
    "murārī": "Mura + ari, “enemy”; slayer of Mura, epithet of Kṛṣṇa",
    "vaiṣṇava": "devotee of Viṣṇu",
    "holī": "spring festival of colour, bonfires, and renewal",
    "dharmadās": "dharma + dāsa, “servant”; Kabīr’s disciple and named addressee",
    "rāmā": "Rāma, “the delightful one”; Viṣṇu’s avatāra",
    "instrumental": "instrumental music",
    "sitāra": "sitar; long-necked plucked lute",
    "ālāpa": "unmetered melodic introduction",
}
# These cards are deliberately scoped to the recorded line.  Similar-looking
# words elsewhere may have another referent, so they must never be promoted to
# the global form table above.  The explanations are based on the local lyric
# context and, where relevant, the documented Odia music / named-aarti sources
# in docs/SANSKRIT_POPUP_REVIEW.md.
CONTEXTUAL_GLOSSES = {
    ("chalo-shirdi-ku-jibare-sabhien", "verse2-1", 3): "high-pitched Odia double-headed drum",
    ("e-barashe-aasi-achi", "v1-ghanta", 3): "principal percussion drum of Odissi music",
    ("e-barashe-aasi-achi", "v1-ghanta", 4): "traditional wind horn or trumpet",
    ("hanuman-bahuk", "line-025", 1): "Kuru teacher and warrior named with Bhīṣma",
    ("jai-ambe-gauri", "verse-12-line-3", 1): "named authorial voice of this ārati",
    ("jai-ambe-gauri", "verse-12-line-3", 4): "named authorial voice of this ārati",
    ("jai-durge-durgati-pariharini", "o-brahmananda-sharana-me-aayo", 1): "poet's signature-name",
    ("jai-durge-durgati-pariharini", "aayo-brahmananda-alap", 1): "poet's signature-name",
    ("jai-durge-durgati-pariharini", "aayo-brahmananda-alap", 2): "poet's signature-name",
    ("jai-durge-durgati-pariharini", "brahmananda-brahmananda-sharana-me-aayo", 1): "poet's signature-name",
    ("jai-shiva-shankar-jai-gangadhar", "vaidyanath-kedar-hare", 1): "Śiva's Himalayan shrine-name",
    ("kakad-aarti", "line-078", 2): "a name of Viṣṇu",
    ("koi-bhaje", "refrain-koi-bhaje", 5): "Viṣṇu's avatāra; husband of Sītā",
    ("koi-bhaje", "chorus-hare-krishna-hare-rama", 3): "Viṣṇu's avatāra; husband of Sītā",
    ("koi-bhaje", "chorus-hare-krishna-hare-rama", 7): "Viṣṇu's avatāra; husband of Sītā",
    ("kyun-nahin-manegi-meri-maa", "promo-mh-one", 11): "television channel name",
    ("kyun-nahin-manegi-meri-maa", "promo-mh-one", 16): "a bell",
    ("leke-bhesh-fakirika", "aur-muslim-ko-kahein-ram-ram", 1): "a Muslim; follower of Islam",
    ("main-dharu-tiharo-dhyan", "ooche-parbat-basa", 4): "mountain-shrine name of the Goddess",
    ("meri-maa-jagdambe-man-jaye", "promo-spoken", 11): "television channel name",
    ("meri-maa-jagdambe-man-jaye", "promo-spoken", 16): "a bell",
    ("namaskar-mera", "guru-nityananda", 2): "honorific personal name",
    ("sadho-rama-anupam-bani", "verse4-line1", 1): "poet's signature-name",
    ("sheronwali-kripa-kijiye", "spoken-intro-1", 28): "performer addressed by the speaker",
    ("sheronwali-kripa-kijiye", "spoken-intro-1", 42): "performer addressed by the speaker",
    ("shri-guru-prarthana", "verse-6a", 0): "route or way",
}
PLACEHOLDERS = {"proper name", "proper name or untranslated term", "untranslated term"}


def canonical(value: str) -> str:
    value = value.casefold()
    return re.sub(r"[^a-zāīūēōṛṝḷṅñṭḍṇśṣḥ]", "", value)


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
        for line_id, line in page.get("SONG_LINES", {}).items():
            for word_index, word in enumerate(line.get("words", [])):
                if str(word.get("gloss") or "").strip().casefold() not in PLACEHOLDERS:
                    continue
                replacement = CONTEXTUAL_GLOSSES.get((song.name, line_id, word_index))
                replacement = replacement or GLOSSES.get(canonical(str(word.get("roman") or "")))
                if replacement and word.get("gloss") != replacement:
                    word["gloss"] = replacement
                    count += 1
        if count:
            write(path, page)
            changed[song.name] = count
    print(json.dumps({"songs": changed, "count": sum(changed.values())}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())

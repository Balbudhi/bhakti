# Song processing standard

Every song uses the same source-to-reader contract. A YouTube link, MP3, or
M4A begins the same process regardless of language, deity, musical form, or
whether the user supplied a translation.

## Models and cost policy

- **Authoritative audio, timing, translation, and reconciliation:**
  `google/gemini-3.6-flash` through OpenRouter. Pin this explicit model for a
  review packet so a song can be reproduced later.
- **Optional preflight only:** `google/gemini-3.1-flash-lite`. It may inspect
  metadata or draft a low-risk first pass, but it never alone determines a
  public lyric, translation, sequence, or timestamp.
- Run one full-song 3.6 Flash transcription, then one full-song 3.6 Flash
  lyric-aware alignment pass. The second pass receives the entire first
  transcript and must correct omissions, order, repetitions, and first-syllable
  timings. Run extra calls only for an explicit reported uncertainty, not by
  default. Record model IDs and reported API cost in the ignored review packet.

## Required song data

Every `songs/<slug>/data.js` supplies the same globals:

```js
window.SONG_META = {
  title, credit, sourceUrl, sourceTitle, languages, subjectTags,
  translationStatus, sourceStatus
};
window.SONG_LINES = { /* line id → source text, literal/poetic English, words */ };
window.SONG_SEQUENCE = [
  { ref, section: "invocation|refrain|verse|bridge|closing|spoken|instrumental", repeats }
];
window.SONG_TIMINGS = [{ start, end }];
```

`SONG_SEQUENCE.length` must equal `SONG_TIMINGS.length`. A repeated line that
returns after another line is a new sequence entry. `repeats` only represents
immediately contiguous occurrences. A timing starts at the first audible
syllable of the displayed lyric instance, not at a chorus, backing voice, or
later repetition.

## Translation contract

1. Gemini first transcribes source-language audio and identifies language,
   script, and all audible lyric instances.
2. Gemini independently produces a literal English line translation, preserves
   poetic imagery, and creates word-level glosses. It must explicitly mark any
   uncertainty; it may not invent a connective, theological interpretation,
   or omitted line.
3. When a user supplies a translation, it is a comparison witness—not an
   automatic baseline and not disposable raw material. Gemini compares both
   versions, records every material difference, and gives a reason before a
   public wording changes.
4. The final reader may publish only the reviewed result. The ignored review
   packet preserves source metadata, raw passes, reconciliation findings,
   suggested trims, translation comparison, and model/cost record.

## Automated intake

Run from this repository:

```sh
python3 scripts/intake_bhakti_youtube.py '<youtube-url>' songs/<slug> --skip-transcription
python3 scripts/process_song_gemini.py songs/<slug>

# For an existing reviewed lyric catalogue, this is the one timing pass.
python3 scripts/align_song_lyrics.py songs/<slug>

# If a full-song timing response fails duration/order validation, use exact
# decoded windows once; this remains one timing pass, not a duplicate transcript.
python3 scripts/align_song_windows.py songs/<slug>
```

The intake downloads **audio only**, collects title/uploader/description, and
keeps all API evidence in `songs/<slug>/.transcription/`. Never create or keep
a video unless the user specifically asks. Do not automatically trim musical
introductions, interludes, or outros; only trim confirmed non-song platform
material after it is recorded in the review packet.

## Publish gate

Before publishing, validate the data syntax, render desktop and 390px mobile,
click every line, and confirm the player seeks to that line's first vocal
onset. Any missing lyric, sequence mismatch, uncertain translation, conflicting
timestamp, or unclear source credit blocks publication rather than being
silently guessed.

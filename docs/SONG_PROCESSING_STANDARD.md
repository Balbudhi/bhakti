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
  transcript/order audit. **Do not use a whole-recording response for precise
  timestamps.** One lyric-aware timing stage receives the audited catalogue in
  short contextual windows; each event records its heard opening words and
  must reconstruct the audited performance order exactly. This avoids accepting
  an approximate time in the middle of a long displayed line. Run extra calls
  only for an explicit failed gate, not by default. Record model IDs and
  reported API cost in the ignored review packet.

As checked on 2026-08-20, OpenRouter lists 3.6 Flash at $0.75/M text or audio
input and $3.75/M output. The lower-cost `google/gemini-3.1-flash-lite` lists
$0.25/M text input, $0.50/M audio input, and $1.50/M output. Use Lite only for
non-authoritative metadata/preflight work; it must not become a cheap way to
avoid the transcript, first-syllable timing, or gloss-derived translation gate.

## Required song data

Every `songs/<slug>/data.js` supplies the same globals:

```js
window.SONG_META = {
  title, singer, lyricist, composer, album, devotionalFocus,
  languages, subjectTags, translationStatus, sourceStatus
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

### Public metadata rule

Every reader uses one compact credit treatment. When the singer, writer, and
composer are the same person—or only one role is evidenced—show that person
once without role labels. Render explicit labels only when sources establish a
real distinction, for example `Sung by A · Words by B · Music by C`. Unknown
roles are omitted: absence is never rendered as a claim that another person
did the work. A devotional salutation appears only when it is specific to the
song (for example, `Jai Mātā Dī` for a Śakti song), not as generic boilerplate.
Never render local source paths, review packets, extraction notes, or source
location boilerplate on a public reader.

## Translation contract

1. Gemini first transcribes source-language audio and identifies language,
   script, and all audible lyric instances.
2. Gemini first creates a complete word-level gloss map and grammar note for
   each verified line. Only then does it produce literal English from that map.
   It must explicitly mark uncertainty; it may not invent a connective,
   theological interpretation, looser synonym, or omitted line.
3. When a user supplies a translation, it is a comparison witness—not an
   automatic baseline and not disposable raw material. Gemini compares both
   versions, records every material difference, and gives a reason before a
   public wording changes.
4. The final reader may publish only the reviewed result. The ignored review
   packet preserves source metadata, raw passes, reconciliation findings,
   suggested trims, translation comparison, and model/cost record.

## Automated intake

Run from this repository. This is the production command for both single songs
and batches; it runs independent songs concurrently while serializing the final
shared catalogue write:

```sh
python3 scripts/bhakti_pipeline.py --workers 3 --publish \
  --song song-slug='https://www.youtube.com/watch?v=…'

# Or: {"songs":[{"slug":"…","source":"/absolute/audio.m4a", ...}]}
python3 scripts/bhakti_pipeline.py --workers 3 --publish --batch intake.json
```

It performs transcript → transcript audit → precise windowed timing → word
glosses → gloss-derived literal translation → deterministic reader generation.
It writes review evidence beneath ignored `.transcription/`, and emits no
reader/catalogue output when a gate fails. It does not commit or push; after
the normal visual checks, GitHub Actions deploys a path-scoped commit.

The older component commands below are diagnostics for already-existing
readers, not a replacement for the end-to-end pipeline:

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

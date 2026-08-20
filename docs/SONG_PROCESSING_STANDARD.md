# Song processing standard

Every song uses the same source-to-reader contract. A YouTube link, MP3, or
M4A begins the same process regardless of language, deity, musical form, or
whether the user supplied a translation.

## Models and cost policy

- **Authoritative audio, timing, translation, and reconciliation:**
  `google/gemini-3.7-flash` through OpenRouter. Pin this explicit model for a
  review packet so a song can be reproduced later.
- **Optional preflight only:** `google/gemini-3.1-flash-lite`. It may inspect
  metadata or draft a low-risk first pass, but it never alone determines a
  public lyric, translation, sequence, or timestamp.
- For recordings up to 15 minutes, run one full-song transcription and one
  full-song audit that receives the first transcript. For longer recordings,
  FFmpeg selects low-energy boundaries near five-minute targets; 15-second
  overlap is included on both sides. Each segment is transcribed, then audited
  with its own first transcript, and overlap occurrences are reconciled
  deterministically. Silence is only a boundary hint, never the authority.
- Local code assigns unique display-occurrence IDs and compresses only
  immediately contiguous identical repeats. For recordings up to 15 minutes,
  one full start-only call supplies coarse onsets and one 120-second verification
  grid (15-second context overlap) supplies the independent measurement. Only
  disagreements receive a narrow retry. For longer recordings, each already-
  audited 4–6 minute segment receives one exact-lyrics, start-only timing call;
  segment overlap and strict monotonic/coverage checks catch seam failures.
  Local code derives ends from the next accepted start. The model never
  determines order, grouping, repeats, or ends.
- The normal timing path therefore uses one full pass plus one bounded
  verification pass for ordinary songs, and one call per audited segment for
  long recordings. It never sends the full recording once per line. Record
  every model ID and provider-reported cost in ignored review evidence.

As checked on 2026-08-20, OpenRouter lists 3.7 Flash at $0.375/M input and
$1.875/M output, while 3.6 Flash lists $0.75/M input and $3.75/M output. The
lower-cost `google/gemini-3.1-flash-lite` lists $0.25/M text input, $0.50/M
audio input, and $1.50/M output. Use Lite only for non-authoritative metadata
or preflight work; it must not become a cheap way to avoid the transcript,
first-syllable timing, or gloss-derived translation gate.

## Required song data

Every `songs/<slug>/data.js` supplies the same globals:

```js
window.SONG_META = {
  title, subtitle, writer, singer, composer, credit, pageCredit,
  languages, subjectTags, searchAliases, audioSources,
  timingStatus, translationStatus, sourceStatus
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
later repetition. The model supplies starts only; deterministic code sets each
end to the next start (and the final end to the recording duration).

Section kinds remain machine-readable sequencing metadata. The public reader
does not print “Invocation,” “Refrain,” “Verse,” or other section labels; those
headings interrupt the bhajan rather than helping the listening experience.

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

Store `writer`, `singer`, and `composer` separately even when the visible line
is compact. When writer and singer are distinct, the library credit orders the
writer first and singer second; the reader may name the form and writer in its
subtitle (for example, `A Vachana by Akkamahādevī`) and show the singer beneath.
Titles, forms, historical names, honorifics, and devotional names use reviewed
IAST in display text, including `Śirḍī Sāī`, `Akkamahādevī`, and `Jī`.
Contemporary people and institutions may retain their own established Latin
spelling when a native-script form has not been verified; the pipeline must
not invent diacritics from an English metadata string. Every catalogue entry
also stores `searchAliases`. The library searches the display form, ordinary
diacritic-free/common-transliteration forms, the slug, and explicit aliases,
so `Shirdi Sai`, `Akkamahadevi`, `Ishwar`, and source-preferred artist spellings
find the reviewed display form. Aliases are search metadata and are never
rendered as competing credits.

## Translation contract

1. Gemini first transcribes source-language audio and identifies language,
   script, and all audible lyric instances.
2. Gemini first creates a complete word-level gloss map and grammar note for
   each verified line. The same record must identify the grammatical agent,
   action/state, patient/complement, modifiers, negation/modality, literal
   image and agency, idiom, and cross-line relation. Only then does it produce
   English from that semantic frame. It must explicitly mark uncertainty; it
   may not invent a connective, theological interpretation, substitute
   metaphor, looser synonym, or omitted line.
   The English must be intelligible, but conventional English is not the final
   authority. Preserve supported literal strangeness, repetition,
   personification, agency, ambiguity, and concrete ritual images. A human
   translation is not rewritten merely because a smoother idiom exists.
3. When a user supplies a translation, it is the editorial baseline—not
   disposable raw material. The production translation stage copies it exactly.
   If lexical evidence appears to conflict, the line is flagged for human review
   without silently changing the approved wording.
4. The final reader may publish only the reviewed result. The ignored review
   packet preserves source metadata, raw passes, reconciliation findings,
   suggested trims, translation comparison, and model/cost record.
5. Without a human baseline, Gemini exposes materially different renderings
   when they change agency, metaphor, ambiguity, or poetic force. Such a line
   blocks publication until reviewed; trivial synonyms do not. The fidelity
   record must affirm that agency and imagery are preserved, all meaning is
   accounted for, and there are no unsupported additions.
6. A separate adversarial Gemini call reviews the completed draft. It cannot
   rewrite; it independently checks agency, imagery, completeness, additions,
   and unresolved poetic choices. Its failure or review recommendation blocks
   publication, so the drafting model never certifies itself.

Run the hidden difficult-line benchmark after changing either prompt:

```sh
python3 scripts/benchmark_translation_prompt.py
```

The automatic pass never receives the expected translations. A separate
locked-baseline pass verifies that approved human wording is copied exactly.

For a text-only editorial audit of existing readers, run:

```sh
python3 scripts/audit_translation_style.py all --workers 2
```

It reuses the reviewed hover glosses, requires exact word-index support, caches
each batch, and produces review packets without altering the public site.

## Automated intake

Run from this repository. This is the production command for both single songs
and batches; it runs independent songs concurrently while serializing the final
shared catalogue write:

```sh
python3 scripts/bhakti_pipeline.py --workers 3 --publish \
  --song song-slug='https://www.youtube.com/watch?v=…'

# Or: {"songs":[{"slug":"…","source":"/absolute/audio.m4a","searchAliases":["ordinary spelling"], ...}]}
python3 scripts/bhakti_pipeline.py --workers 3 --publish --batch intake.json
```

It performs transcript → transcript audit → exact ordered start-only timing →
focused retry when needed → word glosses → gloss-derived literal
translation → deterministic reader generation. It writes review evidence beneath
ignored `.transcription/`, and emits no reader/catalogue output when a gate
fails. It does not commit or push; after the normal visual checks, GitHub
Actions deploys a path-scoped commit.

The supported focused timing repair for an already-correct transcript is:

```sh
python3 scripts/review_timing_boundary.py <song-slug> <preceding-sequence-index>
```

It sends only the two already-verified adjacent lyrics and asks only for the
following line's first-syllable start. The older generic/window alignment
scripts are legacy diagnostics and are not publication paths.

The intake downloads **audio only**, collects title/uploader/description, and
keeps all API evidence in `songs/<slug>/.transcription/`. Never create or keep
a video unless the user specifically asks. Do not automatically trim musical
introductions, interludes, or outros; only trim confirmed non-song platform
material after it is recorded in the review packet. On the local `Morning
Aarti` benchmark, `silencedetect` finds only opening and closing silence.
Half-second RMS valleys instead route six overlapping 4–6 minute segments;
their audited lyric continuity is authoritative, not the energy minimum itself.
Internal leading/trailing overlap fragments are evidence, not separate public
performances. Long glosses and translations are cached in 40-line text batches
so a large structured response cannot truncate the whole job.

Listener audio preserves the best original stream. YouTube intake prefers its
highest-quality audio-only stream (normally Opus) and keeps the highest native
M4A/AAC stream as a compatibility fallback. Do not transcode Opus to AAC and
describe that as an upgrade. Temporary fixed-rate AAC used to normalize model
timebases is deleted after processing and is never published.

## Publish gate

Before publishing, validate the data syntax, render desktop and 390px mobile,
click every line, and confirm the player seeks to that line's first vocal
onset. Any missing lyric, sequence mismatch, uncertain translation, conflicting
timestamp, or unclear source credit blocks publication rather than being
silently guessed.

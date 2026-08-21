# Song processing standard

Every song uses the same source-to-reader contract. A YouTube link, MP3, or
M4A begins the same process regardless of language, deity, musical form, or
whether the user supplied a translation.

### Language-gated intake

For a conservatively held recording whose language is not established from
metadata, set `"holdIfSanskrit": true` in its intake row. The first audio
transcription is retained as private review evidence. If that pass identifies
Sanskrit, the pipeline writes a `held-language` packet and deliberately stops:
no audit, timing, gloss, translation, reader, catalogue entry, or public audio
is produced. The audio and first-pass evidence remain available for later
review. If it is not Sanskrit, the normal pipeline continues unchanged.

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
  immediately contiguous identical repeats. Never merge near-refrains merely
  because they differ only by a final auxiliary, vocative, pickup, pronoun, or
  other small sung variation: those are separate textual events with their own
  source form, timing, and word meanings. For recordings up to 15 minutes,
  one full start-only call supplies coarse onsets and one 120-second verification
  grid (15-second context overlap) supplies the independent measurement. Only
  disagreements receive a narrow retry. For longer recordings, each already-
  audited 4–6 minute segment receives one exact-lyrics, start-only timing call;
  segment overlap and strict monotonic/coverage checks catch seam failures.
  Local code derives ends from the next accepted start. The model never
  determines order, grouping, repeats, or ends.

### Textual-witness verification

Some sung works have an independently digitized text or a responsibly
identified transcription. Those witnesses address a specific failure mode: a
model can hear a plausible near-word in dense, archaic, or rapidly sung
diction. They never authorize the system to overwrite what this performance
actually sings.

`data/source_witnesses.json` registers only a work, its edition/witness,
stable acquisition pages, verification state, and comparison policy—not a
copied text. `scripts/source_witness.py` acquires a working copy only into the
ignored song review packet. After the first audio transcript, the audit selects
relevant witness excerpts and asks the model to listen again. It must accept a
witness reading only when the audio supports it; preserve an audible variant
and record the difference; and leave an unresolved disagreement explicitly
uncertain (which blocks generation). Private comparison reports retain page
URLs and every candidate mismatch.

The initial registered implementation is *Hanumān Bāhuk*, using a digitized
2016 *Bhāratīya Sāhitya Saṅgraha* reading edition as a public working witness,
not as a claimed critical edition. To recheck a previously transcribed
registered work without repeating the first audio pass, run:

```sh
python3 scripts/bhakti_pipeline.py --song hanuman-bahuk=EXISTING_SOURCE \
  --source-witness-audit --publish
```

That invalidates only the witness-aware audit and dependent timing/gloss/
translation artifacts; it preserves the first audio transcript and listener
master.

Before a corpus release, run the zero-cost consistency pass:

```sh
python3 scripts/audit_transcript_corpus.py
```

It checks every public source/roman/word-map/timing record against its private
audited transcript and writes only a review queue. A mismatch is never
auto-normalized: harmless romanization differences, audible performance
variants, and a possible mishearing need different evidence. The report routes
known works to the textual-witness layer; only a source reading corroborated by
the recording may change the public reader.
- A failed full-track timing response may trigger a deterministic evenly spaced
  grid, but that grid is a routing hint only: it is never accepted as onset
  evidence and never rejects an accurate clip-relative start. Each valid start
  in a structured window survives independently even when a sibling onset is
  malformed. The fallback path publishes only after a second lyric-aware
  window measurement agrees; unresolved boundary cases alone receive a narrow
  check. This prevents one bad repeated-line match from cascading across the
  rest of a song.
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
On August 20, 2026, a benchmark run against the reviewed `jab-subah-ki-aarti`
packet returned all 29 raw start candidates from 3.1 Flash Lite but failed the
monotonic/coverage gate after occurrence 16, leaving occurrences 17–28 invalid
for about $0.0029 on that call. Treat Lite timing as a cost probe only, not a
publishable start source.

## Required song data

Every `songs/<slug>/data.js` supplies the same globals:

```js
window.SONG_META = {
  title, subtitle, writer, singer, composer, credit, pageCredit,
  languages, subjectTags, searchAliases, audioSources,
  timingStatus, translationStatus, sourceStatus
};
window.SONG_LINES = { /* line id → source, sourceWords, roman, English, words */ };
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

Every non-instrumental line also has a validated `sourceWords` map. It links
each exact source-script surface token to one or more public word indices,
including compounds and sandhi. The same indices drive source-script,
romanized, and English highlighting. All three layers are selectable and
interactive: tapping, clicking, hovering, or keyboard-activating any mapped
span opens the same short meaning and outlines every corresponding span. A
reader must fail publication rather than expose an incomplete source map.
Within one song, an identical visible token in the same grammatical/devotional
role carries the same short explanation wherever it recurs. This is a local
glossary rule, not a license to flatten context: a changed gloss is permitted
only where changed syntax or imagery materially requires it, and the grammar
note must say why. A divine name or title may never degrade into its bare
Romanized spelling as a hover meaning; it must explain the identity or role.
Hover activation is registered only on devices that report a fine pointer with
real hover support. Touch devices require an intentional tap or keyboard focus,
so karaoke auto-scroll cannot open a meaning merely by moving a word beneath a
stationary touch location.
Romanized display text is normalized to precomposed standard IAST. Model output
such as `r` plus a combining ring below (`r̥`) is rewritten as `ṛ` (and the
corresponding `ṝ`, `ḷ`, and `ḹ` forms) before publication; this prevents
oversized detached marks and gives every extended glyph one consistent shape.

### Public metadata rule

Every published `SONG_META` stores `writer`, `singer`, and `composer` as
separate strings. Any unverified role is the empty string and is omitted
publicly rather than guessed, including a genuinely uncredited singer. The reader labels
the verified roles as `Poet`, `Singer`, and `Music`. When one person holds
several roles, group the labels once—for example,
`Poet · Singer · Music — Shri Chandra Bhanu Satpathy`. Never infer one role
from another merely to fill the display.

Language tags describe the text actually sung, not the singer's identity or
the script alone. A predominantly Hindi song retains a Sanskrit tag when an
audible Sanskrit invocation is part of the recording; individual source lines
use the corresponding `lang` code. Conversely, Sanskrit-derived vocabulary in
ordinary Hindi does not by itself justify a Sanskrit tag.

Album, source collection, uploader, venue, and devotional boilerplate do not
appear in a song header. The header contains only the title, evidence-backed
people and roles, subject tags, language tags, and the word-meaning hint.
Unknown roles disappear without leaving an “unknown” placeholder. Never render
local paths, review packets, extraction notes, or source-location boilerplate.
The homepage displays the verified singer beneath each title when known, then sorts
by singer, subject tags, language tags, and title.

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

For a source-backed composite liturgy, `SONG_META.sectionNotices` may add a
small title and poet notice before the relevant sequence index without
splitting the recording into separate song pages. This is a reviewed manual
exception, not model-inferred structure. `adaptedSequenceIndices` may mark an
exact displayed line as a Sai-specific adaptation when a source comparison
establishes the substitution. The badge attributes only the adaptation; it
must not imply that the original poet wrote the substituted divine name.
The reviewed implementation and source batch for the composite morning reader
are recorded in `docs/KAKAD_ARTI_SOURCES.md`.

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

### Preserved philosophical terms

`data/preserved_terms.json` is a curated allowlist derived from the Vedanta
translation standard—not from the much larger glossary manifest. A listed term
stays in canonical IAST in English, remains linked to its source-word index, and
uses the existing short hover for a context-specific explanation. A tooltip
contains the meaning only; it never repeats the already-visible term before a
parenthetical definition. Use `intellect; faculty of discernment`, not
`buddhi (intellect; faculty of discernment)`. Divine names and proper names
receive a role or contextual identity rather than the same spelling again. Bare
flattenings forbidden by the entry fail validation; `māyā` may not become only
“illusion.” An unlisted candidate is review output, never an automatic registry
addition. New entries require the preserve-or-translate decision procedure and
human approval. Bhakti deliberately does not inherit the Vedanta reader's full
grammar cards or school-by-school glossary UI.

Public English uses attested words. Rare but established English is permitted
when it is exact and understandable in context: `adamantine`, for example, is
the real adjective for diamond-like hardness and may render `vajra` imagery.
Transparent source-supported compounds such as `thunderbolt-hard` are also
permitted, with a hyphen when it improves reading. The pipeline must not invent
pseudo-Latin vocabulary or import franchise-specific fictional coinages such
as `adamantium`, `vibranium`, or `mithril`; these fail both generation and the
public reader audit. Preserved Indic philosophical terms continue to follow
the curated-term policy above rather than being disguised as English.

### Library preface and disclosure

The homepage acknowledgment is centered and follows the reader's three-level
order: Hindi source, interactive IAST, then linked literal English. Tapping,
clicking, or hovering any mapped span in any of the three layers shows its
meaning and highlights the corresponding spans in the other two. The English line is: `Countless salutations to the poets of
these bhajans and the singers and musicians who brought them to life.` The Hindi
is original site copy, not a quotation: `इन भजनों के कवियों तथा गायन-वादन से
इन्हें साकार करने वाले कलाकारों को कोटि-कोटि प्रणाम।` Here `गायन-वादन`
explicitly includes vocal and instrumental performance without implying that
instrumentalists literally “gave voice.”

The automation notice stays behind the circular `?` control rather than in the
main reading flow. It states professionally that the readers are produced by
an AI-based transcription, timing, and translation pipeline, and that any
errors belong to the pipeline rather than the poet, singer, or musician. It contains
neither an apology nor a request for corrections.

### Installed web-app updates

Adding the site to the iPhone or iPad Home Screen is the supported installation
path. The manifest uses standalone display mode and every page includes Apple's
standalone metadata. The service worker checks for a new release on load and
when the installed app becomes visible again, with a five-minute throttle. A
new worker reloads the page once after it takes control, but defers while audio
is playing. Ordinary launches do not force a reload. HTML, scripts, styles, and
reader data use network-first, cache-bypassing fetches; audio is never placed in
the application shell cache. The previous cached page remains an offline
fallback.

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

To apply an already-reviewed style batch deterministically without rerunning
audio or translation generation, use:

```sh
python3 scripts/apply_translation_style_review.py <song-slug> --apply
```

This command only rewrites `SONG_LINES[*].english` from the cached
`translation-style-audit/review.json` packet after validating the line IDs,
segment reconstruction, and word-index references. It never guesses, retranslates,
or touches timing/audio data.

## Automated intake

Run from this repository. This is the production command for both single songs
and batches; it runs independent songs concurrently while serializing the final
shared catalogue write:

```sh
python3 scripts/resolve_youtube_music_audio.py 'Rom Rom Mein Basne Wale Ram Asha Bhosle'

python3 scripts/bhakti_pipeline.py --workers 7 --publish \
  --song song-slug='https://www.youtube.com/watch?v=…'

# Or: {"songs":[{"slug":"…","source":"/absolute/audio.m4a","searchAliases":["ordinary spelling"], ...}]}
python3 scripts/bhakti_pipeline.py --workers 7 --publish --batch intake.json

# Same Gemini 3.7 Flash quality; sync audio + half-price Batch text stages.
python3 scripts/bhakti_pipeline.py --workers 7 --economy --publish --batch intake.json
```

OpenRouter Batch is text-only and rejects audio, video, image, and file content
parts ([official Batch limitations](https://openrouter.ai/docs/batch-quickstart#limitations)). Economy mode is therefore deliberately hybrid: transcription,
transcript audit, and lyric-aware timing use synchronous Gemini 3.7 Flash;
word-gloss and translation-review requests use the identical model and prompts
through Batch at 50% lower token prices. Batch inputs and results are retained
by OpenRouter for 30 days; use fast mode for fully synchronous delivery or when
that retention policy is inappropriate.
Batch submissions use a separate asynchronous concurrency cap (default 32,
`BHAKTI_BATCH_MAX_CONCURRENCY`) rather than occupying the four synchronous
Gemini slots for their full queue time. Stage dependencies remain intact, but
all independent songs/windows in a stage may wait in OpenRouter concurrently.

### Measured cost trace

The seven-song, 42.34-minute official-audio batch on 2026-08-20 finished the
synchronous path in 5m54s , including focused repairs. The
cached provider artifacts attribute the ordinary path approximately as follows:

- primary transcription: 7.5%;
- transcript-aware audit: 13.6%;
- onset alignment and corroboration: 23.6%;
- word glosses and semantic frames: 21.3%; and
- translation plus independent review: 34.1%.

This means deleting the second transcription check would risk completeness for
only a small saving. The safe large-corpus lever is `--economy`: the text-only
55.4% of the measured pipeline uses half-price Batch rates, reducing a typical
complete-song bill by about 27.7% while audio stages stay synchronous. The safe fast-path
optimization is to reuse an already-paid timing-window measurement when a
narrow recovery independently corroborates it; never demand a redundant second
narrow call merely because the narrow result disagrees with the coarse pass.
Generation from reviewed artifacts remains zero-cost with `--generate-only`.
A live strict-schema probe resolved to `google/gemini-3.7-flash`, returned the
required JSON, and cost $0.00016125 for 90 input plus 154 output tokens—exactly
half the $0.00032250 synchronous list-price calculation for the same usage.

If every review artifact already exists and only deterministic reader or
catalogue output needs refreshing, run `--generate-only --batch intake.json`.
That mode makes no provider calls and reports zero new API cost.

It performs transcript → transcript audit → exact ordered start-only timing →
focused retry when needed → word glosses → gloss-derived literal
translation → deterministic reader generation. It writes review evidence beneath
ignored `.transcription/`, and emits no reader/catalogue output when a gate
fails. It does not commit or push; after the normal visual checks, GitHub
Actions deploys a path-scoped commit.

For hosted intake on the public repository, use the `Intake Bhakti Songs`
`workflow_dispatch` workflow on `main`. It accepts one URL per line and exposes
an explicit mode selector: `economy` (the default) uses synchronous audio stages
plus half-price OpenRouter Batch for text-only stages; `fast` keeps every stage
synchronous when completion time matters more. It commits generated
readers with `GITHUB_TOKEN` and deploys Pages in the same workflow. A GitHub
hosted job has a 5.5-hour ceiling even though OpenRouter permits a batch to take
up to about 24 hours, so use smaller owner-dispatched groups for economy mode
rather than one enormous hosted submission.

The hosted control surface is GitHub itself; do not build a second login or a
public submission form. The job runs only when `github.actor` equals the
repository owner. It accepts at most 50 publicly downloadable HTTPS media URLs,
rejects embedded credentials and any hostname resolving to local, private,
reserved, or otherwise non-global addresses, restricts workers to 1–7, has no
public event or webhook trigger, and reads the OpenRouter key from an encrypted
repository secret. Public `yt-dlp`-supported media URLs share the same path. A public visitor may view the repository but
cannot dispatch a billable run. To use it, open **Actions → Intake Bhakti Songs
→ Run workflow**, paste one link per line, choose the worker count and processing
mode, and run it.
When a source description is unstructured but independently establishes roles,
record a reviewed source-ID override in `data/source_credits.json`; the one-link
hosted intake then receives the verified title, poet, singer, music, language,
and subject tags without guessing from an uploader name.

Subject tags may be both broad and specific when the source supports both. For
example, a verified Vaiṣṇo Devī performance carries both `Śakti` and
`Vaiṣṇo Devī`; a generic Devī song must not acquire the specific tag by guess.
Public tags use reviewed IAST, while ordinary spellings such as `Vaishno Devi`
remain searchable aliases.

As tested on August 21, 2026, YouTube rejects GitHub-hosted runner IPs with
`Sign in to confirm you're not a bot` before metadata or audio extraction. The
current nightly yt-dlp, EJS solver, Node 24, and cookie-free `web_embedded`
client do not remove that IP-level gate. Do not upload a personal YouTube
session cookie to GitHub as a workaround. The hosted path remains fully usable
for public direct media URLs; YouTube requires the local fetch stage or a future
separately trusted downloader with suitable egress.

### Direct Google provider

Provider choice changes transport and billing only; it must never change the
prompts, schemas, audio, reasoning effort, retries, uncertainty handling, or
publication gates. OpenRouter remains the default:

```sh
BHAKTI_GEMINI_PROVIDER=openrouter python3 scripts/bhakti_pipeline.py --publish --url URL
```

Direct Google uses its official OpenAI-compatible audio and structured-output
endpoint. Supply the key through `GEMINI_API_KEY`, or store it in
`~/Dev/gemini.key` with mode `0600`:

```sh
BHAKTI_GEMINI_PROVIDER=google python3 scripts/bhakti_pipeline.py --publish --url URL
```

The client strips OpenRouter's `google/` model prefix only at the direct Google
transport boundary and maps reasoning effort to Google's compatible top-level
field. A direct request still targets Gemini 3.7 Flash. Direct Google Batch is
deliberately rejected rather than silently approximated; use OpenRouter
`--economy` for the established hybrid economy path. Before changing the
production default, run a short audio plus strict-schema probe and compare its
JSON, model resolution, timing behavior, and validation result with the
OpenRouter path.

The August 21, 2026 live probe used a 16-second Hindi song excerpt and the same
strict JSON schema on both transports. OpenRouter resolved to Gemini 3.7 Flash,
returned the exact expected source and Roman line, and cost `$0.00197025`.
Google rejected the request before inference with `429 RESOURCE_EXHAUSTED`:
the calling Google project had no available quota.
That is a billing-state failure, not a model-quality result. The hosted workflow
is pinned to OpenRouter until a future direct key successfully passes:

```sh
python3 scripts/probe_gemini_provider.py AUDIO --start SECONDS \
  --source 'SOURCE LINE' --roman 'ROMAN LINE'
```

The direct client treats this specific depleted-prepay response as permanent
and fails immediately rather than spending a minute retrying it. Do not unlink
billing, buy credits, or switch the production provider automatically; those
are explicit account/billing decisions.

The published listener audio is never replaced for provider compatibility.
Because Google's documented direct audio formats omit WebM/Opus and M4A
containers, the direct transport makes a temporary in-memory mono MP3 payload
at 112 kb/s; Gemini documents that it internally reduces audio resolution far
below that rate. The conversion creates no persistent duplicate, does not
change the song timeline, and is bounded so the base64 request stays below the
20 MB inline limit. Longer recordings are segmented before transport.

Seven songs may progress concurrently without producing an uncontrolled API
burst. A process-wide scheduler independently caps Gemini requests at three,
starts them at least 350 ms apart, prefers OpenRouter's highest-throughput
compatible provider, allows provider fallbacks for the same model, and honors
the server's `Retry-After` header before bounded backoff. This keeps the Mac and
local stages busy while respecting upstream rather than using a blunt two-song
limit.

The supported focused timing repair for an already-correct transcript is:

```sh
python3 scripts/review_timing_boundary.py <song-slug> <preceding-sequence-index>
```

It sends only the two already-verified adjacent lyrics and asks only for the
following line's first-syllable start. The older generic/window alignment
scripts are legacy diagnostics and are not publication paths.

The intake downloads **audio only**, collects title/uploader/description, and
keeps all API evidence in `songs/<slug>/.transcription/`. Never create or keep
a video unless the user specifically asks. You may pass a `music.youtube.com`
watch/share URL directly; yt-dlp resolves it to the canonical `youtube.com/watch`
URL before download, and the intake keeps the best original listener audio
stream plus an `audio.m4a` compatibility copy. Do not manually rewrite the URL
to some other host just to make it work. Do not automatically trim musical
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
timebases is 128 kb/s, deleted after processing, and never published; it does
not change the listener master or claim to improve it.
If a provider returns an empty response to an otherwise valid full-song
transcription, the pipeline retries that exact request once with a temporary
metadata-free mono MP3. This is a transport fallback only, never a substitute
for the preserved listener source or a reason to relax the JSON gate.

High-quality listener audio is published as stable assets on the repository's
`media-v1` GitHub Release, not committed to Git and not included in the Pages
artifact. `data/media.json` is the public URL map; reader generation prefers
that map and falls back to local files only for development. Run
`python3 scripts/publish_media_release.py` before the final reader rebuild.
This separation is required because GitHub Pages caps the published site at
1 GiB, while the growing audio library is larger and must retain its original
quality. The owner-only intake workflow uploads or replaces release assets,
rebuilds readers with their stable URLs, and commits only HTML/JS/metadata.

For YouTube-family sources, first resolve to the canonical official-audio track.
`scripts/resolve_youtube_music_audio.py` accepts a `music.youtube.com` URL, a
plain YouTube/youtu.be URL, or a search query. It canonicalizes watch URLs to
`https://www.youtube.com/watch?v=ID`, inspects the provided track, and keeps it
only when the metadata itself shows official-audio markers such as
`Provided to YouTube by`, `Auto-generated by YouTube`, or a `- Topic` channel.
Otherwise it searches YouTube Music, expands album browse results, and fails
closed if more than one candidate remains materially plausible. Use its
`resolved_url` for `yta` or the pipeline; the production pipeline then performs
explicit `yt-dlp -f bestaudio` intake plus the native AAC compatibility copy so
listener audio quality stays deterministic.

## Publish gate

Before publishing, validate the data syntax, render desktop and 390px mobile,
click every line, and confirm the player seeks to that line's first vocal
onset. Any missing lyric, sequence mismatch, uncertain translation, conflicting
timestamp, or unclear source credit blocks publication rather than being
silently guessed.

# Bhakti

A static, offline-capable library of devotional songs. Every song page carries the
lyrics in their original script, an IAST transliteration, a literal English
translation, and a hover-or-tap gloss for each individual word — all synchronised to
the recording, so the line you are reading is the line being sung.

**Live site: [bhakti.eeshan.xyz](https://bhakti.eeshan.xyz)** · 229 songs · no build
step, no framework, no tracking.

## What a song page shows

- **Three aligned rows per line** — source script, IAST, literal English — in that
  order, so a reader who knows none of the script can still follow the sound and the
  sense.
- **Word-level meanings.** Every IAST token has a literal gloss. Hovering or tapping a
  word highlights its counterparts in the other two rows and shows the meaning.
- **First-syllable seeking.** Tapping a line seeks to the exact moment that line's
  first syllable is sung, not to an approximate chorus onset.
- **True performance order.** A refrain that returns is a separate entry with its own
  timing; repetition is preserved rather than collapsed.
- **Evidenced credits only.** Poet, singer, and composer are shown separately only
  where the distinction is actually established by a source. Unknown roles are omitted
  rather than guessed at or padded.
- **Restrained IAST.** Reviewed devotional terms, honorifics, and titles are shown in
  IAST. Terms with no adequate English equivalent (`māyā`, for example) stay in IAST
  with a contextual gloss instead of being flattened.

## Library features

- Search across titles, credits, languages, and subject tags. Diacritics are folded,
  so `Vaishno Devi` finds `Vaiṣṇo Devī`.
- A play queue with drag reordering, shuffle, and shareable queue links — the whole
  queue is encoded in the URL, so a link restores someone else's exact listening order.
- Installable as a web app. On iPhone or iPad use Safari's **Share → Add to Home
  Screen**; the manifest then opens Bhakti standalone.
- A service worker caches the app shell for offline browsing and reading. It picks up a
  newly deployed release when the app is opened or resumed, and reloads only once the
  new version takes control — never mid-playback.

## Repository layout

```
index.html                 Library page
songs/<slug>/index.html    Generated song page
songs/<slug>/data.js       SONG_META, SONG_LINES, SONG_SEQUENCE, SONG_TIMINGS
assets/                    Stylesheets, client JavaScript, icons
data/songs.js              Generated catalogue used by search and the queue
data/media.json            Audio release manifest (URL + SHA-256 per song)
data/preserved_terms.json  Allowlist of terms that stay in IAST in English
scripts/                   Content pipeline, audits, and tests (Python + Node)
docs/                      Design and content standards
```

Audio is not stored in the repository. Listener audio is published as GitHub release
assets and referenced from `data/media.json` with a SHA-256 per file; the pages load it
from there.

## How the song pages are produced

Song pages are generated, not hand-written. The pipeline in `scripts/` transcribes a
recording, times it, glosses it, and translates it using a large language model, then
emits deterministic `data.js` and HTML. This is stated plainly on the site itself, in
the library's "About these songs" panel.

The stages are deliberately separated so that each one can be checked:

1. Transcription of the complete recording.
2. An independent transcription and running-order audit.
3. Exact ordered start-only timing, with a bounded verification pass.
4. Literal word glosses and grammar notes.
5. An English translation derived from those glosses — never written first and
   back-fitted.
6. An independent adversarial translation review that can reject but cannot rewrite.
7. Deterministic page and catalogue generation.

Publication is gated. Missing, reordered, duplicated, non-increasing, or
out-of-duration timings; unresolved transcription uncertainty; unmappable glosses; or a
translation that changes agency, loses imagery, or adds unsupported material all block
the release rather than being smoothed over. A supplied human translation is treated as
the editorial baseline and copied exactly.

`docs/SONG_PROCESSING_STANDARD.md` is the full content contract, and
`docs/DESIGN_STANDARD.md` is the visual and interaction contract for the site.

## Running the site locally

The site is entirely static. Serve the repository root over HTTP — opening
`index.html` from the filesystem will not work, because the pages use absolute
`/assets/...` paths and a service worker.

```bash
python3 -m http.server 8000
```

Then open `http://localhost:8000`. Audio streams from the public release, so playback
needs a network connection; everything else works offline once cached.

## Tests

Python tests use `unittest`, and the client-side tests run under Node with no
dependencies.

```bash
python3 -m unittest discover -s scripts -p 'test_*.py'
```

```bash
node scripts/test_queue.js && node scripts/test_library_search.js
```

Before a content release, the repository's own audits should pass:

```bash
python3 scripts/audit_bhakti_contract.py && python3 scripts/audit_audio_quality.py
```

## Generating a new song page

Generation calls a paid model API and requires your own key. Nothing in this repository
contains or requires a maintainer's credentials.

Provide a key through the environment (preferred) or through an owner-only file with
mode `0600`:

```bash
export OPENROUTER_API_KEY='your-key'
```

```bash
python3 scripts/bhakti_pipeline.py --workers 7 --publish \
  --song song-slug='https://example.com/recording.m4a'
```

Useful variants:

- `--batch intake.json` processes a manifest of songs, running independent songs
  concurrently.
- `--economy` routes the text-only stages through batch pricing while audio stages stay
  synchronous; identical model, prompts, and gates.
- `--generate-only` rebuilds pages and the catalogue from already-reviewed artifacts
  with no API calls and no cost.

`ffmpeg` and `yt-dlp` must be on `PATH` for audio intake. Review artifacts are written
under an ignored `.transcription/` directory and are never published.

## Deployment

Pushing to `main` deploys the site to GitHub Pages via
`.github/workflows/deploy-pages.yml`. A second workflow, `Intake Bhakti Songs`, runs the
same pipeline on a hosted runner; it is `workflow_dispatch`-only, restricted to the
repository owner, and accepts only public HTTPS media URLs. It has no public form,
issue, comment, or webhook trigger, and reads its API key from an encrypted repository
secret — a visitor can read the repository but cannot dispatch a billable run.

## Contributing

Corrections are the most valuable contribution. A mistranscribed word, a misplaced line
start, a translation that flattens an image, or a wrong credit — please open an issue
with the song slug and the specific line.

If you are changing the site's UI, read `docs/DESIGN_STANDARD.md` first; if you are
changing content or the pipeline, read `docs/SONG_PROCESSING_STANDARD.md`. Song pages
under `songs/` are generated output — fix the generator or the reviewed source data
rather than editing a page by hand.

## License and attribution

The code in this repository — everything under `scripts/` and `assets/`, and the page
templates — is released under the [MIT License](LICENSE).

The MIT License does not extend to the devotional material. The songs, their recordings,
and any supplied human translations belong to their poets, composers, performers, and
publishers. They are presented here for study and devotional use with attribution to
everyone the sources establish, and no ownership over them is claimed. If you hold
rights to a recording or text here and would like it changed or removed, please open an
issue.

> इन भजनों के कवियों तथा गायन-वादन से इन्हें साकार करने वाले कलाकारों को कोटि-कोटि प्रणाम।
>
> *Countless salutations to the poets of these bhajans and the singers and musicians who
> brought them to life.*

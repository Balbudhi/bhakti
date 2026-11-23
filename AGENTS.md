# Bhakti song-page contract

## Design authority

`docs/DESIGN_STANDARD.md` is the maintained visual and interaction contract.
Read and apply it before changing public UI, responsive behavior, controls,
icons, disclosure, player layout, or motion. New features reuse the established
language before introducing another surface or component style.

This repository is a public static song library deployed at
`https://bhakti.eeshan.xyz`. Its source/deployment repository is not a public
product URL. Do not expose review packets, local paths, extraction notes, or
generic provenance filler on a song page page.

## Reuse completed translation reviews

Before repeating a library-wide translation audit, consult
`data/translation-review-status.json` and its linked report. Reuse a `finished`
mark when the reader file SHA-256 matches; if it differs, inspect the actual
changes before deciding what needs review. Preserve `owner_protected` English
exactly using `data/editorial_baselines.json`. Focus `needs_source_review` work
on its recorded open definitions. A concrete new defect or source can reopen an
affected passage; a completion mark is not evidence against the owner’s report.
The marks cover translation review, not a new listening or exhaustive word-analysis audit.

## Adding or revising songs

Follow `docs/ADD_A_SONG.md`: one page, with `scripts/song.py` for every mechanical step.
The agent writes the text, the word meanings and the English itself and looks things up
when needed. Do not read the rest of `docs/` first, and do not start the older paid
pipeline, a library-wide audit, or a chain of review agents for an ordinary song.

The older model pipeline (`python3 scripts/bhakti_pipeline.py --batch intake.json`,
documented in `docs/TRANSLATION_WORKFLOW.md`) remains for hosted intake and for audio whose
words cannot be established otherwise. Always set `--budget-usd`. Its gates still apply to
its own output; `--generate-only` makes no API calls. OpenRouter with
`google/gemini-3.7-flash` is its baseline; credentials come only from the key file named by
`OPENROUTER_API_KEY_FILE` and are never printed, copied, committed or put in arguments. Keep raw
evidence private. For a YouTube link, resolve the official audio first
(`python3 scripts/resolve_youtube_music_audio.py <url-or-query>`) and keep the original
audio-only stream; never transcode a lossy source and call it better.

Semantic and audio shuffle assessments are required for every new song (`song.py release`
runs them). Do not bypass a hold or invent musical labels.

## Song-page schema and content rules

Generated `data.js` must define `SONG_META`, `SONG_LINES`, `SONG_SEQUENCE`,
and `SONG_TIMINGS`. Every lyric line has source script → IAST → literal English
in that order; each IAST token must have a literal hover gloss. A general
translation is written **after** and constrained by the word map, not before it.
It must remain intelligible without erasing purposeful literal strangeness.
Read adjacent lines together and preserve repetition, personification, agency,
ambiguity, and concrete devotional images. A supplied human translation is the
editorial baseline and must not be rewritten merely because another phrasing
sounds smoother or more conventional.

`SONG_SEQUENCE` is the actual performance order. A line returning after any
other line needs a separate entry. Its timing begins at that instance’s first
audible syllable, whether lead, response, duet, choir, pickup, or invocation.
Never use a later chorus onset for an earlier displayed line. Only immediate,
identical contiguous performances may be represented as a repeat.

Use standard section kinds only: `invocation`, `refrain`, `verse`, `bridge`,
`closing`, `spoken`, or `instrumental`. These are internal processing metadata;
do not render section labels on the song page. Do not invent public roles. Every
shown name carries its role (Poet, Singer, Composer), even a single name; a bare name
does not tell the reader who it is. Credit the poet the tradition names and never
write "Traditional" as a credit or label. Omit unknown roles without calling
attention to the absence.

Display reviewed Indic titles, devotional terms, historical names, and
honorifics in IAST. Keep an established contemporary artist/institution spelling
when no native-script form has been verified; never manufacture diacritics from
English metadata. Internal search must also match ordinary spellings through
automatic folding plus optional `searchAliases`; those aliases are not visible.

Translate ordinary words and philosophical concepts into contextually precise
English, including short phrases where necessary. Keep genuine proper names
and explain their evidenced meaning or relationship in the linked gloss.
`data/preserved_terms.json` retains legacy metadata, not a mandate to leave new
English opaque. Existing owner-approved English remains locked. Do not flatten
`māyā` to bare “illusion” everywhere or replace any term globally by spelling.
`data/bhakti_lexicon.json` supplies cited, language-scoped candidate senses;
choose by grammar and the whole passage. The chosen primary gloss and English
must agree. Dictionary alternatives are not interchangeable popup definitions.
Do not import Vedanta's full indexing engine, grammar cards or expositions.

## Release checks

- Run `python3 scripts/audit_bhakti_contract.py`, `python3 -m py_compile
  scripts/*.py`, and `git diff --check`. Existing migration-needed song pages are
  an explicit content task, never an excuse to omit required fields from a new
  song.
- Run `python3 scripts/audit_youtube_trims.py` before release. A high-confidence
  verified platform/spoken/promotion intro without an applied trim is a release
  failure. New intake trims before any transcript or timing stage; historical
  repairs remove the spoken occurrence and shift retained timestamps by the
  reviewed offset.
- Run `python3 scripts/audit_shuffle_profiles.py` before release. It checks the
  current reader/media identities, qualification, and paired catalogue/profile
  revision without API calls; direct reader edits must pass the same gate.
- Use only the Codex in-app Browser for desktop and 390px mobile visual checks.
  Do not use Chrome, Zen, external extensions, Playwright CLI/MCP, or a global
  tool removal. Test the exact first-syllable seek for every song page line.
- Stage exact paths only; inspect the staged diff; commit and push only your
  own scoped files. GitHub Pages deploys `main` automatically.

# Bhakti reader contract

This repository is a public static song library deployed at
`https://bhakti.eeshan.xyz`. Its source/deployment repository is not a public
product URL. Do not expose review packets, local paths, extraction notes, or
generic provenance filler on a reader page.

## One-command production pipeline

The API production model is `google/gemini-3.6-flash` through OpenRouter. It
uses the Dev-wide owner-only key file documented in `/Users/eeshan/Dev/AGENTS.md`.
Never read, print, commit, or copy that key. Local ASR research is optional and
must never silently replace this production path.

For one or more local audio files or source URLs, use:

```sh
python3 scripts/bhakti_pipeline.py --workers 3 --publish \
  --song song-slug='https://www.youtube.com/watch?v=…'
```

For a larger batch, use a JSON manifest:

```json
{"songs":[{"slug":"song-slug","source":"/absolute/song.m4a","title":"…","writer":"…","singer":"…","languages":["Hindi"],"subjectTags":["Śirḍī Sāī"]}]}
```

```sh
python3 scripts/bhakti_pipeline.py --workers 3 --publish --batch intake.json
```

The pipeline preserves audio-only source input, then performs distinct stages:

1. full-song transcription;
2. independent transcription/order audit;
3. one lyric-catalogue timing pass in short contextual windows;
4. literal word glosses and grammar notes;
5. literal English derived from those glosses only; and
6. deterministic `data.js`, reader HTML, and catalogue generation.

It blocks publication for unresolved transcription uncertainty, timing-order
mismatch, non-boundary unmatched vocals, low-confidence/unanchored first
syllables, source/IAST omissions, non-mappable glosses, or uncertain literal
translations. It never fixes those errors by guessing. Do not replace this
with manual song-page construction or separate generic audio passes.

For an existing reader whose wording needs review but whose audio must not be
rerun, use `python3 scripts/retranslate_bhakti.py --workers 3 all`. It creates
an ignored, text-only gloss-first comparison packet and does **not** overwrite
public translations until each material change is reviewed.

## Reader schema and content rules

Generated `data.js` must define `SONG_META`, `SONG_LINES`, `SONG_SEQUENCE`,
and `SONG_TIMINGS`. Every lyric line has source script → IAST → literal English
in that order; each IAST token must have a literal hover gloss. A general
translation is written **after** and constrained by the word map, not before it.

`SONG_SEQUENCE` is the actual performance order. A line returning after any
other line needs a separate entry. Its timing begins at that instance’s first
audible syllable, whether lead, response, duet, choir, pickup, or invocation.
Never use a later chorus onset for an earlier displayed line. Only immediate,
identical contiguous performances may be represented as a repeat.

Use standard section kinds only: `invocation`, `refrain`, `verse`, `bridge`,
`closing`, `spoken`, or `instrumental`. These are internal processing metadata;
do not render section labels on the song page. Do not invent public roles. Show a
compact single credit when one person is evidenced; label singer/writer/music
only when a real distinction is evidenced. Omit unknown roles without calling
attention to the absence.

## Release checks

- Run `python3 scripts/audit_bhakti_contract.py`, `python3 -m py_compile
  scripts/*.py`, and `git diff --check`. Existing migration-needed readers are
  an explicit content task, never an excuse to omit required fields from a new
  song.
- Use only the Codex in-app Browser for desktop and 390px mobile visual checks.
  Do not use Chrome, Zen, external extensions, Playwright CLI/MCP, or a global
  tool removal. Test the exact first-syllable seek for every reader line.
- Stage exact paths only; inspect the staged diff; commit and push only your
  own scoped files. GitHub Pages deploys `main` automatically.

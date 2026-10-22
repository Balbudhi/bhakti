# Whole-library repair task

## Goal

Repair and publish the entire Bhakti song library with complete performed lyrics,
accurate timings, intelligible literal poetic English, contextual word meanings,
correct interactive mappings, and minimal useful devotional tags. Prioritize
Kabīr omissions and the outstanding Gurbāṇī review; complete the four prepared
additions. Do not claim that pipeline execution alone establishes correctness.

## Owner requirements

- Compare the actual audio for missing words, clipped material, repetitions and
  first-syllable starts. Printed lyrics and cached transcripts are evidence to
  compare, not proof that every word was sung or captured.
- Choose the right meaning for the passage before drafting English. Preserve
  grammatical agency, negation, relationships, imagery, repetition and poetry.
  Improve confusing grammar without adding or removing meaning.
- Translate ordinary words and philosophical concepts into intelligible English,
  using short contextual phrases where necessary. Retain genuine proper names;
  explain their evidenced meanings or relationships in the clickable gloss.
- The selected gloss, English rendering and highlighted source words must agree.
  Alternative senses are useful evidence, not permission to select arbitrarily.
  Reuse a rendering when language, sense and context agree, not merely spelling.
- Preserve supplied human translations. Aruṇācala Akṣaramaṇamālai and Koī Hor
  Nahī Hai Merā are editorial references; investigate source/gloss conflicts
  separately rather than silently rewriting the owner's English.
- Use modest dictionary assistance and automated preparation/review. Defer the
  Vedanta project's full indexed language-model and grammar architecture.
- Keep tags minimal and grounded in the song. Preserve the existing reader UI,
  scripture-section styling and linked word interactions.
- Check the current Gemini options rather than assuming a newer model is better.
  Restore the usable OpenRouter route; account credits have been replenished. Any batch must have an explicit
  bounded reservation and retained response evidence.
- Review corrections autonomously and publish verified batches; keep uncertain
  readings and unfinished work explicit. Do not require routine user approvals.

## Task list and current evidence

- [x] Inventory the committed library: 254 songs, 6,546 stored lyric lines,
  9,979 display blocks and 13,526 performed occurrences including repeats.
- [x] Identify 17 Kabīr-associated recordings; their expanded public lyrics match
  stored audits. This does not establish completeness against audio.
- [x] Inspect the owner's two editorial references and Vedanta translation rules.
- [x] Prepare five cited Hindi dictionary entries with 19 unselected senses.
- [x] Independently review 20 guarded wording/spelling proposals across three songs.
- [x] Implement and independently review pipeline cache, contextual-sense and
  dictionary integration; resolve the identified review defects.
- [ ] Publish the verified pipeline and preparation changes.
- [x] Finish the deterministic repair inventory and enforce saved owner baselines.
- [x] Update the processing instructions and restored provider configuration.
- [ ] Apply, inspect and publish the 20 reviewed textual corrections.
- [ ] Qualify Gemini 3.7 Flash versus 3.8 Flash on representative audio and
  translation cases after credits are available; use stronger models only when
  their measured quality warrants their cost.
- [ ] Review every published song's source, glosses, English, mappings and tags;
  route actual lexical defects through fresh gloss reconstruction.
- [ ] Verify missing lyrics, clipping, repetitions and timing against recordings.
- [ ] Complete and publish the four prepared new recordings and outstanding
  Gurbāṇī audio repairs; retain the existing scripture citations and styling.
- [ ] Visually verify corrected readers in the Codex in-app Browser and confirm
  deployed files match reviewed changes.

## Current step and next step

Current: all three integration findings are resolved. Fresh production output
must contain complete fidelity/review evidence; a cache cannot bypass that gate.
The two saved owner baselines protect 136 lines even if the current reader is
changed. Twenty reviewed corrections have been applied locally and inspected
on desktop and 390px mobile. Seven mixed-script repairs and Sundarakāṇḍa marker
mapping fixes are in review; preserve unrelated dirty intake work.

Credits were replenished: the read-only check showed about $29.99 available.
The first bounded Gemini comparison request returned a documented MAX_TOKENS
failure: its 16,384-token allowance was consumed mainly by reasoning. It cost
$0.06263025 and produced no usable complete transcript. No remaining requests
were launched on that configuration. The comparison is being corrected to use
the production audio output allowance, within the cumulative $2 experiment cap.
No model winner, fresh audio verification, or full-library accuracy is claimed.

Next: publish the verified infrastructure and first editorial batch, complete
model qualification, then process audio and text repair batches. The goal remains
the complete library and four additions, not these preliminary fixes.

The previous Gurbāṇī evidence and selected additions remain documented in
`GURBANI_REVIEW_TASKS.md`. Private preparation output is under
`.transcription/library-review/`; it is not public song-page content.

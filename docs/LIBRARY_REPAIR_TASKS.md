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
- [x] Publish the verified pipeline and preparation changes (`b1c90598`).
- [x] Finish the deterministic repair inventory and enforce saved owner baselines.
- [x] Update the processing instructions and restored provider configuration.
- [x] Apply, inspect and publish the 20 reviewed textual corrections plus three
  contextual rasa corrections, seven reader transliteration repairs, and 48
  Sundarakāṇḍa marker-map repairs (`5bd8fdfe`; 11 readers).
- [ ] Qualify Gemini 3.7 Flash versus 3.8 Flash on representative audio and
  translation cases with the replenished credits; use stronger models only when
  their measured quality warrants their cost.
- [ ] Review every published song's source, glosses, English, mappings and tags;
  route actual lexical defects through fresh gloss reconstruction.
- [ ] Verify missing lyrics, clipping, repetitions and timing against recordings.
- [ ] Complete and publish the four prepared new recordings and outstanding
  Gurbāṇī audio repairs; retain the existing scripture citations and styling.
- [ ] Visually verify corrected readers in the Codex in-app Browser and confirm
  deployed files match reviewed changes.

## Current step and next step

Current: the contextual pipeline and first eleven-reader repair batch are live.
Deployment succeeded; all 22 published data/page files match the reviewed commit.
Desktop and 390px checks covered the corrected reader presentation and selected
word interactions. This does not establish fresh audio/timing accuracy.

Seven further readers now have eight reviewed tag additions: explicit Guru
references and Hari classified under the existing Viṣṇu facet. The registry
requires the exact supporting text to remain in the performance sequence and is
integrated into generation. The largest tag group wraps cleanly at 390px.
Independent review confirmed the witnesses and found no missing clear existing
facet in the nine Gurbāṇī readers. This tag batch is being released.

The bounded Gemini comparison remains under its cumulative $2 cap. The first
16,384-token audio request exhausted its allowance in reasoning and cost
$0.06263025. At the corrected allowance, both models returned the Gagan clip;
3.8 used more tokens and time, without establishing superior accuracy. The 3.7
Merā clip exceeded the intended wall deadline; its full reservation remains
charged against the experiment until actual cost is known, and it was not
retried. Both models' gloss candidates still need contextual editorial review.
No model winner or full-library accuracy is claimed.

Next: release the reviewed tag batch; finish model comparison; inspect all 17
Kabīr readers' English and contextual glosses; resolve newly identified
Sundarakāṇḍa lexical-token loss. Continue bounded audio and text batches toward
all 254 readers and the four additions. Preserve unrelated dirty intake work.

The previous Gurbāṇī evidence and selected additions remain documented in
`GURBANI_REVIEW_TASKS.md`. Private preparation output is under
`.transcription/library-review/`; it is not public song-page content.

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
- Use dictionary assistance and automated preparation/review. The latest owner
  instruction reopens the Vedanta translation-engine design: recover that design,
  research embedding/API/local options, and identify a fast, principled
  implementation. Reuse the design rather than inventing a competing system.
- Keep tags minimal and grounded in the actual sung text. Album, artist or
  dedication metadata does not establish a subject. Remove inherited Sāī labels
  when the writing does not refer to Sāī. Preserve the existing reader UI,
  scripture-section styling and linked word interactions.
- Keep the measured Gemini 3.7 baseline and focus on the harness; use a more
  capable model for typed unresolved cases when justified, without continuing
  broad model comparisons. The owner permits higher model cost when needed.
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
- [x] Complete the bounded Gemini 3.7/3.8 comparison; retain 3.7 as baseline,
  reject the failed text candidates, and record the limits of this comparison.
- [ ] Recover the existing Vedanta translation-engine design and research a
  small embedding/dictionary implementation with contextual sense selection.
- [ ] Identify the newly mentioned backlog recordings from saved requests and
  intake evidence; review and publish the intended additions.
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
facet in the nine Gurbāṇī readers. This tag batch is live in `28739e7b`; all 15 deployed page/data/catalogue files
match the commit, and the library Guru filter includes the corrected songs.

The bounded Gemini comparison is complete under its cumulative $2 cap
($0.41718375 reported plus $0.26 reserved for an unknown outcome). The first
16,384-token audio request exhausted its allowance in reasoning and cost
$0.06263025. At the corrected allowance, both models returned the Gagan clip;
3.8 used more tokens and time, without establishing superior accuracy. The 3.7
Merā clip exceeded the intended wall deadline; its full reservation remains
charged against the experiment until actual cost is known, and it was not
retried. Both models' gloss candidates still need contextual editorial review.
No model winner or full-library accuracy is claimed.

The second reviewed batch repairs 26 lines in 12 Kabīr-associated readers:
21 source-supported name spellings and five concept/mapping corrections. The
17-reader audit accounts for 309 stored lines; six source/semantic questions
remain held. Eight further Sundarakāṇḍa lines restore lost lexical tokens,
remove structural markers or clarify name glosses. Generation now preserves
combined marker/lyric tokens, and the new contract guard detects uncovered IAST
letters. The 254-reader scan has no remaining uncovered-letter findings.
Representative repaired wording and popups pass desktop and 390px checks.

The four additions are running from strict committed code with a $12 shared
reservation ledger, three simultaneous API calls and a 600-second request
deadline. Six new edge-trim requests completed; drafts are not public releases.

A whole-library tag review supports 77 additional actions and four semantic
removals; five incidental-name additions and three uncertain dedication removals
were excluded. Applying against committed readers changes 61 metadata records
(the working-tree count was 59 because two independently edited readers already
had additions). Exact performed witnesses are retained for regeneration.

Next: monitor the four additions through audio and text review;
review the 11 locally prepared southern readers before release; integrate the
independently reviewed wider tag corrections; recover the translation-engine
implementation plan. Continue the goal across all 254 readers and the requested
additions. Preserve unreviewed intake work until its evidence supports adoption.

The previous Gurbāṇī evidence and selected additions remain documented in
`GURBANI_REVIEW_TASKS.md`. Private preparation output is under
`.transcription/library-review/`; it is not public song-page content.

## Southern backlog release evidence

Two reviewed Tamil readers are live in `c48d702f` (six deployed public files match): Toṭuṭaiya Seviyan (Dharmapuram
P. Swaminathan) and Tiruppāvai 27, Kūḍārai Vellum Sīr Gōvindā (M. L.
Vasanthakumari). Both were regenerated through the production generator from
reviewed cached stages. All 20 display groups retain cached performance order
and timing; native AAC/Opus durations and trim records agree. All 20 browser
seek controls reach their indexed starts with range-capable audio. Desktop and
390px presentation checks pass. Four native media assets were uploaded.

The timing evidence remains the saved full pass plus verification windows,
not a new independent listening pass. Two Toṭuṭaiya starts have 0.68/0.75-second
measurement spread within the existing tolerance; their limits are retained in
the private release evidence. Historical caches lack source-audio hashes.

The other local readers are not all release-ready. Jagadoddharana contains a
different Sāī composition; Harivarasanam's cached transcript contains only
humming/instrumental records, which may be a wrong version or a transcription
omission. Neither fulfills the intended hymn without recording review.
Uyarvara has source, attribution and gloss issues; Brahmam has an unresolved
verb interpretation. Five further readers have guarded editorial proposals.

## Expanded owner scope and active parallel work

The latest owner instruction supersedes the original goal wording that deferred
the Vedanta architecture: recover its design, inspect the Time Crystal/Dev
DeepSeek harness, and implement useful economical parts. The maintained scope is
this task document. Existing-song repairs and backlog intake both remain required.

- [x] Recover the source-first Vedanta translation design and research API/local
  embedding options in `TRANSLATION_ENGINE_PLAN.md`.
- [x] Implement exact per-token dictionary-sense evidence and independent consumer
  checks; 68 focused tests pass against the isolated scoped pipeline. This is
  structural verification, not a claim of automatic linguistic correctness.
- [ ] Reuse appropriate bounded source-research mechanics from the existing Dev
  harness after inspecting actual code; do not import unfinished controllers or
  another project's budget. Qualify semantic behavior separately.
- [ ] Review connotation, readable source-supported compounds and contextual
  vocabulary consistency alongside literal agency and imagery.
- [ ] Publish four further reviewed southern readers; resolve Kolaru's repeated
  phrase representation separately before release.
- [ ] Correct backlog recording identities: Harivarasanam needs the evidenced
  307-second Sony/Magnasound Yesudas art track; the Shweta Mohan recording is
  Jagadoddharana Jaya Jagadeesha, a Sathya Sai bhajan, not the Purandaradasa hymn.
- [ ] Audit evidenced section-level attribution for composite aartis and long
  traditional recordings, retaining the established Sai aarti presentation.
- [ ] Fix mobile filter row position/touch highlighting and add a singer facet.
- [ ] Add play-next versus append choices, retain played queue history and previous
  navigation, and clear upcoming songs without interrupting current playback.

The four-song Gurbani run stopped on an explicit provider503 after 51 successful
responses. It has $1.8996075 reported cost and a retained $0.01898925 unknown
reservation within its $12 cap. Exact successful-request replay is being reviewed
for recovery; no completed paid evidence should be needlessly regenerated.
So Satgur's timing/gloss stages are available; Dhan Dhan still has two unresolved
first-syllable measurements. No new Gurbani reader is published from this run.

UI batch `aa480e47` adds a singer facet and preserves horizontal tag position and
focus. It adds disclosed play-next/append choices, clears only upcoming entries,
keeps previous navigation and exposes played history within the queue. Five DOM
regressions, queue/session/sharing checks and desktop/390px browser checks pass.
The actual audio continued from 8.404 to 8.438 seconds without pausing on clear;
history remained after reload and selecting a played occurrence retained order.
Asset versions changed across all tracked entry pages and the generator template.

The content-only Sāī pass covers all 83 tagged recordings in the 256-song
committed catalogue: 13 removals independently reviewed against 222 performed
line definitions, 70 retained with explicit sung witnesses. These removals and
related misleading subtitles are being integrated with whole-performed-source
guards. A direct Śrīhari address also supports Viṣṇu in one of those songs;
incidental parentage alone does not justify adding another minimal facet.

## Latest published content batches

- `ae3ebcc4`: Mārgaḻi Tiṅgaḷ, Palukē Baṅgāramāyenā, Jō Acyutānanda
  and Veṅkaṭācala Nilayam published with eight verified native release assets.
  All 80 browser seek controls reach their cached starts; corrected word popups
  and 390px text bounds checked. This is not a fresh first-syllable listening audit.
- `36d2ea1f`: all 13 approved album-derived Sāī tags removed, misleading subtitles
  aligned, and direct Śrīhari tagged Viṣṇu. Whole-performed-source hashes guard
  removals; reviewed subtitles survive future generation.
- `e99abf84`: Kōḷaṟu Pātikam published. Two exact contiguous repeats display ×2/×4
  with unchanged expanded words and timestamps; all 49 seek controls checked.
- `6921f970`: seven composite readers receive ten reviewed metadata corrections.
  Doi's distinct compositions now begin at83/94/106; the 108-name Sanskrit litany
  replaces the misleading Shejarti/Marathi label. Mobile dividers match existing
  style, with no fabricated author.

The committed catalogue now has 261 songs (seven additions to the initial254).
Four prepared southern items still require source/meaning/recording repairs.
Three new Gurbani recordings have complete transcription/timing/gloss stages;
all55 source/gloss/English rows have an independent textual review with exact
correction proposals. Their material issues remain held pending adjudication and
derived-packet review. The long Satgur recording still has timing disagreement.

Next automatic-pipeline slice: persist rejected drafts, attach typed repair
findings/evidence, reconstruct affected glosses before re-deriving English, and
re-review within bounded attempts and money. Never use the unrelated working-tree
autoaccept function to clear semantic uncertainty.

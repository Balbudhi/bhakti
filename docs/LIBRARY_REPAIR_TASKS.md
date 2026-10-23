# Whole-library repair task

## Goal

Repair and publish the entire Bhakti song library with complete performed lyrics,
accurate timings, intelligible literal poetic English, contextual word meanings,
correct interactive mappings, and minimal useful devotional tags. Prioritize
Kabīr omissions and the outstanding Gurbāṇī review; complete the four prepared
additions. Do not claim that pipeline execution alone establishes correctness.

## Current delivery requirement — automated whole-library pass

The owner explicitly requires one runnable, resumable pass over the complete
catalogue, not further disconnected manual pilots. Implement and use dictionary
retrieval and embedding-based contextual sense ranking now. Flash is the normal
model; automatically escalate a failed transcription, timing or semantic unit to
an available Gemini Pro model within a recorded budget. Preserve successful
stages and paid evidence; repair only affected dependencies. Independent source
review must demonstrate a concrete defect before replacing existing English.

Priority cohort: Pattā Bolā Vṛkṣa Se and Rehnā Nahī̃ Isa Desa by Shujaat Khan,
including suspected omissions, followed by the outstanding library/backlog.
The owner's “hem of Your garment” translation is Koī Hor Nahī Hai Merā
(`koi-hor-nahi`). Its exact English and Aruṇācala Akṣaramaṇamālai already match
the saved immutable baseline; a model cannot replace them. Source/gloss conflicts
are reported separately. An unchanged good translation is a successful outcome.

Required executable result: catalogue inventory → evidence/cache validation →
needed audio/text audit → exact/dense dictionary retrieval → targeted repair →
Pro escalation when necessary → independent verification → guarded candidate
publication. Every catalogue entry gets a durable status, evidence identity,
changed-line diff, model route and cost. Missing evidence is distinct from a
verified no-change result. Stop at the configured money limit without resetting
or losing resume state; do not regenerate entire songs for a failed line.

Current parallel ownership: model routing/cost accounting; timing provenance and
joint alignment; lexical corpus import; embedding retrieval; pass coordinator;
priority-cohort source review. Shared route interface is reviewed before callers
are implemented. The lead owns integration, protected-English checks, live
qualification on real failures, and publication. The complete library remains
the goal; a passing pilot alone does not complete it.

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
- [x] Recover the existing Vedanta translation-engine design and research a
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

## Earlier release evidence

At the first release: the contextual pipeline and first eleven-reader repair batch are live.
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

The four additions ran from strict committed code with a $12 shared
reservation ledger, three simultaneous API calls and bounded request deadlines.
Their final accounting and remaining timing hold are recorded below.

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
- [x] Publish four further reviewed southern readers; resolve Kolaru's repeated
  phrase representation separately before release.
- [ ] Correct backlog recording identities: Harivarasanam needs the evidenced
  307-second Sony/Magnasound Yesudas art track; the Shweta Mohan recording is
  Jagadoddharana Jaya Jagadeesha, a Sathya Sai bhajan, not the Purandaradasa hymn.
- [x] Correct the seven reviewed composite readers using evidenced section-level
  attribution and the established Sai aarti presentation. Wider library review remains open.
- [x] Fix mobile filter row position/touch highlighting and add a singer facet.
- [x] Add play-next versus append choices, retain played queue history and previous
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

## Current step and next step — 22 October

Published `6a8ebfbe` makes selected long word meanings scrollable and keeps them
above the player. Native in-app Browser pointer and keyboard checks reached the
last definition in a 844 × 390 landscape view without scrolling the page; Escape
returned focus to the source word. Ten interaction cases and the placement
regression pass. All tracked entry pages use the new asset version.

Published `399a28c1` covers all 15 catalogue languages in ISO metadata. It does not
resolve mixed-language lines by guessing from the first language or script. Three
independently reviewed reader corrections now have exact-source registry
persistence: 18 and 20 Hindi line codes in the two Ghana recordings, and
46 Punjabi codes in Meri alongside its retained Hindi lines. Their lyrics,
word maps and timing remain unchanged; mobile labels and bounds were checked.

The five-song text-only audit completed 84 lines in five calls for $0.2676105, with
no retries or active calls. All proposed English exactly retained the current
wording and all source-token indices were covered. This checks compatibility with
existing glosses; it is not independent proof of transcription, gloss accuracy or
audio completeness. Frozen inputs, raw responses and accounting remain in the
local five-song audit evidence.

The four-Gurbāṇī production/recovery run finished 111 requests, accounting for
$4.0813095 including the retained $0.01898925 unknown reservation from the 503.
Three readers are published in `373d26bc` with independently adjudicated text
and clean timing evidence. The committed catalogue now contains 264 songs.
All 109 browser line-seek controls reach their cached starts; desktop/390px
citations, word meanings and layout have been inspected. Source-backed minimal
tags are applied and survive generation. All 273 affected public files from the
popup/language-map/three-reader release match their committed deployed bytes. The long Satgur recording remains held: two
additional ending passes confirmed the expanded phrase order but did not resolve
its first-syllable timing disagreement; normalized sung variants were not adopted.

The automatic semantic-repair implementation has passed independent code review
and staged-source integration tests. It is not yet linguistically qualified for
paid production. Scheduler-deadline, recording/order identity, cache-reuse,
interrupted-adoption and distant-English-context defects have verified fixes. Continue
with source-first repair, preserving exact owner English and prior paid evidence.

Next: qualify the bounded repair implementation on actual held semantic cases.
The separate two-recording Kabīr audio audit finished exactly two calls for
$0.15923025, within its $0.60 cap, with no retries or unknown charges. It reported
Sunta’s four extra printed stanza groups absent from this abridged recording and
Kya Tan’s final questioned vowel as nonlexical before two returning refrains.
New disagreements remain held: Sunta’s ending count and कहे/काहे, and Kya Tan’s
पासा/आसा. No new source text, counts or timings were published from these audits. Continue the whole-library recording/translation audit and the
remaining backlog. No complete-library accuracy or goal-completion claim.

The semantic/language integration is published in `5a2b27ff`; all seven changed
public catalogue/reader files match the deployment. Staged-source checks passed
33 semantic tests, the transport test collection, and 19 language persistence
cases. The five repeat-unit migrations are now published in `242760ee`: expanded source,
Roman tokens, indexed English/glosses and every numeric interval are preserved.
All 25 affected seek controls were exercised at 390px; the repeat badges and
text have no horizontal overflow. This verifies UI seek behavior, not a new
independent listening judgment. Seven unbuilt legacy directories remain open.

The correct 307-second Harivarāsanam recording is downloaded privately with native
Opus/AAC and verified official metadata. The old 173-second folder is archived;
no audio or semantic evidence from it can be transferred to the replacement. A
fresh production run is authorized within the integrated backlog pass but has
not been dispatched; the disconnected one-song runner was stopped.

Completed paid evidence and original four-Gurbāṇī caches are preserved under the
ignored project folder `.transcription/library-review/20261022-releases/` with an
archive manifest. The live reader never exposes these research artifacts.


### Current integration checkpoint

- `bbcffba9` is deployed: compact filter spacing and a Poets row above Singers.
  Joint explicit credits contribute each named poet; no writer is inferred from
  an album or singer. All four changed public assets match deployed bytes.
  Mobile, tablet, desktop and large-screen layouts were inspected; 390px poet
  selection preserves the correct pressed button and horizontal row position.
- The no-network whole-library pass inventoried 264 committed songs, 6,719 unique
  lines and 406 local audio assets (3,979,923,728 bytes). Missing old metadata is
  an evidence gap, not permission to regenerate all translations. Ten current
  working-reader divergences were held, and the two owner baselines protected.
- The actual Patta omission is a merge bug: a short internal pickup plus seven
  occurrences of four speech-verse lines and two sorrow-remembrance repetitions
  were deleted. The corrected saved-source sequence has 59 rather than 49
  occurrences. All 29 existing lexical units have a source-bound reuse mapping;
  five new source units need semantics. No new public wording is published yet.
- Rehna has two saved independent onsets at 518.300/518.350 seconds that the old
  code rejected against an uncertain 538.4 routing estimate. The new parser
  retains that evidence. This is a saved-evidence repair, not fresh listening.
- Private integration contains reviewed merge/timing fixes, persisted Flash→Pro
  routing, atomic call/budget caps, and a paired-review publication guard. It
  preserves failed/unknown paid outcomes and exact owner English. The integrated
  execution caller and source adapter remain under active implementation/review.
- Real dictionary import is implemented: 173 private Platts entry candidates,
  23 reviewed lemma links, and a private full MW corpus. Indexed retrieval ranks
  language-matched attested alternatives and never chooses a meaning itself.
  Real embedding capability/semantic qualification is still pending. The large
  Sanskrit corpus must be queried by its index, not reread into every prompt.

Current step: integrate and exercise the actual bounded priority pass (Patta,
Rehna, held semantic cases), then run the remaining eligible published queue and
backlog. Passing existing translations stay byte/object-exact unless a concrete
source-supported defect is confirmed and the proposed change passes paired review.
The goal remains active; no whole-library accuracy claim.


## Integrated execution checkpoint — 22 October 2026

The previous continuation verified the deployed homepage filter change; it did
not advance the outstanding translation pass. This continuation starts the
reviewed integrated caller against catalogue `9fa148b4`, covering all 264
published songs and 6,719 unique stored lines in its inventory. The first paid
selection is Pattā Bolā Vṛkṣa Se and Rehnā Nahī̃ Isa Desa. Bounds: $4, 32 chat
requests, 40 minutes, plus a separate $0.03/32-request embedding cap. This is
an execution limit, not evidence that the full library is complete.

The private runtime combines the reviewed source-merge, timing, route, candidate
guard, lexical retrieval and caller changes. Its 20 caller/resume tests pass,
including positive supplied-English declarations outside the registry. A run
cannot rewrite those translations, overwrite changed original inputs, accept a
tampered candidate, or silently restart an uncertain paid request. Flash is
attempted first; failed quality units have one bounded Gemini Pro escalation.
The dictionary index has 173 sourced full Platts entries plus five previously
reviewed entries with concise senses, 178 entries/192 senses total. Exact
language/form retrieval precedes contextual embedding ranking; ranking never
establishes the selected meaning by itself.

Rehna's reviewed cached timing repair is published in `9fa148b4`. The shared
boundary before “kahata kabīra…” changes from 538.29 to 518.325 seconds, based
on two retained clear measurements (518.300 and 518.350). All metadata, lyric
objects, performance order and other starts remain exact. The mobile seek
control reaches the new onset and the 390px layout has no horizontal overflow.
Public data and HTML match the committed hashes. This is adoption of retained
acoustic evidence, not a new complete listening audit.

Private execution/evidence locations:
- `/tmp/bhakti-priority-integrated-20261022/`: frozen plan, code hashes, dictionary,
  durable request ledgers, per-stage artifacts and candidate readers.
- `/tmp/bhakti-rehna-release/`: exact diff/release/deployment evidence.
- `/tmp/bhakti-remaining-backlog/`: recording-level backlog manifest, excluding
  published duplicates and retaining ambiguous collection matches.

Remaining work includes the live priority run, publication of accepted semantic
candidates, integration of the reviewed engine into the maintained source, the
full eligible library pass, unresolved audio/source coverage, and backlog
production. An inventory or a held candidate is not a completed song repair.


The first integrated execution ended with two explicit unresolved results after
seven chat calls ($1.3874905 reported); it did not publish semantic changes.
Patta's Flash result passed fidelity for all five new units but requested a
choice between an impersonal precept and direct imperative in “Aisī bānī boliye.”
Automatic Pro escalation ran, then its glossary record omitted accounting for
one supplied overlapping dictionary entry. Both attempts and charges are intact.
Independent editorial review accepts the complete Flash wording and mappings;
a narrow hash-bound adjudication/resume path is being added to adopt that decision
without rerunning paid semantics or silently clearing original review evidence.
Rehna's source-first review returned actual findings; its Pro review returned an
extra context-only ID in a bounded target batch. That mismatch remains held and
is being diagnosed before any repair is applied. The corrected onset remains live.

The maintained engine integration passes 174 focused tests plus five instrumental
and Roman-contract checks. The instrumental audit now exempts only refs used
exclusively as instrumental cues; a ref also sung as a verse still requires all
lyric fields. Gloss/English requests above40 lines use the existing bounded cache
batches. Full release audits report no audio-quality errors and111 clean trim
checks; the seven pre-existing unpublished directories still lack data.js.

The owner's latest question requires a single consistent treatment of divine
names such as Hari, Kṛṣṇa and Viṣṇu. Their current uses are being inventoried;
meaning-in-English versus name-in-English presentation is awaiting clarification.
No global replacement or change to supplied English is authorized by that audit.

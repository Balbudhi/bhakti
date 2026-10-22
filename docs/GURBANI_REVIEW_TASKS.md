# Gurbāṇī reader repair and expansion

## Outcome and current step

Review all nine published songs in `data/scripture_metadata.json` against their
actual recordings, repair transcription, IAST/symbols, timing, word mappings,
glosses and English, and add four suitable recordings by existing performers.
Use the owner-selected Together provider, then editorial review; third-party
translations are comparison evidence, never replacement English. Preserve
literal imagery, agency, repetition and source ambiguity. Publish scoped work.

Current step: the editorial slice is published in commit `24040780`. All nine
readers and the catalogue were verified live: 19 files match the committed
bytes. The slice contains 132 distinct reviewed proposal records and changes
139 lines including danda cleanup.

Current continuation: minimal devotional tags are published in `7a026203` and
all 19 deployed metadata files match the commit. Together credentials are
configured locally; text requests work. Six Whisper clip responses omitted
phrases and corrupted repeated lines, so full audio intake remains held.
A short GPT-OSS gloss reconstruction also made substantive errors. A bounded candidate-only style review was attempted but produced no usable
review packet. No Together proposal was applied and no review process remains
running.

Next: establish reliable text review and a qualified audio route before
resuming the prepared 13-song batch. All nine existing readers passed desktop
and 390px browser checks. Every-line first-syllable listening and the four new
readers remain unfinished. The real callers are the library, song reader,
hover/tap word mapping, and first-syllable player seek.

## Task list

- [x] Inventory nine readers and assign parallel reviews.
- [x] Publish minimal devotional tags without a separate Hari filter.
- [x] Switch default text processing and hosted configuration to Together;
  update credentials guidance and processing documentation.
- [x] Run bounded sung-Punjabi audio qualification; preserve failed evidence.
- [ ] Establish a replacement audio route that retains all sung occurrences.
- [ ] Inspect every unique lyric and every performance occurrence against audio.
- [ ] Correct mixed scripts, Romanization, punctuation and source word mapping.
- [ ] Reconstruct glosses before deriving literal, intelligible poetic English.
- [ ] Review each proposed change and all fidelity/alternative findings.
- [x] Resolve four official recordings and verify scripture authors/locations.
- [x] Independently review 121 proposed textual deltas across all nine readers.
- [x] Adjudicate the remaining text-only meanings; review 28 additional or
  superseding records against the source, glosses and commentary.
- [x] Preserve original audio and prepare a fresh isolated 13-song batch.
- [x] Regenerate the nine readers and their catalogue titles; retain previous
  spellings as search aliases and reuse the existing scripture-section UI.
- [ ] Run new recordings through the complete production pipeline.
- [ ] Remap source-section boundaries after transcription/order changes.
- [ ] Run contract, audio quality, trim and scoped regression checks.
- [x] Check all nine published readers at desktop and 390px mobile in the Codex
  in-app Browser; compare the established Sāī ārati section styling.
- [ ] Verify the four new readers in-browser after the pipeline produces them.
- [x] Inspect and publish the scoped editorial slice; verify all 19 deployed files.
- [ ] Publish and verify the remaining audio repairs and four new readers/media.

## Ownership and dependencies

Lead owns task record, editorial integration, scripture registry, catalogue and
release. Pipeline agent owns the isolated processing workspace and manifests.
Three editorial reviewers cover disjoint song groups; UI agent owns narrow
renderer/mapping/validation fixes. Discovery agent researches four additions.
Source and audio decisions precede dependent glosses/translations. Tests for a
code defect must distinguish the reported defect before its fix is accepted.

API work is production only: one bounded batch, seven song workers, at most
three simultaneous calls and 350 ms stagger; retain caches and provider cost
records. Use focused retries for diagnosed disagreements. Do not loop paid
calls for stylistic preference or hide unresolved fidelity flags.

## Known findings / verification limits

- `gur-satgur-ka-jo-sikh-akhaye`: mixed-script `japਾਵai` in Romanized lyric.
- Several readers mix ASCII pipes/dandas and macron e/o spellings.
- Initial editorial findings include changed agency and lost concrete imagery.
- Canonical/performance differences require audio confirmation, not automatic
  replacement by the printed text.
- Existing API cache refresh flags do not invalidate all nested caches; isolate
  fresh processing so old evidence cannot masquerade as a new audit.
- Initial browser alias lookup failed. Browser inventory identified the working
  Codex in-app connection (ID 1); visual QA of the nine current readers is done.
- Preserve all unrelated dirty/untracked intake work in the main workspace.
- The owner explicitly replaced OpenRouter with Together. The old credit hold
  is superseded by failed Together audio qualification; see
  [the pilot report](TOGETHER_AUDIO_QUALIFICATION.md). No silent provider fallback.

## Editorial slice and held audio questions

The reviewed changes correct mixed-script `japāvai`, consistent IAST e/o,
historical names, contextual word popups, English word linkage and concrete
agency/imagery errors. Examples include flowers offered to the divine Light
(aṅg 663), attachment to pleasure (633), the scribes recording and Dharma
considering their records (6), first-person meditation/ferrying (394), and the
bride sighing with tear-filled eyes (337). Each proposed delta received an
independent review against the stored text and source evidence. This does not
certify whole-song accuracy or renewed agreement with the recording.

No Gurmukhi, performance order or timing changes belong to this slice. Held
questions include Koī's second-person verbs, Japu/Rehrās variants in So Dar,
`prema/pria`, `paga/pagu`, and `kholi/kholhi` in Merā Manu Locai, and represented
repeated phrases in Merā and Terā. These
must be resolved from the recording before dependent changes are published.

The second editorial review resolved the non-audio questions. The graced
person remains the subject of merging; Nānak is the signature/address. The
Name/rasa cuts sins, while the mind becomes pure. So Dar retains its repeated
One, coloring image and distinct delight; its birth/passing clause follows the
dictionary entry citing this exact verse. Merā retains the wetting image and
the Guru as the agent of union. Defensible existing readings, such as
servanthood versus service to servants, were retained rather than presented as
proven errors. Comparative commentary informed adjudication; English was
composed from the reviewed word meanings rather than copied.

Key comparison evidence: [aṅg 663](https://www.gurugranthdarpan.net/0663.html),
[305](https://www.gurugranthdarpan.net/0305.html),
[603](https://www.gurugranthdarpan.net/0603.html),
[633](https://www.gurugranthdarpan.net/0633.html),
[6](https://www.gurugranthdarpan.net/0006.html),
[757](https://www.gurugranthdarpan.net/0757.html),
[96](https://www.gurugranthdarpan.net/0096.html),
[338](https://www.gurugranthdarpan.net/0338.html), and
[1206](https://www.gurugranthdarpan.net/1206.html).

A generator defect also replaced contextual name explanations with generic
identities. The cleaner now retains a useful supplied explanation ahead of a
generic fallback, while preserving the curated term hints and rejecting empty
or placeholder meanings. Twelve focused glossary regressions pass.

Final editorial checks: source text, source-word maps, performance sequence,
timings and unrelated metadata are unchanged. The seven other readers pass the
public contract; Merā and Terā retain only their pre-existing repetition
findings, which need new audio/timing evidence. Seven source-witness tests and
two mixed-script reader regressions pass, along with Python compilation and
diff whitespace checks. No new recording or first-syllable verification is
claimed. The full goal remains unfinished pending a qualified audio route for its
outstanding checks and additions.

Release evidence before editorial integration: 272 listener-audio inventories
passed; 108 stored trim reviews passed; Python compilation passed. The full
contract audit still reports existing issues, including repeated phrases in
Merā/Terā and mixed-script text in other readers. The new regression exercises
the real public data reader and detects script leakage even when both Roman
text and its linked word token share the corruption. The initial browser alias failure was resolved using the browser inventory;
see the completed visual verification below.

## Selected additions

- `satgur-kai-bhane-chal` — Bhai Harjinder Singh; complete existing intake.
- `dhan-dhan-ramdas-guru` — Bhai Harjinder Singh.
- `so-satgur-pyara-mere-naal-hai` — Bhai Lakhwinder Singh.
- `sabh-gobind-hai` — Bhai Harjinder Singh.

Official-art-track resolution and primary textual citations are recorded in the
processing manifest. Total selected new audio is approximately 44 minutes; the
nine existing recordings total approximately 96 minutes.

## Initial evidence

Renderer review exercised all 182 current unique lines and 3,061 linked spans:
no index-out-of-range or lost-surface rendering defect. Structural completeness
does not prove semantic linkage. A regression now detects mixed-script Roman
text even when the line and word token contain the same corruption.

Audio audit targets include `prema` versus `pria` in Merā Manu Locai, second-
person verbs in Koī Āṇi Milāvai, and Japu/Rehrās wording in So Dar. Printed text
remains secondary evidence; do not erase clearly performed variants.

## Browser verification after publication

All nine current readers were inspected in the Codex in-app Browser at its
1280px desktop width and a temporary 390 × 844 mobile viewport. Titles, source
script, IAST, tags and section notes render without horizontal overflow or
replacement glyphs. The internal Kabīr section in Merā was inspected at both
sizes, and the Sāī ārati reader confirms the same hairline, typography and
spacing treatment. The viewport override was reset afterward.

Tapping `locai` displayed “longs; yearns” and highlighted its source, Roman and
English counterparts. Tapping repaired `japāvai` displayed its causative meaning
and linked the corresponding source and English phrases. The Gurbāṇī filter
returns exactly nine readers; searching the old title “Gagan Mein Thaal” finds
the renamed reader. This verifies these visible interactions, not every lyric
seek or a renewed comparison with the audio.

At that earlier checkpoint, the OpenRouter account reported exhausted credits. All 13
prepared song directories have both original listener audio formats, and all
fresh stage directories remain empty: there is no running pipeline to wait on.
The previous goal turn made progress by publishing the editorial slice; this
continuation completed the previously unavailable visual checks.

## Historical dependency audit (before the Together instruction)

The original goal turn and both subsequent continuations confirmed the same
exhausted OpenRouter account. The intervening turns completed editorial
publication and browser verification; no authorized independent work remains
that can establish audio accuracy or produce the four new readers. The latest
check confirms 13 prepared jobs, zero fresh pipeline artifacts, and zero new
public readers. There is no running pipeline to wait for. Resume after credits
are restored; do not mark the full objective complete or substitute a different
transcription provider.

## Reviewed subject tags

Subject tags describe devotional themes and named divine references in the
performed text. Gurbāṇī is a source/tradition facet and does not replace those
subjects. Reuse existing devotional filters: Hari invocations use Viṣṇu, Govinda
and Murāri use Kṛṣṇa, and the bow-bearing epithet in Merā also supports Viṣṇu.
Guru is applied where teacher devotion or the performed Vāhigurū invocation
appears. Nirguṇa marks the supported cosmic/inward, birthless or limitless
Divine themes; it is not assigned to every Gurbāṇī song automatically. So Dar
also receives Śiva and Śakti for its explicitly named divine singers. No Rāma
tag is inferred from the author's name Rām Dās.

No separate Hari or singleton Brahmā/Indra filters were added, following the
owner's request to keep tags minimal and useful for devotional browsing.
Per-song decisions and lyric evidence are stored in scripture_metadata.json
and reapplied by the generator. Metadata-only validation confirms all lyrics,
word maps, translations, order and timings are unchanged.

The tag release passed the catalogue/metadata checks and mobile browser review.
No standalone Hari filter was created.

## Together migration validation

Commit `02d5c5f8` is pushed and Pages deployment `39850497374` succeeded.
Sixteen provider regressions, three preflight cases, and four text-review tests
passed. The preflight permits deterministic generation, blocks unqualified
Together audio before download/model requests, and does not query OpenRouter.
Python compilation and diff checks passed. Listener audio-quality audit and
108 stored trim reviews passed. The repository-wide content contract still
reports existing migration findings, including the held Merā/Terā repetitions;
this migration makes no source, timing, or translation changes.

Together counts internal reasoning against the same token cap as the JSON
response. After calls at 4,096–5,376 tokens returned empty final content, the
style review allowance was raised to 16,384 tokens for GPT-OSS. The earlier
calls are not counted as reviewed lines; their parser errors did not preserve
finish reasons, so token exhaustion is an inference rather than a confirmed
provider diagnostic.

### Substantive text qualification outcome

The tiny strict-schema canary succeeded with `openai/gpt-oss-120b`; this proves
request/schema compatibility only. A separate one-line reconstruction and
review produced wrong lexical readings (including `mai` as “I” and `janaka`
as “creator”) and was rejected. Existing-gloss style batches with smaller caps
returned empty final content. The remaining queued work was stopped; incomplete
in-flight billing is unknown. One Gagan batch at 16,384 tokens and high reasoning
then hit its 120-second read timeout. It was not retried; the remaining eight
songs were not launched on that configuration. The conservative reserved cost
ceiling across these style attempts was $0.0819411, not an actual billing total.

A single distinct non-reasoning Qwen3-Next-80B-A3B-Instruct request was rejected
with HTTP 400 `model_not_available`. Its
[official model page](https://www.together.ai/models/qwen3-next-80b-a3b-instruct)
requires a dedicated deployment. No endpoint was deployed, no retries were
made, and no default was changed. Earlier Qwen3.6-Plus access was blocked by the
account's third-party data-sharing policy; that policy was left unchanged.

Private raw audio trials remain under song-local `.transcription/together-pilot/`.
The isolated workspace preserves text qualification and Qwen response packets;
local style-attempt logs and call journals record the failures. No fresh full
transcription, timing pass, or complete nine-song Together review is claimed.
The already published independent editorial review remains the textual baseline.

# Gurbāṇī reader repair and expansion

## Outcome and current step

Review all nine published songs in `data/scripture_metadata.json` against their
actual recordings, repair transcription, IAST/symbols, timing, word mappings,
glosses and English, and add four suitable recordings by existing performers.
Use the approved Gemini/OpenRouter pipeline, then editorial review; third-party
translations are comparison evidence, never replacement English. Preserve
literal imagery, agency, repetition and source ambiguity. Publish scoped work.

Current step: release the independently reviewed textual corrections from the
existing Gurmukhi and word maps: 132 distinct reviewed proposal records, with
139 lines changed including danda cleanup across all nine readers. The fresh
13-song API batch stopped at credit
preflight; no new audio, timing or translation model calls ran.
Next: publish the safe editorial slice; resume fresh audio-aware stages when
OpenRouter credits are restored, adjudicate differences, regenerate reviewed
readers and source notices, verify and publish. The real callers are the library,
song reader, hover/tap word mapping, and first-syllable player seek.

## Task list

- [x] Inventory nine readers and assign parallel reviews.
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
- [ ] Check desktop/mobile in the Codex in-app Browser when available.
- [ ] Inspect exact staged diff, publish and verify deployed pages/media.

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
- In-app Browser unavailable on the initial attempt; visual QA remains pending.
- Preserve all unrelated dirty/untracked intake work in the main workspace.
- The configured OpenRouter account has exhausted its credit limit. No provider
  substitution or automatic retry loop is authorized by this task's procedure.

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
claimed. The full goal remains unfinished until credits and browser access
allow its outstanding checks and additions.

Release evidence before editorial integration: 272 listener-audio inventories
passed; 108 stored trim reviews passed; Python compilation passed. The full
contract audit still reports existing issues, including repeated phrases in
Merā/Terā and mixed-script text in other readers. The new regression exercises
the real public data reader and detects script leakage even when both Roman
text and its linked word token share the corruption. Browser visual checks are
unavailable because the Codex in-app browser cannot be opened in this session.

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

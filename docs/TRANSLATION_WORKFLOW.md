# Translation and library review workflow

This guide describes the bounded review engine and its actual command interfaces.
The connected workflow is not yet qualified for a whole-library repair. A real
two-row comparison consumed source-dictionary and English-definition evidence
plus four embedding requests, but still added an unsupported `true` to the gloss
and English. Its total cost was $0.1307826; no result was published. Earlier
attempts and task accounting remain in [the repair task](LIBRARY_REPAIR_TASKS.md).

Known lookup targets now use explicit source spans. Candidate expressions and
lookup lemmas have separate bounds, preserving complete definitions when only
some receive embedding scores. Independent review checks primary popup glosses,
semantic frames and final English separately. Validated unchanged writing can
receive a new review without regenerating it. Unknown or unfinished paid attempts
retain their original accounting and replay restrictions.

The latest local fixes separate the attested headword from its quoted definition,
remove duplicate model-facing dictionary metadata, and supply source-bound naming
conventions through intake, repair, benchmark and standalone audit callers. They
have passed focused integration checks with saved real artifacts and synthetic
provider responses; they do not establish improved translation quality. The
reviewer now retains source-only neighboring lines from a short excerpt, with
explicit local order and no invented neighbor translation. Conflicting or missing
source definitions stop before dispatch. Review-task version 2 introduced review-only
renewal, preserving prior findings and validated unchanged writing. The joined
34 context/cache checks pass. A one-call review of the unchanged failed draft
cost $0.070053 and detected the extra `true` in both popup and English. It also
raised questionable naming-popup and synonym-choice objections, so its findings
still need independent adjudication before repair. No new glossary, writer,
source HTTP or embeddings ran, and no result was accepted or published.

Current review task 3 admits structurally valid private writer drafts with doubts
to independent review, then requires separate gloss/frame/English judgments and
source-bound resolution of each concern. Original writer fields remain intact.
Final consumers reconstruct the full writer history and retained coordinator
obligations; absent metadata cannot turn a current review into a legacy one.
Existing-reader repair now uses the shared selective coordinator, retaining
successful stages and exact owner English. The integrated checks establish these
mechanics; the bounded real-song qualification and whole-library pass remain open.
The first actual historical-reader trial of this integrated version stopped at
its initial audit's 180-second timeout without a saved response. Its $0.1625655
reservation is unresolved, not a confirmed charge. No repair or lexical stages
ran; preseeded caches do not establish evidence consumption. The terminal private
run is preserved without retry; see the repair task for accounting and next steps.

The subsequent source-only two-row trial delivered the exact native dictionary
entry, 61 English definitions and actual embedding rankings to writer/reviewer,
but still produced and approved an unsupported predicate qualifier. It also
exposed an original/derived glossary mismatch in writer-reservation validation,
which stopped the run before repair. That binding defect is now corrected:
immutable writer evidence names both exact glossary representations, and each
consumer validates the representation it actually receives. Legacy review-only
renewal checks the original writer input fingerprint before adding a new binding
wrapper; it preserves the old proof and does not purchase another writer call.
Changed source/gloss/grammar or missing original evidence still holds. The saved
trial remains rejected on content and has not been replayed.
Automatic source acquisition currently runs
after the initial glossary; pre-gloss source evidence is the next ordering fix.
These are demonstrated gaps, not qualified translation quality. The complete
trial cost $0.20410305; all responses remain available without a paid replay.

## Bounded intake and boundary recovery

The ordinary `bhakti_pipeline.py` intake command now initializes one shared run
ledger before its workers. A new run defaults to a $1 total ceiling, 128 outbound
requests and 1,800 seconds. These are run limits, not a song-price estimate.
Override them explicitly with `--budget-usd`, `--max-calls` and
`--deadline-seconds`; `--run-dir` selects a private stable state directory.
Existing configured limits and charges remain authoritative on resume. URL
aliases for the same YouTube recording share the canonical run identity.

Resume does not renew the original deadline, replace a missing ledger or reset
an unresolved charge. The existing provider ledger owns spending; the intake
receipt binds its identity and observed request prefix. A hard-killed process
cannot attest later rows that never reached its final prefix checkpoint.
`--generate-only` remains free and bypasses run initialization. Bounded synchronous
intake rejects unsupported text Batch accounting rather than silently changing
its billing mode.

Boundary review covers both ends and distinguishes material belonging to the
performance from unrelated content. Audio application preserves original bytes,
prepares all outputs before replacing them and records actual media offsets.
An existing reader or transcript whose retained interval would change currently
holds before audio mutation; automatic historical adoption is still being built.
Caller/FFmpeg tests establish these mechanics, not acoustic correctness. The
stricter audit currently exposes six historical evidence failures recorded in
the task list. Do not bypass those failures to publish content.

The source/timing consumer accepts an explicit private boundary transform that
binds every original and staged native format. Removal of a displayed occurrence
requires original-edge hearing and independent confirmation of the exact ordered
prefix/suffix; absence from the cropped attachment is insufficient. Durable
receipts bind preserved original files and their source-support snapshot. Fresh
admission also compares that archive with the authoritative live input, while
post-install replay uses the archive without another provider call. This consumer
is integrated. The private historical preparation caller now preserves the
original, cropped source candidate and final candidate separately, invokes the
source/timing consumer and rechecks English after source changes. Its original
deadline persists across interruptions; replay validates underlying review
routes and complete finding history without new model calls. Prepared candidates
remain blocked at generation/publication entrypoints. Historical installation
and production activation remain unfinished.
Timing reuse still requires a qualified clock origin, and cannot substitute a
requested trim length or decoded offset for the browser's playback clock.

Private joint-timing regions may set `max_completion_tokens` to an integer from
1 through 65,536. The same limit applies to both independent hearings and is
part of the existing region/cache identity; omission keeps the prior 65,536
default. Invalid limits fail before audio processing. This permits an explicit
small-response budget for short excerpts without changing uncertainty or
consensus checks. A truncated answer still fails; a lower limit is not evidence
that the model can complete the task within it.

Fresh production onset requests already use an ephemeral canonical AAC copy.
The failed synthetic native nonzero-PTS model probe bypassed that path and is not
a prerequisite for all fresh production timing. A read-only inventory found 426
listener files across 275 song directories: 316 had stream start zero and 110 AAC
files had start 0.047891 seconds. These metadata do not justify timestamp shifts
or establish first-syllable accuracy. Canonical-to-browser correspondence still
needs file-specific evidence for offered listener formats. The actual two-song
IAB check now supplies ten waveform captures across five exact files: Rehna's
native Opus/AAC and both canonical files are compatible with decoded zero, while
Aao's native AAC clock is 43.904–53.754 ms ahead of its canonical decoded axis.
That result applies only to those file hashes and the observed browser. It does
not justify changing old timings whose original axis is unknown, or assigning
the same correction to unmeasured AAC files. Historical reuse holds remain scoped
to missing evidence. Do not extend a synthetic multi-second
offset failure to the whole corpus or resume that terminal probe.

Source repairs map section notices and adaptation markers through the accepted
expanded performance lineage before generation. Credit wording and unrelated
metadata remain exact. Empty attribution spans, new material between credited
sections, or merged repeats with conflicting credits/markers hold for review.
Private candidate generation preserves this checked reader metadata instead of
reapplying old registry positions; ordinary intake keeps its scripture-reference
checks. Saved source-result verification recomputes the same positional mapping.

Boundary installation, reader generation, media publication and site assembly
share per-song transaction locks. Audio preparation occurs before the brief
installation lock; consumers reject pending or changed source snapshots. Changed
listener files use immutable hash-named release assets, preserving URLs used by
older live readers. A completed upload can be reused after interruption, and the
public media manifest is replaced atomically. Both Pages workflows invoke the
same public allowlist assembler, which excludes private pipeline/review state and
rejects a mixed reader snapshot before replacing its artifact. These are release
consistency checks, not acoustic qualification or historical crop approval.

## How a meaning becomes English

The recording determines the performed source and order. A dictionary cannot add
an unheard line, resolve an uncertain onset, or establish which recording was
used. Existing text-only reviews retain their existing audio evidence and make no
new listening claim. Missing historical provenance is recorded separately from a
concrete source defect; it does not automatically trigger retranscription.

For each passage, read every actual occurrence with its neighbors. Establish the
speaker, addressee, agent, action, object, negation, tense, relationship and image.
Then:

1. Retrieve attested dictionary candidates for the explicit source language and
   exact native/roman form, or an individually reviewed inflection/lemma link.
   Preserve the reader's existing compound subdivisions and source-word indices.
2. Use context embeddings to rank those candidates. Keep all alternatives,
   citations, restrictions and whole-entry context available for adjudication.
3. Choose the contextual meaning from grammar and the passage, and record the
   choice, rejected alternatives and reasons in private `sense_decisions`.
   Missing dictionary coverage is not proof of a missing word or sense.
4. Write the primary word gloss and semantic frame first. Derive English from
   those glosses; link each meaningful English phrase to the correct source
   indices. Do not write fluent English and back-fit the glosses to it.
5. Run independent source-first review. A concrete defect produces a typed,
   referenced repair: reconstruct affected glosses/frames before revising their
   English, then review the proposed changes independently again. A merely
   different stylistic preference does not authorize a rewrite.

Preserve connotation through the passage's concrete image, register and
relationships. Keep repetition, personification, bodily states, purposeful
ambiguity and literal strangeness. Improve English syntax without replacing these
with generic devotional language. Transparent compounds are useful when the
source supports every member; opaque literary coinages and invented etymologies
are not. Genuine names retain their evidenced identity or relationship in the
popup; ordinary words and philosophical concepts receive precise contextual
English, including short phrases when necessary.

Owner-supplied English is immutable. `data/editorial_baselines.json` protects the
two designated reference readers, Koī Hor Nahī and Aruṇācala Akṣaramaṇamālai;
supplied human translations remain a
baseline throughout production. A source/gloss conflict is reported separately;
the engine must not distort grammar to justify rewriting the owner's wording.
An unflagged song is not automatically correct.

## Existing-reader reconstruction

`retranslate_bhakti.py` creates private comparison packets through the same
semantic coordinator. All song workers share one bounded run; use
`--budget-usd`, `--max-calls`, `--deadline-seconds` and `--run-dir` to set its
limits and location. Matching accepted stages resume without paid regeneration.
`--reuse-glosses` is deprecated: it now resumes matching accepted English too,
and does not force a new writer/reviewer request. Owner English remains locked;
this command does not publish or change the public reader.

The bounded run freezes the actual `data.js` bytes. Changed public source bytes
hold that existing CLI run and require an explicit separate run for the new
input; they do not renew its old allowance. Evidence/policy changes within an
authorized population use the semantic coordinator's validation and renewal.
Legacy unfinished reports or missing paid-stage state require reconciliation;
they are retained rather than replayed. Never create a new run to evade an
unknown request. A corrected input that failed validation before semantic work
can retry within its original remaining allowance.

## Private reference comparisons

`benchmark_translation_prompt.py` uses the production semantic coordinator,
including selective repair, against frozen reader snapshots. Its private case
identity stays separate from the protected song: source-only generation never
receives the owner reference English as an answer. Preparation is free:

```sh
python3 scripts/benchmark_translation_prompt.py --output-dir /private/path/benchmark
```

Paid execution requires an explicit dollar limit, call limit and original run
lifetime, for example adding `--execute --budget-usd 2.10 --max-calls 8
--deadline-seconds 900`. These are ceilings, not a quoted song price. The default
cases are private Koī/Aruṇācala reference generation and historical/corrected
Rehnā diagnostics. `--cases` selects the recorded cases. Capture actual requests
and check their reservations before execution; output size and context affect
cost. This command does not activate paid embeddings.

Outputs remain `not-reviewed` until a separate editorial reading. A model pass
is not a quality score; an owner/source disagreement is distinct from a bad
generation. Existing prompt examples overlap some reference images, so these
are calibration comparisons, not wholly unseen tests. Owner English is never
published or overwritten by this command.

The run locks concurrent launches, retains raw payment evidence and completed
stage artifacts, and verifies their hashes before reuse. Changed inputs or
implementation hold the existing experiment. Unresolved/interrupted execution
returns nonzero without automatically redispatching; reconcile retained evidence
before any recovery. Do not delete a ledger or create a new run to retry an
unknown request. A private candidate or successful wire test is not evidence of
a completed library repair.

## Dictionary and embedding evidence

The owner's clarified Bhakti policy is to translate ordinary words and concepts,
including difficult ones. Prefer an accurate English word, then a precise short
phrase, then an intentional transparent compound when it improves fidelity or
poetry. Do not force an English substitution or coinage that distorts the passage.
A well-understood term may lack an adequate compact English rendering: compare
the best word, phrase or compound with retention and record the consequential
loss or misleading implication. A retained non-name needs that contextual reason,
an understandable clickable explanation (acknowledging approximation when needed),
and independent review. This is distinct from unresolved source meaning, and
missing dictionary coverage alone is insufficient. Genuine
names may remain, with their evidenced literal/traditional meaning and referent
explained on click. Unknown etymology is not invented. Existing owner English is
still protected. Shared prompt policy version 8 states these rules and explicitly
checks inflection, adjectival relationships and connotations, and compound meaning.

Retention is a wording decision after source meaning has been established.
The glossary still explains the source in English; its legacy
`preserve_in_english` flag does not choose the new rendering. For a targeted
lexical decision, `retained_term` must identify the source spelling and exact
indices, supply an ordinary English paraphrase and explain its consequential
loss. It cannot claim an English dictionary candidate or invented definition.
The linked gloss must explain rather than repeat the term. Without targeted
lexical support, the writer records the same comparison in `choice_note`.
Independent review checks the comparison, clarity of the explanation and actual
passage; structural validation alone does not establish that retention is best.

The integrated discovery algorithm compares contextual meaning with
dictionary **sense definitions**, using embeddings to propose further words.
Then it examines complete dictionary alternatives for the original words and a
small discovered shortlist, and independently reviews the chosen wording in the
whole line. The research basis includes contextual-definition comparison and
whole-sentence fitness in [LexSubCon](https://aclanthology.org/2022.acl-long.87/),
and explicit lexical/semantic relationships in
[WordNet](https://wordnet.princeton.edu/documentation/wninput5wn). This is an
adaptation requiring Bhakti-specific qualification, not a claim to reproduce the
paper's model or benchmark results. A local workload check rejected unrestricted
synonym expansion: one seed group produced 343 sense records and 22 embedding
batches. Rank the bounded explored sense pool before expanding a small set of
new lemmas, retain original candidates, and make exploration limits explicit.
Enable bounded English discovery with `BHAKTI_ENGLISH_DISCOVERY=1` alongside
automatic lexical support and the existing bounded embedding configuration.
The current defaults explore eight related synsets and shortlist at most four
additional lemmas. All original seed definitions and all dictionary senses of
retained words remain available. Compact model evidence includes adjective
position restrictions and lemma-specific verb frames; it does not discard
grammar along with private raw records. These paths have passed joined offline
tests, but their translation-quality benefit is not yet qualified.

`dictionary_corpus.py` imports original Platts HTML captures and Cologne-derived
Sanskrit JSON. Records retain the source language, headword spelling, edition,
page/locus, entry/sense IDs, full context and exact witness hash. A printed entry
without enumerated senses remains an `entry_context` candidate; punctuation is
not used to invent dictionary-authored sense numbers. Fetch failures, exact-query
misses and empty source fragments remain distinguishable. Native Unicode
canonical equivalence is allowed; diacritics are not removed to invent a match.
Hindi evidence is never silently assigned to Punjabi or Sanskrit.

The integrated automatic support producer can now ask the existing glossary call
for up to four English lookup candidates per targeted span, retrieve their full
WordNet alternatives, and supply witnessed source entries and English definitions
to translation and independent review. Enable it for private qualification with
`BHAKTI_AUTO_LEXICAL=1`, `BHAKTI_WORDNET_DIR`, optionally
`BHAKTI_WORDNET_EDITION` (default `3.1`), and a JSON directory array in
`BHAKTI_SOURCE_WITNESS_ROOTS`. `BHAKTI_LEXICAL_SUPPORT_CACHE` sets the private
lookup cache. Missing evidence remains an explicit gap. Cumulative lookup
requirements survive selective repairs and resumed acceptance; an English
dictionary update reuses compatible source glosses and reruns English/review.
This producer performs no additional model call for lookup. Its existing-call
prompt/output additions still have token cost.

Callers with known problem words supply `options.lexical_requested_spans`, each
with `line_id`, ordered `word_indices`, exact Roman `surfaces`, and `reason`.
These request evidence without prescribing an English answer or inventing a
review defect. The initial glossary must provide lookup hypotheses or an explicit
gap for each requested span. Stale spans and disabled lookup configuration hold
before provider calls. Requests survive source-context batching and resume;
absent/empty requests preserve existing cache identities. An explained gap is
not dictionary/embedding qualification. The existing automatic review-to-repair
path still requires lookups for newly detected issues; easy unrequested words
may use contextual interpretation.

Automatic source-form discovery is connected: the glossary can propose up to two
lookup forms for an uncertain span. Existing reader mappings supply the native
form first; fresh transcripts without such mappings retain explicitly proposed
forms as hypotheses. The Hindi Platts adapter passes full witnessed definitions
to both translation and review. Each selected relationship needs an evidenced
decision; a discovery that changes the source gloss returns to targeted gloss
repair. Neither acquisition nor a root resemblance silently changes the word map.
Intake and library runs share a persisted source-request allowance and deadline
(`--source-discovery-max-requests`, default 16). Missing counters stop acquisition
instead of creating a fresh allowance.

Accepted semantic runs bind the actual dictionary evidence they used. A relevant
evidence change renews English and independent review with a validated glossary;
unrelated cache growth does not renew the run. Fresh-source processing now uses
the same selective semantic coordinator, including materialized-evidence renewal
under unchanged configuration. Source acquisition precedes the first English ranking query.
New definitions enter that query as explicitly unselected hypotheses bound to
the exact source language, line and token span; the complete definitions also
reach wording and independent review. Acquisition does not select a sense or
silently change the source glossary.
Punjabi and Tamil acquisition now use separate DDSA adapters for Bhai Maya Singh's
Panjabi Dictionary and the University of Madras Tamil Lexicon. They preserve full
entries and homographs, printed supplement loci, exact-query misses and one shared
run allowance. A Punjabi word never falls back to the Hindi adapter. Inflected
source-to-headword claims reach the actual translation/review callers; a stem
entry alone does not establish the meaning of its ending. The source-form
decision contract uses `inflected_form`: the
attested lemma must be a witnessed headword and quotation, with a nonempty
`form_explanation` accounting for the performed ending or particle and its role
in the whole line. The target's original indices/spelling remain unchanged.
This explanation is a model claim for independent review, not dictionary proof;
a disagreement follows the existing typed glossary/frame repair path.
The default five-entry Hindi corpus has no token matches in the five representative qualification songs;
configuring an encoder alone cannot correct that coverage gap. No full-library
translation-quality claim follows from these structural tests.

Example preparation, using private paths and an explicit JSON array of native
queries:

```sh
python3 scripts/dictionary_corpus.py acquire \
  --queries /private/path/native-queries.json --cache /private/path/platts-cache
python3 scripts/dictionary_corpus.py platts-cache /private/path/platts-cache \
  --output /private/path/platts-candidates.json
python3 scripts/dictionary_corpus.py csl /private/path/mw.json \
  --code mw --edition 1899 --output /private/path/mw-candidates.json
python3 scripts/bhakti_lexical_retrieval.py build \
  --lexicon /private/path/reviewed-corpus.json --index /private/path/lexical.sqlite
```

Acquisition makes dictionary HTTP requests, not model calls. Inspect its error/gap
report and review lemma links before using the resulting corpus. A broader
`--matchtype containing` query is acquisition evidence only; it does not relax
exact matching in the translation engine. Keep raw captures, normalized corpora
and indexes private, honoring their source licenses. Do not put them in static
song pages or copy a dictionary translation over the song's gloss-derived English.

SQLite indexes exact aliases and lemma links; runtime lookup reads only the
needed entries. The index binds the full corpus content hash and file identity.
A changed configured corpus is rejected until an explicit rebuild. A rebuild
retains reusable content-addressed vectors; it does not make an old vector valid
for changed source text, context or embedding configuration.

The encoder is `google/gemini-embedding-001` through OpenRouter's Google Vertex
route, with 768 dimensions and one shared default task space for documents and
queries. The exact observed response alias `gemini-embedding-001` is accepted for
that canonical request; other models are rejected. There is no claim that a
provider-specific retrieval task parameter was forwarded. Cache keys bind model,
provider, dimension, task, formatting version, exact text and source-entry hash.
Only currently retrieved candidates are embedded, never the whole corpus by
default. The conservative input cap is 2,048 UTF-8 bytes per string. Longer
queries repeat each complete performed context and grammar alongside contiguous
source-definition spans, bounded to 32 parts and 64 total embedding inputs per
target. Scores are weighted by span length within each complete evidence item,
then equally across distinct performed contexts. The maximum across separate
evidence hypotheses only prioritizes English exploration; it does not choose
the source meaning. Incomplete coverage yields an explicit unranked status and
preserves the full evidence for translation/review. English definitions that do
not fit remain available without ranking. Without a configured encoder, cache
misses are reported as missing ranking evidence. Existing unchanged short-query
vectors remain reusable under their original identity.

The live qualification returned real 768-dimensional vectors. In the actual
“मन रे तू चल अपने निकेतन में” context, the saved candidates ranked **will, mind,
heart, weight**. Mind outranked weight, but will ranked above mind. This is direct
evidence that similarity is a retrieval aid, not the semantic selector. The two
qualification requests reported $0.00006525; that small test does not establish
whole-song translation quality. The original failed alias-validation reservation
remains in the accounting history. See the [OpenRouter embedding API](https://openrouter.ai/docs/api/api-reference/embeddings/submit-an-embedding-request)
and [Google embedding documentation](https://ai.google.dev/gemini-api/docs/embeddings).

## Models, finite attempts and cost

The library stage router starts with `google/gemini-3.7-flash` through OpenRouter.
An eligible failed unit may receive at most one
`google/gemini-3.1-pro-preview` attempt. These are the router's supported defaults,
not a claim that Pro is always necessary or a newer model is better. Stage
validators and independent review determine acceptance. Missing source evidence
and locked-baseline conflicts do not become reasons to spend more on Pro.
Transport failures escalate only under the route's explicit classification;
unknown outcomes require worker termination and retain their reservation.
Authentication, budget, persistence and unreconciled active-request failures stop
the run. Restarting does not create another Flash or Pro allowance.

New intake and fresh-source repairs share separate glossary, writer and reviewer
routes. A malformed reviewer response retries the reviewer while preserving the
writer's English; a valid source-sense objection repairs the implicated glossary
before rewriting. A valid English objection reuses the glossary and repairs the
writer. Subsequent independent review starts at the baseline model. Explicit
`semantic_stage_escalation=False` disables Pro for a bounded baseline experiment;
zero semantic repair rounds alone does not disable malformed-output escalation.
An unresolved, validated semantic judgment is saved as `SemanticQualityHold`
with exact source/gloss/candidate file hashes. That outcome does not establish
payment settlement: a batch must separately check its ledgers before continuing
other songs. Generic transport, persistence and budget failures remain distinct.

Chat and embeddings have separate ledgers and call caps. Their combined limits
must fit the approved total. Each reserves a conservative amount before dispatch,
retains raw responses and reported usage, and preserves unknown cost until it can
be reconciled. Embedding requests are serialized, stop after failure, and never
retry automatically. A validated embedding response does not clear a previously
blocked ledger. Provider costs and reservations are different quantities; report
both rather than calling an unknown outcome free.

Keep credentials in the existing secure configuration: `OPENROUTER_API_KEY_FILE`
points to an owner-only file, or the existing environment/hosted secret supplies
the key. Never put the key value in an argument, example, report or repository.
Together's text route does not replace audio-capable Gemini; its failed sung-audio
qualification remains documented separately.

## Inventory, run and resume

The inventory uses a fixed committed catalogue revision. Unpublished intake
folders cannot enter the population, and working readers that diverge from that
revision are held rather than overwritten. Every catalogue member receives a
state and evidence record; Patta and Rehna are first in the current priority
order. Dry preparation makes no model calls:

```sh
python3 scripts/bhakti_library_pass.py --root /path/to/bhakti \
  --catalogue-ref COMMIT_SHA --state-dir /private/path/library-run
```

To activate the reviewed index and bounded lazy embeddings, set these variables
before building the run inventory. Replace the numeric placeholders with the
approved allowances; the deadline is an absolute Unix timestamp.

```sh
export BHAKTI_LEXICON_PATH=/private/path/reviewed-corpus.json
export BHAKTI_LEXICAL_INDEX=/private/path/lexical.sqlite
export BHAKTI_EMBEDDING_LEDGER=/private/path/embedding-ledger.json
export BHAKTI_EMBEDDING_BUDGET_USD=APPROVED_EMBEDDING_USD
export BHAKTI_EMBEDDING_MAX_CALLS=APPROVED_EMBEDDING_CALLS
export BHAKTI_EMBEDDING_DEADLINE_AT=ABSOLUTE_UNIX_DEADLINE
```

After the integrated execution path has been qualified, the same command accepts
bounded execution flags:

```sh
python3 scripts/bhakti_library_pass.py --root /path/to/bhakti \
  --catalogue-ref COMMIT_SHA --state-dir /private/path/library-run \
  --execute --all --budget-usd APPROVED_CHAT_USD --max-calls APPROVED_CHAT_CALLS \
  --deadline-seconds 1800 --timeout 600
```

Use `--slugs patta-bola-vrksha-se rehna-nahi-isa-desa` instead of `--all` for that
subset. Model flags are `--model` and `--pro-model`; use only a route the bounded
client supports. `--flags` accepts a JSON object keyed by published slug; an
explicit `audio` flag requests the supported source route, not a promise that
missing source evidence can be repaired. `--source-reuse-maps /private/path/maps.json`
accepts a JSON object mapping a published slug to its reviewed source-reuse map
path; those exact file hashes are frozen into the run identity. The source adapter and reviewed
source-equivalence map integration must be ready for the selected case; unsupported
or ambiguous repairs remain held. No command here publishes a candidate.

Resume by repeating the execution command with the **same state directory,
revision, selected population, models and limits**. `run.json` freezes input
fingerprints and the original absolute deadline. Accepted stage artifacts and
source checkpoints are reused only when their identities and validators still
match. Completed per-song outcomes, including unresolved ones, are not silently
retried. Changed inputs or limits require explicit reconciliation and a new plan;
deleting caches or creating a fresh state directory to reset paid attempts is
not recovery. An exhausted deadline is not extended by restarting.

Inspect `inventory.json`, `queue.json`, `frozen-inventory.json`, `run.json`,
`api-ledger.json`, route attempt records and per-song private candidates. Distinguish
`protected`, `review-needed`, `repair-needed`, `unresolved`, `accepted` and
`untouched-valid`: acceptance concerns the evidenced candidate, not deployment or
fresh audio clearance. A whole pass ending with unresolved songs is unfinished
content work. The runner preserves remaining work when a bound stops execution.

Current-reader audits retain valid findings independently of malformed sibling
rows or later model approval. The runner reconciles the finding journal with
the original attempt artifacts on both fresh and cached execution. Returned
partial reviews survive transport failure; unknown outcomes keep their original
retry restrictions. Descriptive notes with an explicit false review flag are
observations, while actual open choices remain holds. A targeted repair must
match the original source-word quotation and receive an explicit independent
disposition for that finding. Private partial repairs cannot be published while
other findings remain unresolved. Older failed artifacts without an integrity
anchor require explicit reviewed recovery; their provenance is not invented.

The source adapter also contains bounded observation operations for short or
focused audio units. These preserve raw observations, exact source hypotheses
and frozen textual witnesses, with independent unit retries. They do not yet
replace the library caller's source-repair path: long-recording partitioning,
discrepancy adjudication and guarded source-delta adoption still need integration.
An observed segment is neither a complete-source certificate nor permission to
publish a changed reader.

Only confirmed target fields may change; metadata, other lines, timing and owner
English retain their guards. Source/order changes invalidate dependent timing and
semantic work; gloss changes invalidate affected English/review, and timing-only
changes need not rerun translation. Publication still requires the content,
audio, trim and in-app-browser checks in [the processing standard](SONG_PROCESSING_STANDARD.md)
and [design standard](DESIGN_STANDARD.md), followed by review of the exact scoped
diff. The library runner produces private candidates and has no `--publish` flag.

### Lexical evidence and language resolution

Policy version 4 sends each dictionary entry and repeated source passage once,
with explicit entry, sense, token and context references. It retains all candidate
senses and their citations; an embedding score still ranks evidence rather than
choosing a translation. A saved Rehna request reconstructs exactly while shrinking
from 468,914 to 163,332 characters (65.17%). This is a measured request-size
reduction, not a measured provider bill or translation-quality improvement. The
policy version invalidates older semantic request caches; do not insert this
change into an already-frozen version-3 paid run.

An empty or absent per-line language falls back only to one unambiguous known
language in the song's language list. A nonempty unknown language, invalid
metadata, or multilingual ambiguity stays unresolved. This fixes generated empty
labels that had suppressed dictionary retrieval, including 105 lines in six
recent readers. An existing explicit language remains authoritative; script alone
does not determine language (for example, Sanskrit can be written in Kannada).

The [recent-song editorial review](RECENT_SONG_EDITORIAL_REVIEW.md) is a concrete
failure set for future pipeline qualification. Passing schema, token indices or a
model's fidelity flags is not proof that the resulting English is grammatical or
faithful. Read the joined verse and its returning variants; reconcile the chosen
sense, source agency, imagery, English phrase and clickable word map together.

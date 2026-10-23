# Contextual translation engine

Status checkpoint — 22 October 2026: the contextual-sense, indexed-retrieval,
bounded Flash→Pro routing, retained-review-finding and targeted-repair components
are implemented. The live priority run used a private corpus of **178 entries /
192 senses** and OpenRouter `google/gemini-embedding-001` at 768 dimensions:
**5 validated embedding calls, $0.0023958**. The embedding ledger and SQLite cache
were carried forward without resetting spent allowance. This was selective
retrieval for the priority songs, not embedding or qualifying the whole library.
The repository's default JSON lexicon remains the smaller 5-entry / 19-sense set;
the expanded corpus/index must be configured explicitly.

**The whole automatic library pass has not succeeded or been qualified.** The
priority run exposed real source, timing and translation holds; later model
agreement does not erase an earlier concrete finding. Current boundaries are:

- `bhakti_library_pass.py` executes its song loop serially. Production intake in
  `bhakti_pipeline.py` has parallel song workers; those are different callers.
- A general source-investigation caller is still missing. Registered source
  witnesses and dictionary acquisition exist, and the library source adapter
  handles reviewed cached reconstruction, but its current `run_source_candidate`
  path explicitly holds broader `audio-review` / `focused-audio-review` requests.
- Review receives target English, neighboring source and explicitly referenced
  distant source/gloss/English. Complete assembled English context for every
  review batch is still pending; a whole-candidate hash is not visible context.
- Connotation and compound handling are prompt/editorial rules, not a dedicated
  semantically validated module. Sense-ID/alternative checks establish structural
  accountability, not linguistic correctness or cross-language qualification.

Evidence for this checkpoint is the actual maintained caller/policy/retrieval
code and the retained priority-run embedding ledger (five validated requests).
No additional paid calls were made for this status update. Gemini 3.7 Flash is
the normal first route, with bounded Gemini 3.1 Pro escalation for failed units;
owner English, original failed evidence and unresolved holds remain protected.

## Recovered design and available assets

The maintained Vedanta design is source-first: exact witness and context → word
division and grammar → traditional adjudication where needed → reviewed English.
Its [translation standard](../../vedanta-timeline/docs/SANSKRIT_TRANSLATION_STANDARD.md),
especially §§6.3, 7 and 8, requires contextual senses, complete grammar, concrete
images and meaningful names. Ordinary concepts become precise English phrases;
preservation in IAST requires a deliberate reason. Multiple meanings can remain
active when the passage supports them; neither the surface referent nor its
poetry should disappear.

The current [grammar tooling boundary](../../vedanta-timeline/docs/GRAMMAR_ENGINE_INTEGRATION_PLAN.md)
explicitly supersedes the older parser-confidence design. Dictionary lookup,
parser agreement and embedding similarity are retrieval aids, not grammatical
or publication authority. The original research found no implemented embedding
dictionary engine in the Vedanta docs/scripts searched. Bhakti subsequently implemented its own indexed
retrieval and bounded embedding client; that implementation does not establish
semantic qualification of the wider design.

| Existing asset | Reuse | Limit |
| --- | --- | --- |
| `scripts/bhakti_translation_policy.py` and `data/bhakti_lexicon.json` | Shared editorial rules, language filters and per-token sense decisions; default 5 Platts entries / 19 senses; configured priority corpus 178 entries / 192 senses | Dictionary evidence is language-specific; no general inflection analysis or comprehensive cross-language qualification |
| `scripts/dictionary_corpus.py`, `scripts/bhakti_lexical_retrieval.py`, `scripts/bhakti_embedding_client.py` | Source-backed acquisition, derived SQLite lookup, cached exact/dense ranking and bounded embedding requests; exercised in the priority run | Selective live retrieval is not a whole-corpus embedding or a successful automatic library pass |
| `scripts/bhakti_pipeline.py` | Audited performed text; gloss → frame → English → independent review; actual neighboring source context; exact caches, scheduler, deterministic generation | Faithfulness flags are model claims; the demonstrated Har Jīu agency error passed them |
| `scripts/editorial_baselines.py` | Saved owner English enforcement before writing | Never rewrite the owner's English to fit a new analysis; report conflicts separately |
| `scripts/audit_translation_style.py` / `scripts/retranslate_bhakti.py` | Existing-text audit and explicit gloss reconstruction | Choose reconstruction when glosses are wrong; polishing English cannot repair them |
| [Vedanta source locator](../../vedanta-timeline/docs/SOURCE_LOCATOR.md) and [provider registry](../../vedanta-timeline/docs/SOURCE_DATABASE_REGISTRY.md) | Existing discovery map, source pointers and acquisition records | A provider listing is not an admitted lexical entry |
| [Prakriya source manifest](../../prakriya/sources/manifest/clean_witnesses.json) | Read-only Sanskrit witnesses, hashes, raw/clean links, limitations; Amara, Yādava, Halāyudha, Vaijayantī and grammatical sources | Research eligibility is not semantic approval; preserve apparatus and unresolved readings; do not import its unfinished interpreter |
| [Prakriya lexical method](../../prakriya/research/recovery-v1/agent-workflow-20261020/lexical-method.md) | Complete entry/context, local restrictions, competing attachments, discriminating evidence, narrow result | A research procedure with pending qualifications, not executable or universally verified rules |

Apply those source principles to each song's actual language. Do not force Hindi
dictionary meanings onto Punjabi, or Sanskrit derivation rules onto a modern
vernacular. The Bhakti user authorizes automatic agent review and repair; this
does not make similarity scores or unexamined model agreement sufficient evidence.

## Original implementation sequence

The following sequence records the design intent. JSON sense decisions, SQLite
retrieval and the embedding client now exist; the checkpoint above states what
has actually run and what remains unfinished. These steps are not completion
claims.

1. **Use the existing JSON evidence first.** Extend the existing lexicon schema with
   stable entry/sense IDs, language/register, exact headword/homograph, native and
   reviewed roman lookup keys, dictionary edition/locus, source URL and captured
   text hash, exact evidence spans, restrictions, provenance and review status.
   Keep source quotation, dictionary interpretation and song-specific sense
   decision distinct. Import only the vocabulary needed by the current library
   first. Source acquisition and agent verification can run automatically; an
   unavailable or damaged witness becomes a named dependency, not an invented
   definition. Preserve source licenses and keep restricted corpus material out
   of public song payloads.
2. **Retrieve candidates locally.** Keep the existing exact JSON lookup as the
   first implementation; add explicit context and selected-sense records to its
   live gloss/translation/review callers. Preserve native-script identity;
   diacritic folding may discover
   candidates but cannot merge entries or authorize source correction. Unknown
   language, inflection or compound segmentation triggers a bounded analysis /
   lookup task. Any proposed lemma link remains attributable and reviewable.
3. **Add indexed/dense ranking only when needed.** Once vocabulary growth or a
   measured retrieval failure warrants it, add derived SQLite text lookup and
   embed individual sourced
   senses with their headword, restrictions and short context, not whole books
   or existing English song translations. Retrieve exact matches first; use
   dense ranking for contextual ordering and related evidence discovery. Return
   all relevant homograph alternatives with small entry sets; for larger sets,
   preserve explicit alternative coverage rather than trusting a top-one result.
   Keep retrieved evidence separate from a selected sense. SQLite plus cached
   vectors and an exact cosine scan is sufficient initially; no hosted vector
   database, graph framework or new website component is needed.
4. **Make the semantic decision explicit.** For each source token/span, the
   gloss stage records candidate IDs, chosen sense(s), rejected alternatives,
   contextual rationale, grammatical role and evidence. Include the actual
   stanza/neighboring lyrics, expanding across a batch boundary when a clause
   remains incomplete. Named entities receive an evidenced identity/relationship
   or literal epithet gloss. Ordinary concepts receive contextual English.
   A missing lexical entry is a retrieval gap, not proof the sense is absent.
5. **Review source first.** An independent reviewer derives agency, attachments,
   negation, scope and images from the source and evidence before comparing the
   draft frame and English. It checks meaning-bearing English spans against the
   source word indices, including implicit grammatical function words. It must
   identify unsupported frame claims and empty repeated-name glosses. Derive the
   final English from accepted contextual glosses; do not use a borrowed full
   translation as the answer to imitate.
6. **Repair only failed units.** A typed failure returns to its responsible
   stage: `missing_evidence`, `language_or_lemma_conflict`, `agency_or_attachment`,
   `sense_conflict`, `imagery_or_omission`, `alignment`, or `owner_baseline_conflict`.
   Gemini 3.7 Flash handles normal work and one evidence-informed repair. Escalate
   an unresolved semantic unit to an explicitly configured, currently qualified
   Pro model, then independently review the repaired result. Limit attempts and
   spend; unresolved facts remain unpublished while unaffected units continue.
   No repeated approval request is needed for ordinary authorized repairs.

The first slice extends `scripts/bhakti_translation_policy.py` and its existing
JSON records, threads explicit sense decisions through the production text
stages, and routes `scripts/retranslate_bhakti.py` through those same stages.
That closes the existing-song bypass immediately, without a disconnected
retrieval adapter. Keep decisions in private artifacts rather than changing the
public reader schema. The separate index builder and embedding client have since
been implemented and used on the priority run. The broader semantic qualification below is still
required; those live calls do not establish its success.

Cache keys include exact source and neighboring-context bytes, language/lemma
analysis, witness/entry revisions, retrieval algorithm, embedding model revision
and dimensions, task format, policy, generation/review model and schema. A changed
dictionary or context invalidates dependent decisions, not the audio transcript.
Validate response cardinality, indices, finite vectors and dimensions; never
silently truncate an entry or reuse vectors from another embedding space.

## Embedding options checked against current primary documentation

| Option | Practical fit | Qualification needed |
| --- | --- | --- |
| `google/gemini-embedding-001` through OpenRouter | Reuses the existing provider/credential boundary; listed at $0.15 per million input tokens when researched | Check current availability and provider parameter support at preflight; qualify actual Indic retrieval, rather than extrapolating from multilingual rankings |
| Local `intfloat/multilingual-e5-small` | MIT model; 384 dimensions, 512-token input limit, documented query/passage prefixes; no per-request API charge | Pin model revision, include download/runtime/startup cost, prevent truncation, and evaluate low-resource languages; the model card explicitly warns their performance can degrade |

OpenRouter documents `/api/v1/embeddings`, `dimensions`, `input_type` and indexed
responses. Its API field does not alone prove that every provider honors the same
task semantics. [OpenRouter API reference](https://openrouter.ai/docs/api/api-reference/embeddings/submit-an-embedding-request).
The quoted price is a planning input, not a budget authorization.
[Model listing](https://openrouter.ai/google/gemini-embedding-001).

Google documents separate retrieval-query/document task types for Embedding 001
and 768/1536/3072 dimensional options. Its newer Embedding 2 has different task
formatting and multi-input aggregation behavior; it is not a drop-in adapter
replacement. Text-only dictionary retrieval does not require the multimodal
model. [Google embedding guide](https://ai.google.dev/gemini-api/docs/embeddings).
The local alternative's usage and limitations come from its authors'
[model card](https://huggingface.co/intfloat/multilingual-e5-small).

**Adapter exercised in the priority run:** OpenRouter Embedding 001, 768
dimensions, through the bounded client. Actual validated responses establish
that exercised transport/dimension path, not general Indic retrieval quality.
Keep the local encoder as an alternative to qualify if API access is unavailable
or measured costs justify it. Both remain optional ranking aids; exact
lookup and evidence-based review work without them. Do not run two encoders over
the entire library merely to choose one.

## Acceptance and automatic rollout

Before any paid run, freeze the source vocabulary, exact evidence records,
representative evaluation cases, allowed model route, maximum calls/tokens/cost,
latency bound and stop conditions. Reserve charge before dispatch in a
process-safe ledger, retain unknown outcomes, and reuse exact cached responses.
Inventory and deduplicate repeated words/contexts before making requests.

The first offline tests cover language separation, homographs, compounds,
missing evidence, stale hashes, source spans, cache invalidation, owner English,
and malformed vectors. The semantic qualification set must include the known
Har Jīu sin-cutting agency error; Gagana's flowers/light imagery; Guru chanting
causation; Jo Naru's merging subject; meaningful Nānak/Govinda name glosses; and
contrasting man/rāg/ras/māyā/hār senses. Recheck each expected reading against its
source, not a frozen model output. Add representative actual lines for every
language admitted in a rollout; the five Hindi entries do not qualify Punjabi,
Tamil, Sanskrit or the whole library.

Compare exact retrieval against exact-plus-dense on that fixed set: required
evidence recall, exclusion of wrong-language entries, chosen-sense correctness,
agency/images/omissions, popup alignment, latency and total cost. Accept dense
ranking only if it preserves required evidence and provides measured benefit.
Accept a semantic route only when every case in its declared population is
accounted for and every material error is resolved or explicitly held. Numeric
coverage, confidence and a few attractive examples cannot certify fidelity.

Then qualify the automatic workflow on the targeted song population. The current
library executor is serial; parallel production intake does not yet supply
parallel library-pass execution. Preserve transcript/audio/timing artifacts for
text-only repairs. Publish only after source/evidence review, alignment and owner
baseline gates pass; retain a per-unit evidence/review ledger and re-open only
dependencies of later corrections. Report actual coverage and unresolved items,
without claiming that a dictionary index solved all translation problems.

## Reusing the existing agent harness

Read-only research found a working adaptive-worker boundary in
[`shilpa/scripts/task-together.mjs`](../../shilpa/scripts/task-together.mjs)
(`openTogether`), [`src/together.ts`](../../shilpa/src/together.ts)
(`create_together_driver`) and [`src/provider.ts`](../../shilpa/src/provider.ts).
It composes DSH tools and retained sessions, explicit tool/write scope, request
identities, cancellation/reconciliation, request limits and absolute deadlines.
Its provider transport delegates monetary accounting to a separate broker and
budget. Reuse must retain a Bhakti-owned reservation; another project's wallet
or old run allowance is not transferable.

The [Prakriya direct Together study](../../prakriya/docs/DIRECT_TOGETHER_AGENT.md)
records successful transport/source access but a rejected lexical-procedure
report: valid citations did not prevent wrong local-symbol and attachment rules.
Shilpa's [status](../../shilpa/README.md) likewise separates working components
from unfinished whole-workflow qualification. Time Crystals' current
[procedure](../../somu/time-crystals/RESEARCH-PROCEDURE.md) and
[implementation ledger](../../somu/time-crystals/planning/research-design-tasks.md)
distinguish archived controllers from the partially implemented replacement.
None establishes a qualified Bhakti agent engine.

The narrow proposed reuse is an optional bounded source-investigation worker for
a named missing lexical, compound or syntactic dependency. Give it exact source
copies and read/search tools; require cited spans, competing readings, the
evidence distinguishing them and any unresolved dependence. Review those findings
before admitting evidence into the existing lexicon and sense decisions. Keep
complete-context gloss/translation/review in the existing pipeline; a question
whose evidence is already supplied does not need a persistent tool loop. No new
agent/provider route was activated by this research.

For connotation and compounds, reuse the Vedanta standard's §§6.3, 7.4–7.7 and 8:
distinguish attested meanings from meanings activated by the present passage;
preserve literal referents, grammar and images; reject English with added
overtones. Its examples distinguish governable from servile “biddable” and
affection from weaker “fondness.” A transparent English compound is useful when
its parts and relation preserve the source and remain intelligible; otherwise
use a precise short phrase and meaningful gloss. Do not concatenate every
dictionary sense. No named Joycean/portmanteau engine was found in the inspected
Vedanta, Prakriya or Anvaya design files. Such handling remains a contextual
editorial procedure to qualify, not an implemented generator of compounds.

## Bounded semantic repair implementation

`bhakti_semantic_repair.py` now connects the production `run_one` caller to typed
independent-review feedback. A gloss-sense or grammatical-frame defect rebuilds
the affected word map before deriving English again; an English-only defect
keeps the accepted glosses. The assembled result receives another independent
review, including referenced distant source, gloss and English context. At most
two repair rounds are allowed. Missing source evidence and locked-owner conflicts
remain holds; the implementation does not clear adverse review flags.

Repair dispatch requires `BHAKTI_API_RUN_LEDGER` and a positive
`BHAKTI_API_RUN_BUDGET_USD`. `--semantic-repair-seconds` defaults to 600 seconds
for the semantic run; `--semantic-repair-rounds` accepts 0–2. Absolute deadlines
survive resume and are checked after the shared scheduler and immediately before
the bounded worker dispatch. A restart cannot reset spent rounds or money. Use
one active process per song; overlapping independent launches are unsupported.

Exact compatible existing gloss/English artifacts are reused. Historical English
without recording/order context is retained as a draft for fresh review instead
of being regenerated. Adopted candidates persist before the first gloss checkpoint
so interruption also preserves that saving. Acceptance binds the performed order,
actual audio hashes, trim evidence and exact semantic pair. Generation and
generate-only hydration both require that accepted pair for repair-managed songs.
Owner-supplied English remains exact at every acceptance and publication boundary.

The initial repair slice was independently reviewed with 33 semantic and 15
local transport tests; later routing, retrieval and finding-preservation changes
have their own focused checks. These are historical slice results, not a current
whole-harness test total. The later priority runs exercised real held cases but
left unresolved defects; source-first qualification of the intended population
is still required. Each production run must freeze its exact reviewed code and
exclude unrelated unreviewed local pipeline edits. Exact-response replay wrappers must forward optional
`deadline_at` to the bounded transport.

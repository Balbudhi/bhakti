# Qualification plan: semantic and musical shuffle

15 November 2026. This extends [the research assessment](SHUFFLE_RESEARCH.md) with ant-colony and local/global optimization, measured feature feasibility, and a mandatory intake contract. The research sections below preserve the original research-only scope and evidence; the subsequent implementation authorization and current state are recorded here.

## Active implementation — authorized 15 November 2026

The owner authorized implementation and release. Implemented outcome: theme/audio-informed ordering over every selected occurrence, automatic assessments on future intake, and preserved queue/share behavior. Work was isolated on `codex/intelligent-shuffle`; the original dirty workspace was untouched. The release population is the 353-song catalogue at `ea872026`. Engine, queue integration, intake coordination, source-bound editorial reductions, final projection and public assembly passed focused independent review and checks. Real callers are the existing library shuffle event and playlist shuffle action; normal intake, generate-only and site assembly enforce their assessment duties. All 353 audio and 350 semantic assessments are accepted; three upstream source/translation exceptions remain explicit. The completed budget is 794 calls and $9.235581375 accounted including the reserved failed request, below the original $10/850-call cap. Release verification uses the exact committed artifact and automatic Pages deployment.

Budgets: semantic pilot $2 /120 calls /45 minutes; total including pilot $10 /850 calls with no model escalation. Cached per-song proposal/review only, never pairwise calls. Audio uses local extraction, private exact-hash recovery of missing published media, bounded isolated tool/model qualification. Method accuracy and listener utility are not inferred from execution success.

## Implemented behavior and evidence

The runtime is browser-local iterated local search: eight varied complete constructions, at most 256 local proposals, and randomized selection from a bounded archive. Themes, devotional actions, named-subject roles, measured body sound and directional ending-to-beginning sound contribute separately. A recent-window term discourages repetition. These weights are explicit engineering choices, not a validated listener preference model. No singer/composer match stands in for meaning. No tag or measurement is required for membership in a listening queue.

Library shuffle uses every currently visible song. Playlist shuffle preserves every played/current occurrence and its playback position, then orders only the upcoming suffix. Occurrence identity is preserved, including duplicates. Explicit-order share links preserve the result independently of future metadata; legacy seeded links retain their decoder. Invalid or mismatched runtime profiles fall back to the existing random ordering. Public assembly rejects missing or stale required assessments rather than publishing mismatched inputs.

All retained recordings receive whole-stream physical measurements plus beginning/end windows. BPM, key, mood, learned embeddings and crossfades are not enabled. The initial beat-checkpoint server failure was resolved through an author-confirmed mirror; a subsequent neural probe executed successfully. Neither that probe nor the classical baseline has independent beat annotations for these Bhakti recordings, so rhythm accuracy remains unqualified. See the [rhythm follow-up](research/shuffle-qualification-2026-11-15/rhythm-followup.md). The sound component uses the measurements actually qualified here. The separate [audio qualification report](research/shuffle-qualification-2026-11-15/audio-qualification.md) records methods, domains and limitations.

Semantic extraction and a separate reviewer see the complete unique performed text, accepted English and literal glosses. Controlled definitions distinguish themes, actions, named subjects and their roles. Unsupported assertions are rejected; neutral unknown is valid. Independent source review led to three conservative reductions, stored separately from immutable model receipts. New source or changed base features cannot silently inherit those editorial decisions. Three pre-existing upstream source/translation exceptions remain explicitly unavailable; every other current song and future intake requires current assessments. See the [operational contract](TRANSLATION_WORKFLOW.md#mandatory-shuffle-assessments).

Integrated browser evidence on the 345-song snapshot: twelve real-profile runs preserved membership, with 23.3 ms median and 30 ms maximum ordering time in the Codex in-app desktop browser. Full-library shuffle, suffix reshuffle while playing, two-occurrence fixed prefix, explicit share URL and exact reload order passed. A 390×844 viewport produced a seven-song Namdev search queue containing exactly the selected titles, played a newly added recording, and had no horizontal document overflow. This is desktop CPU with a mobile viewport, not a physical-phone speed claim. Numerical objectives and playback checks do not establish improved human enjoyment; there was no blinded human listening study.

The required contract and retained-audio audits pass on the expanded 353-song snapshot. The trim command passes but checks zero historical private receipts in this isolated checkout; no audio or timing was changed. Python compilation passes. The unchanged legacy pipeline suite has four baseline failures reproduced before these changes; the new profile and actual-caller integration tests cover the changed behavior. The final paired profile revision is `ca868db3411ebf807633812f9528d69b5ad05274e1ec66f6bee0103d3ca842c2`. The 354-entrypoint asset check and exact public assembly pass. [Sixteen final-population runs](research/shuffle-qualification-2026-11-15/engine-sanity-final-353.json), alternating fresh shuffle and a two-occurrence fixed prefix, preserved membership and profile inputs; mean ordering time was 29.95 ms, maximum 36.48 ms. The [actual solver and exposure report](research/shuffle-qualification-2026-11-15/engine-benchmark-actual-345.md) preserves the earlier frozen 345-song comparison and its 1,024-seed rare-track follow-up. ILS outperformed ants at matched time; the sparse initial exposure concern did not persist. The [semantic qualification report](research/shuffle-qualification-2026-11-15/semantic-qualification.md) records actual coverage, error controls, costs and limits.

## Outcome and order of work

Produce an ordering preference over every eligible song occurrence, using information whose meaning and reliability have been established on this library. The plan must connect actual media/text → assessed attributes → calibrated transition components → complete-order optimization → listener evaluation → future intake enforcement. A better optimizer cannot repair incorrect meanings or unreliable musical attributes.

Original research sequence: identify obtainable information on real examples, specify the acquisition/review contract, and compare algorithm families theoretically. Then: a bounded representation qualification experiment, followed by exact-oracle and realistic ordering comparisons. Runtime integration follows only after those results support it. Existing queue ownership, shared order compatibility, and the two distinct shuffle operations remain as specified in the earlier assessment.

The leading algorithm comparison is **iterated local search versus ant-colony construction plus the same local search**, with simulated annealing and bounded block optimization as controls. Ants are a serious candidate, not a predetermined winner. The desired output is a varied family of good orders; repeatedly returning the single lowest-cost order is not a satisfactory shuffle.

## The theoretical problem

Each queued occurrence is a vertex, including intentional repeats of the same recording. Playlist shuffle holds the played/current prefix fixed and permutes only the remaining multiset; fresh library shuffle starts a new session from the selected visible set. Let the remaining order be π and its inherited recent context be h.

A useful objective family is

`E(π | h) = Σ transitionCost(previous,current) + λ Σ recentWindowPenalty + μ Σ positionOrTimePenalty`.

The first component combines separately normalized lyrical and acoustic evidence; it may be directional because the ending of A and beginning of B differ from the reverse. Window terms represent monotony or repeated singer/subject, not an obligation to maximize dissimilarity. Position/time terms may account for short sessions and exposure. Do not invent personalized familiarity without actual history. Unavailable features contribute neutral evidence on fixed scales; they never remove vertices.

With only additive adjacent costs this is a directed Hamiltonian-path problem, with an optional fixed start. General instances are NP-hard. Metric symmetric-TSP approximation guarantees do not transfer to arbitrary directed, nonmetric, or history-dependent costs. An energy arc is an optional preference hypothesis, not a default law. Global set diversity is unchanged by permutation and cannot optimize an ordering; diversity has to concern windows, prefixes, adjacency, or repeated sessions.

For exact reference, solve small directed additive instances with Held–Karp dynamic programming (`O(n²2^n)` time and `O(n2^n)` storage), or a correctly constrained integer-programming formulation. Use these to measure heuristic optimality gaps on the stated numerical objective. A finite-memory objective needs an expanded state or another exact formulation; an additive-path oracle cannot certify its optimum. None of these objective optima certify musical enjoyment.

### Ant-colony construction

In an ant-colony system, many simple constructive searches communicate indirectly through a table of edge preferences, conventionally called pheromone. A candidate adaptation is:

1. Start each ant with the fixed prefix boundary, or an independently selected first occurrence for a fresh session.
2. Construct a complete path through unvisited occurrences. Combine directed pheromone with an incrementally evaluated compatibility heuristic and explicit exploration.
3. Improve the constructed path with the same bounded swap/relocate search used by the non-ant comparator.
4. Evaluate the full objective, retain several good but distinct orders, evaporate old reinforcement, and reinforce a bounded number of successful paths.
5. Limit pheromone concentrations, detect stagnation, and restart or diversify. Stop at the explicit resource budget, not an imagined convergence certificate.

Using `exp(-incrementalCost/temperature)` avoids the undefined reciprocal of a zero distance; numerical bounds are still required. The complete candidate set remains available. A candidate list can accelerate proposals if there is a full-set exploration/fallback path, but even a membership-preserving list can restrict early choices and cause late outliers. Measure that effect explicitly.

Ant System, Ant Colony System, and MAX–MIN Ant System are distinct algorithms. ACS local pheromone updates and its exploitation rule should not be silently conflated with MAX–MIN bounds and best-ant reinforcement. A hybrid must be named as a hybrid and ablated. The original [ACS paper](https://faculty.csu.edu.cn/_resources/group1/M00/00/64/wKiylmHsBXyARBY7AAUIrZ-tJPM870.pdf) already evaluates a local-search-enhanced variant; attributing its success entirely to decentralized construction would be misleading.

Specify the first ant benchmark as a **MAX–MIN-derived adaptation**: immutable pheromone during each generation; independent seeded construction; the common local improver; deterministic reduction; evaporation and a predefined iteration-best/best-so-far deposit schedule; clipping to positive lower and upper bounds; a documented stagnation reset. This differs from ACS, whose local updates occur during construction. Use stable log probabilities proportional to `α log τ(i,j) − β ΔE(history,j)`, optionally mixed with a uniform exploration floor. Pairwise pheromone remembers edges; the actual incremental evaluator still handles history. Positive construction probability is not a practical coverage or finite-time optimality guarantee. Inverse-cost deposits additionally need strictly positive normalized scores; rank-based reinforcement is a separately declared variant.

The [MAX–MIN paper](https://www.cs.ubc.ca/~hoos/Publ/fgcs00.pdf) studies both local search and premature concentration. The [controlled iterated-local-search account](https://arxiv.org/pdf/math/0102188) uses the same fast 3-opt engine to distinguish perturbation from full restart. The [multi-colony study](https://iridia.ulb.ac.be/~mbiro/paperi/TwoStuDor-etal2010is.pdf) shows communication benefits depend on local-search strength and search duration. Accordingly test one colony, independent colonies, and infrequent ring/replace-worst exchange at equal total work. Exchange complete evaluated orders under one objective revision; do not average incompatible pheromone matrices or broadcast every improvement by default.

For 336 remaining occurrences, one all-remaining construction examines 56,616 candidate extensions; 16 ants × 32 generations examine 28,987,392 before local improvement. Count extensions, primitive feature evaluations, move proposals, and complete evaluations separately. Proposed 0.1/0.5/2-second single-core checkpoints are experiment budgets, not achieved browser latencies. A pheromone-disabled ablation must retain the heuristic, ant count, local improver and budget. Learned methods such as [DeepACO](https://papers.neurips.cc/paper_files/paper/2023/file/883105b282fe15275991b411e6b200c5-Paper-Conference.pdf) remain later comparators: their Euclidean routing experiments do not establish transfer to this history-dependent devotional objective.

“Decentralized” here describes coordination among searches, not a need for servers or listener devices to exchange state. Many ant methods still use shared pheromone and best-solution updates. At a few hundred songs, parallel local workers are an optional speed experiment; network distribution introduces communication and reproducibility costs without an established need. If independent colonies are tested, compare them to equally parallel independent local-search restarts, with the same worker and total CPU budgets.

Reset search learning per shuffle by default. Persistent pheromone changes results across sessions, can repeatedly reinforce the same adjacencies, and needs an explicit state/version/share policy. It should not emerge accidentally from caching. Pheromone strength is optimization history, not confidence that two songs are musically compatible.

### Local and whole-order improvement

Local search can improve a whole-order objective: a swap or relocation is a local *move*, not necessarily a greedy next-song decision. Iterated local search repeatedly improves a complete order, perturbs it, and improves again. Simulated annealing can accept worse moves to escape local minima. Larger-neighborhood removal/reinsertion is admissible only when every removed occurrence is restored before a candidate is accepted.

Start with relocation and swaps because their affected directed edges are relatively easy to reason about. Reversing a segment changes all its internal directed edges; symmetric four-edge 2-opt formulas are invalid without extra structure. For window or position terms, prove the affected-term calculation or recompute the full objective. Include cross-boundary effects from the fixed history.

Ant-colony reinforcement gives population memory; iterated local search gives trajectory memory; both can become trapped or repetitive. Compare each constructor before and after an identical improver. Retain stochastic output selection among several qualified orders and measure adjacency repetition across sessions, rather than claiming that stochastic optimization preserves uniform randomness.

Other serious comparators are best-of-K complete random orders, recent-window MMR, and bounded random-block optimization. Block membership provides a useful exposure control but limits available transitions. LKH/OR-Tools-style routing methods are relevant for the pairwise core, not automatically for the complete window-aware objective. Neural combinatorial methods require compatible objective/training evidence; solving Euclidean tours well does not establish transfer here.

### Optimization is not exact sampling

A local softmax or stochastic ant is not an exact sampler from a whole-order Gibbs distribution. For example, from A let A→B and A→C both cost one, B→C cost 100, and C→B cost zero. An immediate-cost softmax chooses B and C equally; full-path Gibbs weights differ by `exp(-100/T)`. Finite annealing also does not establish equilibrium sampling. The product needs controlled variation and good listening outcomes, not an unsupported sampling theorem.

Positive next-step probability and eventual inclusion do not establish adequate early exposure. Report rank- and elapsed-time-based exposure for individual songs and sparse/rare cohorts, as well as the variety of resulting orders. Exact equal exposure is a possible design constraint, not assumed to be the owner's only priority.

## Obtaining information we can trust

There are four different levels of evidence:

1. **Identity and execution:** these exact text/media bytes were processed with these settings.
2. **Reproducible measurement:** a numerical descriptor is correctly computed for its specified signal/window.
3. **Interpretive validity:** the descriptor or tag corresponds to the intended musical or lyrical property.
4. **Decision utility:** using it improves the requested ordering experience.

A successful command proves level one, and sometimes two. It does not automatically establish three or four. This distinction controls both the pilot claims and the future intake gate.

| Attribute | Acquisition route | Acceptance evidence | Allowed abstention |
| --- | --- | --- | --- |
| Recording duration, channels, sample rate | Decode/probe actual listener media | Exact file identity; decoder/version; plausible ranges | Decode failure recorded for repair |
| Signal level/dynamics | Defined FFmpeg or numerical analysis | Units, channel policy, windows, clipping/gating policy, reproducibility | Unsupported/invalid measurement |
| Tempo/pulse | Beat tracker or tempogram candidates | Independent beat/tap annotations and admissible metrical levels on a held-out sample | Unmetered, ambiguous, or undetermined; no fabricated BPM |
| Sonic character | Frozen embedding and/or descriptive audio model | Actual audio input, fixed model/window/pooling, blinded sonic judgments | Unqualified model/domain |
| Named referent and role | Reviewed lyric text plus source spans | Resolved contextual use; primary versus passing/signature distinction | Unnamed or ambiguous referent |
| Theme/action/imagery | Source + accepted gloss/English; assistant or API proposals | Supporting line IDs, counterevidence, independent substantive review | No applicable concept; unresolved interpretation |
| Compatible next-track relation | Combine accepted components | Held-out transition and sequence preferences | Insufficient evidence of benefit |

Do not label RMS dBFS as LUFS or perceived loudness. Do not call spectral centroid a validated mood. A beat tracker's confidence or agreement between windows can be confidently wrong. An audio-text embedding is not evidence that a song's lyrics express a theological claim.

### Semantic API and editorial contract

Use one cached per-song/section proposal operation, not an API judgment for every song pair. Inputs contain the vocabulary revision, distinct performed passages with stable line IDs, accepted contextual glosses/English, performance structure, known ambiguities, and a source fingerprint. Credits/album association cannot create an unnamed referent. The output contains concept IDs, role, prominence, evidence line IDs, exact supporting spans, contrary evidence, and unresolved alternatives. Status is `proposed`, never self-certified `reviewed`.

A separate review examines whether the evidence entails the tag and whether the whole song supports its prominence. It can reject or narrow proposals but cannot silently rewrite source/owner English. Deterministic validation checks IDs, spans, completeness, duplicates, and hashes; it cannot establish meaning. Assistant-produced examples demonstrate the evidence format, not independent gold labels. Hash agreement with publication establishes identity, not translation accuracy.

Support centrality and confidence separately. Review a negative/ambiguous set, including a poet's signature, an ordinary beloved mistaken for Sāī, a practice criticized rather than endorsed, and a composite sharing one incidental verse. Long recordings receive section-level coverage with explicit aggregation; sampling several lines does not qualify their complete thematic profile.

The existing provider adapter can later deliver structured proposals, but neither its current transcription qualification nor a model's ability to emit JSON qualifies thematic interpretation. Pin model/provider/prompt/schema revisions and measure per-facet precision, omissions, and abstention by language and length. A text-only model has not listened. An audio-description API must receive actual recording excerpts with offsets/coverage, not just title and artist.

[Calibration research](https://proceedings.mlr.press/v70/guo17a.html) shows why model confidence and correctness must be distinguished. [Selective prediction](https://papers.neurips.cc/paper_files/paper/2017/hash/4a8423d5e91fda00bb7e46540e2b0cf1-Abstract.html) provides the risk–coverage framing for abstention. Its image-classification guarantees do not transfer automatically to LLM lyrical judgments. Six examples cannot establish a reliable error rate; correlated model agreement cannot replace independent evidence.

## Proposed future mandatory intake contract

**Every new recording must have a versioned assessment receipt for semantic and acoustic metadata. Every feature used in ordering must have passed its applicable qualification. A song never needs an invented tag, BPM, key, or mood to remain eligible.**

The receipt separates `accepted`, `reviewed_unknown`, `not_applicable`, `failed`, and `pending`. Unknown is a substantive outcome with a reason; failed means the process did not finish or produced invalid evidence, and belongs in a repair queue. Only accepted values enter similarity calculations. These states cannot all collapse into an empty tag array or one global success flag.

A proposed artifact boundary is:

```text
SemanticProfile = text/gloss hash + vocabulary revision
                + entity-role assertions + theme/action assertions
                + exact evidence references + coverage + review outcomes
AudioProfile    = retained-media hash + decode/extractor/model recipe
                + whole-recording descriptors + timed-window descriptors
                + optional pulse hypotheses/embedding + qualification states
Assessment      = schema/producer revision + dependency identities
                + qualification-policy/evidence revision + support envelope
                + per-component outcome + missingness reason + repair status
```

The runtime scorer consumes a derived projection of accepted fields, not raw API prose or a single all-purpose tag list. Semantic overlap, audio-body similarity, and end→start compatibility remain separately observable. Themes are editorial claims; an embedding is a numerical representation; a measured level is a signal statistic. They require different evidence and should not share an undifferentiated confidence score.

Qualification has an applicability envelope: supported languages/registers, recording styles, duration/structure regimes, and relevant input conditions, plus a defined acceptance/abstention rule. Computational validity and domain suitability are separate. A new model/recipe or an out-of-envelope song triggers targeted requalification or an explicitly unqualified neutral component; it cannot inherit `accepted` simply because extraction returned a value. Keep per-recording review separate from model-level validation. An accurately computed signal statistic can apply broadly to decoded audio while a claimed musical interpretation has a much narrower envelope.

Require receipt completeness for new-intake ordering-readiness, not nonempty predictions. Legacy songs and temporarily unqualified features remain eligible with neutral contributions. Existing content/transcription publication rules remain independently binding. The proposed operational mandate is not yet an implemented release gate; activation needs the shared validator and all writer/deployment paths described below.

Receipt existence, assessment attempted, triage completed, and feature qualified are distinct states. An all-`pending` placeholder does not satisfy the mandate. A `failed` component requires evidence of a real bounded attempt plus a recorded repair or deferral disposition; `reviewed_unknown` and `not_applicable` require substantive reasons. Assessment completion means every required component has a supported outcome or a triaged failed attempt, not that every component qualified. None of these states removes the song from queue eligibility.

For the proposed **new-intake publication gate**, completed triage alone is insufficient: an unresolved failed attempt still needs successful retry or a substantive reviewed fallback assessment. A fallback records what was actually examined and which components remain unavailable; a deferral note alone does not certify assessment. This distinguishes operational tracking from permission to publish new intake. Previously published/legacy tracks remain playable throughout migration.

Semantic identity depends on reviewed text, gloss decisions, vocabulary and annotator/reviewer versions. Acoustic identity depends on the actual retained listener media, decode/channel/window settings, extractor and model revision. A changed trim or recording invalidates acoustic evidence; a changed translation/gloss can invalidate derived semantics; changing a presentation label alone need not force full reanalysis if stable concept identity is unchanged. Store dependencies explicitly and process only stale components.

Keep raw proposals, detailed review evidence, and model artifacts private. Export a compact accepted-profile sidecar keyed by stable song/recording identity. Queue occurrences retain their own identity and join this sidecar; they do not carry duplicate evidence packets. A ready receipt must be validated against the actual bytes used for generation, not merely the files originally submitted to the pipeline.

## Experiment sequence and decision gates

1. **Real-example feasibility:** a bounded lyric and audio sample, using installed tools and no paid calls. Deliver actual artifacts, offsets, timings and limitations. This is the current research-stage probe.
2. **Representation qualification:** a stratified 24–40-recording development pilot, followed by held-out work/artist groups. Compare transparent features, one semantic model/proposal route, one acoustic representation, and their combination. Determine usable attributes from precision/coverage and listener judgments, not desired schema slots.
3. **Algorithm correctness and search quality:** exact small directed instances; adversarial cluster/outlier/missing-feature examples; actual catalogue-derived costs. Compare random/softmax/ant constructors with and without the same local improvement. Include ILS/annealing, bounded blocks, and routing reference where assumptions fit. Measure objective gap separately from perceptual preference.
4. **Matched-budget comparison:** report elapsed time, total worker CPU, peak memory, candidate constructions, edge evaluations, and full-objective evaluations. Compare anytime curves under fixed budgets, not ant iterations versus local-search iterations. Freeze semantic labels, feature scaling, weights, search budgets, and held-out evaluation cases before final evaluation; paired seeds/cases and confidence intervals use independent runs, not correlated ants as replicates.
5. **Listening qualification:** cross the strongest two representations and two optimizers, and always retain the actual current shuffle implementation as an explicit held-out control. Compare actual boundary excerpts and longer sequences, with identical occurrence sets and starting context, randomized presentation, “no preference,” and explicit assessments of coherence, monotony, welcome surprise, and thematic connection. Measure short-session exposure and repeated-run adjacency diversity. Winning against another proposed optimizer does not establish an improvement over today's experience.
6. **Operational integration:** implement the mandatory receipt lifecycle, stale-component repair, public sidecar, all writer/release validations, and queue compatibility. Only after these pass should an intelligent ordering become a default. No model inference is required during listening.

Budgets are bounds, not performance claims. The present acoustic probe is capped at three existing files, at most five 30-second windows each, and ten minutes wall time; no installations, downloads, or paid inference. A later five-recording timing run must establish feasible wall-time/memory caps before any larger extraction. API experiments require a frozen per-song workload, token/audio limits, bounded retries, price-derived spending cap, and abort rules before execution. This research turn does not spend provider quota.

The future algorithm benchmark should include ordinary catalogue subsets and the full current population, plus duplicate occurrences, absent features, and fixed-prefix cases. Tiny exact instances verify optimization correctness; they do not establish performance at catalogue size. Synthetic feature graphs expose failure mechanisms; they do not establish musical accuracy.

Choose a method only if the added information and computation improve the decision-relevant outcome. If the confidence interval excludes a worthwhile gain, prefer the cheaper method. If the budget expires with wide uncertainty, report inconclusive rather than equivalent. Ant-colony coordination wins only if it adds benefit beyond matched local search, tuning effort, and repeated-session predictability.

## Evidence from this follow-up

### Semantic feasibility on actual lyrics

The [six-song evidence packet](research/shuffle-qualification-2026-11-15/bhakti-shuffle-semantic-capability.md) records exact source/English spans, line IDs, full input hashes, API schema and review rules. All six inputs matched public files byte-for-byte. Five received complete unique-line inspection; the 539-line Sundarakāṇḍa received bounded sampling. These are assistant proposals, with **zero independent gold reviews and zero API calls**, not accepted production annotations or a measured accuracy rate.

| Example | Obtainable candidate with evidence | Important boundary |
| --- | --- | --- |
| Rehnā Nahī̃ Isa Desa | Impermanence: `verse-1-line-1..2`, world as paper packet dissolved by a drop | Kabīr in the signature is the poet, not automatically the worshipped subject |
| Guru Caraṇa Re Karo Dhyāna | Guidance and meditation: `refrain-1`, `v2-1..3`; life as a frail boat, Guru as favorable wind | The Guru is unnamed; do not invent Sāī identity |
| Tumhī Mere Lagan Lagāī Re | Longing: `tu_hi_more_lagan`, `manwā_lāge_na` | `सइयाँ` is not evidence for Sāī; current empty subject tags do not imply absent meaning |
| Uyarvara Uyar Nalam | Divine presence: `l026..27`, `l036..37`, `l040`; limits of apprehension at `l006` | Mind as addressee differs from divine object of worship; avoid unsupported sect/doctrine labels |
| Hanumān Cālīsā | Praise, service, protection: `chaupai-01`, `02`, `07`, `22`, `26` | Hanumān as central subject differs from Rāma as served lord and Tulsīdās as signature |
| Sampūrṇa Sundarakāṇḍa | Sampled episodes of service (`line-025`), recognition (`165..166`), separation (`171`, `177`), refuge (`500`) | Partial inspection cannot establish whole-recording prominence or exhaustive theme coverage |

This demonstrates why separate theme, action, imagery and entity-role facets are useful. Ocean/crossing imagery can connect the Guru song and a separation episode without claiming that their meanings or referents are identical. Preserve episode/speaker context and keep relatedness weaker than identity. The candidate vocabulary must be tested against negative cases and the remaining corpus before adoption; its expressiveness is not established by these six examples alone.

### Acoustic feasibility on actual listener files

The [audio capability report](research/shuffle-qualification-2026-11-15/bhakti-shuffle-audio-capability.md) and [machine-readable measurements](research/shuffle-qualification-2026-11-15/bhakti-shuffle-audio-capability.json) preserve exact commands, versions, identities, offsets, errors and raw summaries. Installed Python 3.14.7, NumPy 2.4.6 and FFmpeg 8.1 processed five nominal 30-second windows from each of three existing Opus listener sources. All 15 windows produced finite descriptors. The measured window-analysis stage took **3.03 seconds**, excluding preceding inventory, hashes and probing; this is not an end-to-end catalogue benchmark.

| Recording | Duration | Sample coverage | Window integrated loudness, chronological (LUFS) |
| --- | ---: | ---: | --- |
| Harivarāsanam | 173.3 s | 86.5% | −14.9, −15.3, −16.0, −15.7, −15.5 |
| Kyā Tan Mā̃jhatā | 230.3 s | 65.1% | −13.2, −12.8, −12.4, −12.0, −10.5 |
| Sampūrṇa Sundarakāṇḍa | 7,228.4 s | 2.08% | −17.0, −13.9, −13.4, −13.9, −22.1 |

The latter two hashes match `data/media.json`; Harivarāsanam's local file is its catalogue first source but has no corresponding media-manifest entry. No remote audio was downloaded. The “Live” alias on Kyā Tan Mā̃jhatā is catalogue metadata, not an independently verified performance classification.

FFmpeg `ebur128` supplied window integrated loudness/true peak. NumPy supplied RMS quantiles, fraction of frames below −50 dBFS, and spectral-centroid quantiles on an explicit 22,050 Hz mono diagnostic decode. The [FFmpeg documentation](https://ffmpeg.org/ffmpeg-filters.html#ebur128) distinguishes momentary, short-term and integrated measures. Do not average window LUFS into whole-track LUFS. The low-level fraction is not calibrated silence; centroid is not mood. The probe did not pin/log the negotiated channel/rate graph at the loudness stage, which must be resolved before treating it as the production measurement recipe.

No human listening, beat annotation, tempo, tāla, rāga, instrumentation, embedding or transition-preference accuracy was qualified. Default Python lacks the inspected music-analysis/model packages; other environments remain unqualified. No package/model installations occurred. The long recording's sampled ending differs from its interior, but the cause is unestablished. Two-percent coverage cannot certify a whole-recording description.

The next representation experiment should therefore pair (a) full-recording physical descriptors plus retained beginning/body/ending windows, (b) Beat This! pulse hypotheses checked against independent taps/beat annotations, and (c) one frozen sonic embedding selected from the prior report's current model/license shortlist. Keep the physical-only baseline. Do not use a general audio API's confident BPM prose as the beat reference. Text API proposals use the evidence schema above; audio API proposals, if compared, receive actual timed excerpts and coverage. Compare their incremental usefulness and review cost against local extraction before choosing a provider. No such API experiment has been run here.

### Where a future mandate must actually be enforced

The [caller and release map](research/shuffle-qualification-2026-11-15/bhakti-shuffle-intake-plan.md) distinguishes the published source from this older, heavily modified working checkout and supplies precise function references. Its decisive integration points are:

1. **Retained audio:** assess after `apply_lossless_trim()` and `preferred_listener_audio()`, binding the accepted trim transaction and actual retained asset hash. Temporary model AAC is not the listener source.
2. **Accepted semantics:** consume `complete_semantics()` output plus final reviewed metadata overrides. Share a pure final-reader projection or validate the exact emitted semantic projection; pre-override guesses are insufficient.
3. **Generation:** `generate() → _generate()` validates cached profile freshness and acceptance. `--generate-only` skips `run_one()` and must stay free of provider calls, so a gate only in ordinary intake is ineffective.
4. **Other writers:** style-review application and reader rebuilding can directly change `data.js`. The final `assemble_public_site.py` boundary must check reader/profile dependency and exact-output pairing over the copied release snapshot.
5. **Shipping:** hosted-intake git staging and public-site assembly both currently exclude the proposed sidecar. Update both deliberately during implementation; creating a JSON file does not make it ship.

One future owner module should define dependency identities, validation and compact public projection; a serialized bundle writer owns sidecar/catalogue updates. Freeze the actual accepted inputs under existing boundary locks; create reader/profile/receipt from those same objects; record exact emitted-byte digests; recheck inputs before adoption. Canonical dependency hashes allow presentation-only edits without paid reanalysis. Exact-byte pairing prevents an interrupted or bypassed update from silently shipping stale features. Keep detailed proposals, review evidence and local paths private.

Pin the legacy population at activation (337 in this inspected published snapshot); do not infer legacy status from a caller flag. Backfill via accepted public/cached text and retained listener audio, without rerunning the transcription pipeline. New intake requires completed reviewed assessments or substantive reviewed fallbacks. Legacy omissions remain explicit and neutral during migration. The caller audit also found an unexecuted existing `page_html(meta)` versus `(meta, slug)` mismatch in the published rebuild path; verify that prerequisite in future integration rather than claiming the route already works.

### Deliverable and remaining qualification

This follow-up completes the theoretical comparison, actual feature-feasibility probes, proposed acquisition/review contract and release-enforcement plan. The [full theory notes](research/shuffle-qualification-2026-11-15/bhakti-shuffle-theory-notes.md) retain primary-method comparisons and implementation/license references. Independent review corrected qualification-envelope inheritance, omission of current shuffle from the final control group, and placeholder-receipt acceptance. Final review found no unresolved material defect in this bounded deliverable: it checked six semantic input hashes, three audio identities, all 15 successful command records, reported values/coverage/stage timing, ant-work arithmetic and the gate/caller distinctions. It did not rerun audio extraction or independently certify lyrical interpretations; those remain explicit future qualification tasks.

What remains is empirical qualification, not additional confidence from literature: multilingual independent review; pulse/sonic-model validation; exact-objective algorithm checks; matched-budget search; and held-out listening. No shuffle algorithm, mandatory production gate, bulk tags, or paid model analysis has been installed by this research work.

# Intelligent shuffle: research and design assessment

Research date: 15 November 2026. This section records the initial investigation, when the scope was research only. The owner subsequently authorized implementation, bulk assessment and release; current qualification and release evidence are recorded in [the implementation plan](SHUFFLE_QUALIFICATION_PLAN.md). The subsequent [qualification plan](SHUFFLE_QUALIFICATION_PLAN.md) adds ant-colony/local-search theory, a bounded three-recording audio probe, six lyric examples, and a concrete future intake mandate. This is a private repository design document, not song-page content. Current catalogue evidence is from published revision `a87bfbef`, not the older, extensively modified working checkout.

Completed with five sub-agents covering current queue/catalogue, sequencing literature, audio literature/tooling, semantic representation, and independent critique. The critic's material corrections—distinct shuffle operations, finite-seed versus ideal randomness, counting assumptions, representation–optimizer interactions, and missing-data/stopping rules—are incorporated. The audio specialist checked the expanded source/model section. Empirical effectiveness on Bhakti remains an explicitly unperformed future experiment, not a claimed result.

## Decision being made

The desired product is a more thoughtfully ordered shuffle of the songs the listener already selected. Subject, meaning, and sound should influence ordering without excluding songs. This differs from retrieving a handful of recommendations from a large catalogue, training a personalized recommender, or mixing tracks as a DJ would.

The defensible architecture is **reviewed semantic facets and cached recording features feeding a replaceable sequence scorer**, with no model inference during listening. The evidence does not yet identify a winning balance between thematic continuity and musical continuity for this repertoire. Themes-only, acoustics-only, and hybrid are competing hypotheses. Nor does the literature justify simply choosing the closest song at each step.

The proposed qualification should compare a cheap scored-permutation baseline, a stochastic all-candidate sequencer, bounded within-block reordering, and a globally improved permutation. Keep the same features when comparing algorithms, and the same algorithm when comparing features. This distinguishes an improvement in representation from an improvement in search.

## Actual system and data

The published catalogue has 337 songs, 37 literal subject labels, and 18 language labels. Languages are populated for all songs; subject tags for 324, singer for 260, writer for 225, composer for 104, general credit for 313. None of the 337 song metadata objects contains theme, mood, tempo, beat, energy, key, timbre, or embedding fields. Empty subject tags are not necessarily an error: a song can express an idea without naming a deity.

Existing subjects mix entities such as Kṛṣṇa, a tradition/source label such as Gurbāṇī, and an orientation such as Nirguṇa. They also include passing mentions, not only principal addressees. Production data has spelling variants such as Rāmakṛṣṇa/Śrī Rāmakṛṣṇa and Narasimha/Nṛsiṃha. Normalize evidenced spelling aliases without merging distinct theological uses automatically.

The implementation is Fisher–Yates, with no semantic or acoustic weighting. Full-library orders use a finite seeded pseudorandom generator; filtered subsets use `Math.random`. This is practical randomization, not a claim of exactly uniform access to all 337! permutations. Library shuffle takes the current filtered/search-visible set. Playlist shuffle changes the upcoming suffix. Relevant current references:

- `assets/library.js:319–322` and `assets/app.js:656–664`: visible-set selection and library shuffle.
- `assets/app.js:731–733`: shuffle upcoming playlist occurrences.
- `assets/queue.js:26–44,121–130,210–253`: snapshots, occurrence identity, and shuffle.
- `assets/queue.js:447–494,675–690`: shared-order decoding and persistence.
- `scripts/bhakti_pipeline.py:5653–5673`: explicitly enumerated catalogue export.
- `scripts/tag_taxonomy.py:133` onward and `data/song_tag_overrides.json`: reviewed source-based subject overrides, covering 80 songs.
- `docs/GURBANI_REVIEW_TASKS.md:451–459`: mentioned names are not necessarily primary addressees.

An implementation must preserve the **multiset of occurrences**, not deduplicate song IDs. Each occurrence has an `entryId`; its song has a `queueId`. There are two distinct operations. **Library shuffle** starts a new session from the visible set, chooses a new current song, starts playback, and resets repeat to off. **Playlist shuffle** preserves the played/current prefix and audio position while explicitly replacing the upcoming order, including prior manual ordering in that suffix. Both preserve their eligible occurrence population. Subsequent manual edits, Next, reload, repeat, or new metadata must not trigger implicit reranking.

Queue snapshots intentionally omit classification details. Join a metadata sidecar/catalogue by `queueId`, rather than duplicating a taxonomy or embedding in every saved occurrence. The browser only needs compact reviewed fields; private evidence stays private.

Legacy whole-library share links reconstruct Fisher–Yates from a seed and the current catalogue. Reinterpreting those seeds using changing semantic metadata would change shared orders. Prefer the existing explicit permanent-ID order encoding for a first intelligent-shuffle version; retain the legacy decoder. A future compact semantic seed must specify algorithm and metadata/catalogue revision semantics.

## Evidence: what transfers, and what does not

| Primary source | What was actually studied | Consequence and limit |
| --- | --- | --- |
| [Bittner et al., ISMIR 2017](https://archives.ismir.net/ismir2017/paper/000086.pdf) | Ordering an existing playlist as a shortest Hamiltonian path/cycle over acoustic features; separately, crossfade optimization; curator evaluation. | Directly relevant problem formulation. Greedy paths have end artifacts. Their feature geometry and DJ setting do not establish devotional preferences or justify crossfades here. |
| [Moor et al., CIKM 2023](https://research.atspotify.com/publications/exploiting-sequential-music-preferences-via-optimisation-based-sequencing) | Position and recent-history preference models; off-policy evaluation and a randomized experiment involving seven million users. | Strong evidence that sequencing can matter. Interaction-trained consumption optimization is not evidence that our chosen theme labels or acoustic distances improve listening. |
| [Spotify's account of that experiment](https://research.atspotify.com/2023/10/exploiting-sequential-music-preferences-via-optimisation-based-sequencing) | Reports 2.52% more completed tracks and 2.73% fewer skips for its best local-sequential model. | These are platform-specific relative improvements, not predictions for Bhakti. Completion is also not a sufficient measure of meaningful devotional listening. |
| [Gabbolini and Bridge, 2024 survey](https://www.cs.ucc.ie/~dgb/papers/Gabbolini-Bridge-2024.pdf) | More than twenty years of playlist generation, continuation, curation, and evaluation. | Distinguishes tasks and warns that playlist statistics and ground-truth reconstruction do not necessarily measure quality. |
| [Schweiger et al., 2025](https://link.springer.com/article/10.1140/epjds/s13688-025-00531-3) | Coherence and diversity of user-curated playlists and reordering methods. | Local continuity and global diversity can coexist. Descriptive patterns in curated playlists do not prove a causal listener preference. |
| [Spotify Engineering, 13 November 2025](https://engineering.atspotify.com/2025/11/shuffle-making-random-feel-more-human) | Generate several random permutations, score freshness, select the best. | Useful inexpensive baseline preserving membership. Selection changes the distribution of permutations; it is not mathematically uniform shuffle afterward. |
| [Tamm and Aljanaki, 2026](https://arxiv.org/html/2604.23077v1) | Nine pretrained audio representations with five recommendation approaches, Music4All-Onion, track-level vectors from 30-second previews, hot/cold recommendation. | Model rankings depend on task. This does not test real song endings/beginnings or permutation of a fixed devotional collection. |
| [MUUNRiver-Bench, September 2026](https://arxiv.org/abs/2609.16090) | Seven relation-dependent retrieval tasks on 3,440 synthesized/expert-reviewed tracks; six models in eight configurations. | “Similar” depends on the requested relationship. Simple audio/text fusion did not consistently improve a backbone. Synthetic retrieval results are diagnostic, not listening-quality validation. |
| [CLAP2 / LAION-Audio-XL, 8 November 2026](https://arxiv.org/abs/2611.11592) | Released audio-text models and improved MAEB/HEAR performance at comparable sizes. | Relevant recent candidate, not evidence of better devotional semantics or transition ordering. |

The full-text review already changed the initial recommendation: it is not justified to declare themes the principal signal and audio secondary before comparing them. Likewise, a better predictive or acoustic-smoothness metric can coexist with worse sequence outcomes. A newer or larger encoder is not automatically a better choice.

Specific method-level findings matter more than the headline results:

- In the 2017 sequencing paper, the one-ended greedy path leaves bad tail pairings; extending both ends creates artifacts at both ends. Its blind pilot used six 30-track playlists. Three comparisons unanimously preferred sequencing; the rest were mixed, including a worse playlist. Its metric/TSP approximation reasoning cannot be transferred unchanged to arbitrary directed or history-dependent costs.
- In the [full CIKM 2023 paper, §§4–5](https://mounia-lalmas.blog/wp-content/uploads/2023/11/cikmmoor.pdf), position-only optimization admits a linear-programming treatment; the local-sequential problem uses a greedy heuristic. One-track memory improves predictive AUC yet performs worse than the myopic baseline on RIPS@3 despite smoother acoustic transitions. Longer memory performs better. Thus neither prediction accuracy nor local smoothness is sufficient validation.
- [Pauws et al., ISMIR 2006](https://archives.ismir.net/ismir2006/paper/000031.pdf) combine unary, pairwise, and global penalties with simulated annealing on collections of 2,248–71,194 songs. Their search permits insertions/deletions/replacements because their task includes selecting a short playlist. Only membership-preserving moves transfer to this task. This is a reason to seriously compare richer optimization, not to copy its entire constraint system.
- [Chen et al., NeurIPS 2018](https://proceedings.neurips.cc/paper_files/paper/2018/file/dbbf603ff0e99629dda5d75b6f75f966-Paper.pdf) explicitly develop sliding-window DPP inference, including 100-item sequences and a ten-item diversity window. It would be incorrect to dismiss all DPPs as unordered-set methods; it would also be incorrect to assume local repulsion gives the continuity sought here.

## Semantic representation

Use separate facets, not a flat bag of interchangeable tags:

1. **Entities and roles:** named deity/person/place, with primary addressee, central subject, or secondary mention distinguished where evidenced.
2. **Themes and poetic acts:** longing, refuge, remembrance, praise, impermanence, compassion, service, self-inquiry, unity, divine play, etc. These examples are provisional categories, not assignments to songs.
3. **Tradition/form:** preserve existing classifications without treating them as semantic identity.
4. **Recording properties:** measured rhythm/timbre/loudness and reviewed sonic descriptors, attached to this recording rather than every setting of the poem.

Start vocabulary development with a varied sample, then inspect the full inventory for omissions. Fifteen to twenty-five themes and two to four tags per song are planning hypotheses, not quotas. A short song may warrant one theme; a long composite can warrant more. Retain unresolved and intentionally untagged states. Refrain repetition should not numerically erase less-repeated but meaningful verses.

Each concept needs a stable ID, display label, aliases, definition, inclusion/exclusion examples, and optionally a small number of reviewed broader/related links. [W3C SKOS](https://www.w3.org/TR/skos-reference/) provides the vocabulary-management distinctions; ordinary JSON can express the needed subset. This does not require RDF infrastructure or a graph database. Relatedness is not identity and should not recursively make all devotional themes equivalent.

Private assignments should record theme ID, prominence, supporting lyric-line IDs, a brief rationale, reviewer status, and source-text/vocabulary revision. Public runtime data should contain only accepted IDs and useful strengths. A spelling mention alone is insufficient: “feet” need not imply surrender, “name” need not establish a specific practice, and an unnamed Guru must not become Śirḍī Sāī automatically.

Read reviewed source, glosses, and English together. A model may propose assignments in cached offline batches, including proposals for missing concepts. It must not silently expand the accepted vocabulary, override owner English, or turn uncertain translation into confident metadata. Changed source text invalidates the affected assignments. New songs reuse the vocabulary unless review establishes a useful distinction.

For initial transparent similarity, compare weighted theme sets, downweight near-universal concepts, distinguish central from secondary tags, and cap any rarity weighting. Weighted Jaccard is a candidate, not an empirically selected metric. Empty sets mean unknown/no assigned theme, not perfect equality. Test broader-term credit separately; similarity through many graph hops is not justified.

Dense text embeddings are an independent comparator or suggestion tool. Compare a short reviewed semantic description and section-level representations; blindly embedding a whole long song can truncate it. [Multilingual MiniLM](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) is a small released 384-dimensional baseline with a 128-token sequence limit. Supported modern languages do not certify Sanskrit, Braj, Awadhi, or historical devotional diction. Generic keyword extraction such as [KeyBERT](https://github.com/MaartenGr/KeyBERT) does not resolve poetic meaning.

Stronger compact text candidates belong in the comparison too: [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) has Apache-2.0 weights, instruction-aware multilingual embeddings, and a much longer context; [multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small) is an MIT-licensed 384-dimensional baseline with specified query/passage prefixes. Neither's broad language coverage establishes fidelity to this corpus. Test source-only, accepted-English-only, and separately combined representations; do not treat translation/source agreement as an independent truth check. [MMTEB](https://arxiv.org/abs/2502.13595) helps shortlist models, not settle this literary task.

Relevant lyric-specific evidence is more precise than generic semantic similarity: [LyricSIM](https://arxiv.org/html/2306.01325v1) starts with 2,775 Spanish-song pairs and 63 annotators, retaining 676 higher-quality pairs. Its judgments distinguish literal topic from message, feelings, and lyrical situation. Consensus filtering can discard hard cases, and Spanish popular lyrics do not validate Indic devotional interpretation. [The 2024 lyric-perception study](https://arxiv.org/html/2404.02342v1) finds several contributing semantic/acoustic/phonetic dimensions, without establishing which improves a playlist. These are reasons to ask reviewers separately about thematic connection and desired adjacency.

Prominence and certainty must be separate. A passing reference can be certain but unimportant to ordering; a central image can remain ambiguous. An illustrative private assertion, not an actual song annotation, is:

```json
{
  "song": "hypothetical-song",
  "textRevision": "reviewed-text-and-gloss-hash",
  "assertions": [
    {
      "concept": "theme.longing-for-presence",
      "prominence": "central",
      "evidenceLineIds": ["refrain-1", "verse-2"],
      "status": "reviewed"
    }
  ]
}
```

For long works, retain a content view of distinct performed passages and a performance view with duration/repetition. Test capped repetition weighting: neither ignoring a repeated refrain nor counting it twenty times as independent semantic evidence is adequate. Maximum passage similarity can also overmatch hour-long works sharing one incidental verse. Normalize each facet, avoid counting a concept and all its ancestors as independent matches, and cap isolated-passage contributions. Group alternate performances of the same evidenced work when measuring document frequency and splitting evaluation data; shared title alone does not establish identity.

Vocabulary growth is an editorial operation: add a concept when existing labels conflate a useful, evidenced distinction, with examples and exclusions. A legitimate rare concept need not already occur in many songs; it may be searchable before it has an ordering weight. Preserve stable IDs across label changes and record deprecated mappings. Optional imagery or devotional-action facets can be added if they distinguish useful relationships, without forcing every song to populate every facet.

Thematic *compatibility* need not be thematic sameness. Longing followed by assurance might form a meaningful movement, whereas two texts containing the same vocabulary could endorse and criticize opposite positions. Such directional connections are hypotheses to test, not automatic consequences of a concept hierarchy. A handful of reviewed concept-level relationships is preferable to inventing a narrative for every song pair; the relation can be disabled if listeners do not find it useful. Keep emotional stance in the poem separate from the sound of the recording.

## Acoustic representation

Separate three questions: does a song sound broadly similar, does its ending flow into the next beginning, and does the resulting sequence remain engaging? One embedding or BPM cannot answer all three.

Analyze the actual post-trim listener recording; cache by media-content hash, extractor/model version, and settings. Keep originals intact. Store distinct body and boundary profiles, validity flags, and sampling coverage. Use actual retained silence/applause when assessing what the listener hears; a nonsilent-window descriptor may supplement, but must not misrepresent, the true boundary.

An inexpensive baseline can measure loudness/dynamic range, onset density, pulse strength, tempo hypotheses and variability, and spectral/timbral summaries. Energy is an acoustic proxy, not a synonym for devotional emotion. Use time-varying tempo where appropriate. [Librosa's tutorial](https://librosa.org/doc/latest/auto_tutorials/03-advanced/plot_dynamic_beat.html) explicitly addresses the failure of a single global tempo under substantial changes.

Keep uncertain/unmetered states and plausible half/double-tempo alternatives. Do not equate 60 and 120 BPM automatically, nor treat a confident tracker activation as calibrated confidence. [A 2025 Carnatic study](https://arxiv.org/abs/2509.11241) found off-the-shelf neural trackers did not consistently beat its older baseline before adaptation. [The 2026 SMC Blind Spot report](https://arxiv.org/abs/2605.12287) illustrates slow-tempo and confident-error failures in a different difficult corpus. Neither supplies Bhakti-specific failure rates.

Candidate offline toolchain:

| Option | Reason to test | Cost/licensing/maturity boundary |
| --- | --- | --- |
| [librosa](https://github.com/librosa/librosa) | Transparent CPU features and dynamic rhythm baseline. | ISC; no training or recommendation service. Runtime must still be measured on long recordings. |
| [Essentia](https://essentia.upf.edu/tutorial_rhythm_beatdetection.html) | Integrated rhythm and timbre extraction. | Library and model licenses differ; see [official licensing](https://essentia.upf.edu/licensing_information.html). Not a uniformly permissive bundle. |
| [Beat This!](https://github.com/CPJKU/beat_this) | Released modern beat/downbeat model for a bounded comparison. | Code and published weights MIT; CPU fallback; small and main checkpoints. Domain qualification still required. |
| [MusiCNN](https://github.com/jordipons/musicnn) | Older, compact learned acoustic baseline. | ISC repository; music tags are not theological themes. |
| [MERT](https://github.com/yizhilll/MERT) | Music-specific representation. | Apache-2.0 code; selected weights such as [v1-95M](https://huggingface.co/m-a-p/MERT-v1-95M) are CC-BY-NC-4.0. |
| [CultureMERT-95M](https://huggingface.co/ntua-slp/CultureMERT-95M) | Continued pretraining on Greek, Turkish, Hindustani, and Carnatic music; serious domain-adapted comparator to base MERT. | Released ISMIR 2025 model, CC-BY-NC-4.0 weights; tagging gains do not guarantee similarity or sequencing gains. |
| [MuQ / MuQ-MuLan](https://github.com/tencent-ailab/muq) | Music and music-text representations. | MIT code, CC-BY-NC-4.0 weights; released model training differs from the paper's largest setting. |
| [CLAP2](https://github.com/LAION-AI/clap2) | Very recent audio/text embedding candidate with smaller model variants. | November 2026 release; MIT repository and Apache-2.0 for the inspected [small checkpoint](https://huggingface.co/laion/clap2-small-audioxl-s1B). That card specifies English text, 32kHz audio, and training/evaluation inputs up to 30 seconds. Longer inference is not equivalent to validated long-recording understanding. |
| [MERIT](https://github.com/AMAAI-Lab/MERIT) | Released lightweight heads separate melody/rhythm/timbre over frozen MERT. | [May 2026 paper](https://arxiv.org/html/2605.27346v1) evaluates attribute retrieval, not sequence preference. Using the heads still requires compliance with the MERT backbone's weight license. |

Models should be compared on the same recordings/windows, not given different amounts of audio and then ranked as if architecture alone caused the difference. Full-track summaries, boundary descriptors, and section aggregation are separate ablations. A capped five-window scan can miss a long medley's changes: record that limitation and test it rather than calling sampled coverage complete.

The expanded full-text audio review supplies several discriminating results:

| Study | Useful result | Why it does not settle Bhakti's design |
| --- | --- | --- |
| [Cross-Cultural Music Similarity, July 2026](https://reference-global.com/article/10.5334/tismir.341?tab=article) | 125 listeners, 1,130 pairs of 20-second clips, including Hindustani and Carnatic material. CLAP Music&Speech attained 64.9% playlist-co-membership triplet agreement versus melody features' 60.7%. | Correlations were low (.14 and .15 respectively), listeners predominantly European, and most pairs had one rater. Its fitted ensembles use random pair splits, which do not establish unseen-work/culture generalization. CultureMERT did not beat base MERT here. Co-membership is not next-track preference. |
| [When Do Pretrained Audio Representations Help?, October 2026 revision](https://arxiv.org/html/2608.06928v3) | Includes ID-only, random-vector, shuffled-ID controls, and full-catalogue checks. Benefits vary with recommendation interface and shrink after strong history-based adaptation. | Historical next-item ranking differs from fixed-set sequencing. Crop and experimental-coverage differences still matter; the result is not a reason to discard audio representations. |
| [Perceptually-Aligned Music Similarity, January 2026](https://arxiv.org/html/2601.19109v1) | CLAP/MuQ-MuLan match some human similarity comparisons around 72%. | Five-second synthesized instrumental excerpts, including same-song comparisons; no devotional vocals or sequence outcomes. |
| [Universal Music Representations?, 2025](https://arxiv.org/html/2506.17055v1) | Foundation-model performance varies across Western, Greek, Turkish, Hindustani, and Carnatic tagging tasks. | Supervised probes and fine-tuning do not validate raw embedding distance. Domain training and model size alone cannot choose a sequencer. |
| [Don't CLAP, September 2026](https://arxiv.org/html/2609.30540v1) | Diagnoses attribute-binding and temporal-order weaknesses in music-text models. | It does not invalidate ordinary audio-to-audio similarity and predates CLAP2; do not transfer an untested failure rate to that release. |
| [Steering Dense Music Retrieval, August 2026](https://arxiv.org/html/2608.08757v1) | Sparse representations support concept-level retrieval edits. | Its concept-inversion step is training-free, but the sparse autoencoder is trained. Acoustic concept steering does not establish abstract devotional understanding. |

The April 2026 recommendation study in the earlier table is specifically rock/pop-dominated, uses 30-second previews pooled into track vectors, and ranks against a cold-item pool of only 589 items in that condition. It does not test actual song beginnings/endings. The [2024 album-sequencing study](https://arxiv.org/html/2408.04383v1), covering 51,010 albums, supports considering trajectories and changes of direction, but reproducing authored album order is different from improving shuffle.

Indian-music resources provide components rather than ready-made sequence judgments: [Saraga](https://mtg.github.io/saraga/) and [CompMusic](https://compmusic.upf.edu/datasets) offer contextual, melodic, rhythmic, and structural material; [compIAM](https://github.com/MTG/compIAM) supplies Indian art-music analysis tools. These do not supply a comprehensive bhajan-theme ontology or preferred next-song labels. The [Indian Semi-Classical Music Dataset](https://zenodo.org/records/6584259) includes Bhajan and Qawwali among nine styles but its released short mel-spectrogram segments cannot substitute for full listener recordings. Check data/component licenses before reuse. [CCMSim](https://github.com/pxaris/CCMSim) provides human similarity annotations and reproducible analysis for a sanity check, not Bhakti ground truth.

For this collection, a larger frozen model can be an economical feature if it runs once per recording; conversely, a supposedly simple system becomes expensive if it adds robust melody separation, rāga recognition, or automatic tāla analysis. Compare measured end-to-end extraction cost rather than parameter counts. Conventional descriptors, an audio-text embedding such as CLAP2, and music-specific/domain-adapted representations remain serious alternatives. Narrow the first comparison on development evidence and license constraints, without declaring the newest model superior.

## Objective and competing algorithms

For playlist shuffle, let P be the immutable played/current prefix and R the remaining **occurrence multiset**. A valid output is P followed by a permutation π of R. For fresh library shuffle, P is empty and the visible set creates a new session with a new current song. No hard subject, artist, tempo, or similarity filter changes R. If all features are absent, return the existing random shuffle rather than fail or cluster empty vectors.

A proposed score combines directed boundary compatibility, semantic relation, body-level sonic compatibility, and short-window repetition/monotony penalties. Position or elapsed-time weights may reflect the fact that listeners do not finish a 337-song queue. No evidence yet selects numerical weights. Report tradeoffs rather than hiding them in one opaque “quality” number. Maintain a separate evaluation of listener preference, coverage, exposure, and latency.

One explicit research objective is `E(pi) = alpha * sum(positionWeight * transitionMismatch) + beta * sum(recentWindowRepetition) + gamma * sum(positionFreshness)`. An energy-arc term is optional, not assumed: a listener may want sustained contemplation rather than a build and taper. Without genuine listening history, omit freshness/familiarity estimates. Calibrate separate facet scales before combining them so a vector's arbitrary magnitude cannot decide the music policy. Weights encode a preference hypothesis, not a scientific fact.

An entropy-regularized formulation makes the intended tradeoff explicit: maximize `expected utility - temperature * KL(orderDistribution || uniformPermutation)`. For finite utilities and positive temperature, the exact optimum is proportional to `exp(utility/temperature)` over valid permutations. This is a mathematical specification of biased randomness, not a claim that we can sample that distribution exactly at full scale or that it gives equal early exposure. Greedy softmax, finite annealing, and best-of-K search generally produce different distributions. Do not conflate them.

Missing-feature handling is part of the score contract: use fixed facet weights and calibrated, centered feature scales; missing or unqualified evidence contributes zero evidence on that scale. Do not divide each candidate's score by its own total of available feature weights, which can unintentionally reward sparsely annotated recordings. Distinguish a reviewed lack of a shared theme from missing annotation. Quality masks or empirically checked reliability can shrink a contribution toward neutral; an uncalibrated model confidence is not a probability of correctness.

| Method | Advantages | Failure mode / qualification |
| --- | --- | --- |
| Ideal uniform Fisher–Yates | Exact membership; equal position marginals under independent unbiased draws. | No deliberate flow. Compare against the current seeded implementation as the real control. |
| Artist-spacing only | Tests whether a simple familiar repetition rule explains most benefit. | Can misread desired long artist passages; no semantic understanding. Soft preference only. |
| Best/scored K random permutations | Simple, bounded, full membership by construction; Spotify precedent. | Small K may barely improve transitions; large K reinforces the chosen score's biases. |
| All-remaining stochastic sequential sampling | Can deliberately find thematic or sonic neighbors; cheap at this scale. | Myopic choices, homogeneous runs, and stranded outliers; positive probability is not equal early exposure. |
| Random blocks, reorder only inside each | Bounds displacement; preserves unbiased membership of completed block prefixes. | Sparse desirable neighbors may fall in different blocks; within-block rank remains biased. |
| Whole-permutation swap/insertion/local search or annealing | Repairs greedy bad endings and scores the entire path plus run penalties. | Optimizes a possibly wrong surrogate more effectively; needs random restarts, compute bounds, and position-exposure checks. |
| Hamiltonian cycle then independent uniform rotation | For an unanchored shuffle, exact equal per-position marginals conditional on any chosen cycle. | Does not give a uniform permutation; repeated adjacency can remain. A fixed current-song anchor defeats the marginal guarantee. |
| Learned autoregressive/generative recommender | Potentially learns complex relationships with enough valid data. | No demonstrated Bhakti interaction dataset; retrieval objectives and candidate pruning do not meet full-membership semantics automatically. |

MMR's [relevance-versus-redundancy principle](https://aclanthology.org/X98-1025/) is useful for run penalties, but a set-diversity algorithm is not by itself a sequencing objective. With the full song set fixed, a purely set-based diversity value is constant across all permutations. Likewise, selecting a diverse subset using a DPP solves a different problem unless an order-sensitive extension is specified.

Additional exact counterexamples distinguish the algorithms:

- On a one-dimensional metric with song features `0, 1, -2, 4`, starting at zero, nearest-next yields `0 → 1 → -2 → 4`, total distance ten. `0 → -2 → 1 → 4` costs eight. Even a genuine metric does not make greedy globally optimal.
- With four theme clusters of sizes 85, 84, 84, 84, zero within-theme cost, and unit cross-theme cost, the shortest path has just three cross-theme transitions and roughly 84-song runs. Uniform shuffle has about 252.748 expected cross-theme transitions. Neither extreme establishes the desired balance.
- With a fixed starter and 336 candidates, best-of-32 uniform permutations proposes one uniquely ideal next song with probability only `1-(335/336)^32 ≈ 9.10%`. A perfect scoring function cannot select a missing proposal.
- A full-set DPP determinant is invariant under simultaneous row/column permutation and therefore cannot choose an order. Sliding-window DPPs are a distinct comparator, with a positive-semidefinite kernel and local-diversity objective that must be defined.

For the sequential candidate, a transparent policy is

`p(j | history,R) = epsilon / |R| + (1-epsilon) * softmax(score(j)/temperature)`

with positive temperature and epsilon, finite normalized scores, stable arithmetic, and removal of the selected occurrence. This guarantees full eventual coverage and positive next-step support, not comparable early exposure.

**Exact counterexample:** after a dense-cluster starter, suppose 99 remaining tracks are mutually similar and one is isolated. As temperature tends to zero, with epsilon = 0.1 the isolated song is selected only by the exploration component. Its chance in the next ten positions is `1 - product(1 - 0.1/m, m=91..100) = 1.043%`, against 10% for uniform shuffle. This is a mathematical limiting example, not an observed catalogue result. It disproves the claim that a little exploration alone solves practical exclusion.

**Block alternative:** uniformly shuffle the remaining occurrences, divide into fixed blocks of b, and optimize/sample order only within each block. Every occurrence has b/N probability of belonging to the first full block and mb/N of appearing in the first m full blocks; displacement relative to the original random order is at most b−1 positions. These guarantees survive arbitrary within-block ordering. They are position guarantees, not elapsed-time guarantees. For a 336-song suffix and b=6, a particular desirable pair shares a block with probability only 5/335 ≈ 1.49%, exposing the cost of tight movement bounds. This is a derived design alternative, not a literature-validated winner.

Exact probability statements here and for cycle rotation assume ideal uniform random draws. Production pseudorandom implementations approximate those distributions and need empirical seed checks. In particular, the existing full-library 24-bit seed can reach at most 2^24 orders, not all 337! orders; this is an existing implementation detail, not evidence of a perceptible shuffle defect.

For an anchor outside that suffix, one uniquely ideal next song is in the first six-song block only 6/336 ≈ 1.79% of the time. Selecting the first block for similarity would intentionally surrender the exact first-block exposure guarantee. A better block solver can enumerate each block's orders and optimize entry/exit endpoints jointly by dynamic programming. For pairwise additive costs, 56 blocks of six require 40,320 internal permutations, then a small endpoint-state computation. This is exact only under fixed block membership and the specified pairwise objective; longer-window penalties need more state. Sum-product endpoint calculations can sample weighted block orders, whereas retaining only the minimum internal cost cannot.

The recommended algorithm decision is therefore conditional: use scored random permutations as the lowest-complexity comparator; retain the all-candidate sampler only if its continuity gains survive tail-exposure tests; prefer bounded reordering if it gives comparable listener benefit with stronger control over displacement; accept global local search only if it improves actual preferences, not merely its own cost function. Do not commit to one optimizer before this discriminating comparison.

For a fresh 337-song order whose first song is chosen without scoring, scoring the remaining candidates requires 336+335+...+1 = 56,616 evaluations. An anchored suffix containing M songs requires M(M+1)/2 evaluations; M=337 would require 56,953. A full 337×337 float32 directed cost matrix is 454,276 bytes before container/serialization overhead. These are exact arithmetic counts, not browser benchmarks. Expensive feature extraction belongs offline. A vector database or recommendation backend is not compelled by this workload.

There are 113,232 directed non-self pairs, and about `10^704.59` fixed-start full orders. Exhaustive global search is impossible; evaluating bounded whole-order improvement is still entirely plausible. [OR-Tools routing](https://developers.google.com/optimization/routing/tsp), with [Apache-2.0 source](https://github.com/google/or-tools), is an offline reference comparator, not a proposed browser dependency. It exposes guided local search and time limits, and does not guarantee an optimal returned tour. Integer-cost scaling/rounding must be controlled. With directed boundary costs, a segment reversal changes internal edges too; symmetric four-edge delta formulas are not automatically valid.

Two contemporary applications are useful architectural references rather than turnkey choices. [AudioMuse-AI](https://github.com/NeptuneHub/AudioMuse-AI/blob/main/docs/ALGORITHM.md) demonstrates cached sonic features and embedding-based paths but brings server/index infrastructure and candidate filtering/artist caps that should not be imported. Its application is [AGPL-3.0-only](https://github.com/NeptuneHub/AudioMuse-AI/blob/main/LICENSE), separate from model licenses. [LatentJam](https://github.com/Nikita-sud/latentjam) is an Apache-2.0 beta with local audio/metadata and smoothing; its documented 100-song candidate pool does not meet this full-set contract. Study these systems' mechanisms and failure cases, not their feature labels as evidence of quality.

## Evaluation and cost control

First choose 24–40 recordings deliberately covering the catalogue's languages/styles, unmetered passages, acceleration, noisy masters, long medleys, missing metadata, and minority themes. This is a pilot workload proposal, not a statistically powered effectiveness claim. Record why each is included. Reserve songs and, where possible, singers for a held-out comparison.

Separate three experiments:

1. **Meaning:** can reviewers apply definitions consistently and trace central/secondary tags to lines? Inspect disagreement, overbroad labels, missing concepts, and incorrect entity merges.
2. **Representation:** same ordering method with subjects-only, themes-only, basic-audio-only, themes+audio, then one frozen embedding if warranted. Do not assume fusion wins.
3. **Ordering:** same representation/scorer across random, artist-spacing, scored permutations, stochastic sequence, blocks, and bounded global search. Mechanical diagnostics can reject invariant failures or excessive costs, not reject a perceptual contender merely for a worse surrogate distance. After screening, cross the best two representations with the best two algorithms on held-out trials to detect interactions that one-factor comparisons miss.

Use paired and counterbalanced blind comparisons with the same occurrence pool and starting context. Evaluate actual tail→head excerpts for abruptness, then multi-song listening for coherence, surprise, monotony, and desire to continue. Include “no preference.” Excerpts cannot establish long-session quality. For a personal library, owner preference is a relevant product outcome, but it is not a population-level scientific result.

Annotation evaluation needs difficult contrasts: same deity/different theme; same theme/different language; same singer/unrelated meaning; a name as signature versus addressee; criticism versus endorsement of outward ritual; and a long work matching only one minor verse. Reviewers first annotate independently without seeing model suggestions, then distinguish guideline defects, factual errors, and legitimate ambiguity. [Multi-label annotation research](https://aclanthology.org/2022.coling-1.322/) explains why label prevalence and multiplicity make one agreement percentage misleading. Report per-concept precision/coverage and disagreement by language/length, not an arbitrary global kappa target.

Do not use the optimizer's own distance as the primary success measure. Do not count many correlated adjacent transitions as independent listeners. Report uncertainty at the listener/session level and maintain a held-out final comparison. Inspect early ranks, elapsed listening time, whole-queue tails, longest homogeneous runs, and per-song/cohort exposure across many seeds. Equal exposure is a design tradeoff to report, not an unrequested absolute product constraint.

Mechanical invariants include exact occurrence multiset preservation; immutable prefix/current playback for suffix shuffle; correct new session/current selection and repeat reset for library shuffle; duplicates; filtered subsets; no-feature fallback; unavailable-media behavior; stability after subsequent reload/repeat/manual edits; and legacy/shared explicit order compatibility. These checks must pass before any listening experiment in a future implementation.

Bounded cost proposal: no paid calls by default; measure CPU runtime/memory on five diverse recordings first. A five-window × 30-second × 40-song pilot contains at most 100 minutes of detailed-window audio, plus a cheap whole-recording scan. This is input volume, not compute time. Tagging cost depends on actual token volume and human review; calculate it after the pilot rather than quoting an invented dollar total. Cache source/recording hashes so new songs incur incremental work. Stop adding model complexity if a simpler candidate is indistinguishable within the decision-relevant uncertainty or if the annotation/compute burden outweighs the measured benefit.

Operationalize that stopping rule carefully: failing to detect an improvement in a small pilot does not establish equivalence. Prefer the simpler system if the interval excludes a benefit large enough to matter; if the budget ends with a wide interval, report “inconclusive” and retain the baseline without declaring the contender ineffective. The initial representation comparison is finite: current baseline, one semantic representation, one acoustic representation, and their hybrid. Small development comparisons can select at most two representations and two ordering methods for the held-out crossed evaluation. Other models remain named alternatives with a specific escalation trigger, not an implied authorization for an unlimited benchmark grid. Set wall-time/memory caps after the five-recording measurement and before running the larger batch.

Human review is not free: under an explicitly hypothetical five minutes per recording, one pass across 337 recordings is 28.1 person-hours; two passes are 56.2 hours before difficult long works. At two minutes each, one pass is 11.2 hours. Measure actual pilot effort rather than promise those rates. Model-assisted proposals can reduce clerical work; they do not eliminate source reading. Any later paid annotation cost is based on per-song input/output tokens and bounded retries, not an LLM judgment for all 56,616 pairs.

Before a decisive listening comparison, choose the smallest preference improvement worth its operating/editorial cost and a sample/stopping plan; do not retrospectively select a favorable metric. Pilot variance informs the final sample size. Match search time budgets when comparing optimizers. Report random-seed adjacency diversity as well as within-session flow, so the system does not become one excellent playlist replayed in different rotations.

## Implementation boundary and notice restoration

The leading future prototype hypothesis is a **fresh random order of the eligible suffix/set followed by bounded, stochastic membership-preserving improvement**, using transparent semantic and acoustic components plus short-run penalties. It can revise earlier choices and repair a bad tail while keeping the result a shuffle. Compare it seriously with bounded-block ordering and the all-remaining sampler; the evidence does not yet choose its search budget or guarantee perceptual superiority. The preference for this prototype is a design judgment based on the observed failure modes and modest problem size, not a result measured on Bhakti. A deeper neural representation can be substituted later without changing queue ownership or membership rules.

This recommendation does not require a large learned recommender, but it also does not exclude stronger models merely to keep the initial design small. The stopping criterion is decision-relevant improvement in meaning and listening, with cost and exposure made visible. If the best representation and optimizer cannot beat the current experience on held-out judgments, retain current shuffle and use the reviewed semantic work for discoverability instead.

No shuffle code or song metadata has been changed by this investigation. Future build order would be representation contract and reviewed pilot → independent listening/algorithm comparison → chosen queue integration and compatibility tests → actual browser/phone checks. The review must remain capable of choosing uniform shuffle if the proposed intelligence does not help.

Separately, the requested About notice was restored exactly: “Any errors belong to the pipeline, not to the poet, singer, or musician.” History shows removal in `2280078a` on 22 August 2026, titled “Show current song count in About panel.” Restoration commit `84057966` changes only `index.html` and the existing notice assertion. GitHub Pages deployment succeeded, and the live disclosure was checked in the in-app browser; local desktop and 390px checks showed the complete text and working Escape dismissal. The focused notice test, Python compilation, and whitespace check passed; the contract audit marked all 337 songs ready. The broader UI suite has the same 339 failing subtests on the unchanged published baseline and the candidate. Isolated checkout audio files/trim evidence are absent, so audio audits do not establish media readiness; no media changed in this notice release.

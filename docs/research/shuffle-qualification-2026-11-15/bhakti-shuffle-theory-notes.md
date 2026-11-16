# Theoretical sequencing research notes

Research only. No shuffle implementation or model calls. Research cutoff: 2026-11-15. The proposed Bhakti adaptations below are not claims of published validation on devotional music.

## Recommendation

Use a shared, exact evaluator and local improvement engine, with MMAS-style ant construction and iterated local search competing to supply promising complete orders. Ants are a credible candidate, particularly for asymmetric transitions; the literature does not establish that decentralization or pheromone learning beats equally well-engineered local search for this workload. These ants are numerical algorithms, not LLM agents or paid model calls.

## Primary methods and comparison findings

- Canonical ACS, Dorigo and Gambardella 1997: ants mix exploitation of the best pheromone-times-heuristic edge with proportional sampling. During construction they locally move pheromone toward tau_0; after construction, global updating reinforces best-route edges. ACS-3-opt uses orientation-preserving restricted 3-opt for asymmetric problems. Original comparisons favor ACS on several asymmetric instances, but a competing genetic/local-search algorithm wins on symmetric instances. The authors note that comparisons against stronger Lin–Kernighan local search are confounded by different improvement engines. Thus “ants beat simulated annealing” is not unconditional. Original IEEE paper, sections III, VI–VII: https://iridia.ulb.ac.be/~mdorigo/Published_papers/All_Dorigo_papers/DorGam1997tec.pdf . The author URL worked by direct download; the web reader failed. Related accessible author manuscript with transition/update equations: https://staff.washington.edu/paymana/swarm/dorigo97-bs.pdf . Downloaded IEEE text: /tmp/bhakti-acs1997.txt; PDF: /tmp/bhakti-acs1997.pdf.

- MAX–MIN Ant System, Stützle and Hoos 2000: reinforces an iteration-best or best-so-far solution, bounds pheromone, initializes at the upper bound, and studies diversification/reinitialization. Positive lower bounds avoid zero construction probabilities under appropriate heuristic conditions. The paper isolates components experimentally and integrates local search. Repeatedly reinforcing the global best can concentrate search prematurely. Empirical advantages depend on problem structure and local search, not a universal optimization theorem. Author full text, sections 4–5: https://www.cs.ubc.ca/~hoos/Publ/fgcs00.pdf .

- Multi-colony communication, Twomey et al. 2010: factorial experiment compares communication policies/local-search strengths against parallel independent runs. Communication’s benefit changes when local search is added. Aggressive sharing can over-exploit, especially on smaller instances or longer searches; ring/replace-worst policies preserve exploration better. Independent runs are a necessary meaningful control. Full text, sections 3–10: https://iridia.ulb.ac.be/~mbiro/paperi/TwoStuDor-etal2010is.pdf .

- Iterated local search, Lourenço, Martin and Stützle: searches successive local optima by perturbing and improving an existing solution. Controlled TSP experiments use the same fast 3-opt implementation: a suitable double-bridge perturbation reaches many more local optima in the same time than full random restarts. Perturbations must resist being immediately undone without turning each iteration into a restart. Author manuscript, sections 3–4 and Table 2: https://arxiv.org/pdf/math/0102188 .

- DeepACO, NeurIPS 2023: learns construction heuristics with a GNN and optionally alternates objective-directed local search with neural-guided perturbation. Ablations separate ordinary local search, random perturbation and training with local search. In reported TSP500/1000 comparisons, LKH-3 remains stronger on objective quality; several comparison results come from other papers. Transfer to non-Euclidean devotional-song costs is unproven. Full text, sections 4–5, Tables 1–2: https://papers.neurips.cc/paper_files/paper/2023/file/883105b282fe15275991b411e6b200c5-Paper-Conference.pdf .

## Concrete MMAS-derived benchmark recipe

This is a proposed adaptation, not canonical ACS.

1. Input: fixed ordered prefix P; remaining occurrence IDs R; versioned features; versioned cost function. Intentional repeated occurrences of the same recording retain distinct IDs.
2. Each ant starts after P, retaining its final w-1 items for window costs. It constructs a permutation of every R occurrence. Weak tags and uncertain audio never remove a candidate.
3. Freeze the pheromone matrix during a generation. Ants run independently with derived random seeds. Reduce results and update pheromone deterministically at generation boundaries.
4. At state h, calculate the actual incremental cost DeltaE(h,j) for every remaining candidate j. Use a positive heuristic eta(h,j)=exp[-beta*DeltaE(h,j)], evaluated stably. Sample proportionally to tau_ij^alpha*eta(h,j), optionally with an explicit uniform exploration component.
5. Improve each completed order using the same bounded local improver as competing methods.
6. Evaporate pheromone, reinforce the selected improved iteration-best/best-so-far order, and clip to [tau_min,tau_max], with tau_min positive. Specify the reinforcement schedule before evaluation.
7. On measured stagnation, reset/smooth pheromone while preserving the good-order archive. Measure both objective progress and population/edge diversity.
8. Return an eligible archived order under a separately specified serving rule.

Use positive normalized cost for inverse-cost deposits: zero/negative objectives invalidate naive 1/E deposits. Rank-based deposits are a separately named variant. Canonical ACS updates pheromone during construction; immutable per-generation snapshots change that algorithm. Shared asynchronous ACS updates make scheduling semantically consequential. MMAS-style batch updating makes reproducibility and decentralization easier to qualify.

## Objective and correct local moves

Pairwise-only costs produce a directed Hamiltonian path with a fixed entry boundary. A cycle is appropriate only if wraparound or unanchored random rotation is intentional. Window repetition costs, position freshness, prefix exposure and session shape create a richer permutation problem that cannot generally be represented by a fixed edge matrix.

Pair pheromone can learn good edges but cannot fully encode “good unless the previous three songs also concerned surrender.” Keep the true history-dependent incremental evaluator during construction and the full evaluator during improvement.

Eligible moves: swap two unfixed occurrences; relocate one occurrence or short block; reconnect segments without reversal; reverse only with correct directed costs. Reversing an asymmetric segment changes all internal directed edges, not just boundary edges. Window costs require all affected windows to be updated. A symmetric 2-opt shortcut can falsely report improvement.

ILS perturbations must respect the locked prefix. ALNS destruction may temporarily put occurrences in a repair buffer; repair must restore exactly the same occurrence multiset before scoring/adoption. No dropping or substitution.

## Decentralized comparisons

Compare (1) one colony, (2) independent colonies under the same total work/CPU budget, and (3) colonies with infrequent ring or replace-worst exchange. Exchange complete evaluated orders rather than blindly averaging matrices. Re-evaluate migrants against identical objective/feature versions and specify their reinforcement rule. Different objective weights cannot exchange deposits as though costs were commensurate.

Aggressive sharing synchronizes colonies and sacrifices exploration. More workers are more work unless total core-seconds and elapsed time are reported. At 337 songs, numerical parallel runs on one machine suffice for qualification; distributed infrastructure is not justified by the ant metaphor.

## Fair construction/improvement ablation

Use one objective and feature snapshot, identical occurrence/anchor constraints, and exactly the same local-improver implementation.

- Random construction without improvement: baseline.
- Stochastic heuristic construction without pheromone: compatibility heuristic value.
- MMAS construction without improvement: incremental pheromone value.
- Random/heuristic construction plus common improver: improvement without pheromone.
- MMAS plus common improver: pheromone benefit after improvement.
- ILS plus common improver: strong perturbation-based competitor.
- SA or ALNS with the same objective: alternative escape mechanisms for richer costs.

The pheromone-disabled ant control retains counts, seeds, heuristics and improvement budget. MMAS-plus-3-opt versus unimproved greedy is not a decisive comparison.

## Exact scale and work counts

For 337 songs with one fixed first song:

- Remaining occurrences: 336.
- All-remaining construction candidate evaluations: sum(1..336)=56,616.
- Sixteen ants for 32 generations: 512 constructed orders and 28,987,392 candidate-extension evaluations before improvement.
- Undirected song pairs: 56,616; directed non-self pairs: 113,232.
- Full 337 by 337 Float32 matrix: 454,276 bytes, approximately 444 KiB.
- Fixed-start permutations: 336!, approximately 10^704.5894.

A random shuffle only needs its completed-order scoring; equal completed orders do not imply equal computational work. Record candidate extensions, complete evaluations, local-move proposals, accepted moves, primitive edge/feature evaluations, elapsed time and total CPU time. Validate incremental scores against full recomputation.

Proposed research checkpoints, not promises of production latency: 0.1, 0.5 and 2 seconds per run on a fixed single-core setup, with exact work counts and independent seeds. Start with bounded screening and expand meaningful contenders only. No provider calls required.

For arbitrary window objectives, exhaustive fixed-anchor permutations on at most nine total occurrences form an exact small oracle. For pairwise-only objectives, subset DP handles larger small instances. Include sparse bridge songs, isolated recordings, missing features, duplicate recording occurrences, asymmetry and dense thematic clusters.

## Optimization versus sampling and guarantees

Metaheuristics find low-cost orders. Returning the single best may collapse variation despite randomized construction. Serving must separately balance quality and variety, for example by sampling an archive of sufficiently good and sufficiently different orders. Archive sampling is not an exact sample from a known global distribution.

Positive pheromone bounds plus a positive exploration floor give nonzero construction probabilities, not finite-time optimality or equal early exposure. A bound on finding a particular 336-item permutation can be positive yet uselessly small. Local improvement maps many constructions to one local optimum. Finite annealing is not an exact Gibbs sampler.

Evaluate perceived flow, semantic connections, first-5/10/20 exposure, tail deterioration and repeated adjacency separately from the optimizer objective. Otherwise the optimizer may learn flaws in the scoring function.

## Open-source/current implementation references

- OR-Tools, Apache-2.0: https://github.com/google/or-tools . Strong offline pairwise-routing benchmark. Official documentation requires search limits and does not promise optimality: https://developers.google.com/optimization/routing/tsp . Integer costs require deliberate scaling/rounding.
- ALNS Python, MIT: https://github.com/N-Wouda/ALNS . Custom state/objective, destroy/repair operators and stopping rules; suitable rich-objective offline comparator.
- DeepACO, MIT: https://github.com/henry-yeh/DeepACO . Hybrid-design reference, not a drop-in static browser implementation.
- GFACS, MIT: https://github.com/ai4co/gfacs . GFlowNet-guided ant sampling; later candidate if learned sampling has an evidenced need. No claim of exact sampling on new Bhakti objectives.
- LKH-3 fork: https://github.com/c4v4/LKH3 . Explicit academic/non-commercial terms; not a permissive open-source license. Useful benchmark reference with licensing boundary. Original host https://akira.ruc.dk/~keld/research/LKH-3/ timed out in this pass.

## Structural conclusion

The meaningful decision is MMAS-plus-common-improvement versus ILS-plus-common-improvement, with independent parallel runs as the decentralization baseline. This gives ants a serious fair test and prevents stronger local search, greater compute or weaker comparators being mistaken for pheromone benefit. Metadata quality and listening-grounded objective validation remain separate prerequisites.

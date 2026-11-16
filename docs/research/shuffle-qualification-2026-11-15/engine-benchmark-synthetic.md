# Seeded ordering engine: numerical benchmark

15 November 2026. Synthetic frozen features, 16 paired seeds, 32 and 337 occurrences. This evaluates the stated engineering objective, not musical preference or annotation quality. No model calls or network access.

Base revision: `a2a610e89ff028fc68b451286b622900394ecb0c`. Engine SHA-256: `69ae9ab3cfbec42fe5b89929b18e26c818564aebbc7dacb1cba87ff46f136327`. Runtime: `v21.4.0`. Raw trials, counters, wall/process CPU times, calibration and paired summaries: [engine-benchmark-synthetic.json](engine-benchmark-synthetic.json).

Every method preserves the same occurrence set and fixed first item. MMAS uses four ants per frozen generation: 8 constructions mean 2 generations; 16 mean 4. The disabled-pheromone control keeps the same heuristic, construction budget, local improver and local-proposal count. ILS uses the identical local improver. Calibration uses disjoint seeds to approximate MMAS8 elapsed time with an ILS work budget; actual measured ratios below determine whether this matching succeeded.

## 337-occurrence results

| Method | Mean wall ms | Mean process CPU ms | Mean objective improvement over paired random |
| --- | ---: | ---: | ---: |
| ils-construction | 4.57 | 3.23 | 3.363 |
| ils-local256 | 61.82 | 35.52 | 37.397 |
| ils-local1024 | 219.77 | 119.68 | 85.508 |
| ils-local4096 | 823.19 | 446.75 | 124.130 |
| ils-time-matched | 447.92 | 229.17 | 109.966 |
| mmas8-construction | 443.75 | 189.94 | 80.406 |
| mmas8-local256 | 428.67 | 217.93 | 83.313 |
| no-pheromone8-local256 | 401.35 | 226.93 | 84.920 |
| mmas16-local256 | 707.95 | 397.32 | 84.970 |
| no-pheromone16-local256 | 754.16 | 375.26 | 83.690 |
| random | 0.93 | 0.70 | 0.000 |

Positive paired difference below means the left method returns a lower objective. The intervals are approximate normal summaries across the 16 seeds on one synthetic instance; they are not evidence about the population of music or listeners.

| Left − right advantage | Mean | Approximate 95% interval | Left/right elapsed |
| --- | ---: | --- | ---: |
| mmas8-local256 versus ils-time-matched | -26.653 | [-29.364, -23.942] | 0.957 |
| mmas8-local256 versus no-pheromone8-local256 | -1.607 | [-4.020, 0.807] | 1.068 |
| mmas16-local256 versus no-pheromone16-local256 | 1.280 | [-0.469, 3.029] | 0.939 |

## Interpretation and limits

The cheaper initial ILS run had less optimization work than MMAS. Increasing ILS work to approximately matched elapsed time reverses that initial comparison on this synthetic instance. Pheromone-disabled comparisons isolate the coordination contribution; their intervals do not establish a useful pheromone advantage. This is a reason to retain ILS as a serious comparator and to avoid claiming ants win from unmatched budgets. It does not settle the choice on accepted library profiles or demonstrate improved listening.

The benchmark records final sampled archive orders rather than only best-found scores; `bestScore` is retained separately in raw data. A near-best archive keeps seed variation. Uniform exposure, global optimality, a perceptually meaningful objective, and perceptual superiority are not claimed. Weights remain explicit provisional defaults.

Correctness tests independently enumerate tiny directed/window orders; an anchored two-choice fixture requires the exact optimum. They also cover occurrence multiplicities, fixed context, missing/unaccepted metadata, audio direction/proximity, deterministic replay, informative seed variation, strict work caps and 4096-occurrence fallback. For >512 total input occurrences, no quadratic cache/pheromone is allocated; the same local improver receives at most 16 proposals. A separate informative 4096-occurrence smoke run measured roughly74ms at prefix7 and7ms at prefix4000 on this host; those are observations, not browser guarantees.

Reproduce: `node scripts/test_smart_shuffle.js`; `node scripts/benchmark_shuffle.js`. Actual projection: `node scripts/benchmark_shuffle.js --actual --profiles data/shuffle-profiles.js`. The benchmark has a 120-second wall cap checked between trials. Browser responsiveness and listener comparisons remain integration/qualification work.

A concrete calibration counterexample: with16distinct recordings split evenly between two accepted themes and no audio features, the present scorer assigns1.0 to a contiguous8A/8B order and2.5 to alternating2A/2B blocks. The recent-window penalty discourages some repetition but does not guarantee short thematic runs. Whether the longer coherent stretches are welcome requires sequence/listener assessment; this is not a permutation-correctness defect.

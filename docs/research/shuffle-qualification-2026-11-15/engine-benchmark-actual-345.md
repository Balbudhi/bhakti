# Actual catalogue ordering qualification — 15 November 2026

The measured 345-song catalogue supports the bounded ILS production default (8 constructions, 256 local proposals). It does not support adopting ants: elapsed/CPU-matched ILS improved the chosen objective substantially more than MMAS. These are numerical ordering and exposure findings, not listening preference or semantic accuracy measurements. No weights or profiles were changed in response to these results.

## Frozen instance and reproducibility

The raw [benchmark](engine-benchmark-actual-345.json) records source revision `f2d4a37446e95284b18e1a0b54adb27693a5ba7a`, engine SHA256 `69ae9ab3cfbec42fe5b89929b18e26c818564aebbc7dacb1cba87ff46f136327`, benchmark-script hash, Node version, individual runs, budgets, CPU/wall time, first-20 position counts and diversity. Profile revision was `d854e95c18fcfc2f68a99d7b9f271738c878b491d4bf9f50da6a10e4b87a39ee`; file SHA256 `ca003a470facb4fda38b1947c3ddeb1b4dddb5abbc274d20d3152617e21393b5`. The [captured input](engine-benchmark-actual-345-input.json) preserves exactly 345 songs and their profiles through concurrent catalogue growth. Archived JSON is losslessly compacted; hashes recorded during execution identify the original source bytes, not the later compact serialization. 342 semantic statuses and all 345 audio statuses were accepted. Twenty tracks had no accepted themes, including the fixed first track.

All runs hold `koi-hor-nahi` as the current first song (`fixedPrefix:1`). Early windows exclude that anchor. Findings apply to this context; they do not establish equal exposure from every starting song. Sixteen paired seeds (1–16) compare methods; 128 disjoint paired seeds (200000–200127) inspect exposure for production, elapsed-matched ILS, and random. Timing calibration uses separate seeds. Host CPU time is not browser interaction latency.

## Solver result

Mean values across the 16 paired runs; objective gain means random score minus selected score (larger is better).

| Method | Wall ms | CPU ms | Objective gain | Longest shared-theme run |
| --- | ---: | ---: | ---: | ---: |
| Random | 0.67 | 0.72 | 0.00 | 7.00 |
| ILS 8/256, production | 29.47 | 32.69 | 26.22 | 6.00 |
| ILS 8/1024 | 108.32 | 110.11 | 57.81 | 4.88 |
| ILS 8/2502, elapsed matched | 256.18 | 255.96 | 82.94 | 4.75 |
| MMAS 8/256 | 251.60 | 254.10 | 31.86 | 7.31 |
| Same construction, pheromone disabled, 8/256 | 249.39 | 250.69 | 31.97 | 7.62 |
| MMAS 16/256 | 446.50 | 449.06 | 32.61 | 7.00 |
| Pheromone disabled, 16/256 | 440.26 | 439.92 | 31.73 | 7.31 |

Elapsed-matched ILS outperformed MMAS8 by 51.08 objective units (descriptive paired normal interval 48.90–53.26). Their elapsed ratio was 0.982 and CPU ratio 0.993, MMAS/ILS. Holding construction and local work constant, pheromone8 gave −0.11 gain (−1.54–1.33); pheromone16 gave +0.87 (0.16–1.59). The latter small gain does not overcome the much larger advantage of spending the same elapsed time on ILS local improvement. More constructions and an ant label are not evidence of better ordering. The construction-only and local-search ablations remain in the raw file.

Intervals describe variability over seeds on this one fixed instance. They are neither population confidence statements nor claims about listener utility. Production deliberately spends much less time than either elapsed-matched solver.

## Exposure, repetition and rare themes

Across 128 new seeds, the mean longest shared-theme run was 7.11 random, 5.83 production and 5.11 elapsed-matched ILS; maxima were 12, 9 and 9. Production reduces runs here without grouping the whole catalogue into theme blocks, but a hard maximum run length is not guaranteed. Full-order distinct directed-adjacency fractions were 0.837, 0.827 and 0.741 respectively: stronger optimization measurably repeats more adjacencies. These fractions depend on the number of runs and are not independent measures of musical quality.

The movable cohorts contained 3 semantic-unavailable, 19 theme-unavailable, zero audio-unavailable and zero fully unknown tracks. Production's mean first-20 theme-unavailable count was unchanged from random; its first-10 difference was +0.023 and first-50 difference +0.008. Semantic-unavailable first-20 difference was +0.016. The available cohorts show no substantial systematic deferral; this does not test audio-missing behavior because no such track exists in this instance.

A rarity threshold of at most seven occurrences per theme selected only **Jeevan Ke Har Mode**, through the sole `gratitude` tag. Initial 128-seed first-20 exposure fell 10→5, entirely five discordant losses; the exact two-sided conditional binomial probability is 0.0625. A normal interval is misleading for that tiny cohort, so a separate bounded investigation used 1,024 fresh paired seeds (500000–501023), captured 345-song inputs, the same anchor and production 8/256. It completed in 31.4 seconds.

| Movable window | Random exposures / 1024 | Production exposures / 1024 | Paired gains / losses |
| --- | ---: | ---: | ---: |
| First 10 | 21 | 19 | 6 / 8 |
| First 20 | 49 | 54 | 23 / 18 |
| First 50 | 145 | 151 | 43 / 37 |
| Last 20 | 51 | 49 | 13 / 15 |

Mean movable rank was 173.377 random and 173.347 production; paired difference −0.030 (descriptive interval −4.80–4.74). There is no persistent early suppression or tail accumulation in this targeted check. This is not proof of uniform exposure. Raw [paired ranks](engine-exposure-actual-345.json) and [summary](engine-exposure-actual-345-summary.json) preserve the evidence. A preliminary attempt coincided with growth to 349 songs and retained only 345 profiles; it was labeled mixed-state exploratory and excluded from this qualification, then replaced by the captured-input experiment.

The rare track is not an overall thematic outlier: its four accepted themes are grace 0.357, gratitude 0.357, humility 0.143 and refuge 0.143 (median theme count is three). It shares a theme with 194 of the other 324 theme-known tracks. Mean weighted Jaccard similarity to those 324 is 0.0974, approximately the 55th percentile among theme-known tracks (catalogue median 0.0818). Its Sai subject also connects it to other tracks. Rarity of one label does not imply isolation of the whole song. No exposure-driven repair is warranted by this evidence.

## Meaning spot checks and remaining limits

Read source and accepted English in the actual seed-1 production path, rather than treating the projected tags as meaning proof. Jagadoddharana → Meruguvantidi Alamelumanga (positions 27→28, zero-based including anchor) moves from Yaśodā playing with the immeasurable divine child to Alamēlumaṅga's tender affection and meeting Vēṅkaṭeśa. A shared affectionate relationship is intelligible, while maternal and conjugal relationships remain different. The broad theme supplies a gentle bridge, not a claim that the poems express the same relationship.

Har Jiyo Kirpa Karo (position 11) asks for grace, meeting the true Guru and the Name as support; the next Doi Kar Teka Hei Matha includes bowing, the Guru and waking for devotional worship. That is a defensible devotional transition across languages. Earlier Rama Rasa → Sai Sai Bol → Sundar Te Dhyan traverses different devotional foci and includes a track without accepted themes; the order retains unrelated/unknown-theme material rather than requiring every transition to share a tag. Such edges remain candidates for listening assessment, not evidence of a scoring defect.

The entire short source/English of Jeevan Ke Har Mode was read for the rare-theme investigation. Its recollection of rescue, immeasurable favors and a lifetime's unrepayable debt supports gratitude alongside grace and humility; the rare label is not a spurious feature manufactured to explain the exposure result. Source-file hashes for bounded spot checks are in the summary JSON. These are examples, not a new whole-catalogue semantic audit.

The engine preserves every occurrence and fixed prefix by construction and tests. It provides no finite-budget global-optimum guarantee, no promise of uniform later positions, and no hard thematic-run cap. Neither these source checks nor physical audio descriptors constitute listening to transitions. Audible pacing, subjective coherence and preference remain outside this numerical qualification. Final catalogue growth needs bounded membership/profile validation, not reinterpretation of these frozen345 results as measurements on the larger instance.

## Final 349-song release sanity

After the four-song increment, [16 fresh production-only runs](engine-sanity-final-349.json) used profile revision `95601ac5ba8f38f8229f668afd495f442b48fbab49b860d6b9b1db876a8ff46a`, 349 catalogue entries and 349 profiles (346 semantic-accepted, 349 audio-accepted). All preserved every occurrence reference, the fixed first song and inputs without mutation, and every selected score was at least as good as its seeded random baseline. Mean host elapsed time was 33.25 ms, maximum 42.16 ms; mean objective gain was 24.65. First/tail theme-missing counts and rare-track ranks are recorded as a small sanity sample, not an exposure estimate. This adds bounded validation of the final population without replacing or inflating the frozen345 comparison.

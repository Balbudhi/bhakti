# Library search ranking

## Outcome and evidence

A remembered title must outrank a deity tag or incidental lyric. On 24 November
2026 the actual mounted catalogue placed `parvati-devi-mahamayavini` 41st of 50
for `Parvati`: metadata phrases were flattened and inherited singer ordering.
The owner clarified that the exact-title `Pārvatī` (`parvati-hanuman-ansh`,
Sadhu Tiwari) must be first, followed by the longer title. Both are regression cases.

Use explicit successive comparisons, not an additive relevance score. This follows
[Algolia's tie-breaking approach](https://www.algolia.com/blog/engineering/how-algolia-tackled-the-relevance-problem-of-search-engines)
and [Meilisearch's ordered ranking rules](https://specs.meilisearch.dev/specifications/text/0123-ranking-rules-setting-api.html).
Those sources identify field importance, exactness, position, proximity and typo cost
as separate criteria. Our title-first order is a product decision for this library,
not a claim that one order is optimal for every search system. Counting repeated
lyrics or adopting a server/BM25 dependency does not establish the desired ordering.

## Contract

`BHAKTI_SEARCH.filterSongs(songs, {query, lyricIndex, ...facets})` returns the same
song objects in relevance order; it must not mutate input objects, media or DOM.
Catalogue objects and loaded index objects are immutable for a release.

- Empty query retains the existing browse order.
- Every query term is required. Existing common-spelling/IAST folding, native-script
  matching, phrase protection for known names, and conservative typo eligibility stay.
- The first comparison is reliability: complete word/prefix/approximate matches outrank accidental
  inside-word fragments (`hnad` inside `krshnadamodaram` must not beat `hand`).
- Fields, in strict priority order: title; credited people (writer, singer, composer,
  ensemble and legacy credit); discovery fields (aliases, subtitle, slug); subject/
  language tags; terms combined across metadata; performed lyrics/glosses; terms
  combined across metadata and lyrics. A query must be fully explained by a tier;
  a title containing only one of several requested words gets no title-only bonus.
  A field is one individual value: words split across writer and singer, across two
  aliases, or across two lyric lines belong to the corresponding combined tier.
- Within a field: full value; phrase at start; whole-word phrase elsewhere; all whole
  words; token prefixes; bounded spelling correction. Then fewer edits, smallest
  covering word window, earlier position and shorter matching field break ties.
  Approximate lyric matches share the final combined tier and use cached edit cost;
  they do not rescan every lyric line for phrase/proximity bonuses. Approximate
  metadata matches use field identity, edit cost and field length.
  Overlapping prefixes that require reassignment retain their field priority with
  conservative whole-field proximity (for example, `ram rama` → `Rama Ramayana`).
- Final ties use folded title, credited name and slug, never keyword frequency.
  A long/repeated chorus cannot accumulate enough weight to outrank a title.
- Existing exact-name candidate protection is evaluated before facets; facets remove
  results, never reinterpret a person's name. An exact known metadata phrase may
  still admit the same actual phrase in lyrics, not scattered unrelated words.
- Full-vocabulary fuzzy retrieval remains a last resort when there is no reliable
  exact match. Ranking does not make fuzzy retrieval unconditional. No semantic
  paraphrase or guessed synonyms are introduced.
- After deferred lyrics arrive, preserve title priority, latest input, selected
  facets, input focus, existing row nodes and ongoing audio. Network failure keeps
  metadata search and the existing retry behavior.

## Implementation and verification order

1. Add discriminating tests before changing ranking: actual Parvati catalogue/DOM,
   each field tier, phrase/prefix/proximity, a title missing one term, typo field
   priority, accidental internal fragments, deferred index/facets and empty input.
2. Keep field-specific normalized forms in the existing per-song cache. Rank candidates
   once, then sort their small tuples. Reuse cached fuzzy retrieval/costs; scan only
   matched metadata for fuzzy field attribution. No new payload or eager lyric load.
3. Run focused search/filter/player tests. Measure actual catalogue cold/warm queries
   including Parvati, native script, multiword names and typos. Target warm p95 under
   20 ms locally and compare cold fuzzy cost to the previous ~123 ms baseline; report
   actual numbers, not phone claims. No expensive work inside sort comparisons.
4. Run required release audits, assemble, verify resources, publish and compare served
   bytes. Retain existing source/audio review limits; this patch changes search only.

Current step: complete; implementation, independent review and publication verified.
Root owns implementation and integration; independent review was read-only.
No per-query API/model calls or new dependencies.

## Validation, 24 November 2026

- 37 focused search/filter tests pass, including the actual catalogue and mounted
  input handler, deferred lyrics, facets, retained rows, focus and audio identity.
  The independent review's overlapping-prefix regression was reproduced and fixed.
- A 386-song benchmark uses the actual generated 3.9 MB lyric index and compares
  the old/current functions in Node on the same machine. Run each of 14 queries
  cold, then 25 times warm; report the 24th sorted warm observation as p95.
  This is local computation timing, not a phone or browser-rendering measurement.
  Warm p95: `Parvati` 2.21 ms (previous 1.87), `parvti` 7.63 ms (5.33),
  worst tested `take my hnad` 17.36 ms (8.33). First typo search including lazy
  vocabulary construction: 121.96 ms (112.74). No search-index payload growth.
- Contract, Python compilation, subject candidate decisions and shuffle identity
  audits pass. The trim audit still reports the six previously recorded review
  discrepancies. The owner authorized publication preserving those recordings,
  explicitly including the live Satpathy `He Sadaguru`; search changes no audio.
  Translation-review statuses are unaffected by this search release.
- Published runtime commit `12e164b1d2fccb80bf43b24e0dbc44608588cfb0`;
  Pages run `45361607541` passed the complete deployment checks. All 779 checked
  served files match the assembled release, including search code, index, every
  reader and entrypoint. Browser verification was waived by the owner.

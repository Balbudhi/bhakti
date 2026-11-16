# Bounded semantic-tagging capability pilot

Research date: 2026-11-15. This is an assistant annotation exercise, not independently reviewed gold, a model benchmark, or production metadata. No paid API calls, model runs, all-song tagging, or product changes were performed.

## Input integrity and boundaries

Six files in `/tmp/bhakti-notice-20261115/songs/<slug>/data.js` were fetched from `https://bhakti.eeshan.xyz/songs/<slug>/data.js` and compared byte-for-byte with the local file: all six matched. Their public status fields are reviewed/audio-reviewed and reviewed/gloss-derived literal/word-gloss-reviewed. These fields establish the public editorial baseline, not an independent guarantee of correctness. Accepted English below is copied after removing display-token markup; it has not been revised.

| Song | Language label | Unique line records / sequence entries | Public data SHA256 |
|---|---|---|---|
| rehna-nahi-isa-desa | Hindi | 11 / 24 | 862da0dec192a81b1797e853e1a577475587170742fdd5b3120641a7988b2908 |
| guru-charana-re-karo-dhyana | Odia | 11 / 37 | f218dd48a385379521557be869c63bc326ef65288d8a9115c92774ff9b637ec5 |
| tumhi-mere-lagan-lagai-re | Hindi | 6 / 17 | 230d97d34e033cb91496ad572d6baefe4d215fa29da7fb123d46f0b0087e97dc |
| uyarvara-uyar-nalam | Tamil | 49 / 57 | 98af934d7b431f1e8578379dd5b58f6821a83abdbe5bf40c7f212622622ec708 |
| hanuman-chalisa | Awadhi | 47 / 47 | a21789a93578610ae8fc624dbf77123d320396c616a3af236b377ee4a43c75d4 |
| sampurna-sundarakanda | Awadhi | 539 / 539 | 8e0e863c981a6a84ae04d008a9eeb11102b0bd7376a86f9b5bfc4d366c92eb7e |

All unique source/English line records of the first five were inspected. The long sixth recording was sampled at its opening, at intervals, at its ending and in contiguous passages around the selected evidence. Consequently, no full-song centrality or exhaustive concept-coverage claim is made for it. Line count is dictionary-entry count, not maximum numeric suffix. Repeated sequence entries do not create new semantic evidence automatically. Instrumental/stage directions are not lyric assertions.

## Actual examples and tentative assertions

### 1. Rehnā Nahī̃ Isa Desa

Public page: https://bhakti.eeshan.xyz/songs/rehna-nahi-isa-desa/

- `verse-1-line-1`: `ये संसार कागज़ की पुड़िया` — “This world is a packet of paper”. `verse-1-line-2`: `बूंद पड़े ढल जाना है` — “Upon a drop falling, it is bound to flow away”. The parallel burning-thicket image at `verse-2-line-1` / `verse-2-line-2` and repeated no-staying refrain support **impermanence**, tentatively central. **Fragile world / paper-and-water imagery** is directly evidenced; it need not become a global controlled tag until useful.
- `verse-3-line-2`: `सतगुरु नाम ठिकाना है` — “The true Guru's Name is the refuge”. Supports **refuge in the teacher's name**, a concluding supporting theme, and **Guru**, a relational referent. It does not identify a historical teacher.
- `verse-3-line-1`: `कहत कबीर सुनो भाई साधो` — “Says Kabīr, listen, O brother seekers”. Kabīr has **poet-signature/speaker** role, not the song's devotional addressee. Do not recommend it as a song worshipping Kabīr merely because his name appears.
- Public `Nirguṇa` metadata is retained as existing metadata; this bounded lyric exercise does not independently certify a doctrinal classification.

### 2. Guru Caraṇare Kara Dhyāna

Public page: https://bhakti.eeshan.xyz/songs/guru-charana-re-karo-dhyana/

- `refrain-1`: `ଗୁରୁ ଚରଣରେ କର ଧ୍ୟାନ` — “Meditate at the feet of the Guru”. Supports **meditation**, an imperative practice; **Guru**, central devotional focus; **feet imagery**.
- `v1-3`: `ଗୁରୁ ନାମେ ଦୃଢ଼ କର ମନ` — “Make the mind firm in the name of the Guru.” Supports **attention to the name**. It does not by itself specify audible chanting or group singing.
- `v2-1`: `ଜୀବନ ନାବ ତ ବହୁତ ଦୁର୍ବଳ` — “The boat of life is indeed exceedingly frail,”; `v2-2` describes crossing the ocean of Great Time; `v2-3`: `ଗୁରୁ ଅନୁକୂଳ ପଛୁଆ ପବନ` — “the Guru is the favorable following wind.” Supports **guidance through life's vulnerability** and **boat/ocean crossing imagery**, supporting passage-level assertions.
- `v3-2`: `ମିଳନ୍ତି ଶ୍ରୀଗୁରୁ ପ୍ରଭୁଙ୍କ କୃପାରେ` — “the revered Guru is attained through the Lord's grace.” Supports **grace**, supporting. It does not name the Lord.
- Specific teacher identity is **reviewed-unknown for this proposal**: the available text does not establish Śirḍī Sāī. Existing tag-override evidence makes the same distinction. Unknown identity does not block Guru, meditation or imagery annotations.

### 3. Tumhī More Lagan Lagāī Re Fakīrwā

Public page: https://bhakti.eeshan.xyz/songs/tumhi-mere-lagan-lagai-re/

- `tu_hi_more_lagan`: `तू ही मोरे लगन लगाई रे फकीरवा` — “You alone kindled devotional longing within me, O fakir.” Supports **devotional longing**, central; **fakir**, addressed role, identity unspecified.
- `manwā_lāge_na`: `मनवा लागे न कहीं तोरे बिन सइयाँ` — “My heart finds no peace anywhere without You, my Beloved.” Supports **longing in absence**; **beloved** is a relationship/address, not a resolved proper name.
- `bahiyā_pakaṛ_ke`: `बहियाँ पकड़ के जगाए रे फकीरवा` — “Holding my arm, You awakened me, O fakir.” Supports **awakening imagery** and the addressee's agency. It does not justify a generic claim that the narrator independently attained awakening.
- `more_ghaṭ_mẽ`: `मोरे घट में है तोरी साँस रे फकीरवा` — “Your breath is within my vessel, O fakir.” Supports **breath / vessel imagery**, a supporting image. Turning it into an exact doctrinal identity claim is unsupported.
- Borderline: **historical identity of the fakir/beloved remains unknown**. `सइयाँ` must not be matched to Sāī by roman-prefix similarity. The current empty subjectTags does not mean the song lacks meaning; this is a strong example of semantic richness beyond current entity tags.

### 4. Uyarvaṟa Uyar Nalam

Public page: https://bhakti.eeshan.xyz/songs/uyarvara-uyar-nalam/

- `l004`: `துயர் அறு சுடர் அடி தொழுது எழு என் மனனே` — “My mind, worship his radiant feet that end suffering, and rise!” Supports **worship/praise**, directed to one's mind as interlocutor and the divine as object. Do not collapse grammatical addressee and worshipped referent.
- `l027`: `உடல்மிசை உயிர் எனக் கரந்து எங்கும் பரந்துளன்` — “like life within a body, hidden, he pervades everywhere.” With `l026`, `l036`, `l037` and `l040`, supports **divine pervasion/presence**, tentatively central, plus **life-in-body imagery**.
- `l006`: `மனன் உணர்வு அளவு இலன் பொறி உணர்வு அவை இலன்` — “He is beyond the measure of the mind’s awareness; he is not those things perceived by the senses.” Supports **limits of mental/sensory apprehension**, supporting theme, not a denial of every possible form of knowing.
- `l044`: `நிரல் நிறை ஆயிரத்து இவை பத்தும் வீடே` — “Among the thousand, ordered and full, these ten are liberation itself.” Supports **liberation**, passage/closing theme.
- `l043` names Caṭakōpaṉ of Kurukūr in **poet/signature** role. `l049` invokes refuge in Āḻvār's feet in the closing; do not automatically let that coda displace the principal body of the hymn.
- Existing Viṣṇu classification may be supplied as reviewed legacy evidence. This exercise does not infer a sect or convert pervasion into an undifferentiated “nonduality” tag. Precise doctrinal interpretation is unresolved and not needed for useful ordering.

### 5. Hanumān Cālīsā

Public page: https://bhakti.eeshan.xyz/songs/hanuman-chalisa/

- `chaupai-01`: `जय हनुमान ज्ञान गुन सागर` — “Hail Hanuman, ocean of wisdom and guṇas!” Supports **Hanumān**, central addressee, and **praise**, central devotional action.
- `chaupai-02`: `राम दूत अतुलित बल धामा` — “Envoy of Rama, abode of incomparable strength”; `chaupai-07`: `राम काज करिबे को आतुर` — “eager to carry out the work of Rama.” Supports **service/messenger duty**, recurring theme; Rāma is the served Lord and narrative referent, not interchangeable with the principal direct addressee.
- `chaupai-22`: `तुम रक्षक काहू को डर ना` — “when you are the protector, there is no fear for anyone”; `chaupai-26`: `संकट तें हनुमान छुड़ावै` — “Hanuman frees from distress”. Supports **protection/refuge** and **relief from distress**, recurring themes.
- `doha-2b`: `बल बुधि बिद्या देहु मोहिं` — “Grant me strength, intellect, and wisdom”. Supports **petition**. Store who petitions whom; this is distinct from recounting Hanumān's past deeds.
- `doha-1a` invokes the guru's feet; `chaupai-37` asks grace in the manner of a guru. Guru is a real reference, but the opening reference alone cannot justify ranking this as primarily a teacher-focused hymn.
- `chaupai-40a` names Tulsidas in poet/signature role. Names in enumerations (`chaupai-14`, `chaupai-15`) do not each become central subjects.
- Some accepted English lines elsewhere warrant separate translation attention; this pilot does not repair or depend on contested readings. Narrative events and healing claims are tagged as content asserted by the hymn, not real-world efficacy claims.

### 6. Sampūrṇa Sundarakāṇḍa: deliberately incomplete long-form demonstration

Public page: https://bhakti.eeshan.xyz/songs/sampurna-sundarakanda/

- `line-025`: `राम काजु करि फिरि मैं आवौं। सीता कइ सुधि प्रभुहि सुनावौं ॥` — “Having accomplished Rāma’s work, I will return and relate tidings of Sītā to the Lord.” Supports **service/messenger mission** in this passage.
- `line-165`: `राम दूत मैं मातु जानकी` — “I am Rama’s messenger, O Mother Janaki”. `line-166` identifies the signet ring as a recognition token. Supports **messenger identity** and **recognition/token imagery**, with speaker and addressee retained.
- `line-171`: `बूड़त बिरह जलधि हनुमाना` — “As I was drowning in the ocean of separation, O Hanuman”; continuation calls him a vessel. `line-177` explicitly describes Sītā as distressed by separation. Supports **separation/longing** and **ocean/vessel imagery**, for this episode. This connects meaningfully with the fakir song without claiming identical religious referents or emotional trajectories.
- `line-500`: `आएँ सरन तजउँ नहिं ताहू` — “once he comes for refuge, I do not abandon him.” With adjacent lines and narrative speaker attribution, supports **acceptance of one seeking refuge**, episode-level; preserve that it is a declaration by a character, not a narrator's personal petition.
- Names in `line-002` / `line-251` include Brahmā and Śiva in invocatory/theological relations. These mentions alone must not outweigh the narrative's central figures.
- Status: **partial semantic review**. No exhaustive top-level theme set, coverage percentage, or full-song prominence certified. Complete future annotation requires a stable episode manifest covering every performed unique passage, local episode proposals, independent checking and a final synthesis that sees all episode summaries plus citations. Do not simply take the first 32K tokens or maximum segment match. Actual sequence determines whether a repeated passage is heard again; content tagging and duration/repetition weighting remain separate.

## Candidate vocabulary arising from these examples

This exercise supports investigating themes of impermanence; refuge/protection; grace; longing/separation; service; divine pervasion/presence; limits of mental/sensory apprehension; liberation; and guidance. Actions include praise/worship, petition, meditation/attention, remembrance, and service. These are candidates with scope notes still required, not an imposed quota or finished universal ontology. Some concepts span facets; choose one canonical ID and record relationships rather than duplicate independent score contributions. For example, service as an enacted action and service as a dominant narrative theme are assertion roles of a common concept.

Entities and roles are open-ended: deity/saint names, unnamed teacher, fakir, beloved, poet/signature, narrative speaker, narrated participant, central object of worship. Do not force every role into a named entity. Imagery may remain free-text evidence initially; promote repeated useful images to controlled IDs only when evidence and ranking evaluation warrant it. No audio energy, BPM, rāga, tāla, instrumentation, singer identity or performance mood can be certified from these text tags alone.

## Proposed API contract (design only)

The API proposes evidence-grounded assertions; it cannot approve itself. One request uses the complete reviewed text for a short song or one declared contiguous episode for a long song. Same contract works for a human annotator without an API.

Request fields:

- `schemaVersion`, `jobId`, `recordingId`, `workId` if established, `scope` (`complete_text` or explicit episode ID), `inputHash`, `vocabularyVersion`, `policyVersion`.
- `lines`: exact IDs, source, sourceLanguage, acceptedEnglish, reviewed contextual glosses; `performance`: sequence IDs and kinds, supplied separately from unique content.
- `vocabulary`: IDs, facets, definitions, inclusion/exclusion examples and permitted relations. `reviewedMetadata`: separately marked legacy assertions and their evidence, not hidden model hints.
- `coverageManifest`: expected line IDs for the present scope, exclusions and reasons; parent episode manifest for composites.
- Instructions: cite line IDs and exact short substrings; retain agency, negation and speaker; distinguish mention from focus; use no artist/album inference; never guess identity; propose new concept separately; zero assertions is legal with a reason; do not emit confidence-as-probability, rewrite lyrics or certify review.

Response shape:

```json
{
  "jobId": "...",
  "inputHash": "...",
  "scope": {"kind": "complete_text"},
  "assertions": [{
    "conceptId": "theme.impermanence",
    "facet": "theme",
    "role": "asserted_theme",
    "prominence": "central",
    "scopeLineIds": ["verse-1-line-1", "verse-1-line-2"],
    "evidence": [{"lineId": "verse-1-line-1", "sourceQuote": "ये संसार कागज़ की पुड़िया"}],
    "rationale": "The following line describes its dissolution, parallel to the burning-thicket verse.",
    "alternativeReadings": []
  }],
  "unresolved": [{"facet": "entity_identity", "reasonCode": "not_identified_in_text", "lineIds": ["verse-3-line-2"], "detail": "Guru is named as a role, no historical person established."}],
  "newConceptProposals": [],
  "coverage": {"inspectedLineIds": ["..."], "excluded": [{"lineId": "intro-instrumental", "reason": "stage_direction"}]}
}
```

A request may use structured-output schema constraints if the selected provider/model supports them, but schema validity is not semantic validation. Validate provider support before implementation; do not assume arbitrary JSON Schema capability. Exact quote checking and line-ID set accounting are deterministic. The response's `inspectedLineIds` is a claim, not proof that the model read every line.

## Independent critical check and future intake gate

1. Deterministic checker rejects missing/unknown line IDs, mismatched quotes/hashes, unsupported vocabulary IDs, invalid facet/role combinations, duplicate concept contributions and incomplete declared scope accounting. It cannot prove the interpretation.
2. Independent reviewer receives all original text and vocabulary, first considers salient supported concepts independently, then checks proposals for entailment, centrality, speaker/agency, negation, omissions, ambiguity and imported doctrine. Independent model execution is not independent human gold; a second model from a distinct family may help diversify failures but is not a correctness guarantee.
3. Reviewer records `accept`, `reject`, or `unresolved` per assertion with evidence; cannot silently rewrite public translation. A conflict with an accepted translation goes to the existing editorial workflow.
4. Proposed mandatory new-song gate: a complete semantic review record is required, **not a minimum tag count**. Each required facet is `reviewed_supported`, `reviewed_none`, or `reviewed_unknown` with a reason. Empty supported themes are allowed for a short name chant. Unnamed referent is allowed. Model/API failure is `pending` or `failed`, not `reviewed_unknown`; it requires manual review or an explicit existing release exception. The song remains eligible for ordinary shuffle even with no semantic boost.
5. Only accepted assertions enter queue scoring. Unknown and partial facets contribute no asserted similarity and never exclusion. A complete long recording may contain unresolved episodes with explicit coverage/reasons; whole-song centrality cannot be stamped complete from sampled excerpts.
6. Hash the canonical source/accepted English/glosses and performed-content selection independently of unrelated HTML or credits. Changes invalidate dependent assertions; timing-only changes invalidate duration/repetition-derived scores, not necessarily textual interpretation. Vocabulary-definition, policy or model/prompt changes invalidate the appropriate cached proposal/check outputs; preserve reviewed decisions with migration review, not silent reclassification. Owner-approved English remains unchanged.

This gate is a proposed design for the requested next phase. It has not been installed in AGENTS, scripts or release checks.

## What can be measured, and what has actually been measured

Observed here: public-file match 6/6; complete unique-line source/English inspection 5/6; sampled-only long-form inspection 1/6; paid model calls 0; independent semantic gold reviews 0. No accuracy or calibrated confidence claim follows from this exercise. Model self-confidence, two agents agreeing and a valid quote are not semantic accuracy measurements.

A later bounded qualification should create independent held-out reference annotations and track:

- Assertion precision (supported accepted proposals / checked proposals), separately for exact entity identity, role, prominence, themes and images.
- Recall against adjudicated reference assertions, preserving documented alternative readings rather than forcing a single interpretation.
- Operational review coverage (songs/facets with completed review records), evidence coverage (unique performed passages accounted for), and automatic acceptance coverage (proposals accepted without human intervention): three different denominators.
- Risk versus coverage: when uncertain proposals are withheld, how does observed error among retained assertions change? Report abstention rates and errors by language, length and ambiguity; no invented “95% confidence” gate.
- Promotion accuracy: are referenced figures incorrectly elevated to central subject? Signature false positives, ambiguous-name false positives and negation errors deserve their own adversarial cases.
- Downstream blinded thematic-neighbor and actual queue judgments; good tag accuracy is necessary but does not prove good ordering.

Primary methodological sources:

- Geifman & El-Yaniv, selective classification (2017): https://proceedings.neurips.cc/paper/2017/hash/4a8423d5e91fda00bb7e46540e2b0cf1-Abstract.html . Supports separating risk and coverage; its image-classification guarantees do not transfer to this proposed LLM annotation process.
- Guo et al., calibration (2017): https://proceedings.mlr.press/v70/guo17a.html . Predicted confidence must be compared with observed correctness; temperature-scaling results for classifiers do not automatically calibrate verbal model confidence here.
- Marchal et al., multilabel annotation quality (2022): https://aclanthology.org/2022.coling-1.322/ . Label multiplicity and distributions affect agreement, motivating per-facet and chance-aware reporting.
- Oortwijn et al., disagreement resolution (2021): https://aclanthology.org/2021.humeval-1.15/ . Useful for diagnosing underspecified task instructions; legitimate literary ambiguity must still remain explicit.
- W3C SKOS: https://www.w3.org/TR/skos-reference/ . Stable concepts, multilingual labels, scope notes and lightweight relations; not a warrant for doctrinal equivalence.

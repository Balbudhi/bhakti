"""Frozen exact pre-binding callers from347a936e; test-only migration evidence."""
def translate(song_dir: Path, audited: dict[str, Any], glosses: dict[str, Any], job: dict[str, Any], options: argparse.Namespace, *, candidate_only: bool = False, defer_review: bool = False) -> dict[str, Any]:
    options = bhakti_translation_policy.prepare_naming_options(options, audited['packet'].get('verified_lines', []),
        job.get('languages', audited['packet'].get('metadata', {}).get('languages')), source_slug=job.get('slug'))
    options, glosses = bhakti_lexical_producer.prepare_translation(song_dir, audited, glosses, options)
    target = song_dir / ".transcription" / "pipeline" / "05-translation.json"
    lines = audited['packet'].get('verified_lines', [])
    gloss_rows = glosses['packet'].get('glosses', [])
    gloss_by_id = {row['id']: row for row in gloss_rows}
    provided_translation = supplied_translation(job)
    audited_languages = audited.get("packet", {}).get("metadata", {}).get("languages")
    languages = job.get("languages", audited_languages)
    def language_identity(value: Any) -> set[str]:
        aliases = {"hi": "hindi", "hindustani": "hindi", "classical hindi": "hindi"}
        return {aliases.get(str(item).strip().casefold(), str(item).strip().casefold())
                for item in (value or [])}
    for label, evidence_languages in (("audited source", audited_languages),
                                      ("gloss evidence", glosses.get("sense_languages"))):
        if evidence_languages is not None and language_identity(evidence_languages) != language_identity(languages):
            raise RuntimeError(f"translation language conflicts with {label}")
    sense_errors = bhakti_translation_policy.sense_decision_errors(lines, gloss_rows, languages)
    if sense_errors:
        raise RuntimeError(f"translation input violates sense evidence contract: {sense_errors[:3]}")
    support = bhakti_lexical_support.prepare_options(options, lines, languages)
    support_errors = bhakti_lexical_support.support_decision_errors(support, gloss_rows)
    if support_errors:
        raise RuntimeError("translation lexical support: " + str(support_errors[:3]))
    policy = semantic_stage_policy(options)
    fingerprint = text_stage_fingerprint("translation", options.model,
        translation_stage_inputs(lines, gloss_rows, provided_translation, languages, options,
            performance_order=audited["packet"].get("performance_order", [])), policy)
    existing = read_packet(target)
    if (existing and existing.get("fingerprint") == fingerprint and not options.force
            and existing.get("input_contract_version") == TRANSLATION_INPUT_VERSION):
        errors = fresh_translation_contract_errors(
            lines, gloss_rows, existing.get("packet", {}).get("translations", []), **translation_packet_contract_kwargs(lines, existing, options, performance_order=audited["packet"].get("performance_order", []), expected_review_task_version=existing.get("review_task_version", 0)))
        errors.extend(bhakti_lexical_support.support_decision_errors(support, gloss_rows, existing.get("packet", {}).get("translations", [])))
        errors.extend(automatic_evidence_errors(options, existing))
        errors.extend(bhakti_source_discovery.translation_decision_errors(
            getattr(options, 'automatic_source_discovery', None), existing.get('packet', {}).get('translations', [])))
        if errors:
            raise RuntimeError(f"cached translation violates fresh contract: {errors[:3]}")
        if existing.get('review_task_version', 0) == REVIEW_TASK_VERSION:
            return existing
        candidate = copy.deepcopy(existing)
        candidate.pop('review_responses', None)
        candidate.pop('review_task_version', None)
        for row in candidate['packet']['translations']:
            row.pop('independent_review', None)
        if defer_review:
            return candidate
        refreshed = review_translation(song_dir, audited, glosses, job, options, candidate, prepared=True)
        errors = fresh_translation_contract_errors(lines, gloss_rows, refreshed['packet']['translations'], **translation_packet_contract_kwargs(lines, refreshed, options, performance_order=audited['packet'].get('performance_order', [])))
        if candidate_only:
            return refreshed
        if errors:
            stage_quality_failure(options, f'refreshed review violates fresh contract: {errors[:3]}')
        write_json(target, refreshed)
        return refreshed
    provided_rule = ("A human translation is supplied and LOCKED. Copy its wording exactly for every matching line; "
                     "do not silently correct or polish it in this stage. If lexical evidence appears to conflict with it, "
                     "preserve the supplied wording, set human_review_recommended=true, and explain the conflict in choice_note."
                     if provided_translation != "(none supplied)" else
                     "No human translation is supplied; choose the closest supported English and expose material alternatives.")

    def prompt_for(batch: list[dict[str, Any]], context: list[dict[str, Any]]) -> str:
        batch_glosses = [gloss_by_id[line['id']] for line in batch]
        term_registry = preserved_term_registry()
        return f"""Write faithful, complete English translations from the supplied word glosses, semantic frames, and grammar notes ONLY. The semantic frame is authoritative for agency, action/state, patient/complement, negation/modality, literal image, idiom, and cross-line syntax. Do not introduce a looser synonym, devotional interpretation, or omission that it does not support.

For each line, reason in this order before choosing the final English:
1. Compose the indexed token glosses into the closest grammatical English scaffold.
2. Check the scaffold against every semantic-frame field and neighboring line.
3. Preserve the source's agent, experiencer, and voice/state exactly. Never change “my breath abandons me” into “I breathe my last,” “I am broken from the inside” into “I broke from the inside,” a deity dwelling in a palm into an abstract spiritual state, or an interior image into a generic emotion merely because the alternative is conventional English.
4. Apply an established idiom only when `idiom_or_phrase` identifies it and the idiom does not erase a deliberate image. The devotional phrase `raham nazar` means “look upon [someone] with mercy”; do not render it as “cast a glance.” Conversely, do not invent a replacement metaphor such as “kindle” or “stir” when the source image is that a feeling “takes hold.” A possessed relational noun such as a garment hem should remain explicit rather than becoming an ambiguous “your hem.”
5. Make only the smallest grammatical adjustments needed for intelligible English. Prefer the source's transparent spatial vocabulary (“from the inside”) over a smoother intensifying substitute (“deep within”) unless depth is lexically present. Literal and poetic force outrank smoothness.
6. Translate ordinary words and philosophical concepts into precise English, using a short contextual phrase even for registry-listed concepts. A `concept_key` is bookkeeping, not an instruction to leave the term untranslated. When every considered English word, phrase or transparent compound would consequentially distort the passage, retaining the source term is permitted with an understandable clickable gloss. Record the best English paraphrase and its specific loss in `choice_note`, and in a `retained_term` wording decision when lexical support targets it. A legacy `preserve_in_english=true` flag alone does not justify retention. Existing locked English remains exact. Retain genuine proper names, whose clickable gloss must explain their evidenced identity or relationship. The sense used in every English segment must match the chosen primary meaning at its linked word indices, including compounds and inflections; supported alternatives remain separately explained in grammar notes.

{bhakti_translation_policy.naming_prompt(options, batch)}{bhakti_translation_policy.guidance(batch, languages=languages, context_lines=getattr(options, "semantic_full_source", lines), performance_order=getattr(options, "semantic_performance_order", audited["packet"].get("performance_order", [])))}{bhakti_lexical_support.prompt(support, [line['id'] for line in batch], 'translation')}{bhakti_lexical_producer.diagnostics_prompt(options)}{bhakti_source_discovery.prompt(options, [line['id'] for line in batch])}

For each line, return plain literal English plus ordered display segments. Read adjacent lines as a continuous utterance before deciding syntax, punctuation, ellipsis, pronouns, or repeated words; a line may be a deliberate grammatical continuation. Each segment may reference the exact word indices which support it; punctuation or necessary English function-word segments can use an empty index list. Every source word index must appear in at least one segment. Map particles, postpositions, tense/aspect, negation, modality, and honorifics to the English phrase they help create rather than leaving their source index uncovered.

Write lucid devotional English, but do not confuse conventional English with better poetry. Literal strangeness, repetition, personification, unusual agency, and concrete bodily or ritual imagery may be the point. Preserve a supported image such as “my breath will abandon me” even if an English idiom such as “I will breathe my last” sounds smoother. Preserve suffered/resultant states as states: if the lyric says the speaker is broken, keep that brokenness rather than recasting it as the speaker actively broke. Never replace the source's agency, metaphor, ambiguity, or emotional logic merely to sound idiomatic. Correct wording only when it is demonstrably wrong, ungrammatical, or obstructs understanding. Avoid legalistic filler, accidental inversion, duplicate modifiers, and unsupported editorial verbs. Retain sacred sight or encounter as the context warrants, an alms bag, garment hem, cupped or open palm, lotus, dust, ocean, threshold, cage, and Mount Meru when the source supports them.

Use established English words. A rare but attested word is acceptable when it is precise and remains understandable in context. A transparent, source-supported compound may join two ordinary words, preferably with a hyphen when that aids reading. Never invent pseudo-Latin vocabulary or use a franchise-specific fictional coinage such as `adamantium`, `vibranium`, or `mithril`. `Adamantine` is an established English adjective and is not the fictional noun `adamantium`.

Resolve ordinary polysemy from the supplied grammar/song context. When two defensible renderings differ materially in agency, metaphor, ambiguity, or poetic force, include both in `material_alternatives` and set `human_review_recommended=true` instead of silently optimizing for smoothness. This is not required for trivial synonyms. The completed segments must reconstruct `literal_english` exactly, including ordinary spacing and punctuation. Then report a fidelity check: whether agency/image and all source meaning were preserved, every unsupported addition (normally none), and a concise note naming any nonliteral idiom or necessary English function word.

Do not flatten jāti, jñātī, jāta-pāta, and varṇa into an undifferentiated “caste.” Translate jāti/jñātī contextually as community, clan, kin group, or occupational group; translate varṇa as the broader fourfold social order or its rank/classification. When a source contrasts jāti and varṇa, make that distinction intelligible in English.

{semantic_repair_prompt(options)}

TARGET audited source lines (return these IDs only):
{json.dumps(batch, ensure_ascii=False)}

TARGET word gloss record:
{json.dumps(batch_glosses, ensure_ascii=False)}

CURATED PRESERVED-TERM REGISTRY:
{json.dumps(term_registry, ensure_ascii=False)}

NEARBY source context (do not return these IDs unless also targets):
{json.dumps(context, ensure_ascii=False)}

HUMAN-TRANSLATION RULE:
{provided_rule}

Supplied translation:
{provided_translation}

Return strict JSON:
{{"translations":[{{"id":"canonical-id","literal_english":"","segments":[{{"text":"","word_indices":[]}}],"material_alternatives":[],"human_review_recommended":false,"choice_note":"","fidelity":{{"agency_and_image_preserved":true,"all_meaning_accounted_for":true,"unsupported_additions":[],"notes":""}},"uncertainty":""}}],"comparison":[{{"id":"canonical-id","supplied":"","chosen":"","material_change":false,"reason":""}}]}}"""
    schema = {"type": "object", "properties": {
        "translations": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "literal_english": {"type": "string"},
            "segments": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string"}, "word_indices": {"type": "array", "items": {"type": "integer"}}},
                "required": ["text", "word_indices"], "additionalProperties": False}},
            "fidelity": {"type": "object", "properties": {
                "agency_and_image_preserved": {"type": "boolean"},
                "all_meaning_accounted_for": {"type": "boolean"},
                "unsupported_additions": {"type": "array", "items": {"type": "string"}},
                "notes": {"type": "string"}},
                "required": ["agency_and_image_preserved", "all_meaning_accounted_for", "unsupported_additions", "notes"],
                "additionalProperties": False},
            "material_alternatives": {"type": "array", "items": {"type": "string"}},
            "human_review_recommended": {"type": "boolean"},
            "choice_note": {"type": "string"},
            "uncertainty": {"type": "string"}},
            "required": ["id", "literal_english", "segments", "material_alternatives", "human_review_recommended", "choice_note", "fidelity", "uncertainty"], "additionalProperties": False}},
        "comparison": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "supplied": {"type": "string"}, "chosen": {"type": "string"},
            "material_change": {"type": "boolean"}, "reason": {"type": "string"}},
            "required": ["id", "supplied", "chosen", "material_change", "reason"], "additionalProperties": False}},
    }, "required": ["translations", "comparison"], "additionalProperties": False}
    schema = bhakti_source_discovery.extend_schema(schema, options)
    # Literal translations carry indexed English segments, alternatives, and
    # fidelity evidence.  Keep medium recordings in the same bounded batch
    # path as long recordings rather than waiting on one oversized response.
    selected = getattr(options, 'semantic_translation_targets', None)
    candidate_lines = [line for line in lines if line['id'] in selected] if selected is not None else lines
    if not candidate_lines:
        raise RuntimeError('semantic repair has no translation targets')
    cached_candidate = read_packet(target.parent / 'translation-candidate.json') if candidate_only else None
    reuse_candidate = bool(cached_candidate and cached_candidate.get('fingerprint') == fingerprint
                           and cached_candidate.get('input_contract_version') == TRANSLATION_INPUT_VERSION)
    if reuse_candidate:
        result = copy.deepcopy(cached_candidate)
    elif candidate_only and getattr(options, 'semantic_seed_translation', None):
        result = copy.deepcopy(options.semantic_seed_translation)
    elif len(candidate_lines) <= 40:
        result = gemini.call(options.model, gemini.key(), prompt_for(candidate_lines, []), audio=None, timeout=stage_call_timeout(options),
                                       response_schema=bhakti_lexical_support.extend_schema(schema, support, "translation"), schema_name="bhakti_literal_translation",
                             reasoning_effort="high", max_completion_tokens=65536, **stage_transport_context(options))
        capture_writer_response(options, result)
        # This response was just returned by this attempt. Cached candidates and
        # adopted seeds reach only the ordinary local validation below.
        returned_rows = stage_model_rows(result, 'translations', options)
        target_ids = [line['id'] for line in candidate_lines]
        returned_errors = bhakti_lexical_support.support_decision_errors(
            bhakti_lexical_support.project_support(support, target_ids),
            [gloss_by_id[line_id] for line_id in target_ids], returned_rows)
        returned_errors.extend(bhakti_source_discovery.translation_decision_errors(
            bhakti_source_discovery.projected(getattr(options, 'automatic_source_discovery', None), target_ids),
            returned_rows))
        if returned_errors:
            stage_quality_failure(options, 'translation lexical support/source discovery: ' + str(returned_errors[:3]))
    else:
        # Preserve the historical 40-line parent cache shape so already
        # completed work remains reusable, but issue fresh requests in bounded
        # 20-line children. Long translation JSON contains indexed segments and
        # fidelity evidence; a 40-line response can be truncated even with the
        # provider ceiling set to 65,536 tokens.
        batches = [candidate_lines[index:index + 40] for index in range(0, len(candidate_lines), 40)]
        cache_dir = song_dir / ".transcription" / "pipeline" / "translation-batches"
        cache_dir.mkdir(parents=True, exist_ok=True)

        def run(index: int) -> dict[str, Any]:
            batch = batches[index]
            expected = [line["id"] for line in batch]
            cache_path = cache_dir / f"batch-{index:03d}.json"
            start = index * 40
            def batch_fingerprint(target_lines: list[dict[str, Any]], absolute_start: int) -> str:
                return text_stage_fingerprint("translation-batch", options.model,
                    {"lines": target_lines,
                     "glosses": [gloss_by_id[line["id"]] for line in target_lines],
                     "context": nearby_text_context(lines, absolute_start, len(target_lines)),
                     "provided_translation": provided_translation, "languages": languages}, policy)
            batch_identity = batch_fingerprint(batch, start)
            cached = read_packet(cache_path)
            if (cached and cached.get("target_ids") == expected
                    and cached.get("fingerprint") == batch_identity
                    and cached.get("input_contract_version") == TRANSLATION_INPUT_VERSION and not options.force):
                return cached

            def request(target_lines: list[dict[str, Any]], absolute_start: int, label: str) -> dict[str, Any]:
                target_ids = [line["id"] for line in target_lines]
                context = nearby_text_context(lines, absolute_start, len(target_lines))
                response = gemini.call(options.model, gemini.key(), prompt_for(target_lines, context), audio=None,
                                       timeout=stage_call_timeout(options),
                                       response_schema=bhakti_lexical_support.extend_schema(schema, support, "translation"),
                                       schema_name="bhakti_translation_batch", reasoning_effort="high",
                                       max_completion_tokens=65536, **stage_transport_context(options))
                capture_writer_response(options, response)
                returned = [row.get("id") for row in stage_model_rows(response, "translations", options)]
                compared = [row.get("id") for row in response["packet"].get("comparison", [])]
                if returned != target_ids or compared != target_ids:
                    stage_quality_failure(options, f"translation batch {label} returned IDs out of order or incomplete")
                return response

            if len(batch) > 20:
                children = []
                for child_index, offset in enumerate(range(0, len(batch), 20)):
                    child = batch[offset:offset + 20]
                    child_ids = [line["id"] for line in child]
                    child_path = cache_dir / f"batch-{index:03d}-{child_index:02d}.json"
                    child_packet = read_packet(child_path)
                    child_identity = batch_fingerprint(child, start + offset)
                    if not (child_packet and child_packet.get("target_ids") == child_ids
                            and child_packet.get("fingerprint") == child_identity
                            and child_packet.get("input_contract_version") == TRANSLATION_INPUT_VERSION
                            and not options.force):
                        child_packet = {
                            "target_ids": child_ids,
                            "input_contract_version": TRANSLATION_INPUT_VERSION,
                            "fingerprint": child_identity,
                            "response": request(child, start + offset, f"{index}.{child_index}"),
                        }
                        write_json(child_path, child_packet)
                    children.append(child_packet)
                response = {
                    "packet": {
                        "translations": [row for child in children
                                         for row in child["response"]["packet"]["translations"]],
                        "comparison": [row for child in children
                                       for row in child["response"]["packet"]["comparison"]],
                    },
                    "resolved_model": options.model,
                }
                packet = {"target_ids": expected, "input_contract_version": TRANSLATION_INPUT_VERSION,
                          "fingerprint": batch_identity, "response": response, "child_batches": children}
            else:
                packet = {"target_ids": expected, "input_contract_version": TRANSLATION_INPUT_VERSION,
                          "fingerprint": batch_identity, "response": request(batch, start, str(index))}
            write_json(cache_path, packet)
            return packet

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            packets = list(pool.map(run, range(len(batches))))
        result = {"packet": {
                      "translations": [row for packet in packets
                                       for row in packet["response"]["packet"]["translations"]],
                      "comparison": [row for packet in packets
                                     for row in packet["response"]["packet"]["comparison"]],
                  }, "batch_responses": packets, "input_contract_version": TRANSLATION_INPUT_VERSION,
                  "resolved_model": options.model}
    result['packet']['translations'] = stage_model_rows(result, 'translations', options)
    if selected is not None and not reuse_candidate:
        returned = result['packet']['translations']
        if [row.get('id') for row in returned] != [row['id'] for row in candidate_lines]:
            stage_quality_failure(options, 'semantic repair translation target population changed')
        replacements = {row['id']: row for row in returned}
        old = {row['id']: row for row in getattr(options, 'semantic_previous_translations', [])}
        if set(old) != {line['id'] for line in lines}:
            raise RuntimeError('semantic repair previous translation population changed')
        result['packet']['translations'] = [copy.deepcopy(replacements.get(line['id'], old[line['id']])) for line in lines]
    support_errors = bhakti_lexical_support.support_decision_errors(support, gloss_rows, result['packet']['translations'])
    support_errors.extend(bhakti_source_discovery.translation_decision_errors(
        getattr(options, 'automatic_source_discovery', None), result['packet']['translations']))
    if support_errors:
        raise RuntimeError('translation lexical support/source discovery: ' + str(support_errors[:3]))
    for row in result['packet']['translations']:
        row.pop('independent_review', None)
    result["input_contract_version"] = TRANSLATION_INPUT_VERSION
    result["fingerprint"] = fingerprint
    result["automatic_evidence_receipt"] = automatic_evidence_receipt(options)
    if getattr(options, "semantic_coordinator_acceptance", None):
        result["writer_coordinator_acceptance"] = options.semantic_coordinator_acceptance
    candidate_path = target.parent / 'translation-candidate.json'
    semantic_write_json(candidate_path, result)
    bhakti_semantic_repair.assert_baseline(getattr(options, 'semantic_baseline', None), result['packet']['translations'])
    if defer_review:
        return result  # A private writer candidate, never an affirmative 05 acceptance.
    result = review_translation(song_dir, audited, glosses, job, options, result,
                                prepared=True)
    errors = fresh_translation_contract_errors(lines, gloss_rows, result["packet"]["translations"], **translation_packet_contract_kwargs(lines, result, options, performance_order=audited["packet"].get("performance_order", [])))
    if candidate_only:
        return result
    source_issues = bhakti_source_discovery.repair_issues(
        getattr(options, 'automatic_source_discovery', None), lines, result['packet']['translations'])
    if source_issues:
        stage_quality_failure(options, 'new source evidence requires glossary repair: ' + str(source_issues[:1]))
    if errors:
        stage_quality_failure(options, f"translation output violates fresh contract: {errors[:3]}")
    write_json(target, result)
    return result


def review_translation(song_dir, audited, glosses, job, options, candidate, *, prepared=False):
    """Review exact private writer bytes without reconstructing their English."""
    if not prepared:
        options, glosses = bhakti_lexical_producer.prepare_translation(song_dir, audited, glosses, options)
    result = copy.deepcopy(candidate)
    for field in ('semantic_repair_version', 'semantic_run_id', 'coordinator_acceptance'):
        result.pop(field, None)
    lines = audited['packet']['verified_lines']
    gloss_rows = glosses['packet']['glosses']
    gloss_by_id = {row['id']: row for row in gloss_rows}
    languages = job.get('languages', audited['packet'].get('metadata', {}).get('languages'))
    provided_translation = supplied_translation(job)
    candidate_path = song_dir / '.transcription/pipeline/translation-candidate.json'
    review_options = copy.copy(options)
    if candidate.get('writer_route_state'):
        history = bhakti_semantic_repair.validated_writer_history(candidate['writer_route_state'])
    elif candidate.get('writer_evidence'):
        receipt = candidate['writer_evidence']
        history = [{'rows': bhakti_semantic_repair.writer_proof_rows(receipt['current']), 'proof': receipt['current']}]
    else:
        original = copy.deepcopy(candidate)
        original.pop('writer_review_context', None)
        original['packet']['translations'] = bhakti_semantic_repair.writer_rows(original['packet']['translations'])
        proof_path = song_dir / '.transcription/pipeline/writer-drafts' / (bhakti_semantic_repair.digest(original) + '.json')
        if proof_path.exists():
            if bhakti_semantic_repair.digest(read_packet(proof_path)) != bhakti_semantic_repair.digest(original):
                raise RuntimeError('immutable writer draft changed')
        else:
            semantic_write_json(proof_path, original)
        history = [{'rows': bhakti_semantic_repair.writer_rows(original['packet']['translations']),
                    'proof': {'path': str(proof_path), 'candidate_sha256': bhakti_semantic_repair.digest(original)}}]
    context = bhakti_semantic_repair.writer_review_context(lines, gloss_rows, result['packet']['translations'],
        context_identity=bhakti_semantic_repair.review_context_identity(lines, options,
            performance_order=audited['packet'].get('performance_order', [])),
        prior_candidates=history, previous_context=getattr(options, 'semantic_previous_writer_context', None))
    result['writer_evidence'] = bhakti_semantic_repair.writer_evidence_receipt(history,
        bhakti_semantic_repair.review_context_identity(lines, options, performance_order=audited['packet'].get('performance_order', [])),
        getattr(options, 'semantic_previous_writer_context', None))
    if context is not None:
        result['writer_review_context'] = context
        review_options.semantic_writer_review_context = context
    else:
        result.pop('writer_review_context', None)
    review_options.semantic_performance_order = copy.deepcopy(
        getattr(options, "semantic_performance_order", audited["packet"].get("performance_order", [])))
    if hasattr(options, 'semantic_deadline_at'):
        # All final review batches bind the complete assembled evidence. Their
        # payload stays bounded: full source, targets, explicit distant refs.
        review_options.semantic_review_snapshot = bhakti_semantic_repair.digest({
            'lines': lines, 'glosses': gloss_rows, 'translations': result['packet']['translations']})
        references = {ref['line_id'] for issue in getattr(options, 'semantic_repair_feedback', [])
                      for ref in issue.get('references', [])}
        review_options.semantic_distant_context = [
            {'source': line, 'gloss': gloss_by_id[line['id']],
             'draft': next(row for row in result['packet']['translations'] if row['id'] == line['id'])}
            for line in lines if line['id'] in references]
    independent_reviews, review_packets = independently_review_translations(
        song_dir, lines, gloss_rows, result["packet"]["translations"], provided_translation, review_options,
        languages=languages
    )
    review_by_id = {row["id"]: row for row in independent_reviews}
    for row in result["packet"]["translations"]:
        row["independent_review"] = review_by_id.get(row["id"], {})
    result["review_responses"] = review_packets
    result.update(review_task_identity())
    semantic_write_json(candidate_path, result)
    return result

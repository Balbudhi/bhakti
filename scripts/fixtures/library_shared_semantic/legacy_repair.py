# Frozen existing production repair function for real legacy-route fixtures only.
# Original SHA256 b522bce878563afe7b59b760a2c1db75ba7154ceb0379c069abb58679e471dd2
def repair_current_reader(reader: dict, *, slug: str, pre_review: dict, workspace: Path,
                          route_dir: Path, options, dependency_fingerprint: str,
                          deadline_at: float, protected_english: dict | None = None) -> dict:
    """Repair only independently identified targets, then apply the paired gate."""
    import bhakti_model_routes as routes
    import bhakti_candidate_guard as guard
    lines, original_glosses, original_translations = reader_evidence(reader)
    options = lexical_options(options, slug, lines, reader.get("SONG_META", {}).get("languages", []))
    errors = current_review_errors(pre_review, lines, original_glosses,
                                   prepare.json_digest(reader), dependency_fingerprint)
    if errors: raise ValueError('unbound or invalid pre-review: ' + str(errors))
    snapshot = pre_review.get('finding_snapshot')
    if snapshot is not None:
        context = dict(lines=lines, glosses=original_glosses,
            reader_digest=prepare.json_digest(reader), dependency_fingerprint=dependency_fingerprint)
        snapshot = finding_store.validate_snapshot(snapshot, **context)
        if pre_review.get('finding_journal_path'):
            paths = audit_route_paths(route_dir, slug, reader, pipeline.semantic_stage_policy(options),
                protected_english, dependency_fingerprint, options.model, options.pro_model,
                task_version=pre_review.get('review_task_version', 0))
            current = _reconcile_review_history(Path(pre_review['finding_route_state_path']),
                Path(pre_review['finding_journal_path']), context, prior_state_paths=paths[:-1])
            if current != snapshot:
                raise ValueError('retained findings changed before repair')
        guard.authorize_semantic_candidate(reader, reader, source_lines=lines,
            gloss_rows=original_glosses, pre_review=pre_review, post_review=None,
            dependency_fingerprint=dependency_fingerprint, protected_english=protected_english,
            finding_snapshot=snapshot, allow_partial=True)
        repair_findings = [f for f in snapshot['findings'] if f['kind'] == 'defect'
                           and f['issue']['kind'] != 'unresolved_evidence']
        issues = [f['issue'] for f in repair_findings]
    else:
        repair_findings = []
        issues = pre_review['issues']
    if any(issue['kind'] == 'unresolved_evidence' for issue in issues):
        raise ValueError('unresolved source evidence cannot authorize semantic repair')
    targets = {target for issue in issues for target in issue['target_line_ids']}
    if not targets:
        receipt = guard.authorize_semantic_candidate(reader, reader, source_lines=lines,
            gloss_rows=original_glosses, pre_review=pre_review, post_review=None,
            dependency_fingerprint=dependency_fingerprint, protected_english=protected_english,
            finding_snapshot=snapshot, allow_partial=snapshot is not None)
        return {'reader': copy.deepcopy(reader), 'authorization': receipt, 'post_review': None}
    target_lines = [line for line in lines if line['id'] in targets]
    lexical_indices: dict[str, set[int]] = {}
    for issue in issues:
        if issue['kind'] not in ('gloss_sense', 'frame_relation'): continue
        for ref in issue['references']:
            if ref['line_id'] in issue['target_line_ids']:
                lexical_indices.setdefault(ref['line_id'], set()).update(ref['word_indices'])
    request_identity = prepare.json_digest({'version': VERSION, 'reader': reader, 'pre_review': pre_review,
        'policy': pipeline.semantic_stage_policy(options), 'baseline': protected_english, **pipeline.review_task_identity()})
    languages = reader.get('SONG_META', {}).get('languages', [])

    def execute(context):
        local = route_options(options, context)
        local.semantic_full_source = lines
        local.semantic_context_evidence = [
            {'source': copy.deepcopy(source), 'gloss': copy.deepcopy(gloss), 'draft': copy.deepcopy(draft)}
            for source, gloss, draft in zip(lines, original_glosses, original_translations)]
        local.semantic_performance_order = copy.deepcopy(reader['SONG_SEQUENCE'])
        local.semantic_source_identity = dependency_fingerprint
        local.semantic_repair_findings = repair_findings
        local.semantic_confirmed_issues = issues
        local.semantic_repair_feedback = issues
        local.semantic_original_reader = {key: copy.deepcopy(reader['SONG_LINES'][key]) for key in targets}
        local.semantic_baseline = ({key: protected_english[key] for key in targets}
                                   if protected_english is not None else None)
        audited = {'packet': {'verified_lines': target_lines, 'metadata': {'languages': languages},
                              'performance_order': copy.deepcopy(reader['SONG_SEQUENCE'])}}
        attempt_song = context.attempt_dir / slug
        glosses = pipeline.gloss(attempt_song, audited, local)
        # Reconstruction supplies missing modern frames only for confirmed
        # failed targets. It cannot authorize changing other displayed glosses.
        for row in glosses['packet']['glosses']:
            original_line = reader['SONG_LINES'][row['id']]
            old_words = original_line['words']
            for index, word in enumerate(row['word_glosses']):
                actual_word = copy.deepcopy(old_words[index])
                if index in lexical_indices.get(row['id'], set()): actual_word['gloss'] = word['gloss']
                row['word_glosses'][index] = actual_word
            row['grammar_note'] = original_line.get('grammarNote', '')
        job = {'slug': slug, 'languages': languages}
        if protected_english is not None:
            baseline_path = context.attempt_dir / 'locked-target-english.json'
            pipeline.semantic_write_json(baseline_path, local.semantic_baseline)
            job['providedTranslation'] = str(baseline_path)
        translations = pipeline.translate(attempt_song, audited, glosses, job, local, candidate_only=True)
        candidate = copy.deepcopy(reader)
        for row in glosses['packet']['glosses']:
            for index in lexical_indices.get(row['id'], set()):
                candidate['SONG_LINES'][row['id']]['words'][index]['gloss'] = row['word_glosses'][index]['gloss']
        for row in translations['packet']['translations']:
            candidate['SONG_LINES'][row['id']]['english'] = pipeline.segment_english(row['segments'], row['literal_english'])
        post = {'reader_digest': prepare.json_digest(candidate), 'dependency_fingerprint': dependency_fingerprint,
                'attempt_id': context.attempt_id, **pipeline.review_task_identity(),
                'reviews': [row['independent_review'] for row in translations['packet']['translations']]}
        return {'reader': candidate, 'post_review': post, 'glosses': glosses,
                'translations': translations, 'source_lines': target_lines}

    def validate(artifact):
        errors = pipeline.fresh_translation_contract_errors(target_lines,
            artifact['glosses']['packet']['glosses'], artifact['translations']['packet']['translations'])
        try:
            guard.authorize_semantic_candidate(reader, artifact['reader'],
                source_lines=lines, gloss_rows=original_glosses, pre_review=pre_review,
                post_review=artifact['post_review'], dependency_fingerprint=dependency_fingerprint,
                protected_english=protected_english,
                finding_snapshot=snapshot, allow_partial=snapshot is not None)
        except ValueError as exc:
            # The pure gate reports exact rejected mutations; no blanket flag
            # clearing or selection of a less-bad candidate is permitted.
            kind = 'locked_baseline_conflict' if protected_english is not None else 'semantic_candidate_rejected'
            return [{'kind': kind, 'detail': str(exc)}]
        return [{'kind': 'semantic_contract', 'detail': error} for error in errors]

    accepted = routes.run_unit(route_dir, slug + ':targeted-semantics', request_identity, execute, validate,
        deadline_at=deadline_at, dependency_fingerprint=dependency_fingerprint,
        base_model=options.model, pro_model=options.pro_model)
    receipt = guard.authorize_semantic_candidate(reader, accepted['reader'], source_lines=lines,
        gloss_rows=original_glosses, pre_review=pre_review, post_review=accepted['post_review'],
        dependency_fingerprint=dependency_fingerprint, protected_english=protected_english,
        finding_snapshot=snapshot, allow_partial=snapshot is not None)
    return {**accepted, 'authorization': receipt}

"""Frozen pre-stage-split caller: migration fixture, never production code."""
import copy
from pathlib import Path
from bhakti_library_source_pass import digest, file_hash, fresh_target_errors

def process_new_targets(song_dir, plan, metadata, options, route_dir, deadline_at):
    """Fresh text is a routed, independently reviewed subset, never old English."""
    import bhakti_pipeline as pipeline
    import bhakti_library_pass as library
    import bhakti_model_routes as routes
    targets = [line for line in plan['lines'] if line['id'] in plan['new_target_ids']]
    languages = metadata.get('languages', [])
    options = copy.copy(options)
    options.semantic_full_source = plan['lines']
    options = library.lexical_options(options, song_dir.name, plan['lines'], languages)
    reused = plan.get('reuse_by_id', {})
    planned = {line['id']: line for line in plan['lines']}
    if set(reused) != set(planned) - set(plan['new_target_ids']):
        raise ValueError('translation context lacks preserved source rows')
    for line_id, old in reused.items():
        if (old.get('source') != planned[line_id]['source_text']
                or old.get('roman') != planned[line_id]['roman']
                or not isinstance(old.get('english'), str)):
            raise ValueError('translation context differs from preserved source/English')
    context_evidence = []
    if reused:
        old_reader = {'SONG_META': metadata, 'SONG_LINES': copy.deepcopy(reused),
            'SONG_SEQUENCE': [{'ref': event['line_id'], 'section': planned[event['line_id']].get('kind', 'verse'),
                               'repeats': 1}
                              for event in plan['performance_order'] if event['line_id'] in reused]}
        old_sources, old_glosses, old_drafts = library.reader_evidence(old_reader)
        context_evidence = [{'source': copy.deepcopy(planned[source['id']]),
                             'gloss': gloss, 'draft': draft}
                            for source, gloss, draft in zip(old_sources, old_glosses, old_drafts)]
    # New English does not exist yet. These empty drafts check only known order,
    # row availability and scope bounds; they are discarded, never model evidence.
    pending_glosses = [{'id': line['id']} for line in targets]
    pending_drafts = [{'id': line['id'], 'literal_english': ''} for line in targets]
    for offset in range(0, len(targets), 10):
        pipeline.translation_reading_context(targets, pending_glosses, pending_drafts,
            [line['id'] for line in targets[offset:offset + 10]],
            performance_order=plan['performance_order'], full_evidence=context_evidence)
    options.semantic_context_evidence = copy.deepcopy(context_evidence)
    options.semantic_performance_order = plan['performance_order']
    options.semantic_source_identity = digest({'lines': plan['lines'], 'order': plan['performance_order']})
    audited = {'packet': {'metadata': metadata, 'verified_lines': targets,
                         'performance_order': [event for event in plan['performance_order'] if event['line_id'] in plan['new_target_ids']],
                         'uncertainties': []}}
    evidence = {'targets': targets, 'source': plan['lines'], 'order': plan['performance_order'],
                'languages': languages, 'reading_context': context_evidence, 'policy': pipeline.semantic_stage_policy(options)}
    identity = digest(evidence)
    validation_song = Path(route_dir) / 'fresh-source-support' / identity / 'songs' / song_dir.name
    def candidate_errors(value):
        errors = fresh_target_errors(plan, metadata, value)
        if not errors:
            errors.extend(pipeline.bhakti_semantic_repair.derived_support_errors(
                pipeline, validation_song, audited, value['glosses'], value['translations'], options))
        return errors
    unit_id = song_dir.name + ':new-source-semantics'
    decisions = getattr(options, 'editorial_adjudications', None) or {}
    if not isinstance(decisions, dict):
        raise ValueError('editorial_adjudications must map exact unit IDs to decision paths')
    if unit_id in decisions:
        from bhakti_editorial_adjudication import recover_editorial_candidate
        decision_path = Path(decisions[unit_id])
        recovered = recover_editorial_candidate(decision_path,
            unit_id=unit_id, input_fingerprint=identity,
            dependency_fingerprint=digest(evidence['policy']),
            source_evidence=evidence, policy_payload=evidence['policy'],
            validate_candidate=candidate_errors,
            output_dir=Path(route_dir) / 'editorial-adjudications' / digest(unit_id)[:16] / file_hash(decision_path)[:16])
        return {**recovered['candidate'], 'editorial_receipt': recovered['receipt']}
    def execute(context):
        local = library.route_options(options, context)
        attempt_song = context.attempt_dir / 'songs' / song_dir.name
        (attempt_song / '.transcription/pipeline').mkdir(parents=True, exist_ok=True)
        if pipeline.bhakti_lexical_producer.settings(local) is not None:
            from bhakti_embedding_client import file_lock
            # English corpus changes do not repay the unchanged source glossary.
            # Keep the original producing model and complete reading context bound.
            gloss_identity = digest({**evidence, 'model': context.model,
                'policy': pipeline.semantic_stage_policy(local, stage='gloss')})
            gloss_root = Path(route_dir) / 'fresh-source-glosses' / gloss_identity
            with file_lock(gloss_root / 'gloss.lock'):
                glosses = pipeline.gloss(gloss_root / 'songs' / song_dir.name, audited, local)
        else:
            glosses = pipeline.gloss(attempt_song, audited, local)
        errors = pipeline.fresh_gloss_contract_errors(targets, glosses['packet']['glosses'], languages)
        if errors: raise routes.QualityFailure([{'kind': 'source_gloss_contract', 'detail': error} for error in errors])
        translations = pipeline.translate(attempt_song, audited, glosses,
            {'slug': song_dir.name, 'languages': languages}, local, candidate_only=True)
        return {'glosses': glosses, 'translations': translations}
    def validate(value):
        return [{'kind': 'source_semantic_contract', 'detail': error} for error in candidate_errors(value)]
    result = routes.run_unit(route_dir, song_dir.name + ':new-source-semantics', identity,
        execute, validate, deadline_at=deadline_at, dependency_fingerprint=digest(evidence['policy']),
        base_model=options.model, pro_model=options.pro_model)


    errors = candidate_errors(result)
    if errors:
        raise ValueError('fresh source cached semantic evidence invalid: ' + '; '.join(errors))
    return result

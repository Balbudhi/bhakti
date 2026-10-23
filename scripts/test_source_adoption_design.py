"""First dependency's executable contract, not an audio-quality evaluation.

The implementation is intentionally absent. Real existing planner/observation
packet shapes construct inputs. Expected words/order/lineage are handwritten.
Only exact native/Roman matches authorize reuse; IDs in model packets are opaque.
Run: PYTHONPATH=<repo>/scripts python3 -m unittest discover -s <this directory>.
"""
import copy
import unittest
import bhakti_library_source_pass as source

WORDS = {'A': ('मन', 'man'), 'B': ('शीतल', 'śītal'),
         'C': ('नाम', 'nām'), 'D': ('राम', 'rāma'), 'X': ('मान', 'mān')}


def reader(order):
    lines = {}
    for label in order:
        native, roman = WORDS[label]
        lines[label] = {'source': native, 'roman': roman, 'sourceLanguage': 'hi',
                       'sourceWords': [{'text': native, 'wordIndices': [0]}],
                       'words': [{'roman': roman, 'gloss': 'retained ' + label}],
                       'english': '{0:Reviewed English ' + label + '}',
                       'grammarNote': 'Retained note ' + label}
    return {'SONG_META': {'title': 'Source design fixture', 'languages': ['Hindi']},
            'SONG_LINES': lines,
            'SONG_SEQUENCE': [{'ref': label, 'section': 'verse', 'repeats': 1} for label in order],
            'SONG_TIMINGS': [{'start': float(i * 10), 'end': float((i + 1) * 10)} for i in range(len(order))]}


def packet(labels):
    # Raw row IDs intentionally differ from current IDs; a repeated performed
    # line shares its definition but remains a separate performance occurrence.
    unique = list(dict.fromkeys(labels)); counts = {}; order = []
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
        order.append({'line_id': 'raw-' + label, 'occurrence': counts[label]})
    return {'lines': [{'id': 'raw-' + label, 'source_text': WORDS[label][0],
                       'roman': WORDS[label][1], 'language': 'Hindi', 'kind': 'verse',
                       'partial': 'none', 'notes': ''} for label in unique],
            'performance_order': order, 'uncertainties': []}


def fixture(old, heard, focused=None):
    value = reader(old); duration = len(old) * 10.0
    identity = {'audio_sha256': 'a' * 64, 'trim_sha256': None,
                'reader_source_sha256': source.reader_source_identity(value)}
    flags = {'audio': True}
    if focused is not None:
        flags['occurrence_ids'] = [f'occ-{index:03d}' for index in focused]
    evidence = {'identity': identity, 'disagreements': [], 'focused_receipts': [],
                'duration_seconds': duration, 'routing_intervals': value['SONG_TIMINGS'],
                'coverage_requested': focused is None, 'timing_required': False}
    plan = source.plan_audio_review(value, source_evidence=evidence, flags=flags, duration_seconds=duration)
    units = source.materialize_source_units(plan, evidence, duration_seconds=duration)
    if len(units) != 1:
        raise AssertionError('fixture needs one contextual unit')
    unit = units[0]
    segment = {'index': 0, **{key: unit[key] for key in ('clip_start', 'clip_end', 'core_start', 'core_end')}}
    raw = {'segment_audits': [{'segment': segment, 'audit': {'packet': packet(heard)}}]}
    observed = {'status': 'observed', 'source_identity': copy.deepcopy(identity), 'issues': [],
                'unit_results': [{'unit': unit, 'result': raw, 'result_digest': source.digest(raw),
                                  'input_fingerprint': 'b' * 64}]}
    return value, plan, observed


def proposed_words(result):
    rebuilt = result['rebuilt']; rows = {row['id']: row for row in rebuilt['verified_lines']}
    return [(rows[event['line_id']]['source_text'], rows[event['line_id']]['roman'])
            for event in rebuilt['performance_order']]


class SourceDeltaContractTests(unittest.TestCase):
    def reconcile(self, old, heard, focused=None):
        before, plan, observed = fixture(old, heard, focused)
        snapshot = copy.deepcopy((before, plan, observed))
        operation = getattr(source, 'reconcile_source_observations', None)
        self.assertTrue(callable(operation), 'automatic source observation adoption operation is missing')
        result = operation(before, plan, observed)
        self.assertEqual((before, plan, observed), snapshot, 'pure reconciliation mutated its input evidence')
        return before, result

    def assert_proposed(self, result, expected, confirmation):
        self.assertEqual(result['status'], 'proposed', result)
        self.assertEqual(proposed_words(result), [WORDS[label] for label in expected])
        self.assertEqual(result['requires_confirmation'], confirmation)

    def test_same_source_reuses_all_rows_without_manual_map_or_confirmation(self):
        before, result = self.reconcile(['A', 'B'], ['A', 'B'])
        self.assert_proposed(result, ['A', 'B'], False)
        self.assertEqual(result['reused_line_ids'], ['A', 'B'])
        self.assertEqual(result['fresh_line_ids'], [])
        self.assertEqual(result['removed_line_ids'], [])
        self.assertEqual(result['occurrence_lineage'], [{'old_index': 0, 'new_index': 0}, {'old_index': 1, 'new_index': 1}])
        self.assertEqual(result['coverage_scope'], 'whole_recording')

    def test_insertion_retains_existing_occurrence_identity_not_new_position(self):
        _, result = self.reconcile(['A', 'B'], ['A', 'C', 'B'])
        self.assert_proposed(result, ['A', 'C', 'B'], True)
        self.assertEqual(result['reused_line_ids'], ['A', 'B'])
        self.assertEqual(len(result['fresh_line_ids']), 1)
        self.assertEqual(result['occurrence_lineage'], [{'old_index': 0, 'new_index': 0}, {'old_index': None, 'new_index': 1}, {'old_index': 1, 'new_index': 2}])

    def test_deletion_is_an_explicit_proposal_not_forced_retention(self):
        _, result = self.reconcile(['A', 'B', 'C'], ['A', 'C'])
        self.assert_proposed(result, ['A', 'C'], True)
        self.assertEqual(result['removed_line_ids'], ['B'])
        self.assertEqual(result['reused_line_ids'], ['A', 'C'])
        self.assertEqual(result['occurrence_lineage'], [{'old_index': 0, 'new_index': 0}, {'old_index': 1, 'new_index': None}, {'old_index': 2, 'new_index': 1}])

    def test_actual_native_vowel_correction_is_not_overwritten_by_old_source(self):
        _, result = self.reconcile(['A', 'B'], ['X', 'B'])
        self.assert_proposed(result, ['X', 'B'], True)
        self.assertEqual(result['reused_line_ids'], ['B'])
        self.assertEqual(result['removed_line_ids'], ['A'])
        self.assertEqual(len(result['fresh_line_ids']), 1)
        self.assertNotIn(('मन', 'man'), proposed_words(result))

    def test_returning_and_adjacent_repeats_are_not_globally_deduplicated(self):
        _, result = self.reconcile(['A', 'B'], ['A', 'B', 'A', 'A'])
        self.assert_proposed(result, ['A', 'B', 'A', 'A'], True)
        self.assertEqual(result['fresh_line_ids'], [])
        self.assertEqual(result['occurrence_lineage'], [{'old_index': 0, 'new_index': 0}, {'old_index': 1, 'new_index': 1}, {'old_index': None, 'new_index': 2}, {'old_index': None, 'new_index': 3}])

    def test_focused_core_replacement_preserves_outside_order_and_coverage_limit(self):
        _, result = self.reconcile(['A', 'B', 'C', 'D'], ['A', 'B', 'X', 'C', 'D'], [1, 2])
        self.assert_proposed(result, ['A', 'B', 'X', 'C', 'D'], True)
        self.assertEqual(result['coverage_scope'], 'focused')
        self.assertEqual(result['reused_line_ids'], ['A', 'B', 'C', 'D'])

    def test_changed_context_outside_focused_core_is_not_silently_adopted(self):
        _, result = self.reconcile(['A', 'B', 'C'], ['X', 'B', 'C'], [1])
        self.assertEqual(result['status'], 'unresolved')
        self.assertTrue(result['issues'])

    def test_extra_source_beyond_focused_context_anchors_is_not_adopted(self):
        for heard in (['X', 'A', 'B', 'C'], ['A', 'B', 'C', 'X']):
            with self.subTest(heard=heard):
                _, result = self.reconcile(['A', 'B', 'C'], heard, [1])
                self.assertEqual(result['status'], 'unresolved')
                self.assertTrue(result['issues'])

    def test_ambiguous_repeat_context_does_not_choose_an_arbitrary_alignment(self):
        # Two old adjacent identical performances, only one heard. Which old
        # occurrence survives cannot authorize retaining a timestamp by index.
        # The source itself remains usable: mark the correspondence unresolved
        # and obtain fresh scoped timing instead of blocking this whole source.
        _, result = self.reconcile(['A', 'A', 'B'], ['A', 'B'])
        self.assert_proposed(result, ['A', 'B'], True)
        matches = [row for row in result['occurrence_lineage'] if row['new_index'] == 0]
        self.assertEqual(matches, [{'old_index': None, 'new_index': 0}])
        self.assertEqual(result['timing_unresolved_old_indices'], [0, 1])

    def test_explicit_source_uncertainty_blocks_proposal(self):
        before, plan, observed = fixture(['A', 'B'], ['A', 'B'])
        raw = observed['unit_results'][0]['result']
        raw['segment_audits'][0]['audit']['packet']['uncertainties'] = ['second vowel unclear']
        observed['unit_results'][0]['result_digest'] = source.digest(raw)
        operation = getattr(source, 'reconcile_source_observations', None)
        self.assertTrue(callable(operation), 'automatic source observation adoption operation is missing')
        result = operation(before, plan, observed)
        self.assertEqual(result['status'], 'unresolved')
        self.assertTrue(result['issues'])

    def test_changed_recording_identity_is_rejected_before_adoption(self):
        before, plan, observed = fixture(['A', 'B'], ['A', 'B'])
        observed['source_identity']['audio_sha256'] = 'c' * 64
        operation = getattr(source, 'reconcile_source_observations', None)
        self.assertTrue(callable(operation), 'automatic source observation adoption operation is missing')
        with self.assertRaises(ValueError):
            operation(before, plan, observed)

    def test_changed_raw_observation_after_receipt_is_rejected(self):
        before, plan, observed = fixture(['A', 'B'], ['A', 'B'])
        observed['unit_results'][0]['result']['segment_audits'][0]['audit']['packet']['lines'][0]['source_text'] = 'मान'
        operation = getattr(source, 'reconcile_source_observations', None)
        self.assertTrue(callable(operation), 'automatic source observation adoption operation is missing')
        with self.assertRaises(ValueError):
            operation(before, plan, observed)

    def test_owner_english_cannot_enter_or_be_rewritten_by_source_reconciliation(self):
        before, result = self.reconcile(['A', 'B'], ['A', 'C', 'B'])
        self.assert_proposed(result, ['A', 'C', 'B'], True)
        # Reconciliation produces source evidence, not a proposed English edit.
        self.assertNotIn('english', str(result['rebuilt']))
        self.assertEqual(before['SONG_LINES']['A']['english'], '{0:Reviewed English A}')
        self.assertEqual(before['SONG_LINES']['B']['english'], '{0:Reviewed English B}')

    def test_duplicate_source_definitions_retain_distinct_editorial_identity(self):
        before, plan, observed = fixture(['A', 'B', 'A'], ['A', 'B', 'A'])
        before['SONG_LINES']['A-second'] = copy.deepcopy(before['SONG_LINES']['A'])
        before['SONG_LINES']['A-second']['english'] = '{0:Other protected wording}'
        before['SONG_SEQUENCE'][2]['ref'] = 'A-second'
        plan['identity']['reader_source_sha256'] = source.reader_source_identity(before)
        observed['source_identity'] = copy.deepcopy(plan['identity'])
        # Rebuild the real draft with the distinct final definition ID.
        unit = observed['unit_results'][0]['unit']
        unit['expanded_draft'] = source.source_draft(before)
        plan['expanded_draft'] = source.source_draft(before)
        plan['units'][0]['expanded_draft'] = source.source_draft(before)
        operation = getattr(source, 'reconcile_source_observations', None)
        self.assertTrue(callable(operation), 'automatic source observation adoption operation is missing')
        result = operation(before, plan, observed)
        self.assert_proposed(result, ['A', 'B', 'A'], False)
        self.assertEqual(result['reused_line_ids'], ['A', 'B', 'A-second'])
        self.assertEqual([row['line_id'] for row in result['rebuilt']['performance_order']], ['A', 'B', 'A-second'])
        self.assertEqual(before['SONG_LINES']['A-second']['english'], '{0:Other protected wording}')

    def split_observations(self, gap=False, conflict=False):
        before, plan, observed = fixture(['A', 'B', 'C', 'D'], ['A', 'B', 'C', 'D'])
        rows = []
        for index, (core, bounds, indices, labels) in enumerate([
                ((0., 20.), (0., 30.), [0, 1], ['A', 'B', 'C']),
                ((21. if gap else 20., 40.), (10., 40.), [2, 3], ['B', 'X' if conflict else 'C', 'D'])]):
            unit = copy.deepcopy(observed['unit_results'][0]['unit'])
            context = [0, 1, 2] if index == 0 else [1, 2, 3]
            unit.update(id='segment-' + str(index), segment_index=index,
                        core_start=core[0], core_end=core[1], clip_start=bounds[0], clip_end=bounds[1],
                        core_occurrence_indices=indices, context_occurrence_indices=context,
                        target_occurrence_ids=[f'occ-{i:03d}' for i in indices],
                        expanded_draft=source.source_draft(before, context))
            raw = {'segment_audits': [{'segment': {'index': index, **{key: unit[key] for key in ('clip_start', 'clip_end', 'core_start', 'core_end')}},
                                       'audit': {'packet': packet(labels)}}]}
            rows.append({'unit': unit, 'result': raw, 'result_digest': source.digest(raw), 'input_fingerprint': str(index) * 64})
        observed['unit_results'] = rows
        return before, plan, observed

    def test_segment_core_gap_never_establishes_whole_coverage(self):
        before, plan, observed = self.split_observations(gap=True)
        operation = getattr(source, 'reconcile_source_observations', None)
        self.assertTrue(callable(operation), 'automatic source observation adoption operation is missing')
        result = operation(before, plan, observed)
        self.assertEqual(result['status'], 'unresolved')
        self.assertTrue(result['issues'])

    def test_conflicting_segment_overlap_is_not_merged_by_fuzzy_roman_match(self):
        before, plan, observed = self.split_observations(conflict=True)
        operation = getattr(source, 'reconcile_source_observations', None)
        self.assertTrue(callable(operation), 'automatic source observation adoption operation is missing')
        result = operation(before, plan, observed)
        self.assertEqual(result['status'], 'unresolved')
        self.assertTrue(result['issues'])

    def test_compatible_segment_overlap_preserves_one_performance_of_shared_rows(self):
        before, plan, observed = self.split_observations()
        operation = getattr(source, 'reconcile_source_observations', None)
        self.assertTrue(callable(operation), 'automatic source observation adoption operation is missing')
        result = operation(before, plan, observed)
        self.assert_proposed(result, ['A', 'B', 'C', 'D'], False)
        self.assertEqual(result['coverage_scope'], 'whole_recording')

    def test_mixed_language_fresh_line_retains_explicit_lexical_routing(self):
        import bhakti_lexical_retrieval as lexical
        before, plan, observed = fixture(['A', 'B'], ['A', 'C', 'B'])
        before['SONG_META']['languages'] = ['Hindi', 'Tamil']
        raw = observed['unit_results'][0]['result']
        item = next(row for row in raw['segment_audits'][0]['audit']['packet']['lines'] if row['id'] == 'raw-C')
        item.update(source_text='அன்பு', roman='aṉpu', language='Tamil')
        observed['unit_results'][0]['result_digest'] = source.digest(raw)
        result = source.reconcile_source_observations(before, plan, observed)
        self.assertEqual(result['status'], 'proposed', result)
        added = next(row for row in result['rebuilt']['verified_lines'] if row['id'] in result['fresh_line_ids'])
        self.assertEqual(added['language'], 'Tamil')
        self.assertEqual(added['sourceLanguage'], 'ta')
        self.assertEqual(lexical.line_language(added, before['SONG_META']['languages']), 'ta')

    def test_unknown_fresh_language_is_not_silently_dropped_or_guessed(self):
        before, plan, observed = fixture(['A', 'B'], ['A', 'C', 'B'])
        raw = observed['unit_results'][0]['result']
        item = next(row for row in raw['segment_audits'][0]['audit']['packet']['lines'] if row['id'] == 'raw-C')
        item['language'] = 'unidentified mixed language'
        observed['unit_results'][0]['result_digest'] = source.digest(raw)
        result = source.reconcile_source_observations(before, plan, observed)
        self.assertEqual(result['status'], 'unresolved')
        self.assertTrue(result['issues'])

    def test_fresh_homographs_in_distinct_languages_are_not_collapsed(self):
        import bhakti_lexical_retrieval as lexical
        before, plan, observed = fixture(['A', 'B'], ['A', 'C', 'B'])
        before['SONG_META']['languages'] = ['Hindi', 'Sanskrit']
        raw = observed['unit_results'][0]['result']; data = raw['segment_audits'][0]['audit']['packet']
        second = copy.deepcopy(next(row for row in data['lines'] if row['id'] == 'raw-C'))
        second.update(id='raw-C-sanskrit', language='Sanskrit')
        data['lines'].append(second); data['performance_order'].insert(2, {'line_id':second['id'],'occurrence':1})
        observed['unit_results'][0]['result_digest'] = source.digest(raw)
        result = source.reconcile_source_observations(before, plan, observed)
        self.assertEqual(result['status'], 'proposed', result)
        added = [row for row in result['rebuilt']['verified_lines'] if row['id'] in result['fresh_line_ids']]
        self.assertEqual(len(added), 2)
        self.assertEqual({lexical.line_language(row, ['Hindi','Sanskrit']) for row in added}, {'hi','sa'})

    def test_conflicting_existing_language_holds_instead_of_changing_lexical_identity(self):
        before, plan, observed = fixture(['A', 'B'], ['A', 'B'])
        raw = observed['unit_results'][0]['result']; data = raw['segment_audits'][0]['audit']['packet']
        data['lines'][0]['language'] = 'Sanskrit'
        observed['unit_results'][0]['result_digest'] = source.digest(raw)
        result = source.reconcile_source_observations(before, plan, observed)
        self.assertEqual(result['status'], 'unresolved')
        self.assertTrue(result['issues'])

    def test_equivalent_language_alias_retains_explicit_language_on_reused_source(self):
        before, plan, observed = fixture(['A', 'B'], ['A', 'B'])
        raw = observed['unit_results'][0]['result']; data = raw['segment_audits'][0]['audit']['packet']
        data['lines'][0]['language'] = 'hi'
        observed['unit_results'][0]['result_digest'] = source.digest(raw)
        result = source.reconcile_source_observations(before, plan, observed)
        self.assert_proposed(result, ['A','B'], False)
        self.assertEqual([row['sourceLanguage'] for row in result['rebuilt']['verified_lines']], ['hi','hi'])


if __name__ == '__main__':
    unittest.main()

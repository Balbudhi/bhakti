"""Executable design tests; production HEAD is deliberately not implemented yet.

Only provider/time replaced. Real schema validators, private files, hashes, and
stage review/cache paths must run. Fictional provider output tests orchestration,
not linguistic correctness. Run with this directory before repository scripts.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import bhakti_pipeline as pipeline
from test_sense_decisions import decisions_for

REAL_ROOT = Path('/Users/eeshan/Dev/bhakti')


def digest(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


class AutomaticRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.song = self.root / 'songs' / 'fixture'; self.song.mkdir(parents=True)
        self.packets = self.song / '.transcription' / 'pipeline'; self.packets.mkdir(parents=True)
        (self.root / 'data').mkdir()
        (self.root / 'data' / 'preserved_terms.json').write_bytes((REAL_ROOT / 'data' / 'preserved_terms.json').read_bytes())
        (self.root / 'data' / 'editorial_baselines.json').write_text('{"version":1,"songs":{}}')
        self.lines = [{'id': 'a', 'source_text': 'मेरी साँस मुझे छोड़ती है',
                       'roman': 'merī sāṃsa mujhe choṛatī hai', 'kind': 'verse'}]
        self.audit = {'packet': {'verified_lines': self.lines, 'metadata': {'languages': ['Hindi']}}}
        self.options = argparse.Namespace(model='google/gemini-3.7-flash', force=False, timeout=60,
            gloss_batch_size=40, gloss_workers=1, max_attempts=1,
            semantic_repair_rounds=2, semantic_repair_seconds=120)
        self.calls = []; self.now = 1000.0; self.repaired = False
        self.reject_always = False; self.unresolved = False; self.transport_failure = False
        self.baseline = None
        self.patch(pipeline, 'ROOT', self.root)
        self.patch(pipeline, 'translation_policy_payload', return_value={'test': 'fixed-policy'})
        self.patch(pipeline.gemini, 'key', return_value='test-placeholder')
        self.patch(pipeline.gemini, 'call', side_effect=self.provider)
        self.patch(pipeline.time, 'time', side_effect=lambda: self.now)
        p = patch.dict(os.environ, {'BHAKTI_API_RUN_LEDGER': str(self.root / 'ledger.json'),
                                    'BHAKTI_API_RUN_BUDGET_USD': '12'}, clear=False)
        p.start(); self.addCleanup(p.stop)

    def patch(self, obj, name, *args, **kw):
        p = patch.object(obj, name, *args, **kw); value = p.start(); self.addCleanup(p.stop); return value

    def write(self, name, value):
        (self.packets / name).write_text(json.dumps(value, ensure_ascii=False))

    def rows(self, lines, repaired=False):
        choices = decisions_for(lines, ['Hindi'])
        return [{'id': row['id'], 'word_glosses': [
            {'roman': token, 'gloss': meaning, 'concept_key': '', 'preserve_in_english': False}
            for token, meaning in zip(row['roman'].split(), ['my','breath','me','abandons','is'])],
            'semantic_frame': {field: ('my breath' if repaired else 'I') if field == 'agent' else ''
                               for field in pipeline.SEMANTIC_FRAME_FIELDS},
            'grammar_note': '', 'uncertainty': '', 'sense_decisions': choices[row['id']]}
            for row in lines]

    def translation(self, line, good):
        english = self.baseline or ('My breath abandons me.' if good else 'I abandon my breath.')
        return {'id': line['id'], 'literal_english': english,
            'segments': [{'text': english, 'word_indices': list(range(5))}],
            'material_alternatives': [], 'human_review_recommended': False,
            'choice_note': '', 'uncertainty': '', 'fidelity': {
                'agency_and_image_preserved': True, 'all_meaning_accounted_for': True,
                'unsupported_additions': [], 'notes': ''}}

    def issue(self, line_id='a'):
        return {'kind': 'unresolved_evidence' if self.unresolved else 'frame_relation',
            'target_line_ids': [line_id], 'references': [{'line_id': line_id,
                'domain': 'word_glosses', 'word_indices': [1], 'source_quote': 'साँस'}],
            'explanation': 'The grammatical subject is the breath, not the speaker.',
            'evidence': 'The noun sāṃsa agrees with choṛatī.',
            'needed_evidence': 'Resolve audited source from audio.' if self.unresolved else '',
            'hold_reason': 'audited_source_ambiguity' if self.unresolved else ''}

    def review(self, evidence):
        rows = []
        for item in evidence:
            fail = self.reject_always or self.unresolved or item['gloss']['semantic_frame']['agent'] != 'my breath'
            rows.append({'id': item['source']['id'], 'passes': not fail,
                'human_review_recommended': self.unresolved, 'agency_preserved': not fail,
                'imagery_preserved': True, 'all_meaning_accounted_for': True,
                'unsupported_additions': [], 'material_choice': '',
                'reason': 'Subject mismatch.' if fail else 'Source agency preserved.',
                'issues': [self.issue(item['source']['id'])] if fail else []})
            row=rows[-1]
            row['component_judgments']={key:{'status':'supported','reason':'Canned source-grounded fixture conclusion.'} for key in ('gloss','frame','english')}
            if fail:
                row['component_judgments']['frame']={'status':'unresolved' if self.unresolved else 'defect','reason':'The frame changes the breath agency.'}
                if item['draft']['literal_english']=='I abandon my breath.':
                    row['component_judgments']['english']={'status':'unresolved' if self.unresolved else 'defect','reason':'The English changes the breath agency.'}
                    if not self.unresolved:
                        issue=self.issue(item['source']['id']);issue['kind']='english_realization';row['issues'].append(issue)

        return rows

    @staticmethod
    def payload(prompt, marker):
        return json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1].lstrip())[0]

    def provider(self, model, key, prompt, **kw):
        self.calls.append({'name': kw['schema_name'], 'prompt': prompt, 'timeout': kw['timeout']})
        if self.transport_failure:
            raise RuntimeError('bounded API hard wall deadline exceeded; reservation retained, run blocked')
        if kw['schema_name'] == 'bhakti_translation_review':
            evidence = self.payload(prompt, 'EVIDENCE:\n')
            self.calls[-1]['ids'] = [item['source']['id'] for item in evidence]
            return {'packet': {'reviews': self.review(evidence)}}
        if 'word_gloss' in kw['schema_name']:
            lines = self.payload(prompt, 'TARGET LYRICS (return these IDs only):\n')
            # Interface contract: repair feedback is explicit, never hidden in a
            # rewritten source or a force-rerun flag.
            repaired = 'REPAIR FEEDBACK:\n' in prompt
            self.repaired |= repaired
            return {'packet': {'glosses': self.rows(lines, repaired)}}
        lines = self.payload(prompt, 'TARGET audited source lines (return these IDs only):\n')
        glosses = self.payload(prompt, 'TARGET word gloss record:\n')
        by_id = {row['id']: row for row in glosses}
        return {'packet': {'translations': [self.translation(row, by_id[row['id']]['semantic_frame']['agent'] == 'my breath')
                                            for row in lines],
                           'comparison': [{'id': row['id'], 'supplied': '', 'chosen': '',
                                           'material_change': False, 'reason': ''} for row in lines]}}

    def complete(self):
        return pipeline.complete_semantics(self.song, self.audit, {'slug': 'fixture'}, self.options)

    def state(self):
        return json.loads((self.packets / 'semantic-repair-state.json').read_text())

    def test_wrong_frame_repairs_before_english_then_new_independent_review(self):
        original = copy.deepcopy(self.audit)
        glosses, english = self.complete()
        names = [call['name'] for call in self.calls]
        self.assertEqual(sum('word_gloss' in name for name in names), 2)
        self.assertEqual(sum(name == 'bhakti_translation_review' for name in names), 2)
        self.assertEqual(glosses['packet']['glosses'][0]['semantic_frame']['agent'], 'my breath')
        self.assertEqual(english['packet']['translations'][0]['literal_english'], 'My breath abandons me.')
        self.assertEqual(self.audit, original)
        self.assertEqual(self.state()['status'], 'accepted')
        manifest = json.loads((self.packets / 'semantic-acceptance.json').read_text())
        self.assertEqual(manifest['gloss_sha256'], digest(glosses))
        self.assertEqual(manifest['translation_sha256'], digest(english))
        candidates = list(self.packets.glob('semantic-repair/**/translation-candidate.json'))
        self.assertTrue(any('I abandon my breath.' in p.read_text() for p in candidates))

    def test_accepted_resume_validates_manifest_without_paid_calls(self):
        first = self.complete()
        count = len(self.calls)
        self.now += 1000  # An accepted cache does not need a new paid deadline.
        second = self.complete()
        self.assertEqual(first, second)
        self.assertEqual(len(self.calls), count)
        self.assertEqual(self.state()['status'], 'accepted')

    def test_unresolved_audio_evidence_holds_without_repair_or_final_artifacts(self):
        self.unresolved = True
        with self.assertRaisesRegex(RuntimeError, 'audited_source_ambiguity'):
            self.complete()
        self.assertEqual(sum('word_gloss' in c['name'] for c in self.calls), 1)
        self.assertFalse((self.packets / 'semantic-acceptance.json').exists())
        self.assertEqual(self.state()['status'], 'blocked')

    def test_two_round_limit_never_turns_a_failed_judgment_into_acceptance(self):
        self.reject_always = True
        with self.assertRaisesRegex(RuntimeError, 'no_progress|repair_limit_exhausted'):
            self.complete()
        self.assertLessEqual(sum('word_gloss' in c['name'] for c in self.calls), 3)
        self.assertFalse((self.packets / 'semantic-acceptance.json').exists())
        count = len(self.calls)
        with self.assertRaises(RuntimeError): self.complete()
        self.assertEqual(len(self.calls), count, 'restart must not reset exhausted rounds')

    def test_persisted_absolute_deadline_limits_every_call_timeout(self):
        self.options.timeout = 300
        self.options.semantic_repair_seconds = 2
        original_provider = self.provider
        def advance(*args, **kwargs):
            result = original_provider(*args, **kwargs); self.now += 0.75; return result
        with patch.object(pipeline.gemini, 'call', side_effect=advance):
            with self.assertRaisesRegex(RuntimeError, 'deadline'):
                self.complete()
        self.assertEqual(self.state()['deadline_at_epoch'], 1002.0)
        self.assertEqual(len(self.calls), 3)
        for call, remaining in zip(self.calls, [2.0, 1.25, 0.5]):
            self.assertGreater(call['timeout'], 0)
            self.assertLessEqual(call['timeout'], remaining)
        self.assertFalse(self.repaired)
        count = len(self.calls)
        self.options.semantic_repair_seconds = 600
        with self.assertRaisesRegex(RuntimeError, 'deadline'): self.complete()
        self.assertEqual(len(self.calls), count)
        self.assertEqual(self.state()['deadline_at_epoch'], 1002.0)

    def test_transport_failure_is_not_a_semantic_retry(self):
        self.transport_failure = True
        with self.assertRaisesRegex(RuntimeError, 'run blocked'): self.complete()
        self.assertEqual(len(self.calls), 1)
        self.assertFalse((self.packets / 'semantic-acceptance.json').exists())

    def test_saved_owner_baseline_enters_prompt_without_job_provided_translation(self):
        self.baseline = 'My breath abandons me.'
        registry = {'version': 1, 'songs': {'fixture': {'policy': 'preserve_english',
            'englishSha256': 'a'*64, 'plainEnglishByLine': {'a': self.baseline}}}}
        (self.root / 'data' / 'editorial_baselines.json').write_text(json.dumps(registry))
        _, result = self.complete()
        prompts = [c['prompt'] for c in self.calls if c['name'] != 'bhakti_translation_review' and 'word_gloss' not in c['name']]
        self.assertTrue(prompts)
        self.assertTrue(all('LOCKED' in p and self.baseline in p for p in prompts))
        self.assertEqual(result['packet']['translations'][0]['literal_english'], self.baseline)

    def test_owner_population_conflict_stops_before_any_semantic_call(self):
        registry = {'version': 1, 'songs': {'fixture': {'policy': 'preserve_english',
            'englishSha256': 'a'*64, 'plainEnglishByLine': {'absent': 'Saved wording.'}}}}
        (self.root / 'data' / 'editorial_baselines.json').write_text(json.dumps(registry))
        with self.assertRaisesRegex(RuntimeError, 'population|baseline'): self.complete()
        self.assertEqual(self.calls, [])

    def test_invalid_issue_index_domain_is_not_inferred_or_coerced(self):
        rows = self.rows(self.lines)
        good = self.issue()
        self.assertEqual(pipeline.semantic_repair_issue_errors(self.lines, rows, [good]), [])
        for change in ({'domain': 'source_words'}, {'word_indices': [5]},
                       {'line_id': 'unknown'}, {'source_quote': 'NOT PRESENT'}):
            issue = copy.deepcopy(good); issue['references'][0].update(change)
            self.assertTrue(pipeline.semantic_repair_issue_errors(self.lines, rows, [issue]), change)

    def test_index_domain_uses_each_referenced_lines_gloss_array(self):
        short = {'id': 'b', 'source_text': 'प्रेम', 'roman': 'prema', 'kind': 'verse'}
        lines = self.lines + [short]; rows = self.rows(lines)
        issue = self.issue(); issue['references'][0].update(line_id='b', word_indices=[1], source_quote='प्रेम')
        self.assertTrue(pipeline.semantic_repair_issue_errors(lines, rows, [issue]))
        issue['references'][0]['word_indices'] = [0]
        self.assertEqual(pipeline.semantic_repair_issue_errors(lines, rows, [issue]), [])

    def test_full_final_review_reruns_distant_initially_passing_row(self):
        self.lines[:] = [dict(self.lines[0], id=f'line-{i}') for i in range(25)]
        # Only first line is initially wrong. The last row's initial passing
        # frame names a distant dependency; final review must still run it.
        original_rows = self.rows
        def rows(lines, repaired=False):
            result = original_rows(lines, True)
            for row in result:
                if row['id'] == 'line-0' and not repaired: row['semantic_frame']['agent'] = 'I'
                if row['id'] == 'line-24': row['semantic_frame']['cross_line_relation'] = 'Depends on line-0.'
            return result
        with patch.object(self, 'rows', side_effect=rows): self.complete()
        counts = {line['id']: 0 for line in self.lines}
        for call in self.calls:
            for line_id in call.get('ids', []): counts[line_id] += 1
        self.assertTrue(all(count == 2 for count in counts.values()), counts)
        final_distant = [c for c in self.calls if 'line-24' in c.get('ids', [])][-1]
        self.assertIn('line-0', final_distant['prompt'])
        reading = self.payload(final_distant['prompt'], 'ENGLISH READING CONTEXT (context only; target obligations unchanged):\n')
        self.assertIn({'line_id': 'line-24', 'cross_line_relation': 'Depends on line-0.'}, reading['relation_notes'])
        distant = reading['context_rows']
        ref = next(item for item in distant if item.get('source', {}).get('id') == 'line-0')
        self.assertEqual(ref['gloss']['semantic_frame']['agent'], 'my breath')
        self.assertEqual(ref['draft']['literal_english'], 'My breath abandons me.')
        self.assertNotIn('independent_review', ref['draft'])

    def test_small_failed_translation_is_saved_before_strict_exception(self):
        # Existing function: direct strict callers remain strict, but no longer
        # lose the candidate needed for diagnosis or a resumed repair.
        glosses = {'packet': {'glosses': self.rows(self.lines)}}
        with self.assertRaisesRegex(RuntimeError, 'fresh contract'):
            pipeline.translate(self.song, self.audit, glosses, {}, self.options)
        self.assertFalse((self.packets / '05-translation.json').exists())
        files = list(self.packets.rglob('translation-candidate.json'))
        self.assertTrue(files, 'small rejected candidate must be privately recoverable')
        self.assertTrue(any('I abandon my breath.' in path.read_text() for path in files))

    def test_hydration_cannot_backfill_an_unaccepted_repair_summary(self):
        self.write('semantic-repair-required.json', {'version': 1, 'run_id': 'fixture-run'})
        self.write('song-packet.json', {'semantic_repair_version': 1,
             'glosses': {'packet': {'glosses': []}}, 'translation': {'packet': {'translations': []}}})
        with self.assertRaisesRegex(RuntimeError, 'accept|repair'):
            pipeline.hydrate_pipeline_artifacts(self.packets)
        self.assertFalse((self.packets / '04-glosses.json').exists())
        self.assertFalse((self.packets / '05-translation.json').exists())

    def test_generate_rejects_pending_repair_before_legacy_publication_checks(self):
        self.write('semantic-repair-required.json', {'version': 1, 'run_id': 'fixture-run'})
        with patch.object(pipeline, 'publication_errors', side_effect=AssertionError('guard bypassed')):
            with self.assertRaisesRegex(RuntimeError, 'accept|repair'):
                pipeline.generate(self.song, {'slug': 'fixture'}, {}, {}, {}, {}, {}, write_catalogue_after=False)
        self.assertFalse((self.song / 'data.js').exists())

    def test_mismatched_acceptance_hash_cannot_generate_or_hydrate(self):
        self.write('semantic-repair-required.json', {'version': 1, 'run_id': 'fixture-run'})
        glosses = {'packet': {'glosses': self.rows(self.lines, True)}}
        english = {'packet': {'translations': [self.translation(self.lines[0], True)]}}
        self.write('semantic-acceptance.json', {'version': 1, 'status': 'accepted',
            'run_id': 'fixture-run', 'gloss_sha256': digest(glosses),
            'translation_sha256': digest(english)})
        english['packet']['translations'][0]['literal_english'] = 'Changed after review.'
        self.write('song-packet.json', {'semantic_repair_version': 1,
            'glosses': glosses, 'translation': english})
        with self.assertRaisesRegex(RuntimeError, 'accept|hash|repair'):
            pipeline.hydrate_pipeline_artifacts(self.packets)
        with patch.object(pipeline, 'publication_errors', side_effect=AssertionError('guard bypassed')):
            with self.assertRaisesRegex(RuntimeError, 'accept|hash|repair'):
                pipeline.generate(self.song, {'slug': 'fixture'}, {}, self.audit, {},
                                  glosses, english, write_catalogue_after=False)

    def test_packet_metadata_requires_acceptance_even_without_marker(self):
        self.write('song-packet.json', {'semantic_repair_version': 1,
            'glosses': {'semantic_repair_version': 1, 'packet': {'glosses': []}},
            'translation': {'semantic_repair_version': 1, 'packet': {'translations': []}}})
        with self.assertRaisesRegex(RuntimeError, 'accept|repair'):
            pipeline.hydrate_pipeline_artifacts(self.packets)

    def test_malformed_saved_registry_blocks_before_paid_call(self):
        (self.root / 'data' / 'editorial_baselines.json').write_text('{broken')
        with self.assertRaisesRegex(RuntimeError, 'baseline'): self.complete()
        self.assertEqual(self.calls, [])

    def test_changed_generated_feedback_never_resets_stable_input_round_counter(self):
        self.reject_always = True
        original_provider = self.provider
        reviews = 0
        def changing_feedback(*args, **kwargs):
            nonlocal reviews
            if kwargs['schema_name'] == 'bhakti_translation_review':
                reviews += 1
                if reviews > 3:
                    raise AssertionError('A fourth review bypassed the two-round cap')
            result = original_provider(*args, **kwargs)
            if 'word_gloss' in kwargs['schema_name']:
                for row in result['packet']['glosses']:
                    row['semantic_frame']['modifiers'] = f'candidate revision {reviews}'
            if kwargs['schema_name'] == 'bhakti_translation_review':
                for row in result['packet']['reviews']:
                    row['issues'][0]['explanation'] += f' Distinct generated feedback {reviews}.'
            return result
        with patch.object(pipeline.gemini, 'call', side_effect=changing_feedback):
            with self.assertRaisesRegex(RuntimeError, 'repair_limit_exhausted|no_progress'):
                self.complete()
            state = self.state(); count = len(self.calls)
            self.assertEqual(state['rounds_used'], 2)
            self.options.force = True
            with self.assertRaisesRegex(RuntimeError, 'repair_limit_exhausted|no_progress'):
                self.complete()
            self.assertEqual(len(self.calls), count, 'force/resume cannot fund another round')
            self.assertEqual(self.state()['run_id'], state['run_id'])
            self.assertEqual(self.state()['rounds_used'], 2)

    def test_interruption_after_repaired_gloss_ready_resumes_actual_cache(self):
        real_write = pipeline.semantic_write_json
        interrupted = False
        def write_then_interrupt(path, value):
            nonlocal interrupted
            real_write(path, value)
            if Path(path).name == 'gloss-ready.json' and 'semantic-repair' in Path(path).parts:
                rows = value.get('packet', {}).get('glosses', [])
                if rows and rows[0]['semantic_frame']['agent'] == 'my breath' and not interrupted:
                    interrupted = True
                    raise KeyboardInterrupt('Local process interruption after durable validated stage')
        with patch.object(pipeline, 'semantic_write_json', side_effect=write_then_interrupt):
            with self.assertRaises(KeyboardInterrupt): self.complete()
        self.assertTrue(interrupted)
        ready_paths = list(self.packets.glob('semantic-repair/**/gloss-ready.json'))
        self.assertTrue(ready_paths)
        snapshots = {str(path): path.read_bytes() for path in ready_paths}
        gloss_calls = sum('word_gloss' in call['name'] for call in self.calls)
        run_id = self.state()['run_id']; deadline = self.state()['deadline_at_epoch']
        self.complete()
        self.assertEqual(sum('word_gloss' in call['name'] for call in self.calls), gloss_calls)
        for path, value in snapshots.items(): self.assertEqual(Path(path).read_bytes(), value)
        self.assertEqual(self.state()['run_id'], run_id)
        self.assertEqual(self.state()['deadline_at_epoch'], deadline)
        self.assertEqual(self.state()['status'], 'accepted')

    def test_saved_owner_english_rejects_disobedient_provider_even_if_review_passes(self):
        locked = 'My breath leaves me.'
        registry = {'version': 1, 'songs': {'fixture': {'policy': 'preserve_english',
            'englishSha256': 'a'*64, 'plainEnglishByLine': {'a': locked}}}}
        (self.root / 'data' / 'editorial_baselines.json').write_text(json.dumps(registry))
        original_rows = self.rows
        def correct_rows(lines, repaired=False): return original_rows(lines, True)
        # No self.baseline assignment: provider ignores LOCKED and proposes the
        # default different English. Its reviewer also incorrectly passes it.
        with patch.object(self, 'rows', side_effect=correct_rows):
            with self.assertRaisesRegex(RuntimeError, 'baseline|owner|locked'):
                self.complete()
        self.assertFalse((self.packets / 'semantic-acceptance.json').exists())
        self.assertFalse((self.song / 'data.js').exists())
        self.assertEqual(self.state()['status'], 'blocked')
        self.assertTrue(any(locked in call['prompt'] for call in self.calls))

    def test_generate_only_cli_reports_crash_or_mismatched_pair_as_blocked(self):
        import contextlib
        import io
        import sys
        glosses = {'packet': {'glosses': self.rows(self.lines, True)}}
        english = {'packet': {'translations': [self.translation(self.lines[0], True)]}}
        for mode in ('crash_before_manifest', 'mismatched_pair'):
            with self.subTest(mode=mode):
                for name in ('04-glosses.json', '05-translation.json', 'semantic-acceptance.json'):
                    (self.packets / name).unlink(missing_ok=True)
                self.write('semantic-repair-required.json', {'version': 1, 'run_id': 'fixture-run'})
                self.write('song-packet.json', {'semantic_repair_version': 1, 'audit': self.audit,
                    'timing': {'packet': {'timings': []}}, 'glosses': glosses, 'translation': english})
                if mode == 'mismatched_pair':
                    self.write('semantic-acceptance.json', {'version': 1, 'status': 'accepted',
                        'run_id': 'fixture-run', 'gloss_sha256': digest(glosses), 'translation_sha256': '0'*64})
                output = io.StringIO()
                with patch.object(sys, 'argv', ['bhakti_pipeline.py', '--generate-only', '--song', 'fixture=/unused.m4a']), \
                     patch.object(pipeline, 'write_catalogue'), \
                     patch.object(pipeline, 'generate') as generate, contextlib.redirect_stdout(output):
                    status = pipeline.main()
                self.assertEqual(status, 1)
                generate.assert_not_called()
                result = json.loads(output.getvalue())[0]
                self.assertEqual(result['status'], 'blocked')
                self.assertRegex(result['error'], 'accept|repair|hash')
                self.assertFalse((self.packets / '04-glosses.json').exists())
                self.assertFalse((self.packets / '05-translation.json').exists())
        self.assertEqual(self.calls, [])

    def test_pure_english_repair_keeps_gloss_record_bytes_unchanged(self):
        original_provider = self.provider
        original_rows = self.rows
        initial_gloss = None
        def english_only(*args, **kwargs):
            nonlocal initial_gloss
            result = original_provider(*args, **kwargs)
            if 'word_gloss' in kwargs['schema_name']:
                initial_gloss = json.dumps(result['packet'], ensure_ascii=False, sort_keys=True)
            elif kwargs['schema_name'] == 'bhakti_translation_review':
                evidence = self.payload(args[2], 'EVIDENCE:\n')
                for review, item in zip(result['packet']['reviews'], evidence):
                    if item['draft']['literal_english'] == 'I abandon my breath.':
                        review.update(passes=False, human_review_recommended=False, agency_preserved=False)
                        review['component_judgments']['english']={'status':'defect','reason':'The English reverses source agency.'}
                        issue = self.issue(item['source']['id']); issue['kind'] = 'english_realization'
                        review['issues'] = [issue]
            elif 'REPAIR FEEDBACK:\n' not in args[2]:
                for row in result['packet']['translations']:
                    row['literal_english'] = 'I abandon my breath.'
                    row['segments'] = [{'text': row['literal_english'], 'word_indices': list(range(5))}]
            return result
        with patch.object(self, 'rows', side_effect=lambda lines, repaired=False: original_rows(lines, True)), \
             patch.object(pipeline.gemini, 'call', side_effect=english_only):
            glosses, english = self.complete()
        self.assertEqual(sum('word_gloss' in c['name'] for c in self.calls), 1)
        self.assertEqual(json.dumps(glosses['packet'], ensure_ascii=False, sort_keys=True), initial_gloss)
        self.assertEqual(english['packet']['translations'][0]['literal_english'], 'My breath abandons me.')
        self.assertEqual(sum(c['name'] == 'bhakti_translation_review' for c in self.calls), 2)

    def test_changed_performance_order_invalidates_accepted_run_and_review_context(self):
        self.audit['packet']['performance_order'] = [{'line_id': 'a', 'occurrence': 1}]
        self.complete(); old_id = self.state()['run_id']; old_count = len(self.calls)
        self.audit['packet']['performance_order'].append({'line_id': 'a', 'occurrence': 2})
        self.complete()
        self.assertNotEqual(self.state()['run_id'], old_id)
        self.assertGreater(len(self.calls), old_count)
        self.assertTrue(any('"occurrence": 2' in call['prompt'] for call in self.calls[old_count:]))

    def test_source_recording_digest_and_trim_invalidate_but_relocated_path_does_not(self):
        source_path = self.song / '.transcription' / 'source.json'
        source = {'source_url': 'https://www.youtube.com/watch?v=fixture',
                  'audio_sha256': 'a'*64, 'local_source': '/old/location.m4a',
                  'applied_trim': {'start_seconds': 2.5}}
        source_path.write_text(json.dumps(source))
        self.complete(); first = self.state()['run_id']; count = len(self.calls)
        source['local_source'] = '/new/location.m4a'; source_path.write_text(json.dumps(source))
        self.complete()
        self.assertEqual(self.state()['run_id'], first); self.assertEqual(len(self.calls), count)
        for field, value in [('audio_sha256', 'b'*64), ('applied_trim', {'start_seconds': 3.5})]:
            old_id = self.state()['run_id']
            source[field] = value; source_path.write_text(json.dumps(source))
            self.complete(); self.assertNotEqual(self.state()['run_id'], old_id)

    def test_round_zero_reuses_existing_valid_gloss_and_held_english_candidate(self):
        # Existing strict stages leave a rejected candidate at the song's normal
        # stage location. Adoption must rerun review, not pay to reconstruct it.
        glosses = pipeline.gloss(self.song, self.audit, self.options)
        with self.assertRaisesRegex(RuntimeError, 'fresh contract'):
            pipeline.translate(self.song, self.audit, glosses, {}, self.options)
        self.calls.clear()
        self.complete()
        self.assertEqual(self.calls[0]['name'], 'bhakti_translation_review')
        self.assertEqual(sum('word_gloss' in call['name'] for call in self.calls), 1)
        self.assertEqual(sum(call['name'] == 'bhakti_literal_translation' for call in self.calls), 1)

    def test_round_zero_reuses_complete_accepted_stages_without_any_provider_call(self):
        original_rows = self.rows
        with patch.object(self, 'rows', side_effect=lambda lines, repaired=False: original_rows(lines, True)):
            glosses = pipeline.gloss(self.song, self.audit, self.options)
            pipeline.translate(self.song, self.audit, glosses, {}, self.options)
        self.calls.clear()
        self.complete()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.state()['status'], 'accepted')

    def test_version8_held_candidate_migrates_only_under_exact_original_identity(self):
        # Construct the prior immutable fingerprint algorithm explicitly; the
        # source/gloss/baseline inputs are identical, schema version differs.
        glosses = pipeline.gloss(self.song, self.audit, self.options)
        with self.assertRaises(RuntimeError):
            pipeline.translate(self.song, self.audit, glosses, {}, self.options)
        candidate_path = self.packets / 'translation-candidate.json'
        candidate = json.loads(candidate_path.read_text())
        inputs = {'lines': self.lines, 'glosses': glosses['packet']['glosses'],
                  'provided_translation': '(none supplied)', 'languages': ['Hindi']}
        payload = {'stage': 'translation', 'gloss_version': 6, 'translation_version': 8,
                   'model': pipeline.gemini.batch_base_model(self.options.model),
                   'provider': pipeline.gemini.provider_name(), 'policy': {'test':'fixed-policy'}, 'inputs': inputs}
        candidate['fingerprint'] = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        candidate['input_contract_version'] = 8
        candidate_path.write_text(json.dumps(candidate))
        self.calls.clear(); self.complete()
        self.assertEqual(self.calls[0]['name'], 'bhakti_translation_review')
        self.assertEqual(sum('word_gloss' in call['name'] for call in self.calls), 1)

    def test_existing_candidate_with_stale_gloss_fingerprint_is_never_adopted(self):
        glosses = pipeline.gloss(self.song, self.audit, self.options)
        with self.assertRaises(RuntimeError): pipeline.translate(self.song, self.audit, glosses, {}, self.options)
        saved = json.loads((self.packets / 'translation-candidate.json').read_text())
        saved['fingerprint'] = '0'*64
        (self.packets / 'translation-candidate.json').write_text(json.dumps(saved))
        self.calls.clear(); self.complete()
        self.assertEqual(self.calls[0]['name'], 'bhakti_literal_translation')

    def test_actual_audio_bytes_and_trim_artifact_invalidate_accepted_identity(self):
        audio = self.song / 'audio.m4a'; audio.write_bytes(b'first recording fixture')
        trim = self.song / '.transcription' / 'trim-applied.json'
        trim.write_text(json.dumps({'applied': True, 'start_seconds': 1.25}))
        self.complete(); first = self.state()['run_id']
        audio.write_bytes(b'other recording fixture')
        self.complete(); second = self.state()['run_id']
        self.assertNotEqual(first, second)
        trim.write_text(json.dumps({'applied': True, 'start_seconds': 2.25}))
        self.complete(); self.assertNotEqual(second, self.state()['run_id'])

    def test_generate_guard_rejects_changed_performance_and_actual_recording(self):
        audio = self.song / 'audio.m4a'; audio.write_bytes(b'first recording fixture')
        self.audit['packet']['performance_order'] = [{'line_id': 'a', 'occurrence': 1}]
        glosses, translations = self.complete()
        for change in ('order', 'audio'):
            with self.subTest(change=change):
                audited = copy.deepcopy(self.audit)
                if change == 'order': audited['packet']['performance_order'].append({'line_id': 'a', 'occurrence': 2})
                else: audio.write_bytes(b'new recording fixture')
                with patch.object(pipeline, 'publication_errors', side_effect=AssertionError('guard bypassed')):
                    with self.assertRaisesRegex(RuntimeError, 'accept|source|repair'):
                        pipeline.generate(self.song, {'slug': 'fixture'}, {}, audited, {}, glosses, translations,
                                          write_catalogue_after=False)

    def test_historical_accepted_text_with_unbound_order_gets_review_not_reconstruction(self):
        self.audit['packet']['performance_order'] = [{'line_id':'a', 'occurrence':1}]
        original_rows = self.rows
        with patch.object(self, 'rows', side_effect=lambda lines, repaired=False: original_rows(lines, True)):
            glosses = pipeline.gloss(self.song, self.audit, self.options)
            pipeline.translate(self.song, self.audit, glosses, {}, self.options)
        self.calls.clear(); self.complete()
        self.assertEqual([call['name'] for call in self.calls], ['bhakti_translation_review'])

    def test_adopted_owner_candidate_survives_round_zero_gloss_ready_interruption(self):
        self.audit['packet']['performance_order'] = [{'line_id': 'a', 'occurrence': 1}]
        self.baseline = 'My breath leaves me.'
        registry = {'version': 1, 'songs': {'fixture': {'policy': 'preserve_english',
            'englishSha256': 'a'*64, 'plainEnglishByLine': {'a': self.baseline}}}}
        (self.root / 'data' / 'editorial_baselines.json').write_text(json.dumps(registry))
        owner = self.root / 'owner.json'; owner.write_text(json.dumps({'a': self.baseline}, ensure_ascii=False, indent=2)+'\n')
        original_rows = self.rows
        with patch.object(self, 'rows', side_effect=lambda lines, repaired=False: original_rows(lines, True)):
            glosses = pipeline.gloss(self.song, self.audit, self.options)
            pipeline.translate(self.song, self.audit, glosses, {'providedTranslation': str(owner)}, self.options)
        self.calls.clear()
        real_write = pipeline.semantic_write_json
        interrupted = False
        def write_then_interrupt(path, value):
            nonlocal interrupted
            real_write(path, value)
            if Path(path).name == 'gloss-ready.json' and not interrupted:
                interrupted = True
                raise KeyboardInterrupt('after migrated gloss ready')
        with patch.object(pipeline, 'semantic_write_json', side_effect=write_then_interrupt):
            with self.assertRaises(KeyboardInterrupt): self.complete()
        self.assertEqual(self.calls, [])
        _, result = self.complete()
        self.assertEqual([call['name'] for call in self.calls], ['bhakti_translation_review'])
        self.assertEqual(result['packet']['translations'][0]['literal_english'], self.baseline)

    def test_legacy_hydration_without_repair_metadata_is_unchanged(self):
        self.write('song-packet.json', {'glosses': {'packet': {'glosses': []}},
                                      'translation': {'packet': {'translations': []}}})
        pipeline.hydrate_pipeline_artifacts(self.packets)
        self.assertTrue((self.packets / '04-glosses.json').exists())
        self.assertTrue((self.packets / '05-translation.json').exists())


if __name__ == '__main__': unittest.main()

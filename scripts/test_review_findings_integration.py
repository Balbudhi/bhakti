"""Actual audit/router, request cache, and candidate gate; only provider is mocked.

Saved Rehna is the real failing reader. The later all-pass packet is an
adversarial control, not a newly obtained semantic judgment.
"""
import argparse
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import bhakti_library_pass as library
import bhakti_model_routes as routes
import bhakti_candidate_guard as guard
import bhakti_review_findings as findings
from bhakti_semantic_repair import digest
from test_sense_decisions import decisions_for

FIXTURES = Path(__file__).resolve().parent / 'fixtures/review_findings'


def json_block(prompt, marker):
    return json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1].lstrip())[0]


def clean_review(line_id):
    return {'id': line_id, 'passes': True, 'agency_preserved': True,
            'imagery_preserved': True, 'all_meaning_accounted_for': True,
            'unsupported_additions': [], 'human_review_recommended': False,
            'material_choice': '', 'reason': 'Source and changed candidate checked.', 'issues': []}


class FindingIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((FIXTURES / 'rehna-reviews.json').read_text())
        self.reader = json.loads((FIXTURES / 'rehna-reader.json').read_text())
        self.assertEqual(digest(self.reader), self.fixture['reader_digest'])
        self.lines, self.glosses, self.translations = library.reader_evidence(self.reader)
        self.context = dict(lines=self.lines, glosses=self.glosses,
            reader_digest=digest(self.reader), dependency_fingerprint=self.fixture['dependency_fingerprint'])
        self.artifact = {key: copy.deepcopy(self.fixture[key]) for key in
            ('reader_digest','dependency_fingerprint','attempt_id','reviews','issues')}
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.options = argparse.Namespace(model='google/gemini-3.7-flash',
            pro_model='google/gemini-3.1-pro-preview', timeout=600, force=False)
        self.deadline = time.time() + 120
        self.calls = []; self.bad_flash_sibling = False

    def audit(self):
        return library.audit_current_reader(self.reader, slug='rehna-nahi-isa-desa',
            workspace=self.directory/'workspace', route_dir=self.directory/'routes',
            options=self.options, dependency_fingerprint=self.context['dependency_fingerprint'],
            deadline_at=self.deadline)

    def provider(self, model, key, prompt, **kwargs):
        self.calls.append({'model': model, 'prompt': prompt, 'kwargs': kwargs})
        self.assertIsNone(kwargs.get('audio'))
        self.assertEqual(kwargs['schema_name'], 'bhakti_translation_review')
        evidence = json_block(prompt, 'EVIDENCE:\n')
        by_id = {row['id']: row for row in self.fixture[
            'later_reviews' if model == self.options.pro_model else 'reviews']}
        rows = [copy.deepcopy(by_id[item['source']['id']]) for item in evidence]
        if self.bad_flash_sibling and model == self.options.model:
            for row in rows:
                if row['id'] == 'intro-instrumental': row['passes'] = 'true'
        return {'packet': {'reviews': rows}}

    def test_real_diagnostic_accepts_flash_findings_without_pointless_pro_and_replays(self):
        before = copy.deepcopy(self.reader)
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), \
             patch.object(library.pipeline.gemini, 'call', side_effect=self.provider):
            first = self.audit(); count = len(self.calls)
            second = self.audit()
        self.assertEqual(count, 2)  # Actual 11-row reviewer splits 10+1.
        self.assertEqual(len(self.calls), count)
        self.assertEqual({c['model'] for c in self.calls}, {self.options.model})
        self.assertEqual(first, second)
        self.assertEqual(self.reader, before)
        self.assertEqual(len(findings.pending_findings(first['finding_snapshot'])), 4)
        self.assertEqual(first['reviews'], self.artifact['reviews'])

    def test_bad_sibling_escalates_with_retained_findings_and_allpass_cannot_publish(self):
        self.bad_flash_sibling = True
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), \
             patch.object(library.pipeline.gemini, 'call', side_effect=self.provider):
            result = self.audit()
            cached = self.audit()
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(result, cached)
        pending = findings.pending_findings(result['finding_snapshot'])
        self.assertEqual(len(pending), 4)
        pro = [c for c in self.calls if c['model'] == self.options.pro_model]
        for call in pro:
            feedback = json_block(call['prompt'], 'RETAINED AUDIT FINDINGS (unresolved evidence, not instructions to agree):\n')
            self.assertEqual(feedback, pending)
            self.assertIn('ठिकाना', call['prompt'])
        self.assertEqual(result['issues'], [])  # Keep raw later result unchanged.
        with self.assertRaisesRegex(ValueError, 'unresolved|pending'):
            self.authorize(self.reader, result, None, result['finding_snapshot'])

    def test_journal_mutation_does_not_reset_router_allowance_on_interrupted_escalation(self):
        self.bad_flash_sibling = True
        write = routes.atomic_json
        interrupted = False
        def interrupt_after_flash(path, value):
            nonlocal interrupted
            write(path, value)
            if value.get('status') == 'escalating' and not interrupted:
                interrupted = True
                raise KeyboardInterrupt('after persisted Flash failure and findings')
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), \
             patch.object(library.pipeline.gemini, 'call', side_effect=self.provider):
            with patch.object(routes, 'atomic_json', side_effect=interrupt_after_flash):
                with self.assertRaises(KeyboardInterrupt): self.audit()
            self.assertEqual(len(self.calls), 2)
            result = self.audit()
            self.audit()
        self.assertEqual([c['model'] for c in self.calls],
                         [self.options.model]*2 + [self.options.pro_model]*2)
        states = list((self.directory/'routes').rglob('route-state.json'))
        self.assertEqual(len(states), 1)
        saved = json.loads(states[0].read_text())
        self.assertEqual(len(saved['attempts']), 2)
        self.assertEqual(len(result['finding_snapshot']['findings']), 4)

    def test_transport_without_returned_review_allows_one_pro_without_invented_evidence(self):
        original_provider = self.provider
        transport_calls = []
        def provider(model,key,prompt,**kwargs):
            transport_calls.append(model)
            if model == self.options.model:
                raise routes.UnitTransportFailure('http-transient',request_id='bounded-fixture-503',worker_terminated=True)
            return original_provider(model,key,prompt,**kwargs)
        with patch.object(library.pipeline.gemini,'key',return_value='unused'), \
             patch.object(library.pipeline.gemini,'call',side_effect=provider):
            result = self.audit(); self.audit()
        self.assertEqual(transport_calls,[self.options.model,self.options.pro_model,self.options.pro_model])
        self.assertEqual(result['finding_snapshot']['findings'],[])
        self.assertEqual(len(result['finding_snapshot']['reviews']),1)
        state = json.loads(Path(result['finding_route_state_path']).read_text())
        self.assertEqual(state['attempts'][0]['status'],'transport-failed')
        self.assertEqual(state['attempts'][0]['request_id'],'bounded-fixture-503')
        self.assertNotIn('candidate_sha256',state['attempts'][0])

    def test_completed_first_child_findings_survive_later_transport_and_cached_resume(self):
        original_provider = self.provider
        transport_calls = []
        def provider(model,key,prompt,**kwargs):
            targets = [e['source']['id'] for e in json_block(prompt,'EVIDENCE:\n')]
            transport_calls.append(model)
            if model == self.options.model and targets==['outro-instrumental']:
                raise routes.UnitTransportFailure('unknown-outcome',request_id='bounded-fixture-timeout',worker_terminated=True)
            return original_provider(model,key,prompt,**kwargs)
        with patch.object(library.pipeline.gemini,'key',return_value='unused'), \
             patch.object(library.pipeline.gemini,'call',side_effect=provider):
            result = self.audit(); self.audit()
        self.assertEqual(transport_calls,[self.options.model]*2+[self.options.pro_model]*2)
        self.assertEqual(len(result['finding_snapshot']['findings']),4)
        state = json.loads(Path(result['finding_route_state_path']).read_text())
        first = state['attempts'][0]
        self.assertEqual(first['status'],'transport-failed')
        self.assertEqual(first['category'],'unknown-outcome')
        self.assertTrue(first['worker_terminated'])
        self.assertEqual(first['request_id'],'bounded-fixture-timeout')
        candidate = json.loads((Path(result['finding_route_state_path']).parent/'flash/candidate.json').read_text())
        self.assertEqual(first['candidate_sha256'],digest(candidate))
        self.assertEqual(len(candidate['reviews']),10)
        self.assertTrue(candidate['response_contract_errors'])
        for call in self.calls:
            if call['model']==self.options.pro_model:
                self.assertEqual(len(json_block(call['prompt'],
                    'RETAINED AUDIT FINDINGS (unresolved evidence, not instructions to agree):\n')),4)

    def test_partial_diagnostic_never_turns_unterminated_unknown_outcome_into_quality_retry(self):
        original_provider = self.provider
        calls = []
        def provider(model,key,prompt,**kwargs):
            calls.append(model)
            targets = [e['source']['id'] for e in json_block(prompt,'EVIDENCE:\n')]
            if targets==['outro-instrumental']:
                raise routes.UnitTransportFailure('unknown-outcome',request_id='still-running-fixture',worker_terminated=False)
            return original_provider(model,key,prompt,**kwargs)
        with patch.object(library.pipeline.gemini,'key',return_value='unused'), \
             patch.object(library.pipeline.gemini,'call',side_effect=provider):
            with self.assertRaises(routes.UnitUnresolved): self.audit()
        self.assertEqual(calls,[self.options.model]*2)
        state_path = next((self.directory/'routes').rglob('route-state.json'))
        state = json.loads(state_path.read_text())
        self.assertEqual(state['status'],'unresolved')
        self.assertEqual(len(state['attempts']),1)
        attempt = state['attempts'][0]
        self.assertEqual(attempt['status'],'transport-failed')
        self.assertEqual(attempt['category'],'unknown-outcome')
        self.assertFalse(attempt['worker_terminated'])
        candidate = json.loads((state_path.parent/'flash/candidate.json').read_text())
        self.assertEqual(attempt['candidate_sha256'],digest(candidate))
        journals = list((self.directory/'workspace/.transcription/review-findings').glob('*.json'))
        self.assertEqual(len(journals),1)
        self.assertEqual(len(json.loads(journals[0].read_text())['findings']),4)

    def test_shape_missing_sibling_preserves_actual_defect_before_same_unit_pro(self):
        original_provider = self.provider
        raw_flash = []
        def provider(model, key, prompt, **kwargs):
            response = original_provider(model, key, prompt, **kwargs)
            if model == self.options.model:
                response['packet']['reviews'] = [r for r in response['packet']['reviews']
                    if r['id'] != 'intro-instrumental']
                raw_flash.append(copy.deepcopy(response))
            return response
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), \
             patch.object(library.pipeline.gemini, 'call', side_effect=provider):
            result = self.audit(); self.audit()
        self.assertEqual([c['model'] for c in self.calls],
                         [self.options.model,self.options.pro_model,self.options.pro_model])
        self.assertEqual(len(result['finding_snapshot']['findings']),4)
        first = result['finding_snapshot']['reviews'][0]['artifact']
        self.assertTrue(first['response_contract_errors'])
        self.assertIn(raw_flash[0], first['reviewPackets'])
        self.assertEqual(next(r for r in first['reviews'] if r['id']=='verse-3-line-2'),
                         self.artifact['reviews'][-2])
        self.assertTrue(library.current_review_errors(first,self.lines,self.glosses,
            self.context['reader_digest'],self.context['dependency_fingerprint']))
        state = json.loads(Path(result['finding_route_state_path']).read_text())
        self.assertEqual(len(state['attempts']),2)
        self.assertEqual([a['status'] for a in state['attempts']],['quality-failed','accepted'])

    def test_null_response_container_escalates_without_fabricating_findings(self):
        original_provider = self.provider
        def provider(model,key,prompt,**kwargs):
            response = original_provider(model,key,prompt,**kwargs)
            if model == self.options.model: response['packet']['reviews'] = None
            return response
        with patch.object(library.pipeline.gemini,'key',return_value='unused'), \
             patch.object(library.pipeline.gemini,'call',side_effect=provider):
            result = self.audit()
        self.assertEqual(len(self.calls),3)
        self.assertEqual(result['finding_snapshot']['findings'],[])
        first = result['finding_snapshot']['reviews'][0]['artifact']
        self.assertEqual(first['reviews'],[])
        self.assertEqual(first['reviewPackets'][0]['packet']['reviews'],None)
        self.assertTrue(first['response_contract_errors'])

    def test_duplicate_or_unknown_shape_rows_are_quarantined_not_finding_permission(self):
        for corruption in ('duplicate','unknown'):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as tmp:
                self.directory = Path(tmp); self.calls = []
                original_provider = self.provider
                def provider(model,key,prompt,**kwargs):
                    response = original_provider(model,key,prompt,**kwargs)
                    if model == self.options.model:
                        bad = copy.deepcopy(response['packet']['reviews'][-1])
                        if corruption == 'unknown': bad['id'] = 'not-an-audit-target'
                        response['packet']['reviews'].append(bad)
                    return response
                with patch.object(library.pipeline.gemini,'key',return_value='unused'), \
                     patch.object(library.pipeline.gemini,'call',side_effect=provider):
                    result = self.audit()
                pending = result['finding_snapshot']['findings']
                self.assertEqual(len(self.calls),3)
                self.assertEqual(len([f for f in pending if f['kind']=='defect']),
                                 0 if corruption=='duplicate' else 1)
                self.assertFalse(any(f['line_id']=='not-an-audit-target' for f in pending))
                first = result['finding_snapshot']['reviews'][0]['artifact']
                self.assertTrue(first['response_contract_errors'])
                self.assertEqual(len(first['reviewPackets'][0]['packet']['reviews']),11)

    def test_coherent_journal_truncation_is_restored_from_real_route_history_without_calls(self):
        self.bad_flash_sibling = True
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), \
             patch.object(library.pipeline.gemini, 'call', side_effect=self.provider):
            result = self.audit()
            journal = Path(result['finding_journal_path'])
            saved = json.loads(journal.read_text())
            omitted_attempt = saved['reviews'][0]['artifact']['attempt_id']
            saved['reviews'] = saved['reviews'][1:]
            saved['findings'] = [f for f in saved['findings'] if f['attempt_id'] != omitted_attempt]
            journal.write_text(json.dumps(saved, ensure_ascii=False))
            resumed = self.audit()
        self.assertEqual(len(self.calls), 4)
        self.assertEqual({f['finding_id'] for f in resumed['finding_snapshot']['findings']},
                         {f['finding_id'] for f in result['finding_snapshot']['findings']})
        self.assertEqual(len(resumed['finding_snapshot']['findings']), 4)

    def test_missing_prior_attempt_candidate_cannot_turn_truncated_journal_into_acceptance(self):
        self.bad_flash_sibling = True
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), \
             patch.object(library.pipeline.gemini, 'call', side_effect=self.provider):
            result = self.audit()
        journal = Path(result['finding_journal_path'])
        saved = json.loads(journal.read_text())
        omitted = saved['reviews'].pop(0)['artifact']['attempt_id']
        saved['findings'] = [f for f in saved['findings'] if f['attempt_id'] != omitted]
        journal.write_text(json.dumps(saved, ensure_ascii=False))
        candidates = list((self.directory/'routes').rglob('candidate.json'))
        removed = []
        for path in candidates:
            if json.loads(path.read_text()).get('attempt_id') == omitted:
                path.unlink(); removed.append(path)
        self.assertEqual(len(removed), 1)
        with patch.object(library.pipeline.gemini, 'call', side_effect=AssertionError('lost history repaid')):
            with self.assertRaises((ValueError, routes.RunFatal)):
                self.audit()

    def test_pending_feedback_changes_request_cache_not_just_prompt(self):
        local = copy.copy(self.options)
        local.semantic_deadline_at = self.deadline
        local.semantic_full_source = self.lines
        local.semantic_performance_order = self.reader['SONG_SEQUENCE']
        local.semantic_pending_findings = []
        folder = self.directory/'request-cache'
        def run():
            return library.pipeline.independently_review_translations(folder, self.lines,
                self.glosses, self.translations, '(none supplied)', local, languages=['Hindi'])
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), \
             patch.object(library.pipeline.gemini, 'call', side_effect=self.provider):
            run(); self.assertEqual(len(self.calls), 2)
            local.semantic_pending_findings = findings.classify_review(self.artifact, **self.context)['findings']
            run(); self.assertEqual(len(self.calls), 4)
            run(); self.assertEqual(len(self.calls), 4)
        for call in self.calls[2:]:
            self.assertEqual(json_block(call['prompt'],
                'RETAINED AUDIT FINDINGS (unresolved evidence, not instructions to agree):\n'),
                local.semantic_pending_findings)

    def snapshot(self, artifact=None):
        return findings.record_review(self.directory/'manual-journal.json',
            self.artifact if artifact is None else artifact, **self.context)

    def authorize(self, candidate, pre, post, snapshot, *, partial=False, protected=None):
        return guard.authorize_semantic_candidate(self.reader, candidate,
            source_lines=self.lines, gloss_rows=self.glosses, pre_review=pre,
            post_review=post, dependency_fingerprint=self.context['dependency_fingerprint'],
            protected_english=protected, finding_snapshot=snapshot, allow_partial=partial)

    def corrected_candidate(self):
        candidate = copy.deepcopy(self.reader)
        row = candidate['SONG_LINES']['verse-3-line-2']
        row['words'][2]['gloss'] = 'resting place; refuge; destination'
        row['english'] = "{0:The true Guru's }{1:Name }{3:is }{2:the refuge}"
        return candidate

    def post(self, candidate, snapshot, *, explicit=True):
        row = clean_review('verse-3-line-2')
        defect = next(f for f in snapshot['findings'] if f['kind']=='defect')
        if explicit:
            row['finding_dispositions'] = [{'finding_id': defect['finding_id'], 'status': 'repaired',
                'source_quote': 'ठिकाना',
                'explanation': 'The corrected ṭhikānā gloss and its linked English no longer add true; sataguru retains its own modifier.'}]
        return {'reader_digest': digest(candidate),
                'dependency_fingerprint': self.context['dependency_fingerprint'],
                'attempt_id': 'independent-paired-post', 'reviews': [row]}

    def test_only_explicit_finding_bound_repair_can_be_confirmed_and_choices_stay(self):
        snapshot = self.snapshot(); candidate = self.corrected_candidate()
        post = self.post(candidate, snapshot)
        receipt = self.authorize(candidate, self.artifact, post, snapshot, partial=True)
        self.assertEqual(receipt['confirmed_changes'], {'verse-3-line-2': ['english','words']})
        self.assertFalse(receipt['publicationEligible'])
        self.assertEqual(len(receipt['resolved_findings']), 1)
        self.assertEqual({f['line_id'] for f in receipt['pending_findings']},
                         {'refrain-1','refrain-2','verse-1-line-2'})
        with self.assertRaisesRegex(ValueError, 'unresolved|pending'):
            self.authorize(candidate, self.artifact, post, snapshot)
        for lid, row in self.reader['SONG_LINES'].items():
            if lid != 'verse-3-line-2': self.assertEqual(candidate['SONG_LINES'][lid], row)
        self.assertEqual(len(findings.pending_findings(snapshot)), 4)  # No journal erasure.

    def test_snapshot_post_description_with_explicit_disposition_is_not_an_open_choice(self):
        snapshot = self.snapshot(); candidate = self.corrected_candidate()
        post = self.post(candidate,snapshot)
        post['reviews'][0]['material_choice'] = 'The predicate is rendered as a resting place rather than adding truth.'
        receipt = self.authorize(candidate,self.artifact,post,snapshot,partial=True)
        self.assertEqual(len(receipt['resolved_findings']),1)
        self.assertEqual(len(receipt['pending_findings']),3)
        for changes in ({'human_review_recommended':True},{'material_choice':None},
                        {'human_review_recommended':'false'},{'imagery_preserved':False}):
            with self.subTest(changes=changes):
                bad = copy.deepcopy(post);bad['reviews'][0].update(changes)
                with self.assertRaises(ValueError):
                    self.authorize(candidate,self.artifact,bad,snapshot,partial=True)

    def test_clean_changed_target_without_explicit_obligation_disposition_cannot_clear(self):
        snapshot = self.snapshot(); candidate = self.corrected_candidate()
        receipt = self.authorize(candidate, self.artifact,
            self.post(candidate, snapshot, explicit=False), snapshot, partial=True)
        self.assertEqual(receipt['resolved_findings'], [])
        self.assertEqual(len(receipt['pending_findings']), 4)
        self.assertFalse(receipt['publicationEligible'])

    def test_malformed_disposition_containers_fail_as_typed_gate_errors(self):
        snapshot = self.snapshot(); candidate = self.corrected_candidate()
        for bad in (None, {}, [{'finding_id': []}], [{'finding_id': snapshot['findings'][0]['finding_id'],
                     'status': [], 'source_quote': [], 'explanation': 'bad model schema'}]):
            with self.subTest(value=bad):
                post = self.post(candidate,snapshot)
                post['reviews'][0]['finding_dispositions'] = bad
                with self.assertRaises(ValueError):
                    self.authorize(candidate,self.artifact,post,snapshot,partial=True)

    def test_wrong_or_unresolved_disposition_cannot_clear_original_finding(self):
        snapshot = self.snapshot(); candidate = self.corrected_candidate()
        for field, value in [('finding_id','a-different-finding'), ('source_quote','नाम'),
                             ('status','unresolved'), ('explanation','')]:
            with self.subTest(field=field):
                post = self.post(candidate, snapshot)
                post['reviews'][0]['finding_dispositions'][0][field] = value
                try:
                    receipt = self.authorize(candidate, self.artifact, post, snapshot, partial=True)
                except ValueError:
                    continue  # A malformed disposition may reject the whole candidate.
                self.assertEqual(receipt['resolved_findings'], [])
                self.assertFalse(receipt['publicationEligible'])

    def test_unchanged_reader_later_clean_post_cannot_dismiss_old_defect(self):
        snapshot = self.snapshot()
        receipt = self.authorize(self.reader, self.artifact,
            self.post(self.reader, snapshot), snapshot, partial=True)
        self.assertEqual(receipt['resolved_findings'], [])
        self.assertEqual(len(receipt['pending_findings']), 4)
        self.assertFalse(receipt['publicationEligible'])

    def test_quote_must_map_to_referenced_gloss_before_any_repair_permission(self):
        artifact = copy.deepcopy(self.artifact)
        artifact['reviews'][-2]['issues'][0]['references'][0]['word_indices'] = [1]  # नाम, not ठिकाना.
        artifact['issues'] = copy.deepcopy(artifact['reviews'][-2]['issues'])
        snapshot = self.snapshot(artifact)
        self.assertEqual(len(snapshot['findings']), 4)  # Observation is not permission.
        candidate = self.corrected_candidate()
        with self.assertRaisesRegex(ValueError, 'quote|sourceWords|reference'):
            self.authorize(candidate, artifact, self.post(candidate, snapshot), snapshot, partial=True)

    def test_retained_findings_never_authorize_owner_english_or_good_row_changes(self):
        snapshot = self.snapshot(); candidate = self.corrected_candidate()
        protected = {lid: library.editorial_baselines.plain_english(row['english'])
                     for lid,row in self.reader['SONG_LINES'].items()}
        with self.assertRaisesRegex(ValueError, 'protected'):
            self.authorize(candidate,self.artifact,self.post(candidate,snapshot),snapshot,
                           partial=True,protected=protected)
        candidate['SONG_LINES']['verse-2-line-1']['english'] += ' extra unsupported addition'
        with self.assertRaisesRegex(ValueError, 'unapproved|unreferenced'):
            self.authorize(candidate,self.artifact,self.post(candidate,snapshot),snapshot,partial=True)

    def test_actual_repair_stages_touch_only_rehna_target_and_retain_three_choices(self):
        original = copy.deepcopy(self.reader)
        stage_targets = []
        def provider(model, key, prompt, **kwargs):
            schema = kwargs['schema_name']
            if schema == 'bhakti_translation_review':
                old = json_block(prompt, 'ORIGINAL READER ROWS FOR REPAIR COMPARISON:\n')
                if not old:
                    return self.provider(model, key, prompt, **kwargs)
                self.calls.append({'model': model, 'prompt': prompt, 'kwargs': kwargs})
                evidence = json_block(prompt, 'EVIDENCE:\n')
                self.assertEqual([e['source']['id'] for e in evidence], ['verse-3-line-2'])
                self.assertEqual(old['verse-3-line-2'], original['SONG_LINES']['verse-3-line-2'])
                self.assertEqual(evidence[0]['draft']['literal_english'], "The true Guru's Name is the refuge")
                self.assertEqual(evidence[0]['gloss']['word_glosses'][2]['gloss'], 'resting place; refuge; destination')
                obligations = json_block(prompt, 'FINDING OBLIGATIONS FOR THIS REPAIR:\n')
                self.assertEqual(len(obligations), 1)
                self.assertEqual(obligations[0]['issue'], self.fixture['issues'][0])
                review = clean_review('verse-3-line-2')
                review['finding_dispositions'] = [{'finding_id': obligations[0]['finding_id'],
                    'status': 'repaired', 'source_quote': 'ठिकाना',
                    'explanation': 'The extra true modifier is absent from both the corrected gloss and its linked English; the original sataguru qualifier remains.'}]
                return {'packet': {'reviews': [review]}}
            self.calls.append({'model': model, 'prompt': prompt, 'kwargs': kwargs})
            self.assertIsNone(kwargs.get('audio'))
            is_gloss = 'word_gloss' in schema
            marker = ('TARGET LYRICS (return these IDs only):\n' if is_gloss
                      else 'TARGET audited source lines (return these IDs only):\n')
            targets = json_block(prompt, marker)
            self.assertEqual([line['id'] for line in targets], ['verse-3-line-2'])
            stage_targets.append((is_gloss, [line['id'] for line in targets]))
            if is_gloss:
                words = copy.deepcopy(original['SONG_LINES']['verse-3-line-2']['words'])
                words[2]['gloss'] = 'resting place; refuge; destination'
                decisions = decisions_for(targets, ['Hindi'])
                return {'packet': {'glosses': [{'id': 'verse-3-line-2', 'word_glosses': words,
                    'semantic_frame': {field: '' for field in library.pipeline.SEMANTIC_FRAME_FIELDS},
                    'grammar_note': original['SONG_LINES']['verse-3-line-2']['grammarNote'],
                    'uncertainty': '', 'sense_decisions': decisions['verse-3-line-2']}]}}
            return {'packet': {'translations': [{'id': 'verse-3-line-2',
                'literal_english': "The true Guru's Name is the refuge",
                'segments': [{'text': "The true Guru's ", 'word_indices': [0]},
                             {'text': 'Name ', 'word_indices': [1]},
                             {'text': 'is ', 'word_indices': [3]},
                             {'text': 'the refuge', 'word_indices': [2]}],
                'fidelity': {'agency_and_image_preserved': True, 'all_meaning_accounted_for': True,
                             'unsupported_additions': []},
                'human_review_recommended': False, 'material_alternatives': [],
                'choice_note': '', 'uncertainty': ''}], 'comparison': []}}
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), \
             patch.object(library.pipeline.gemini, 'call', side_effect=provider):
            pre = self.audit()
            result = library.repair_current_reader(self.reader, slug='rehna-nahi-isa-desa',
                pre_review=pre, workspace=self.directory/'workspace', route_dir=self.directory/'routes',
                options=self.options, dependency_fingerprint=self.context['dependency_fingerprint'],
                deadline_at=self.deadline)
            count = len(self.calls)
            resumed = library.repair_current_reader(self.reader, slug='rehna-nahi-isa-desa',
                pre_review=pre, workspace=self.directory/'workspace', route_dir=self.directory/'routes',
                options=self.options, dependency_fingerprint=self.context['dependency_fingerprint'],
                deadline_at=self.deadline)
        self.assertEqual(result, resumed)
        self.assertEqual(len(self.calls), count)
        self.assertEqual(stage_targets, [(True,['verse-3-line-2']),(False,['verse-3-line-2'])])
        self.assertEqual(result['reader'], self.corrected_candidate())
        self.assertFalse(result['authorization']['publicationEligible'])
        self.assertEqual(len(result['authorization']['resolved_findings']), 1)
        self.assertEqual(len(result['authorization']['pending_findings']), 3)
        self.assertEqual(self.reader, original)
        self.assertTrue(all(c['kwargs'].get('audio') is None for c in self.calls))

    def test_terminal_accepted_inventory_cache_rechecks_retained_finding_evidence(self):
        # Real inventory/run serialization and cache branch. The first execution
        # seam supplies an already guarded result; provider behavior is covered above.
        from test_bhakti_library_pass import SelectivePassTests, write_js
        fixture = SelectivePassTests('runTest'); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.add_song('rehna-nahi-isa-desa')
        write_js(fixture.root/'songs/rehna-nahi-isa-desa/data.js', self.reader)
        fixture.commit()
        inventory = fixture.inventory(); row = inventory['songs'][0]
        dependency = digest({'inputs':row['fingerprints'], 'source_candidate':None})
        context = {**self.context, 'dependency_fingerprint':dependency}
        first = {**copy.deepcopy(self.artifact), 'dependency_fingerprint':dependency,
            'attempt_id':'original-clean-review', 'reviews':copy.deepcopy(self.fixture['later_reviews']), 'issues':[]}
        journal = fixture.state/'songs/rehna-nahi-isa-desa/review-journal.json'
        snapshot = findings.record_review(journal,first,**context)
        authorization = guard.authorize_semantic_candidate(self.reader,self.reader,
            source_lines=self.lines,gloss_rows=self.glosses,pre_review=first,post_review=None,
            dependency_fingerprint=dependency,finding_snapshot=snapshot)
        candidate_root = fixture.state/'candidate'; song = candidate_root/'songs/rehna-nahi-isa-desa'
        write_js(song/'data.js',self.reader); (song/'index.html').write_text('<script src="data.js"></script>')
        result = {'status':'accepted','publicationEligible':False,'changed':False,
            'candidateRoot':str(candidate_root),'candidateReaderSha256':library.file_hash(song/'data.js'),
            'candidatePageSha256':library.file_hash(song/'index.html'),'authorization':authorization,
            'source':None,'finding_journal':{'path':str(journal),'sha256':library.file_hash(journal)}}
        options = argparse.Namespace(budget_usd=.35,max_calls=2,deadline_seconds=120,
            slugs=['rehna-nahi-isa-desa'],model=self.options.model,pro_model=self.options.pro_model,
            source_reuse_maps={})
        with patch.object(library,'execute_song',return_value=result) as execute:
            library.execute_inventory(fixture.root,inventory,fixture.state,options)
            late = {**copy.deepcopy(self.artifact),'dependency_fingerprint':dependency,
                    'attempt_id':'later-concrete-audit'}
            findings.record_review(journal,late,**context)
            with self.assertRaises((ValueError,routes.RunFatal)):
                library.execute_inventory(fixture.root,inventory,fixture.state,options)
            self.assertEqual(execute.call_count,1)

    def test_source_checkpoint_reuse_still_holds_open_choices_without_rerunning_audio(self):
        from test_bhakti_library_pass import SelectivePassTests, write_js
        import bhakti_library_source_pass as source_pass
        fixture = SelectivePassTests('runTest'); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.add_song('rehna-nahi-isa-desa')
        original_path = fixture.root/'songs/rehna-nahi-isa-desa/data.js'
        write_js(original_path, self.reader)
        (original_path.parent/'index.html').write_text('<script src="data.js"></script>')
        fixture.commit(); row = fixture.inventory()['songs'][0]
        row['plannedStages'] = ['source-merge','semantic-review']
        before = original_path.read_bytes()
        # Keep the three real open choices; this test isolates the no-target gate.
        self.fixture['reviews'][-2] = clean_review('verse-3-line-2')
        source_candidate = {'status':'accepted','reader':copy.deepcopy(self.reader),
                            'source_changed':False,'evidence':{}}
        with patch.object(source_pass,'run_source_candidate',return_value=source_candidate) as source, \
             patch.object(library.pipeline.gemini,'key',return_value='unused'), \
             patch.object(library.pipeline.gemini,'call',side_effect=self.provider):
            first = library.execute_song(fixture.root,row,fixture.state,self.options,self.deadline)
            second = library.execute_song(fixture.root,row,fixture.state,self.options,self.deadline)
        self.assertEqual(source.call_count,1)
        self.assertEqual(len(self.calls),2)
        for result in (first,second):
            self.assertEqual(result['status'],'unresolved')
            self.assertFalse(result['publicationEligible'])
            self.assertEqual(len(result['authorization']['pending_findings']),3)
            self.assertEqual(result['source']['status'],'accepted')
        self.assertEqual(original_path.read_bytes(),before)
        self.assertTrue((fixture.state/'songs/rehna-nahi-isa-desa/source-checkpoint.json').is_file())


if __name__ == '__main__': unittest.main()

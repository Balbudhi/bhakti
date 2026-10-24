"""Reviewed-design regressions: real callers/storage, authentic dictionary witnesses.

Only HTTP/model transports are synthetic. Their chosen senses are delivery controls,
not editorial truth or linguistic qualification. Never call a provider in this suite.
"""
import copy
import io
import json
import os
from pathlib import Path
import shutil
import time
import unittest
from unittest.mock import patch

import bhakti_pipeline as pipeline
import bhakti_source_discovery as discovery
import dictionary_corpus as corpus
import test_automatic_semantic_lexical as automatic
import test_source_discovery_callers as existing
from test_source_citation_witnesses import FIXTURE as REHNA

HERE = Path(__file__).parent
GLOSS = 'bhakti_word_glosses'
WRITER = 'bhakti_literal_translation'
REVIEW = 'bhakti_translation_review'


def source_packet(prompt):
    for marker in ('SOURCE GLOSS EVIDENCE:\n', 'SOURCE DISCOVERY EVIDENCE:\n'):
        if marker in prompt:
            return json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1])[0]
    return None


def compound_decisions(packet):
    quoted = ('vajrāng (˚ra+an˚), vulg. vajr-ang, bajr-ang, adj. & s.m. '
              'Having a hardy frame, hardy; — an epithet of Hauumān; — a robust or hardy man')
    return [{'target_id': target['id'], 'entry_id': eid,
             'status': 'matched', 'attested_form': 'bajr-ang', 'quotation': quoted,
             'relation_kind': 'compound_subentry', 'meaning_applied': 'having a hardy frame',
             'changes_gloss': False, 'form_explanation': '',
             'reason': 'Transport fixture: witnessed complete compound, not root-only derivation.'}
            for target in packet['targets'] for eid in target['candidate_entry_ids']]


class CaptureRequest(Exception):
    pass


class NativeBootstrap(unittest.TestCase):
    def setUp(self):
        self.case = automatic.AutomaticSemanticLexicalTests()
        self.case.setUp(); self.addCleanup(self.case.doCleanups)
        c = self.case
        c.lines = copy.deepcopy(REHNA['lines'])
        c.audit = {'packet': {'verified_lines': c.lines, 'metadata': {'languages': ['Hindi']},
            'performance_order': [{'line_id': line['id'], 'occurrence': 1} for line in c.lines]}}
        c.options.lexical_requested_spans = [{'line_id': 'verse-3-line-2',
            'word_indices': [2], 'surfaces': ['ṭhikānā'], 'reason': 'Resolve the actual dwelling/refuge sense.'}]
        c.options.source_discovery_max_requests = 0
        c.options.source_discovery_budget = discovery.configure_run_budget(c.root, time.time()+60, c.options)
        cache = Path(os.environ['BHAKTI_LEXICAL_SUPPORT_CACHE'])/'source-discovery'/'platts-hi'
        shutil.copytree(HERE/'fixtures/source_before_gloss/platts-hi', cache)
        self.captured = None

    def capture(self, *args, **kwargs):
        self.captured = {'prompt': args[2], 'schema': kwargs['response_schema']}
        raise CaptureRequest('Stop after first real glossary request is constructed.')

    def check_first_request(self, direct):
        c = self.case
        original = copy.deepcopy(c.audit)
        with patch.object(pipeline.gemini, 'call', side_effect=self.capture), \
             patch.object(pipeline.bhakti_lexical_producer, 'lookup_english_cached',
                          side_effect=AssertionError('English dictionary is downstream of source glossary')):
            with self.assertRaises(CaptureRequest):
                if direct: pipeline.gloss(c.song, c.audit, c.options)
                else: c.complete()
        packet = source_packet(self.captured['prompt'])
        self.assertIsNotNone(packet, 'Initial glossary must actually receive the requested native dictionary witness.')
        expected = REHNA['source_discovery']['entries'][0]['dictionary']['whole_entry_text']
        self.assertEqual(packet['entries'][0]['dictionary']['whole_entry_text'], expected)
        target = packet['targets'][0]
        self.assertEqual((target['line_id'], target['word_indices'], target['surfaces']),
                         ('verse-3-line-2', [2], ['ṭhikānā']))
        self.assertIn('source_discovery_decisions', self.captured['schema']['properties']['glosses']['items']['properties'])
        self.assertNotIn('TARGETED LEXICAL SUPPORT:', self.captured['prompt'])
        self.assertEqual(c.audit, original)
        budget = json.loads(Path(c.options.source_discovery_budget['path']).read_text())
        self.assertEqual(budget['requests_started'], 0)

    def test_first_complete_gloss_gets_exact_witness_before_english_lookup(self):
        self.check_first_request(False)

    def test_direct_gloss_uses_same_native_evidence_before_cache_lookup(self):
        self.check_first_request(True)

    def test_missing_budget_cannot_initialize_or_dispatch_in_preflight(self):
        c = self.case
        del c.options.source_discovery_budget
        with patch.object(pipeline.gemini, 'call', side_effect=self.capture), \
             patch.object(discovery, 'acquire_source_candidates', side_effect=AssertionError('Missing outer quota')):
            with self.assertRaises(CaptureRequest): pipeline.gloss(c.song, c.audit, c.options)
        self.assertTrue('source_discovery_budget_missing' in self.captured['prompt'], 'Missing caller quota must be delivered as an honest source gap.')

    def test_typed_context_reference_supplies_context_without_authorizing_neighbor_gloss(self):
        c = self.case
        target = 'verse-3-line-2'; neighbor = 'verse-3-line-1'
        c.options.semantic_full_source = copy.deepcopy(c.lines)
        c.audit['packet']['verified_lines'] = [line for line in c.lines if line['id'] == target]
        c.options.semantic_repair_feedback = [{'kind':'frame_relation', 'target_line_ids':[target],
            'references':[{'line_id':target, 'domain':'word_glosses', 'word_indices':[2], 'source_quote':'ठिकाना'},
                          {'line_id':neighbor, 'domain':'word_glosses', 'word_indices':[1], 'source_quote':'कबीर'}],
            'explanation':'Engineering scope control, not an editorial finding.',
            'evidence':'The neighbor is source context only.', 'needed_evidence':'', 'hold_reason':''}]
        before = copy.deepcopy(c.options.semantic_full_source)
        with patch.object(pipeline.gemini, 'call', side_effect=self.capture):
            with self.assertRaises(CaptureRequest):
                pipeline.bhakti_semantic_repair.routed_gloss(pipeline, c.song, c.audit, c.options)
        prompt = self.captured['prompt']
        rows = json.JSONDecoder().raw_decode(prompt.split('TARGET LYRICS (return these IDs only):\n',1)[1])[0]
        self.assertEqual([row['id'] for row in rows], [target])
        packet = source_packet(prompt)
        self.assertIsNotNone(packet)
        self.assertEqual({row['line_id'] for row in packet['targets']}, {target})
        self.assertEqual(c.options.semantic_full_source, before)
        self.assertTrue('कहत कबीर सुनो भाई साधो' in prompt, 'Context must remain available without a new output row.')


class DiscoveredBeforeWriter(unittest.TestCase):
    def setUp(self):
        self.fixture = existing.SourceDiscoveryCallerTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.case = self.fixture.case
        self.prompts = []
        self.new_query_after_refinement = False
        patcher = patch.object(pipeline.gemini, 'call', side_effect=self.transport)
        patcher.start(); self.addCleanup(patcher.stop)

    def transport(self, model, key, prompt, **kwargs):
        result = self.fixture.transport(model, key, prompt, **kwargs)
        self.prompts.append((kwargs['schema_name'], prompt))
        for row in result.get('packet', {}).get('reviews', []):
            row['component_judgments'] = {key: {'status': 'supported', 'reason': 'Canned transport control, not linguistic approval.'}
                for key in ('gloss', 'frame', 'english')}
        if 'word_gloss' in kwargs['schema_name']:
            packet = source_packet(prompt)
            if packet:
                for row in result['packet']['glosses']:
                    row['source_discovery_decisions'] = compound_decisions(packet)
                    if self.new_query_after_refinement:
                        row['lexical_queries'][0]['source_queries'] = ['bajra']
        return result

    def assert_reconciled(self):
        result = self.case.complete()
        self.assertEqual(self.case.kinds(), [GLOSS, GLOSS, WRITER, REVIEW],
            'A newly witnessed source entry requires glossary adjudication before the first writer, even if reviewer would pass.')
        refinement_prompt = self.case.calls[1]['prompt']
        self.assertTrue('SOURCE EVIDENCE ADJUDICATION TASK:\n' in refinement_prompt,
                        'Refinement must state the actual evidence-change task without inventing reviewer feedback.')
        task = json.JSONDecoder().raw_decode(refinement_prompt.split('SOURCE EVIDENCE ADJUDICATION TASK:\n',1)[1])[0]
        self.assertEqual(task['target_line_ids'], [self.case.lines[0]['id']])
        prior = json.JSONDecoder().raw_decode(refinement_prompt.split('PRIOR TARGET/REFERENCED GLOSS EVIDENCE:\n',1)[1])[0]
        saved = next(self.case.packets.glob('semantic-repair/**/gloss-ready.json'))
        self.assertEqual(prior, json.loads(saved.read_text())['packet']['glosses'])
        self.assertNotIn('REPAIR FEEDBACK:', refinement_prompt)
        self.assertNotIn('SOURCE EVIDENCE ADJUDICATION TASK:', self.case.calls[0]['prompt'])
        self.assertNotIn('SOURCE EVIDENCE ADJUDICATION TASK:', self.case.calls[2]['prompt'])
        packet = source_packet(refinement_prompt)
        self.assertIsNotNone(packet)
        self.assertEqual(packet['entries'][0]['dictionary']['whole_entry_text'],
                         source_packet(self.case.calls[2]['prompt'])['entries'][0]['dictionary']['whole_entry_text'])
        rows = result[0]['packet']['glosses']
        self.assertTrue(rows[0]['source_discovery_decisions'])
        self.assertIn('source_discovery_decisions', self.case.calls[2]['prompt'])
        return result

    def test_new_model_query_refines_gloss_before_writer_without_review_feedback(self):
        original = copy.deepcopy(self.case.audit)
        real_lookup = pipeline.bhakti_lexical_producer.lookup_english_cached
        def lookup(*args, **kwargs):
            self.assertEqual(self.fixture.gloss_count, 2,
                'English dictionary work must wait for the source-informed glossary refinement.')
            return real_lookup(*args, **kwargs)
        with patch.object(pipeline.bhakti_lexical_producer, 'lookup_english_cached', side_effect=lookup):
            result = self.assert_reconciled()
        self.assertEqual(self.case.audit, original)
        count = len(self.case.calls); http = len(self.fixture.http_calls)
        self.assertEqual(self.case.complete(), result)
        self.assertEqual(len(self.case.calls), count)
        self.assertEqual(len(self.fixture.http_calls), http)

    def test_same_entry_id_refreshed_content_refines_gloss_not_only_english(self):
        self.assert_reconciled(); count = len(self.case.calls)
        root = Path(os.environ['BHAKTI_LEXICAL_SUPPORT_CACHE'])/'source-discovery'/'platts-hi'
        manifest = root/'acquisition.json'; records = json.loads(manifest.read_text())
        record = next(r for r in records if r['query'] == 'वज्र')
        path = root/record['path']; raw = path.read_bytes()
        changed = raw.replace(b'thunderbolt', b'thunderbolt [changed fixture evidence]', 1)
        self.assertNotEqual(raw, changed)
        path.write_bytes(changed); record['sha256'] = corpus.sha(changed)
        manifest.write_text(json.dumps(records))
        result = self.case.complete()
        self.assertEqual(self.case.kinds()[count:], [GLOSS, WRITER, REVIEW])
        for call in self.case.calls[count:]: self.assertIn('[changed fixture evidence]', call['prompt'])
        count = len(self.case.calls)
        self.assertEqual(self.case.complete(), result); self.assertEqual(len(self.case.calls), count)

    def test_interrupted_after_refinement_reuses_durable_gloss_before_writer(self):
        original = pipeline.semantic_write_json
        stopped = False
        def save(path, value):
            nonlocal stopped
            original(path, value)
            rows = value.get('packet', {}).get('glosses', []) if isinstance(value, dict) else []
            if (rows and rows[0].get('source_discovery_decisions') and
                    value.get('source_gloss_receipt') and value.get('fingerprint') and not stopped):
                stopped = True
                raise KeyboardInterrupt('After durable source-informed glossary, before writer')
        with patch.object(pipeline, 'semantic_write_json', side_effect=save):
            with self.assertRaises(KeyboardInterrupt): self.case.complete()
        self.assertTrue(stopped)
        count = self.fixture.gloss_count
        self.assertEqual(count, 2)
        self.assertNotIn(WRITER, self.case.kinds())
        self.case.complete()
        self.assertEqual(self.fixture.gloss_count, count, 'Resume must not pay for saved source adjudication twice.')
        self.assertEqual(self.case.kinds()[-2:], [WRITER, REVIEW])

    def test_new_entry_after_one_refinement_holds_before_writer(self):
        self.new_query_after_refinement = True
        real_lookup = pipeline.bhakti_lexical_producer.lookup_english_cached
        with patch.object(pipeline.bhakti_lexical_producer, 'lookup_english_cached', wraps=real_lookup) as english:
            with self.assertRaisesRegex((ValueError, RuntimeError), 'source|ground|refin|evidence'):
                self.case.complete()
        self.assertEqual(english.call_count, 0, 'Unadjudicated source must not spend English discovery work.')
        self.assertEqual(self.case.kinds(), [GLOSS, GLOSS])
        self.assertFalse((self.case.packets/'semantic-acceptance.json').exists())
        self.assertEqual(self.fixture.http_calls, ['बजरंग', 'वज्र', 'bajra'])

    def test_missing_relation_decision_cannot_become_grounded_gloss(self):
        original = self.transport
        def omit(*args, **kwargs):
            result = original(*args, **kwargs)
            for row in result.get('packet', {}).get('glosses', []):
                row.pop('source_discovery_decisions', None)
            return result
        with patch.object(pipeline.gemini, 'call', side_effect=omit):
            with self.assertRaisesRegex((ValueError, RuntimeError), 'source|decision|ground'):
                self.case.complete()
        self.assertEqual(self.case.kinds(), [GLOSS, GLOSS])
        self.assertFalse((self.case.packets/'semantic-acceptance.json').exists())

    def test_actual_refinement_preserves_locked_target_english_and_retained_neighbor(self):
        import bhakti_library_source_pass as source
        c = self.case; target_id = c.lines[0]['id']
        c.options.model = c.options.pro_model = __import__('bhakti_model_routes').FLASH_MODEL
        locked = 'Victory! Victory! Victory! with adamantine limbs, strong!'
        baseline = {'version':1, 'songs':{'fixture':{'policy':'preserve_english',
            'englishSha256':'a'*64, 'plainEnglishByLine':{target_id:locked}}}}
        (c.root/'data/editorial_baselines.json').write_text(json.dumps(baseline))
        neighbor = copy.deepcopy(c.lines[0]); neighbor['id'] = 'retained-neighbor'
        retained = copy.deepcopy(self.fixture.reader['SONG_LINES'][target_id])
        plan = {'lines':[neighbor, *copy.deepcopy(c.lines)], 'new_target_ids':[target_id],
            'performance_order':[{'line_id':neighbor['id'], 'occurrence':1},
                                 {'line_id':target_id, 'occurrence':1}],
            'reuse_by_id':{neighbor['id']:retained}}
        original = copy.deepcopy(plan)
        result = source.process_new_targets(c.song, plan, {'languages':['Hindi']}, c.options,
                                             c.root/'owner-routes', time.time()+60)
        self.assertEqual(c.kinds(), [GLOSS, GLOSS, WRITER, REVIEW])
        self.assertEqual(result['translations']['packet']['translations'][0]['literal_english'], locked)
        self.assertEqual(plan, original)
        for call in c.calls:
            if 'word_gloss' in call['kind']:
                rows = json.JSONDecoder().raw_decode(call['prompt'].split('TARGET LYRICS (return these IDs only):\n',1)[1])[0]
                self.assertEqual([row['id'] for row in rows], [target_id])
        self.assertTrue('Hail, hail, hail' in c.calls[-1]['prompt'], 'Preserved neighbor remains available as context.')
        self.assertFalse((c.song/'data.js').exists())


class EvidenceContinuity(unittest.TestCase):
    def setUp(self):
        self.case = automatic.AutomaticSemanticLexicalTests()
        self.case.setUp(); self.addCleanup(self.case.doCleanups)
        c = self.case
        c.lines[0]['sourceWords'] = [{'text': 'वज्र', 'wordIndices': [0]}]
        c.options.source_discovery_max_requests = 0
        c.options.source_discovery_budget = discovery.configure_run_budget(c.root, time.time()+60, c.options)
        cache = Path(os.environ['BHAKTI_LEXICAL_SUPPORT_CACHE'])/'source-discovery'/'platts-hi'
        shutil.copytree(existing.FIX, cache)
        plan = discovery.source_lookup_plan(c.lines,
            [{'line_id':'v', 'word_indices':[0], 'surfaces':['vajra'], 'source_queries':[]}], ['Hindi'])
        self.packet = discovery.acquire_source_candidates(plan, cache.parent,
            run_budget=c.options.source_discovery_budget)
        c.options.automatic_source_discovery = copy.deepcopy(self.packet)
        c.options.automatic_source_discovery_identity = pipeline.bhakti_lexical_support.content_digest(self.packet)

    def test_native_bootstrap_survives_bound_proposal_omission_in_actual_english_producer(self):
        c = self.case
        original = c.transport
        def grounded(*args, **kwargs):
            result = original(*args, **kwargs)
            if 'word_gloss' in kwargs['schema_name']:
                target = self.packet['targets'][0]; entry = self.packet['entries'][0]
                result['packet']['glosses'][0]['source_discovery_decisions'] = [{
                    'target_id':target['id'], 'entry_id':entry['entry_id'], 'status':'matched',
                    'attested_form':'वज्र', 'quotation':entry['dictionary']['whole_entry_text'],
                    'relation_kind':'exact_form', 'meaning_applied':'adamantine',
                    'changes_gloss':False, 'form_explanation':'',
                    'reason':'Canned contextual adjective control; source witness is authentic.'}]
            return result
        with patch.object(pipeline.gemini, 'call', side_effect=grounded):
            gloss = pipeline.gloss(c.song, c.audit, c.options)
        # The curated vajra binding means discovery.prepare skips this proposal.
        # English retrieval must still receive the exact existing native packet.
        producer = pipeline.bhakti_lexical_producer
        with patch.object(producer, 'produce_support', wraps=producer.produce_support) as actual:
            local, _ = producer.prepare_translation(c.song, c.audit, gloss, c.options)
        delivered = actual.call_args.kwargs['source_discovery']
        self.assertIsNotNone(delivered, 'Source evidence used before gloss must reach subsequent actual English retrieval.')
        self.assertEqual(delivered['entries'], self.packet['entries'])
        self.assertEqual(local.automatic_source_discovery['targets'], self.packet['targets'])

    def test_authenticated_loss_of_last_entry_invalidates_old_source_gloss_receipt(self):
        old = {'packet':{'glosses':[{'id':'v'}]},
               'source_gloss_receipt':discovery.source_gloss_receipt(self.packet)}
        refreshed = copy.deepcopy(self.packet)
        refreshed['entries'] = []; refreshed['evidence'] = []; refreshed['entry_evidence_ids'] = {}
        refreshed['targets'][0]['candidate_entry_ids'] = []
        refreshed['targets'][0]['observations'][0]['status'] = 'witnessed_miss'
        refreshed['targets'][0]['observations'][0]['witness_sha256'] = 'a'*64
        merged = discovery.merge_evidence(self.packet, refreshed)
        self.assertEqual(merged['entries'], [])
        self.assertEqual(discovery.pending_gloss_lines(merged, old), ['v'],
                         'Loss of authenticated evidence cannot leave the old grounded receipt current.')

    def test_expired_narrow_deadline_does_not_dispatch_source_http_or_renew_outer_quota(self):
        c = self.case
        # Remove the cached entry so a real acquisition attempt would be required.
        cache = Path(os.environ['BHAKTI_LEXICAL_SUPPORT_CACHE'])/'source-discovery'/'platts-hi'
        shutil.rmtree(cache)
        c.options.semantic_deadline_at = time.time()-60
        c.options.lexical_requested_spans = [{'line_id':'v','word_indices':[0],
            'surfaces':['vajra'],'reason':'Check actual source entry.'}]
        c.options.source_discovery_max_requests = 2
        c.options.source_discovery_budget = discovery.configure_run_budget(c.root/'later-budget', time.time()+60, c.options)
        with patch.object(corpus, 'acquire_queries', side_effect=AssertionError('Expired semantic deadline must prevent HTTP')):
            local = pipeline.bhakti_lexical_producer.prepare_gloss_source(c.lines, ['Hindi'], c.options)
        self.assertTrue(any(gap['kind'] == 'source_discovery_deadline' for gap in local.automatic_source_discovery['gaps']))
        state = json.loads(Path(c.options.source_discovery_budget['path']).read_text())
        self.assertEqual(state['requests_started'], 0)

    def test_changed_known_native_witness_refines_only_its_row_in_multirow_completion(self):
        c = self.case
        # Let the native helper materialize each call from witnessed cache, not a
        # manually retained options packet, so the outer glossary key truly changes.
        del c.options.automatic_source_discovery; del c.options.automatic_source_discovery_identity
        c.options.lexical_requested_spans = [{'line_id':'v','word_indices':[0],
            'surfaces':['vajra'],'reason':'Check the native target.'}]
        c.lines.append({**copy.deepcopy(c.lines[0]), 'id':'q'})
        c.audit['packet']['performance_order'].append({'line_id':'q','occurrence':1})
        original = c.transport; targets_seen = []
        def transport(*args, **kwargs):
            prompt = args[2]; kind = kwargs['schema_name']
            value = original(*args, **kwargs)
            if 'word_gloss' in kind:
                targets = json.JSONDecoder().raw_decode(prompt.split('TARGET LYRICS (return these IDs only):\n',1)[1])[0]
                ids = [row['id'] for row in targets]; targets_seen.append(ids)
                packet = source_packet(prompt)
                v = value['packet']['glosses'][0]
                v['lexical_queries'][0]['source_queries'] = ['unused-fixture-alias']
                entry = packet['entries'][0]; target = packet['targets'][0]
                v['source_discovery_decisions'] = [{'target_id':target['id'],'entry_id':entry['entry_id'],
                    'status':'matched','attested_form':'वज्र','quotation':entry['dictionary']['whole_entry_text'],
                    'relation_kind':'exact_form','meaning_applied':'adamantine','changes_gloss':False,
                    'form_explanation':'','reason':'Canned source transport control.'}]
                if 'q' in ids:
                    q = copy.deepcopy(v); q['id']='q'; q['lexical_queries']=[]; q['source_discovery_decisions']=[]
                    value['packet']['glosses'].append(q)
            elif kind == WRITER:
                packet = source_packet(prompt); entry = packet['entries'][0]; target = packet['targets'][0]
                row = value['packet']['translations'][0]
                row['source_discovery_decisions'] = [{'target_id':target['id'],'entry_id':entry['entry_id'],
                    'status':'matched','attested_form':'वज्र','quotation':entry['dictionary']['whole_entry_text'],
                    'relation_kind':'exact_form','meaning_applied':'adamantine','changes_gloss':False,
                    'form_explanation':'','reason':'Canned source transport control.'}]
                q = copy.deepcopy(row); q['id']='q'; q['source_discovery_decisions']=[]; q.pop('wording_decisions',None)
                value['packet']['translations'].append(q)
            elif kind == REVIEW:
                q = copy.deepcopy(value['packet']['reviews'][0]); q['id']='q'; value['packet']['reviews'].append(q)
            return value
        with patch.object(pipeline.gemini,'call',side_effect=transport):
            first = c.complete()
            old_neighbor = copy.deepcopy(first[0]['packet']['glosses'][1])
            root = Path(os.environ['BHAKTI_LEXICAL_SUPPORT_CACHE'])/'source-discovery'/'platts-hi'
            manifest = root/'acquisition.json'; records = json.loads(manifest.read_text())
            record = next(row for row in records if row['query']=='वज्र')
            path = root/record['path']; changed = path.read_bytes().replace(b'thunderbolt',b'thunderbolt [new witnessed context]',1)
            path.write_bytes(changed); record['sha256']=corpus.sha(changed); manifest.write_text(json.dumps(records))
            renewed = c.complete()
            calls = len(c.calls)
            with patch.object(discovery.time, 'time', return_value=c.options.source_discovery_budget['deadline_at']+1):
                self.assertEqual(c.complete(), renewed)
            self.assertEqual(len(c.calls), calls, 'Budget-gap becoming deadline-gap is not new dictionary meaning.')
        self.assertEqual(targets_seen, [['v','q'], ['v']], 'Changed native evidence must not repurchase unaffected glossary rows.')
        self.assertEqual(renewed[0]['packet']['glosses'][1], old_neighbor)


class HistoricalSourceGate(unittest.TestCase):
    def setUp(self):
        self.fixture = DiscoveredBeforeWriter()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.case = self.fixture.case
        import bhakti_model_routes as routes
        self.case.options.model = routes.FLASH_MODEL
        self.case.options.pro_model = routes.FLASH_MODEL
        self.frozen = json.loads((HERE/'fixtures/source_before_gloss/legacy-source-acceptance.json').read_text())
        self.route = self.case.root/'historical-routes'
        for relative, data in self.frozen['files'].items():
            path = self.route/relative; path.parent.mkdir(parents=True, exist_ok=True)
            # Relocate only private traversal paths. Original candidate bytes/hashes
            # remain identical; enclosing route payload hashes reflect that path change.
            encoded = json.dumps(data, ensure_ascii=False).replace(self.frozen['original_root'], str(self.route))
            path.write_text(encoded)
        state_path = next(self.route.rglob('route-state.json'))
        state = json.loads(state_path.read_text())
        state['accepted_sha256'] = routes._digest(json.loads((state_path.parent/'accepted-result.json').read_text()))
        for index, attempt in enumerate(state['attempts']):
            candidate = state_path.parent/('flash' if index == 0 else 'pro')/'candidate.json'
            attempt['candidate_sha256'] = routes._digest(json.loads(candidate.read_text()))
        state_path.write_text(json.dumps(state))
        # The ordinary reader validates the restored storage before the tested caller.
        routes.read_unit_cache(state_path)

    def run_target(self):
        import bhakti_library_source_pass as source
        return source.process_new_targets(self.case.song, copy.deepcopy(self.frozen['plan']),
            {'languages':['Hindi']}, self.case.options, self.route, time.time()+60)

    def test_authentic_old_acceptance_cannot_early_return_without_source_gloss_grounding(self):
        self.run_target()
        self.assertEqual(self.case.kinds(), [GLOSS, WRITER, REVIEW],
            'Authenticate the old glossary as a draft, then source-adjudicate before renewed English; no initial reconstruction.')
        self.assertIsNotNone(source_packet(self.case.calls[0]['prompt']))
        count = len(self.case.calls)
        self.run_target(); self.assertEqual(len(self.case.calls), count)

    def test_malformed_present_source_receipt_is_hold_not_missing_legacy_grounding(self):
        import bhakti_model_routes as routes
        result_path = next(self.route.rglob('accepted-result.json'))
        state_path = result_path.parent/'route-state.json'
        result = json.loads(result_path.read_text())
        result['glosses']['source_gloss_receipt'] = {'version':1, 'targets':'malformed fixture'}
        # Integrity-bound malformed old artifact models an earlier weak validator;
        # it is distinct from honest pre-feature absence, never a production adoption.
        result_path.write_text(json.dumps(result, ensure_ascii=False))
        state = json.loads(state_path.read_text()); state['accepted_sha256'] = routes._digest(result)
        state_path.write_text(json.dumps(state))
        with self.assertRaisesRegex((ValueError, RuntimeError), 'source|receipt|ground'):
            self.run_target()
        self.assertEqual(self.case.calls, [])

    def test_native_bootstrap_cannot_hide_prior_unknown_historical_route(self):
        target = self.case.lines[0]['id']
        self.case.options.semantic_repair_feedback = [{'kind':'gloss_sense','target_line_ids':[target],
            'references':[{'line_id':target,'domain':'word_glosses','word_indices':[3], 'source_quote':'बजरंग'}],
            'explanation':'Fixture known-source obligation.', 'evidence':'Native exact lookup.',
            'needed_evidence':'','hold_reason':''}]
        path = next(self.route.rglob('route-state.json'))
        state = json.loads(path.read_text())
        state['status'] = 'unresolved'; state['reason'] = 'unknown-outcome'
        state['attempts'][-1].update(status='transport-failed', category='unknown-outcome', worker_terminated=True)
        path.write_text(json.dumps(state)); original = path.read_bytes()
        with self.assertRaisesRegex((ValueError, RuntimeError), 'unknown|unresolved'):
            self.run_target()
        self.assertEqual(self.case.calls, [])
        self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()

"""Supplied assistant meanings are candidates, never fabricated provider receipts.

Real coordinator, validators, saved state, writer/reviewer and generator run.
Only provider transport is canned; this qualifies plumbing, not song quality.
"""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import bhakti_pipeline as pipeline
import bhakti_semantic_repair as semantic
import bhakti_intake_run as intake
import test_automatic_semantic_repair as fixtures
from test_sense_decisions import decisions_for


class SuppliedGlossTests(unittest.TestCase):
    patch = fixtures.AutomaticRepairTests.patch
    write = fixtures.AutomaticRepairTests.write
    rows = fixtures.AutomaticRepairTests.rows
    translation = fixtures.AutomaticRepairTests.translation
    issue = fixtures.AutomaticRepairTests.issue
    review = fixtures.AutomaticRepairTests.review
    payload = staticmethod(fixtures.AutomaticRepairTests.payload)
    provider = fixtures.AutomaticRepairTests.provider
    state = fixtures.AutomaticRepairTests.state

    def setUp(self):
        fixtures.AutomaticRepairTests.setUp(self)
        self.lines.append({**self.lines[0], 'id': 'b'})
        self.audit['packet']['uncertainties'] = []
        self.baseline = 'My breath abandons me.'
        self.authored = self.rows(self.lines, repaired=True)
        for name in ('song_tag_overrides.json', 'source_credits.json'):
            (self.root/'data'/name).write_bytes((Path(pipeline.__file__).parent.parent/'data'/name).read_bytes())
        for row in self.authored:
            row['grammar_note'] = 'The feminine noun breath governs the verb; I am its object.'
        self.author = self.root/'author.json'
        self.author.write_text(json.dumps({'rows': self.authored}))
        self.review_file = self.root/'editorial-review.json'
        self.review_file.write_text(json.dumps({'subject': self.ref(self.author),
            'note': 'Fixture editorial assessment; genuine independent review is still required.'}))
        self.document = {
            'version': 1, 'origin': 'assistant-editorial', 'slug': 'fixture',
            'source_sha256': semantic.digest(semantic.source_evidence(pipeline, self.song, self.audit)),
            'source_languages': ['Hindi'],
            'policy_sha256': semantic.digest(pipeline.translation_policy_payload()),
            'gloss_contract_version': pipeline.GLOSS_CONTRACT_VERSION,
            'provenance': [{'role': 'author', **self.ref(self.author)},
                           {'role': 'review', **self.ref(self.review_file)}],
            'packet': {'glosses': self.authored}}
        self.document_path = self.root/'provided-gloss.json'
        self.english = self.root/'english.json'
        self.english.write_text(json.dumps({row['id']: self.baseline for row in self.lines}))
        self.job = {'slug': 'fixture', 'source': 'unused', 'title': 'Fixture',
                    'languages': ['Hindi'], 'providedTranslation': str(self.english)}
        self.save_document()

    @staticmethod
    def ref(path):
        return {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def save_document(self):
        self.document_path.write_text(json.dumps(self.document, ensure_ascii=False))
        self.job['providedGlosses'] = self.ref(self.document_path)

    def complete(self):
        return pipeline.complete_semantics(self.song, self.audit, self.job, self.options)

    def assert_no_gloss_calls(self):
        self.assertFalse(any('word_gloss' in call['name'] for call in self.calls), [c['name'] for c in self.calls])

    def test_real_review_and_generator_preserve_supplied_rows_and_english(self):
        gloss, translated = self.complete()
        self.assert_no_gloss_calls()
        self.assertEqual(gloss['packet']['glosses'], self.authored)
        self.assertEqual(gloss['origin'], 'assistant-editorial')
        for key in ('provider', 'resolved_model', 'usage'):
            self.assertNotIn(key, gloss)
        self.assertEqual(sum(c['name'] == 'bhakti_translation_review' for c in self.calls), 1)
        self.assertTrue(all(r['literal_english'] == self.baseline for r in translated['packet']['translations']))
        timing = {'sequence': [{'ref': 'a', 'start': 1, 'end': 2},
                               {'ref': 'b', 'start': 2, 'end': 3}], 'validation_errors': []}
        reader = pipeline.generate(self.song, self.job, {}, self.audit, timing, gloss, translated,
                                   prepare_only=True, write_catalogue_after=False)
        for row in self.authored:
            actual = reader['SONG_LINES'][row['id']]
            self.assertEqual([w['gloss'] for w in actual['words']],
                             [w['gloss'] for w in row['word_glosses']])
            self.assertEqual(actual['grammarNote'], row['grammar_note'])
        calls = len(self.calls)
        self.assertEqual(self.complete(), (gloss, translated))
        self.assertEqual(len(self.calls), calls)
        (self.packets/'semantic-acceptance.json').unlink()
        with self.assertRaises(RuntimeError):
            pipeline.generate(self.song, self.job, {}, self.audit, timing, gloss, translated,
                              prepare_only=True, write_catalogue_after=False)

    def test_invalid_source_rows_policy_and_provenance_fail_before_calls(self):
        original = copy.deepcopy(self.document)
        mutations = {
            'missing-row': lambda d: d['packet']['glosses'].pop(),
            'reordered': lambda d: d['packet']['glosses'].reverse(),
            'duplicate': lambda d: d['packet']['glosses'][1].update(id='a'),
            'wrong-token': lambda d: d['packet']['glosses'][0]['word_glosses'][0].update(roman='terī'),
            'omitted-particle': lambda d: d['packet']['glosses'][0]['word_glosses'].pop(),
            'missing-frame': lambda d: d['packet']['glosses'][0].pop('semantic_frame'),
            'missing-decision': lambda d: d['packet']['glosses'][0]['sense_decisions'].pop(),
            'uncertainty': lambda d: d['packet']['glosses'][0].update(uncertainty='Unresolved agency'),
            'stale-source': lambda d: d.update(source_sha256='0'*64),
            'stale-policy': lambda d: d.update(policy_sha256='0'*64),
            'wrong-language': lambda d: d.update(source_languages=['Sanskrit']),
            'spoofed-provider': lambda d: d.update(provider='openrouter', resolved_model=self.options.model),
            'review-tamper': lambda d: d['provenance'][1].update(sha256='0'*64)}
        for name, mutate in mutations.items():
            with self.subTest(case=name):
                self.document = copy.deepcopy(original); mutate(self.document); self.save_document()
                with self.assertRaises((ValueError, RuntimeError)):
                    self.complete()
                self.assertEqual(self.calls, [])
                self.assertFalse((self.packets/'semantic-acceptance.json').exists())

    def test_real_reviewer_rejects_wrong_agency_without_regenerating_locked_rows(self):
        # Structurally sound but linguistically wrong: only the actual reviewer rejects it.
        for row in self.document['packet']['glosses']:
            row['semantic_frame']['agent'] = 'I'
        self.save_document()
        with self.assertRaises(RuntimeError):
            self.complete()
        self.assert_no_gloss_calls()
        self.assertTrue(any(c['name'] == 'bhakti_translation_review' for c in self.calls))
        self.assertFalse((self.packets/'semantic-acceptance.json').exists())
        self.assertIn('frame_relation', json.dumps(self.state()))
        count = len(self.calls)
        with self.assertRaises(RuntimeError): self.complete()
        self.assertEqual(len(self.calls), count, 'same held input must not reset a paid attempt')

    def test_supplied_hash_and_review_closure_are_frozen_before_bounded_intake(self):
        frozen, _ = intake._inputs(self.root, [self.job])
        self.assertIn(self.ref(self.review_file)['sha256'], json.dumps(frozen))
        before = copy.deepcopy(frozen)
        self.review_file.write_text('changed editorial evidence')
        with self.assertRaises((ValueError, RuntimeError)):
            intake._inputs(self.root, [self.job])
        with self.assertRaises((ValueError, RuntimeError)): self.complete()
        self.assertEqual(self.calls, [])
        self.assertEqual(frozen, before)

    def test_falsey_present_input_never_falls_back_to_generated_glosses(self):
        for value in (None, {}, '', False):
            with self.subTest(value=value):
                self.job['providedGlosses'] = value
                with self.assertRaises((ValueError, RuntimeError, OSError)):
                    intake._inputs(self.root, [self.job])
                with self.assertRaises((ValueError, RuntimeError)):
                    self.complete()
                self.assertEqual(self.calls, [])

    def test_supplied_gloss_requires_locked_english_instead_of_model_authorship(self):
        self.job.pop('providedTranslation')
        with self.assertRaises((ValueError, RuntimeError)):
            self.complete()
        self.assertEqual(self.calls, [])

    def test_changed_document_cannot_reuse_accepted_pair(self):
        self.complete(); count = len(self.calls)
        self.document['packet']['glosses'][0]['grammar_note'] += ' Changed claim.'
        self.document_path.write_text(json.dumps(self.document))  # keep old job SHA
        with self.assertRaises((ValueError, RuntimeError)): self.complete()
        self.assertEqual(len(self.calls), count)

    def test_changed_reviewed_version_cannot_reset_interrupted_attempt(self):
        self.transport_failure = True
        with self.assertRaises(RuntimeError): self.complete()
        state_path = self.packets/'semantic-repair-state.json'
        before = state_path.read_bytes(); count = len(self.calls)
        self.document['packet']['glosses'][0]['grammar_note'] += ' Revised editorial claim.'
        self.author.write_text(json.dumps({'rows': self.document['packet']['glosses']}))
        self.review_file.write_text(json.dumps({'subject': self.ref(self.author), 'note': 'Revised review.'}))
        self.document['provenance'] = [{'role': 'author', **self.ref(self.author)},
                                       {'role': 'review', **self.ref(self.review_file)}]
        self.save_document()  # a genuinely new reviewed document/hash, not stale SHA
        self.transport_failure = False
        with self.assertRaises(RuntimeError): self.complete()
        self.assertEqual(len(self.calls), count)
        self.assertEqual(state_path.read_bytes(), before, 'New input must not reset interrupted history/deadline.')

    def test_saved_supplied_seed_tamper_blocks_resume(self):
        self.transport_failure = True
        with self.assertRaises(RuntimeError): self.complete()
        self.assert_no_gloss_calls()
        paths = list(self.packets.glob('semantic-repair/*/adopted-seeds.json'))
        self.assertEqual(len(paths), 1)
        saved = json.loads(paths[0].read_text())
        saved['payload']['artifacts']['04-glosses.json']['packet']['glosses'][0]['grammar_note'] = 'tampered'
        saved['sha256'] = semantic.digest(saved['payload'])
        paths[0].write_text(json.dumps(saved))
        count = len(self.calls)
        with self.assertRaises(RuntimeError): self.complete()
        self.assertEqual(len(self.calls), count)
        self.assertFalse((self.packets/'semantic-acceptance.json').exists())


class AutomaticSuppliedGlossTests(unittest.TestCase):
    def document_job(self, case, rows, english):
        author = case.root/'author.json'; author.write_text(json.dumps(rows))
        review = case.root/'review.json'; review.write_text(json.dumps({'subject': SuppliedGlossTests.ref(author)}))
        document = {'version': 1, 'origin': 'assistant-editorial', 'slug': 'fixture',
            'source_sha256': semantic.digest(semantic.source_evidence(pipeline, case.song, case.audit)),
            'source_languages': case.audit['packet']['metadata']['languages'],
            'policy_sha256': semantic.digest(pipeline.translation_policy_payload()),
            'gloss_contract_version': pipeline.GLOSS_CONTRACT_VERSION,
            'provenance': [{'role': 'author', **SuppliedGlossTests.ref(author)},
                           {'role': 'review', **SuppliedGlossTests.ref(review)}],
            'packet': {'glosses': rows}}
        path = case.root/'supplied.json'; path.write_text(json.dumps(document))
        baseline = case.root/'english.json'; baseline.write_text(json.dumps(english))
        return {'slug': 'fixture', 'source': 'unused', 'providedGlosses': SuppliedGlossTests.ref(path),
                'providedTranslation': str(baseline)}

    def test_real_automatic_lexical_view_keeps_authored_rows_and_skips_gloss_generation(self):
        import test_automatic_semantic_lexical as automatic
        c = automatic.AutomaticSemanticLexicalTests(); c.setUp(); self.addCleanup(c.doCleanups)
        row = copy.deepcopy(c.gloss[0])
        row['word_glosses'][0]['gloss'] = 'adamantine'
        row.update(grammar_note='An adjective expressing diamond-like hardness.', uncertainty='',
                   semantic_frame={k: '' for k in pipeline.SEMANTIC_FRAME_FIELDS},
                   sense_decisions=decisions_for(c.lines, ['Hindi'])['v'])
        job = self.document_job(c, [row], {'v': 'Adamantine'})
        gloss, english = pipeline.complete_semantics(c.song, c.audit, job, c.options)
        self.assertEqual(c.kinds(), ['bhakti_literal_translation', 'bhakti_translation_review'])
        self.assertEqual(gloss['packet']['glosses'], [row])
        self.assertNotIn('support_decisions', gloss['packet']['glosses'][0])
        self.assertTrue(english['writer_gloss_binding'])
        self.assertEqual(english['packet']['translations'][0]['literal_english'], 'Adamantine')

    def test_actual_pending_witness_holds_before_hidden_gloss_refinement(self):
        import test_source_discovery_callers as sources
        f = sources.SourceDiscoveryCallerTests(); f.setUp(); self.addCleanup(f.doCleanups)
        c = f.case
        c.lines[:] = [{key: c.lines[0][key] for key in ('id', 'source_text', 'roman', 'sourceLanguage', 'kind')}]
        line = c.lines[0]; tokens = pipeline.bhakti_translation_policy.word_tokens(line)
        row = {'id': line['id'], 'word_glosses': [
            {'roman': token, 'gloss': meaning, 'concept_key': '', 'preserve_in_english': False}
            for token, meaning in zip(tokens, ['victory', 'victory', 'victory', 'with adamantine limbs', 'strong'])],
            'grammar_note': 'An epithet addressing Hanumān.', 'uncertainty': '',
            'semantic_frame': {k: '' for k in pipeline.SEMANTIC_FRAME_FIELDS},
            'sense_decisions': decisions_for(c.lines, ['Hindi'])[line['id']],
            'lexical_queries': [{'word_indices': [3], 'surfaces': ['bajaraṅga'],
                'reason': 'Check witnessed whole compound.', 'source_entry_ids': [], 'source_queries': ['वज्र'],
                'english_candidates': [{'expression': 'with adamantine limbs', 'kind': 'compositional_phrase',
                                        'english_lemmas': ['adamantine']}]}], 'lexical_query_gaps': []}
        job = self.document_job(c, [row], {line['id']: 'Victory! Victory! Victory! With adamantine limbs, strong!'})
        with self.assertRaises(RuntimeError):
            pipeline.complete_semantics(c.song, c.audit, job, c.options)
        self.assertEqual(c.kinds(), [], 'New witnessed source evidence must hold supplied words, not regenerate them.')
        self.assertTrue(f.http_calls, 'Actual source acquisition must expose the pending witness.')
        self.assertFalse((c.packets/'semantic-acceptance.json').exists())


if __name__ == '__main__': unittest.main()

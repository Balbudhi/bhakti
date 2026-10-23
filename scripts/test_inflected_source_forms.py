"""Performed reader forms and authentic dictionaries; provider answers are controls."""
import copy
import io
import json
import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import bhakti_pipeline as pipeline
import bhakti_source_discovery as discovery
import test_automatic_semantic_lexical as fixture
from test_sense_decisions import decisions_for

FIX = Path(__file__).parent / 'fixtures/indic-dictionaries'


class InflectedSourceForms(unittest.TestCase):
    def run_case(self, language, *, fresh=False, bad=False, bad_form=False, disagreement=False):
        c = fixture.AutomaticSemanticLexicalTests(); c.setUp(); self.addCleanup(c.doCleanups)
        record = next(r for r in json.loads((FIX/'performed-lines.json').read_text()) if r['language'] == language)
        line = copy.deepcopy(record['line'])
        if fresh:
            line = {key: line[key] for key in ('id', 'source_text', 'roman', 'sourceLanguage', 'kind')}
        c.lines = [line]
        tokens = pipeline.bhakti_translation_policy.word_tokens(line)
        index = tokens.index(record['term'])
        c.audit = {'packet': {'verified_lines': [line], 'metadata': {'languages': [language]},
            'performance_order': [{'line_id': line['id'], 'occurrence': 1}]}}
        before = copy.deepcopy(c.audit)
        Path(os.environ['BHAKTI_LEXICON_PATH']).write_text('{"entries":[]}')
        sources = {r['query']: r for r in json.loads((FIX/'research-responses.json').read_text())}
        requests, calls, packets = [], [], []
        def opener(url, timeout):
            query = parse_qs(urlparse(url).query)['qs'][0]; requests.append(query)
            return io.BytesIO((FIX/sources[query]['path']).read_bytes())
        c.options.source_discovery_opener = opener
        c.options.source_discovery_budget = discovery.configure_run_budget(c.root, time.time()+60, c.options)
        def parse(prompt, label):
            return json.JSONDecoder().raw_decode(prompt.split(label+'\n', 1)[1])[0]
        def transport(model, key, prompt, **kw):
            kind = kw['schema_name']; calls.append(kind)
            if kind == 'bhakti_word_glosses':
                row = {'id': line['id'], 'word_glosses': [{'roman': token, 'gloss': 'contextual meaning',
                    'concept_key': '', 'preserve_in_english': False} for token in tokens],
                    'semantic_frame': {field: '' for field in pipeline.SEMANTIC_FRAME_FIELDS},
                    'grammar_note': '', 'uncertainty': '', 'sense_decisions': decisions_for([line], [language])[line['id']],
                    'lexical_queries': [{'word_indices': [index], 'surfaces': [record['term']],
                        'reason': 'Check the performed inflection, preserving its full grammatical contribution.',
                        'source_entry_ids': [], 'source_queries': [record['head']],
                        'english_candidates': [{'expression': 'contextual meaning', 'kind': 'compositional_phrase', 'english_lemmas': []}]}],
                    'lexical_query_gaps': []}
                return {'packet': {'glosses': [row]}}
            found = parse(prompt, 'SOURCE DISCOVERY EVIDENCE:')
            packets.append(found)
            self.assertTrue(found['entries'])
            self.assertEqual({e['language'] for e in found['entries']}, {pipeline.bhakti_translation_policy.lexical_retrieval.line_language(line, [language])})
            if kind == 'bhakti_translation_review':
                self.assertIn('form_explanation', prompt)
                first = disagreement and calls.count(kind) == 1
                issues = [{'kind': 'frame_relation', 'target_line_ids': [line['id']],
                    'references': [{'line_id': line['id'], 'domain': 'word_glosses', 'word_indices': [index], 'source_quote': line['source_text']}],
                    'explanation': 'Synthetic objection: the ending contribution needs contextual reconstruction.',
                    'evidence': 'The complete source word includes an ending beyond the dictionary lemma.',
                    'needed_evidence': '', 'hold_reason': ''}] if first else []
                return {'packet': {'reviews': [{'id': line['id'], 'passes': not first, 'human_review_recommended': first,
                    'agency_preserved': True, 'imagery_preserved': True, 'all_meaning_accounted_for': True,
                    'unsupported_additions': [], 'material_choice': '', 'reason': 'Transport control only.', 'issues': issues}]}}
            target = parse(prompt, 'TARGETED LEXICAL SUPPORT:')['targets'][0]
            decisions = []
            for i, entry in enumerate(found['entries']):
                decisions.append({'target_id': found['targets'][0]['id'], 'entry_id': entry['entry_id'],
                    'status': 'matched' if i == 0 else 'rejected', 'attested_form': 'support' if bad_form else record['head'],
                    'quotation': entry['dictionary']['whole_entry_text'], 'relation_kind': 'inflected_form',
                    'meaning_applied': 'Contextual test meaning; not an editorial judgment.', 'changes_gloss': False,
                    'form_explanation': '' if bad else 'The dictionary lemma is only a base; the performed ending must contribute its relation in this clause.',
                    'reason': 'Synthetic structural claim subject to independent linguistic review.'})
            row = {'id': line['id'], 'literal_english': 'Contextual meaning. Context.',
                'segments': [{'text': 'Contextual meaning', 'word_indices': [index]},
                    {'text': '. Context.', 'word_indices': [j for j in range(len(tokens)) if j != index]}],
                'wording_decisions': [{'target_id': target['id'], 'chosen_candidate_id': None,
                    'expression': 'Contextual meaning', 'kind': 'compositional_phrase', 'english_evidence_ids': [],
                    'word_indices': [index], 'ordinary_paraphrase': 'contextual meaning', 'component_word_indices': [[index]], 'reason': 'Transport control.'}],
                'source_discovery_decisions': decisions, 'human_review_recommended': False,
                'material_alternatives': [], 'choice_note': '', 'uncertainty': '',
                'fidelity': {'agency_and_image_preserved': True, 'all_meaning_accounted_for': True, 'unsupported_additions': [], 'notes': ''}}
            return {'packet': {'translations': [row]}}
        with patch.object(pipeline.gemini, 'call', side_effect=transport):
            if bad or bad_form:
                with self.assertRaisesRegex((ValueError, RuntimeError), 'form|inflect|headword'):
                    c.complete()
                self.assertNotIn('bhakti_translation_review', calls)
                return
            result = c.complete()
            self.assertEqual(c.audit, before)
            count = len(calls); http = len(requests)
            self.assertEqual(c.complete(), result)
            self.assertEqual((len(calls), len(requests)), (count, http))
        self.assertEqual(calls.count('bhakti_word_glosses'), 2 if disagreement else 1)
        self.assertEqual(calls.count('bhakti_translation_review'), 2 if disagreement else 1)
        self.assertEqual(len(packets[0]['entries']), 7 if language == 'Tamil' else 1)
        self.assertIn(record['head'], requests)
        if fresh: self.assertEqual(requests, [record['head']])

    def test_punjabi_performed_form_reaches_full_dictionary_and_review(self):
        self.run_case('Punjabi')

    def test_tamil_homographs_reach_fresh_transcript_review_without_silent_stemming(self):
        self.run_case('Tamil', fresh=True)

    def test_stem_entry_without_form_explanation_fails_before_review(self):
        self.run_case('Punjabi', bad=True)

    def test_reviewer_form_objection_uses_existing_selective_gloss_repair(self):
        self.run_case('Tamil', disagreement=True)

    def test_definition_fragment_is_not_an_attested_source_lemma(self):
        self.run_case('Punjabi', bad_form=True)

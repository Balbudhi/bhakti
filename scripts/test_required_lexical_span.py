"""New review evidence must add targeted lookup without repaying the glossary."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import test_automatic_semantic_lexical as fixture

class NewlyRequiredLexicalSpanTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.AutomaticSemanticLexicalTests();self.case.setUp();self.addCleanup(self.case.doCleanups)

    def test_actual_complete_repairs_newly_required_span_with_empty_existing_queries(self):
        case=self.case;original=case.transport;review_count=0
        def transport(*args,**kwargs):
            nonlocal review_count
            result=original(*args,**kwargs);kind=kwargs['schema_name']
            if 'word_gloss' in kind:
                result['packet']['glosses'][0]['lexical_queries']=[]
            if kind=='bhakti_translation_review':
                review_count+=1
                if review_count==1:
                    result['packet']['reviews'][0].update(passes=False,human_review_recommended=True,imagery_preserved=False,issues=[{
                        'kind':'english_realization','target_line_ids':['v'],
                        'references':[{'line_id':'v','domain':'word_glosses','word_indices':[0],'source_quote':'वज्र'}],
                        'explanation':'English wording needs physical-hardness dictionary support.',
                        'evidence':'Disambiguate physical hardness from mental obstinacy.',
                        'hold_reason':'','needed_evidence':''}])
            return result
        with patch.object(fixture.pipeline.gemini,'call',side_effect=transport):
            result=case.complete()
            self.assertEqual(case.state()['status'],'accepted')
            self.assertEqual(case.kinds(),['bhakti_word_glosses','bhakti_literal_translation','bhakti_translation_review',
                                           'bhakti_literal_translation','bhakti_translation_review'])
            self.assertEqual(result[0]['packet']['glosses'][0]['lexical_queries'],[])
            self.assertNotIn('support_decisions',result[0]['packet']['glosses'][0])
            self.assertIn('having the hardness of a diamond',case.calls[-1]['prompt'])
            before=len(case.calls);self.assertEqual(case.complete(),result);self.assertEqual(len(case.calls),before)

    def test_selective_accepted_resume_cannot_forget_required_wording_evidence(self):
        self.test_actual_complete_repairs_newly_required_span_with_empty_existing_queries()
        case=self.case;calls=len(case.calls)
        path=case.packets/'05-translation.json';value=json.loads(path.read_text())
        value['packet']['translations'][0]['wording_decisions']=[];path.write_text(json.dumps(value))
        manifest=case.packets/'semantic-acceptance.json';saved=json.loads(manifest.read_text())
        saved['translation_sha256']=fixture.pipeline.bhakti_semantic_repair.digest(value)
        manifest.write_text(json.dumps(saved))
        with self.assertRaisesRegex((ValueError,RuntimeError),'decision|support|target'):
            case.complete()
        self.assertEqual(len(case.calls),calls)

    def test_selective_accepted_dictionary_change_keeps_lookup_obligations_without_regloss(self):
        self.test_actual_complete_repairs_newly_required_span_with_empty_existing_queries()
        case=self.case;calls=len(case.calls)
        case.change_english_definition();result=case.complete()
        self.assertEqual(case.kinds()[calls:],['bhakti_literal_translation','bhakti_translation_review'])
        self.assertIn('TARGETED LEXICAL SUPPORT:',case.calls[-1]['prompt'])
        self.assertIn('having the hardness of a crystal',case.calls[-1]['prompt'])
        self.assertNotIn('English wording needs physical-hardness dictionary support.',
                         case.calls[-2]['prompt'].split('REPAIR FEEDBACK:')[1] if 'REPAIR FEEDBACK:' in case.calls[-2]['prompt'] else '')
        self.assertEqual(result[0]['packet']['glosses'][0]['lexical_queries'],[])
        self.assertTrue(result[1]['packet']['translations'][0]['wording_decisions'])

    def two_round_transport(self):
        case = self.case
        case.lines.append({**copy.deepcopy(case.lines[0]), 'id': 'q'})
        case.audit['packet']['performance_order'].append({'line_id': 'q', 'occurrence': 1})
        original = case.transport
        reviews = 0
        def data(prompt, heading):
            return json.JSONDecoder().raw_decode(prompt.split(heading, 1)[1])[0]
        def issue(line_id):
            return {'kind': 'english_realization', 'target_line_ids': [line_id],
                'references': [{'line_id': line_id, 'domain': 'word_glosses', 'word_indices': [0], 'source_quote': 'वज्र'}],
                'explanation': 'Check physical hardness for ' + line_id,
                'evidence': 'Physical rather than mental hardness', 'hold_reason': '', 'needed_evidence': ''}
        def transport(model, key, prompt, **kwargs):
            nonlocal reviews
            result = original(model, key, prompt, **kwargs)
            kind = kwargs['schema_name']
            if 'word_gloss' in kind:
                template = result['packet']['glosses'][0]
                rows = []
                for source in data(prompt, 'TARGET LYRICS (return these IDs only):\n'):
                    row = copy.deepcopy(template)
                    row.update(id=source['id'], lexical_queries=[],
                               sense_decisions=fixture.decisions_for(case.lines, ['Hindi'])[source['id']])
                    rows.append(row)
                result['packet']['glosses'] = rows
            elif kind == 'bhakti_translation_review':
                reviews += 1
                template = result['packet']['reviews'][0]
                rows = []
                failed = 'v' if reviews == 1 else 'q' if reviews == 2 else None
                for item in data(prompt, 'EVIDENCE:\n'):
                    row = copy.deepcopy(template)
                    row['id'] = item['source']['id']
                    if row['id'] == failed:
                        row.update(passes=False, human_review_recommended=True,
                                   imagery_preserved=False, issues=[issue(failed)])
                    rows.append(row)
                result['packet']['reviews'] = rows
            else:
                template = result['packet']['translations'][0]
                rows = []
                support = data(prompt, 'TARGETED LEXICAL SUPPORT:\n') if 'TARGETED LEXICAL SUPPORT:\n' in prompt else None
                for source in data(prompt, 'TARGET audited source lines (return these IDs only):\n'):
                    row = copy.deepcopy(template)
                    row['id'] = source['id']
                    row.pop('wording_decisions', None)
                    targets = [t for t in support['targets'] if t['line_id'] == source['id']] if support else []
                    if targets:
                        target = targets[0]
                        candidate = next(c for c in target['english_candidates'] if c['expression'] == 'adamantine')
                        entry = next(e for e in support['evidence'] if e.get('gloss', '').startswith('having the hardness of a '))
                        row['wording_decisions'] = [{'target_id': target['id'], 'chosen_candidate_id': candidate['id'],
                            'expression': 'adamantine', 'kind': 'word', 'english_evidence_ids': [entry['id']],
                            'word_indices': [0], 'ordinary_paraphrase': 'hard as diamond',
                            'component_word_indices': [[0]], 'reason': 'Physical control'}]
                    rows.append(row)
                result['packet']['translations'] = rows
            return result
        return transport

    def assert_two_round_acceptance(self, result):
        case = self.case
        self.assertEqual(case.state()['status'], 'accepted')
        self.assertEqual(case.kinds(), ['bhakti_word_glosses'] + ['bhakti_literal_translation', 'bhakti_translation_review'] * 3)
        self.assertEqual([row['lexical_queries'] for row in result[0]['packet']['glosses']], [[], []])
        self.assertTrue(all(row['wording_decisions'] for row in result[1]['packet']['translations']))
        # Earlier lookup survives, but resolved v is not a renewed objection for q.
        repair = case.calls[-2]['prompt'].split('REPAIR FEEDBACK:\n', 1)[1]
        feedback = json.JSONDecoder().raw_decode(repair)[0]
        self.assertEqual([item['target_line_ids'] for item in feedback], [['q']])
        calls = len(case.calls)
        self.assertEqual(case.complete(), result)
        self.assertEqual(len(case.calls), calls)

    def test_two_required_rounds_preserve_both_lookup_obligations_and_corpus_change(self):
        case = self.case
        with patch.object(fixture.pipeline.gemini, 'call', side_effect=self.two_round_transport()):
            result = case.complete()
            self.assert_two_round_acceptance(result)
            calls = len(case.calls)
            case.change_english_definition()
            changed = case.complete()
            self.assertEqual(case.kinds()[calls:], ['bhakti_literal_translation', 'bhakti_translation_review'])
            self.assertTrue(all(row['wording_decisions'] for row in changed[1]['packet']['translations']))
            self.assertNotIn('REPAIR FEEDBACK:', case.calls[-2]['prompt'])
            self.assertEqual(changed[0]['packet'], result[0]['packet'])

    def test_two_required_rounds_resume_after_durable_round_transition(self):
        case = self.case
        original = fixture.pipeline.semantic_write_json
        def interrupt(path, value):
            original(path, value)
            if Path(path).name == 'semantic-repair-state.json' and value.get('rounds_used') == 2:
                raise KeyboardInterrupt('after second repair transition')
        with patch.object(fixture.pipeline.gemini, 'call', side_effect=self.two_round_transport()):
            with patch.object(fixture.pipeline, 'semantic_write_json', side_effect=interrupt):
                with self.assertRaises(KeyboardInterrupt):
                    case.complete()
            self.assertEqual(len(case.calls), 5)
            result = case.complete()
            self.assert_two_round_acceptance(result)

    def test_preparation_preserves_existing_proposals_and_reports_nonword_gap(self):
        case=self.case;producer=fixture.pipeline.bhakti_lexical_producer
        row=case.transport('fixture','fixture','',schema_name='bhakti_word_glosses')['packet']['glosses'][0]
        other=copy.deepcopy(row);other['id']='q';other['lexical_queries']=[]
        other['word_glosses'][0]['gloss']='hard as diamond'
        base={'packet':{'glosses':[row,other]}}
        audited=copy.deepcopy(case.audit);audited['packet']['verified_lines'].append({**copy.deepcopy(case.lines[0]),'id':'q'})
        options=copy.copy(case.options);options.semantic_repair_feedback=[{'kind':'english_realization',
            'references':[{'line_id':'q','word_indices':[0]}]}]
        original=copy.deepcopy(base);calls=len(case.calls)
        local,prepared=producer.prepare_translation(case.song,audited,base,options)
        self.assertEqual(len(case.calls),calls)
        self.assertEqual(base,original)
        self.assertEqual(prepared['packet']['glosses'][0]['lexical_queries'],row['lexical_queries'])
        self.assertEqual(prepared['packet']['glosses'][1]['lexical_queries'],[])
        self.assertEqual(prepared['packet']['glosses'][1]['lexical_query_gaps'][0]['word_indices'],[0])
        self.assertTrue(any(gap['kind']=='proposal_unavailable' for gap in local.automatic_lexical_diagnostics))

if __name__=='__main__':unittest.main()

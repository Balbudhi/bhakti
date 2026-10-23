"""Actual private caller + semantic coordinator regressions; provider answers are fixtures."""
import argparse
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import benchmark_translation_prompt as benchmark
import retranslate_bhakti as retranslate
import bhakti_pipeline as pipeline
import bhakti_model_routes as routes
from bhakti_intake_run import bounded_intake_run
from test_sense_decisions import decisions_for


def block(prompt, marker):
    return json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1].lstrip())[0]


class RemainingSemanticCallers(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve(); self.song = self.root / 'songs/fixture'
        self.song.mkdir(parents=True); (self.root / 'data').mkdir()
        (self.root / 'data/preserved_terms.json').write_bytes((pipeline.ROOT / 'data/preserved_terms.json').read_bytes())
        (self.root / 'data/editorial_baselines.json').write_text('{"version":1,"songs":{}}')
        self.reader = {'SONG_META': {'languages': ['Hindi'], 'title': 'Original'},
            'SONG_LINES': {'a': {'source': 'मन', 'roman': 'mana', 'sourceLanguage': 'hi',
                'sourceWords': [{'text': 'मन', 'wordIndices': [0]}],
                'words': [{'roman': 'mana', 'gloss': 'OWNER_POPUP_SECRET'}],
                'english': '{0:OWNER_ENGLISH_SECRET}'}},
            'SONG_SEQUENCE': [{'ref': 'a', 'section': 'refrain', 'repeats': 2}],
            'SONG_TIMINGS': [{'start': 0, 'end': 10}]}
        self.path = self.song / 'data.js'; self.write_reader()
        self.options = argparse.Namespace(model=routes.FLASH_MODEL, pro_model=routes.PRO_MODEL,
            timeout=30, workers=1, songs=['fixture'], reuse_glosses=False,
            semantic_repair_rounds=1, semantic_stage_escalation=False,
            budget_usd=1., max_calls=12, deadline_seconds=120,
            run_dir=self.root / '.transcription/text-review-run')
        self.case = {'id': 'shadow-case', 'slug': 'fixture', 'mode': 'generation',
            'owner_reference': True, 'target_ids': ['a'], 'excerpt_start': 0, 'excerpt_end': 1}
        self.calls = []; self.mode = 'clean'; self.writer_count = 0
        for p in (patch.object(retranslate, 'ROOT', self.root), patch.object(pipeline, 'ROOT', self.root),
            patch.object(pipeline.gemini, 'key', return_value='OFFLINE'),
            patch.object(pipeline.gemini, 'call', side_effect=self.provider),
            patch.dict(os.environ, {**{k:v for k,v in os.environ.items() if not k.startswith('BHAKTI_API_RUN_')},
                'BHAKTI_AUTO_LEXICAL':'0', 'BHAKTI_GEMINI_PROVIDER':'openrouter'}, clear=True)):
            p.start(); self.addCleanup(p.stop)

    def write_reader(self):
        self.path.write_text(''.join('window.' + key + '=' + json.dumps(value, ensure_ascii=False) + ';\n'
                                    for key,value in self.reader.items()))

    def provider(self, model, key, prompt, **kwargs):
        name=kwargs['schema_name']; self.calls.append((name, model, prompt))
        if self.mode == 'unknown' and 'literal_translation' in name:
            raise routes.UnitTransportFailure('unknown-outcome', request_id='fixture-unknown', worker_terminated=False)
        if 'word_gloss' in name:
            lines=block(prompt, 'TARGET LYRICS (return these IDs only):\n')
            senses=decisions_for(lines, ['Hindi'])
            return {'packet':{'glosses':[{'id':row['id'],
                'word_glosses':[{'roman':'mana','gloss':'mind','concept_key':'','preserve_in_english':False}],
                'semantic_frame':{field:'' for field in pipeline.SEMANTIC_FRAME_FIELDS},
                'sense_decisions':senses[row['id']],'grammar_note':'A noun.','uncertainty':''} for row in lines]}}
        if name == 'bhakti_translation_review':
            evidence=block(prompt,'EVIDENCE:\n'); rows=[]
            for item in evidence:
                bad=item['draft']['literal_english']=='body'
                issue={'kind':'english_realization','target_line_ids':[item['source']['id']],
                    'references':[{'line_id':item['source']['id'],'domain':'word_glosses',
                                   'word_indices':[0],'source_quote':'मन'}],
                    'explanation':'The cognitive noun mind is rendered as body.',
                    'evidence':'मन and its selected gloss mean mind, not body.', 'hold_reason':'','needed_evidence':''}
                row={'id':item['source']['id'],'passes':not bad,'agency_preserved':True,
                    'imagery_preserved':True,'all_meaning_accounted_for':not bad,
                    'unsupported_additions':[],'human_review_recommended':False,'material_choice':'',
                    'reason':'The English noun was checked against source and selected gloss.',
                    'issues':[issue] if bad else []}
                if pipeline.REVIEW_TASK_VERSION >= 3:
                    row['component_judgments']={c:{'status':'defect' if bad and c=='english' else 'supported',
                        'reason':'The cognitive noun is mind.'} for c in ('gloss','frame','english')}
                rows.append(row)
            return {'packet':{'reviews':rows}}
        self.writer_count += 1
        lines=block(prompt,'TARGET audited source lines (return these IDs only):\n')
        english='body' if self.mode=='repair' and self.writer_count==1 else 'mind'
        if self.mode=='owner': english='OWNER_ENGLISH_SECRET'
        return {'packet':{'translations':[{'id':row['id'],'literal_english':english,
            'segments':[{'text':english,'word_indices':[0]}],
            'fidelity':{'agency_and_image_preserved':True,'all_meaning_accounted_for':True,'unsupported_additions':[]},
            'human_review_recommended':False,'material_alternatives':[],'choice_note':'','uncertainty':''}
            for row in lines],'comparison':[]}}

    def bounded(self):
        return bounded_intake_run(self.root,[{'slug':'fixture','source':str(self.path)}],self.options)

    def kinds(self):
        return ['gloss' if 'word_gloss' in name else 'review' if name=='bhakti_translation_review' else 'writer'
                for name,_,_ in self.calls]

    def generation(self):
        return benchmark.run_generation_case(self.case,self.reader,self.root/'private',self.options)

    def test_benchmark_uses_actual_shared_coordinator_with_order_and_source_only_owner_shadow(self):
        original=copy.deepcopy(self.reader); public=self.path.read_bytes(); self.mode='repair'
        # Register an actual owner reference: the private case must not invoke
        # its protection as supplied generator English or bypass a source lock.
        baseline={'version':1,'songs':{'fixture':{'policy':'preserve_english',
            'plainEnglishByLine':{'a':'OWNER_ENGLISH_SECRET'},'englishSha256':'0'*64}}}
        (self.root/'data/editorial_baselines.json').write_text(json.dumps(baseline))
        self.options.semantic_initial_repair={'original_reader':'OWNER_ENGLISH_SECRET'}
        self.options.semantic_previous_writer_context={'private':'OWNER_ENGLISH_SECRET'}
        self.options.semantic_pending_findings=[{'original':'OWNER_POPUP_SECRET'}]
        with self.bounded(), patch.object(pipeline,'complete_semantics',wraps=pipeline.complete_semantics) as complete:
            result=self.generation()
        self.assertEqual(complete.call_count,1)
        audited=complete.call_args.args[1]; job=complete.call_args.args[2]; local=complete.call_args.args[3]
        self.assertEqual(audited['packet']['performance_order'],self.reader['SONG_SEQUENCE'])
        self.assertEqual(local.source_slug,'fixture'); self.assertNotIn('providedTranslation',job)
        self.assertNotIn('slug',job)
        self.assertEqual(self.kinds(),['gloss','writer','review','writer','review'])
        for _,_,prompt in self.calls:
            self.assertNotIn('OWNER_ENGLISH_SECRET',prompt); self.assertNotIn('OWNER_POPUP_SECRET',prompt)
        self.assertEqual(self.reader,original); self.assertEqual(result['semantic_status'],'not-reviewed')
        self.assertEqual(result['lines'][0]['original_english'],'OWNER_ENGLISH_SECRET')
        self.assertEqual(result['lines'][0]['proposed_english'],'mind')
        self.assertEqual(self.path.read_bytes(),public)

    def test_benchmark_case_identity_cannot_equal_owner_slug(self):
        self.case['id']='fixture'
        with self.bounded(), self.assertRaises((ValueError,RuntimeError)):
            self.generation()
        self.assertEqual(self.calls,[])

    def test_benchmark_failure_retains_real_completed_gloss_and_unknown_resume_does_not_replay(self):
        self.mode='unknown'
        with self.bounded():
            with self.assertRaises((ValueError,RuntimeError)): self.generation()
            count=len(self.calls)
            with self.assertRaises((ValueError,RuntimeError)): self.generation()
            self.assertEqual(len(self.calls),count)
        folder=self.root/'private/cases/shadow-case'
        ready=list(folder.rglob('gloss-ready.json'))
        self.assertEqual(len(ready),1)
        self.assertEqual(json.loads(ready[0].read_text())['packet']['glosses'][0]['word_glosses'][0]['gloss'],'mind')
        self.assertFalse((folder/'comparison.json').exists())

    def test_retranslate_repairs_english_without_regloss_and_preserves_public_reader(self):
        original=self.path.read_bytes(); self.mode='repair'
        with self.bounded(),patch.object(pipeline,'complete_semantics',wraps=pipeline.complete_semantics) as complete:
            result=retranslate.run_slug('fixture',self.options)
        self.assertEqual(complete.call_count,1)
        self.assertEqual(self.kinds(),['gloss','writer','review','writer','review'])
        self.assertEqual(complete.call_args.args[1]['packet']['performance_order'],self.reader['SONG_SEQUENCE'])
        self.assertEqual(result['status'],'review-required'); self.assertEqual(self.path.read_bytes(),original)
        self.assertFalse((self.song/'index.html').exists())

    def test_retranslate_default_and_deprecated_reuse_flag_resume_accepted_without_calls_or_new_deadline(self):
        with self.bounded():
            retranslate.run_slug('fixture',self.options)
            states=list(self.song.rglob('semantic-repair-state.json'))
            self.assertEqual(len(states),1); original_state=states[0].read_bytes(); count=len(self.calls)
            retranslate.run_slug('fixture',self.options)
            self.options.reuse_glosses=True
            retranslate.run_slug('fixture',self.options)
            self.assertEqual(len(self.calls),count); self.assertEqual(states[0].read_bytes(),original_state)
        self.assertEqual(count,3)

    def test_retranslate_owner_english_is_locked_and_no_public_mutation(self):
        self.reader['SONG_META']['humanTranslation']={'a':'OWNER_ENGLISH_SECRET'};self.write_reader()
        original=self.path.read_bytes(); self.mode='owner'
        with self.bounded():
            retranslate.run_slug('fixture',self.options)
        writer=next(prompt for name,_,prompt in self.calls if name=='bhakti_literal_translation')
        self.assertIn('OWNER_ENGLISH_SECRET',writer);self.assertIn('LOCKED',writer)
        self.assertEqual(self.path.read_bytes(),original)
        report=json.loads((self.song/'.transcription/translation-review-gloss-first/review.json').read_text())
        self.assertEqual(report['comparison'][0]['proposed'],'OWNER_ENGLISH_SECRET')

    def test_retranslate_actual_unknown_stage_cannot_be_replayed_on_default_resume(self):
        self.mode='unknown'; original=self.path.read_bytes()
        with self.bounded():
            with self.assertRaises((ValueError,RuntimeError)):retranslate.run_slug('fixture',self.options)
            count=len(self.calls); routes_before={str(p):p.read_bytes() for p in self.song.rglob('route-state.json')}
            with self.assertRaises((ValueError,RuntimeError)):retranslate.run_slug('fixture',self.options)
            self.assertEqual(len(self.calls),count)
            self.assertTrue(routes_before)
            self.assertEqual({str(p):p.read_bytes() for p in self.song.rglob('route-state.json')},routes_before)
        self.assertEqual(self.path.read_bytes(),original)

    def test_retranslate_legacy_unknown_report_is_preserved_before_new_coordinator_claim(self):
        report=self.song/'.transcription/translation-review-gloss-first/review.json'
        report.parent.mkdir(parents=True);report.write_text(json.dumps({'slug':'fixture','status':'in-progress',
            'reader_sha256':hashlib.sha256(self.path.read_bytes()).hexdigest()}))
        original=report.read_bytes()
        with self.bounded(), self.assertRaises((ValueError,RuntimeError)):
            retranslate.run_slug('fixture',self.options)
        self.assertEqual(self.calls,[]);self.assertEqual(report.read_bytes(),original)
        self.assertFalse(list(self.song.rglob('semantic-repair-state.json')))

    def test_retranslate_direct_unbounded_call_holds_before_provider(self):
        with self.assertRaises((ValueError,RuntimeError)):
            retranslate.run_slug('fixture',self.options)
        self.assertEqual(self.calls,[])

    def test_retranslate_cli_owns_one_real_bounded_context_and_authentic_reader_hash(self):
        before=self.path.read_bytes()
        second=self.root/'songs/fixture-two/data.js';second.parent.mkdir();second.write_bytes(before)
        self.options.songs=['fixture','fixture-two'];self.options.workers=2
        with patch.object(retranslate,'parse_args',return_value=self.options),contextlib.redirect_stdout(io.StringIO()):
            status=retranslate.main()
        self.assertEqual(status,0)
        saved=json.loads((self.options.run_dir/'run.json').read_text())
        self.assertEqual([j['slug'] for j in saved['identity']['jobs']],['fixture','fixture-two'])
        self.assertEqual({j['source_sha256'] for j in saved['identity']['jobs']},{hashlib.sha256(before).hexdigest()})
        self.assertEqual(saved['identity']['jobs'][0]['source_sha256'],hashlib.sha256(before).hexdigest())
        self.assertEqual(saved['identity']['jobs'][0]['source'],str(self.path))
        self.assertEqual(saved['identity']['budget_usd'],1.)
        self.assertEqual(saved['identity']['max_calls'],12)
        self.assertEqual(self.path.read_bytes(),before);self.assertEqual(second.read_bytes(),before)
        count=len(self.calls);self.assertEqual(count,6);deadline=saved['deadline_at']
        with patch.object(retranslate,'parse_args',return_value=self.options),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(retranslate.main(),0)
        self.assertEqual(len(self.calls),count)
        self.assertEqual(json.loads((self.options.run_dir/'run.json').read_text())['deadline_at'],deadline)


    def test_retranslate_cli_exposes_existing_bounded_controls_and_explicit_reuse_migration(self):
        import sys
        with patch.object(sys,'argv',['retranslate_bhakti.py','fixture','--budget-usd','.75',
                '--max-calls','9','--deadline-seconds','100','--run-dir',str(self.options.run_dir),
                '--reuse-glosses']):
            options=retranslate.parse_args()
        self.assertEqual((options.budget_usd,options.max_calls,options.deadline_seconds),(.75,9,100))
        self.assertEqual(options.run_dir,self.options.run_dir)
        with patch.object(sys,'argv',['retranslate_bhakti.py','--help']), contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit):retranslate.parse_args()
        self.assertIn('resume',output.getvalue().lower())
        self.assertNotIn('rerun English and independent review',output.getvalue())

    def test_retranslate_cli_cannot_hide_unknown_existing_ledger_by_starting_new_state(self):
        with self.bounded():
            ledger=Path(os.environ['BHAKTI_API_RUN_LEDGER'])
            with pipeline.gemini._locked_run_ledger(ledger,1.) as record:
                record['requests'].append({'id':'unresolved-fixture','status':'unknown-outcome',
                    'model':self.options.model,'reservation_usd':.02,'started_at':time.time(),
                    'worker_terminated':False})
        original=ledger.read_bytes();state=(self.options.run_dir/'run.json').read_bytes()
        with patch.object(retranslate,'parse_args',return_value=self.options),contextlib.redirect_stdout(io.StringIO()):
            try:status=retranslate.main()
            except (ValueError,RuntimeError):status=1
        self.assertNotEqual(status,0);self.assertEqual(self.calls,[])
        self.assertEqual(ledger.read_bytes(),original)
        self.assertEqual((self.options.run_dir/'run.json').read_bytes(),state)


    def test_retranslate_validation_only_failure_can_retry_corrected_map_without_new_allowance(self):
        self.reader['SONG_LINES']['a']['sourceWords'][0]['wordIndices']=[99];self.write_reader()
        with self.bounded():
            with self.assertRaisesRegex(RuntimeError,'sourceWords'):
                retranslate.run_slug('fixture',self.options)
            self.assertEqual(self.calls,[])
            self.reader['SONG_LINES']['a']['sourceWords'][0]['wordIndices']=[0];self.write_reader()
            result=retranslate.run_slug('fixture',self.options)
            self.assertEqual(result['status'],'review-required');self.assertEqual(len(self.calls),3)

    def test_retranslate_missing_previously_accepted_state_holds_then_exact_restore_resumes_free(self):
        with self.bounded():
            retranslate.run_slug('fixture',self.options)
            state=next(self.song.rglob('semantic-repair-state.json'));raw=state.read_bytes();state.unlink()
            report=self.song/'.transcription/translation-review-gloss-first/review.json';original=report.read_bytes()
            count=len(self.calls)
            with self.assertRaises((ValueError,RuntimeError)):
                retranslate.run_slug('fixture',self.options)
            self.assertEqual(len(self.calls),count);self.assertFalse(state.exists())
            self.assertEqual(report.read_bytes(),original)
            state.write_bytes(raw)
            self.assertEqual(retranslate.run_slug('fixture',self.options)['status'],'review-required')
            self.assertEqual(len(self.calls),count)

if __name__=='__main__':unittest.main()

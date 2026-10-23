"""Actual translate/review/candidate path; no journal observer is installed."""
import argparse
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import bhakti_pipeline as pipeline
import bhakti_library_pass as library
import bhakti_model_routes as routes
import test_review_findings_integration as fixtures

class NormalContextHoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.song = Path(self.tmp.name)
        reader = json.loads((fixtures.FIXTURES/'rehna-reader.json').read_text())
        self.lines, self.glosses, self.drafts = library.reader_evidence(reader)
        self.target = 'verse-3-line-1'; self.context_id = 'verse-3-line-2'
        self.options = argparse.Namespace(model='fixture-model', timeout=1, force=False,
            unit_context={'fixture': True}, semantic_performance_order=reader['SONG_SEQUENCE'],
            semantic_full_source=self.lines, semantic_context_evidence=[
                {'source':s,'gloss':g,'draft':d} for s,g,d in zip(self.lines,self.glosses,self.drafts)])
        self.extra = None; self.saved_review = None; self.calls = []

    def provider(self, model, key, prompt, **kwargs):
        self.calls.append(kwargs['schema_name'])
        if kwargs['schema_name'] == 'bhakti_translation_review':
            evidence = fixtures.json_block(prompt, 'EVIDENCE:\n')
            self.assertEqual([row['source']['id'] for row in evidence], [self.target])
            reading = fixtures.json_block(prompt, 'ENGLISH READING CONTEXT (context only; target obligations unchanged):\n')
            self.assertIn(self.context_id, [row['source']['id'] for row in reading['context_rows']])
            rows = [fixtures.clean_review(self.target)]
            if self.extra is not None: rows.append(copy.deepcopy(self.extra))
            self.saved_review = {'packet': {'reviews': rows}}
            return copy.deepcopy(self.saved_review)
        draft = copy.deepcopy(next(row for row in self.drafts if row['id']==self.target))
        draft.update(human_review_recommended=False, material_alternatives=[], uncertainty='', choice_note='',
            fidelity={'agency_and_image_preserved':True,'all_meaning_accounted_for':True,
                      'unsupported_additions':[],'notes':''})
        return {'packet': {'translations':[draft], 'comparison':[]}}

    def run_translation(self):
        with patch.object(pipeline.gemini,'key',return_value='unused'), \
             patch.object(pipeline.gemini,'call',side_effect=self.provider), \
             patch.object(pipeline.bhakti_translation_policy,'sense_decision_errors',return_value=[]):
            return pipeline.translate(self.song,
                {'packet':{'verified_lines':[r for r in self.lines if r['id']==self.target],
                           'performance_order':self.options.semantic_performance_order}},
                {'packet':{'glosses':[r for r in self.glosses if r['id']==self.target]}},
                {'slug':'normal-context-fixture','languages':[]},self.options,candidate_only=True)

    def test_material_context_holds_real_translate_and_retains_exact_raw_candidate(self):
        saved = json.loads((fixtures.FIXTURES/'rehna-reviews.json').read_text())
        actual = next(row for row in saved['reviews'] if row['id']==self.context_id)
        for mode in ('typed-issue','failed-fidelity','open-choice','unsupported-addition'):
            with self.subTest(mode=mode):
                self.options.force=True
                self.extra = fixtures.clean_review(self.context_id)
                if mode=='typed-issue': self.extra=copy.deepcopy(actual)
                if mode=='failed-fidelity': self.extra['imagery_preserved']=False
                if mode=='open-choice':
                    self.extra['human_review_recommended']=True
                    self.extra['material_choice']='The source supports materially different readings.'
                if mode=='unsupported-addition': self.extra['unsupported_additions']=['true']
                with self.assertRaises(routes.QualityFailure) as held: self.run_translation()
                self.assertEqual(held.exception.issues[0]['kind'],'unresolved_context')
                self.assertIn(self.context_id,held.exception.issues[0]['detail'])
                directory=self.song/'.transcription/pipeline'
                self.assertFalse((directory/'05-translation.json').exists())
                raw=json.loads((directory/'translation-review-batches/candidate-0.json').read_text())
                self.assertEqual(raw,self.saved_review)
                self.assertEqual(raw['packet']['reviews'][0],fixtures.clean_review(self.target))
                candidate=json.loads((directory/'translation-candidate.json').read_text())
                self.assertEqual([r['id'] for r in candidate['packet']['translations']],[self.target])
                self.assertNotIn('independent_review',candidate['packet']['translations'][0])

    def test_missing_or_nonboolean_context_flags_cannot_look_like_clean_context(self):
        for flag in ('passes','agency_preserved','imagery_preserved',
                     'all_meaning_accounted_for','human_review_recommended'):
            for bad in ('missing', None, 'true'):
                with self.subTest(flag=flag,bad=bad):
                    self.options.force=True; self.extra=fixtures.clean_review(self.context_id)
                    if bad=='missing': self.extra.pop(flag)
                    else: self.extra[flag]=bad
                    with self.assertRaises(routes.QualityFailure): self.run_translation()

    def test_material_context_is_terminal_across_clean_pro_and_cached_resume(self):
        saved = json.loads((fixtures.FIXTURES/'rehna-reviews.json').read_text())
        self.extra = copy.deepcopy(next(row for row in saved['reviews'] if row['id']==self.context_id))
        root = self.song; models=[]; original=self.provider
        def provider(model,*args,**kwargs):
            models.append(model)
            extra=self.extra
            if model==routes.PRO_MODEL: self.extra=None  # Pro is prepared to return all-clean.
            try: return original(model,*args,**kwargs)
            finally: self.extra=extra
        self.provider=provider
        def execute(context):
            self.song=context.attempt_dir/'song'
            self.options=library.route_options(self.options,context)
            return self.run_translation()
        def run():
            return routes.run_unit(root/'routes','normal-context','fixed-input',execute,lambda row:[],
                deadline_at=time.time()+120,dependency_fingerprint='fixed-source',
                base_model=routes.FLASH_MODEL,pro_model=routes.PRO_MODEL)
        with self.assertRaises(routes.UnitUnresolved) as held: run()
        self.assertEqual(held.exception.issues[0]['kind'],'unresolved_context')
        self.assertEqual(models,[routes.FLASH_MODEL,routes.FLASH_MODEL])
        state_path=next((root/'routes').rglob('route-state.json'))
        state=json.loads(state_path.read_text())
        self.assertEqual(state['status'],'unresolved'); self.assertEqual(len(state['attempts']),1)
        raw_path=state_path.parent/'flash/song/.transcription/pipeline/translation-review-batches/candidate-0.json'
        raw=raw_path.read_bytes()
        self.assertEqual(json.loads(raw)['packet']['reviews'][-1],self.extra)
        history=state_path.read_bytes()
        with self.assertRaises(routes.UnitUnresolved): run()
        self.assertEqual(models,[routes.FLASH_MODEL,routes.FLASH_MODEL])
        self.assertEqual(state_path.read_bytes(),history); self.assertEqual(raw_path.read_bytes(),raw)

    def test_passing_context_and_target_only_keep_exact_output_targets(self):
        for extra in (None,fixtures.clean_review(self.context_id)):
            with self.subTest(extra=extra):
                self.options.force=True; self.extra=extra
                result=self.run_translation()
                self.assertEqual([r['id'] for r in result['packet']['translations']],[self.target])
                self.assertEqual(result['packet']['translations'][0]['independent_review'],
                                 fixtures.clean_review(self.target))

if __name__=='__main__': unittest.main()

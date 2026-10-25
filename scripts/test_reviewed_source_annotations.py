"""Source-overlay regressions using real synthetic source routes; no API calls.

Provider responses and downstream operations outside each claimed seam are stubbed.
These checks establish dataflow and preservation, not linguistic correctness.
"""
import copy
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import bhakti_pipeline as pipeline
import bhakti_reviewed_source as reviewed
import test_source_bootstrap_design as source_fixture


class DownstreamReached(Exception):
    pass


class ReviewedSourceAnnotations(unittest.TestCase):
    def setUp(self):
        self.f = source_fixture.SourceStageTests(methodName='runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.song = self.f.song
        self.packet_dir = self.song / '.transcription/pipeline'
        self.declaration_path = self.song / '.transcription/reviewed-source-corrections.json'
        def provider(model, key, prompt, **kwargs):
            audit = kwargs.get('schema_name') == 'bhakti_audited_transcript'
            return {'resolved_model': model, 'packet': {
                'metadata': {'languages': ['Gurbani', 'Punjabi']},
                'verified_lines' if audit else 'lines': [
                    {'id': 'day', 'source_text': 'ਅਨਦਿਨੋੁ', 'roman': 'anadinau',
                     'language': 'Gurbani', 'kind': 'verse', 'notes': ''},
                    {'id': 'name', 'source_text': 'ਨਾਮੁ', 'roman': 'nāmu',
                     'language': 'Punjabi', 'kind': 'verse', 'notes': ''}],
                'performance_order': [{'line_id': 'day', 'occurrence': 1},
                                      {'line_id': 'name', 'occurrence': 1},
                                      {'line_id': 'day', 'occurrence': 2}],
                'uncertainties': []}}
        with patch.object(pipeline.gemini, 'call', side_effect=provider):
            raw = self.f.transcribe()
            self.original = self.f.audit(raw)
        self.original_path = self.packet_dir / '02-transcript-audit.json'
        self.original_bytes = self.original_path.read_bytes()
        self.addCleanup(patch.stopall)
        patch.object(pipeline.gemini, 'call', side_effect=AssertionError('no new model call')).start()

    def declaration(self, *, roman=True, language=True):
        before, after = {}, {}
        if roman:
            before['roman'], after['roman'] = 'anadinau', 'anadino'
        if language:
            before['language'], after['language'] = 'Gurbani', 'Punjabi'
        return {'version': 1,
                'original_audit_sha256': hashlib.sha256(self.original_bytes).hexdigest(),
                'corrections': [{'line_id': 'day', 'before': before, 'after': after,
                    'evidence': {'reviewer': 'fixture reviewer',
                                 'source_url': 'https://example.org/primary-fixture',
                                 'location': 'fixture line1',
                                 'reason': 'Explicit reviewed fixture, not linguistic qualification.'}}]}

    def declare(self, value=None):
        pipeline.write_json(self.declaration_path, value or self.declaration())

    def test_no_annotation_is_exact_no_write_compatibility(self):
        before = {p: p.read_bytes() for p in self.packet_dir.rglob('*.json')}
        self.assertEqual(reviewed.prepare(self.song, self.original), self.original)
        reviewed.require_current(self.song, self.original)
        self.assertEqual({p: p.read_bytes() for p in self.packet_dir.rglob('*.json')}, before)

    def test_derived_view_preserves_original_route_native_and_repetitions(self):
        self.declare()
        effective = reviewed.prepare(self.song, self.original)
        rows = effective['packet']['verified_lines']
        self.assertEqual((rows[0]['roman'], rows[0]['language'], rows[0]['sourceLanguage']),
                         ('anadino', 'Punjabi', 'pa'))
        self.assertEqual(effective['packet']['metadata']['languages'], ['Punjabi'])
        self.assertEqual(effective['packet']['performance_order'], self.original['packet']['performance_order'])
        self.assertEqual([r['source_text'] for r in rows],
                         [r['source_text'] for r in self.original['packet']['verified_lines']])
        self.assertEqual(rows[1], self.original['packet']['verified_lines'][1])
        self.assertNotIn('_source_route', effective)
        self.assertEqual(self.original_path.read_bytes(), self.original_bytes)
        self.assertEqual(json.loads(self.original_bytes), self.original)
        saved = self.packet_dir / '02-reviewed-source.json'
        self.assertEqual(json.loads(saved.read_text()), effective)
        before = saved.read_bytes()
        self.assertEqual(reviewed.prepare(self.song, self.original), effective)
        reviewed.require_current(self.song, effective)
        self.assertEqual(saved.read_bytes(), before)
        with self.assertRaises(ValueError):
            reviewed.require_current(self.song, self.original)

    def test_stale_unknown_duplicate_unbounded_and_unevidenced_edits_reject(self):
        cases = []
        value = self.declaration(); value['original_audit_sha256'] = '0' * 64; cases.append(value)
        value = self.declaration(); value['corrections'][0]['before']['roman'] = 'wrong'; cases.append(value)
        value = self.declaration(); value['corrections'][0]['line_id'] = 'missing'; cases.append(value)
        value = self.declaration(); value['corrections'] *= 2; cases.append(value)
        value = self.declaration(); value['corrections'][0]['after']['source_text'] = 'ਨਵਾਂ'; cases.append(value)
        value = self.declaration(); value['performance_order'] = []; cases.append(value)
        value = self.declaration(); value['corrections'][0]['evidence']['reason'] = ''; cases.append(value)
        value = self.declaration(); value['corrections'][0]['after']['language'] = 'Gurbani'; cases.append(value)
        for value in cases:
            with self.subTest(value=value):
                self.declare(value)
                with self.assertRaises(ValueError):
                    reviewed.prepare(self.song, self.original)
                self.assertEqual(self.original_path.read_bytes(), self.original_bytes)

    def test_current_gate_revalidates_original_router_candidate(self):
        self.declare()
        effective = reviewed.prepare(self.song, self.original)
        state_path = Path(self.original['_source_route']['state_path'])
        state = pipeline.read_packet(state_path)
        # Existing router uses flash/pro directories in attempt order.
        tier = 'flash' if len(state['attempts']) == 1 else 'pro'
        path = state_path.parent / tier / 'candidate.json'
        value = json.loads(path.read_text())
        value['packet']['verified_lines'][0]['roman'] = 'changed'
        pipeline.write_json(path, value)
        with self.assertRaises((ValueError, RuntimeError)):
            reviewed.require_current(self.song, effective)
        self.assertEqual(self.original_path.read_bytes(), self.original_bytes)

    def test_identity_changes_only_for_effective_stage_inputs(self):
        semantic = pipeline.bhakti_semantic_repair
        original_semantic = semantic.source_evidence(pipeline, self.song, self.original)
        self.declare(self.declaration(roman=False))
        language_view = reviewed.prepare(self.song, self.original)
        def timing_identity(view):
            return pipeline.timing_input_identity(self.f.audio,
                pipeline.display_occurrences(view['packet']), {})
        self.assertEqual(timing_identity(language_view), timing_identity(self.original))
        self.assertNotEqual(semantic.source_evidence(pipeline, self.song, language_view), original_semantic)
        self.declare()
        roman_view = reviewed.prepare(self.song, self.original)
        self.assertNotEqual(timing_identity(roman_view), timing_identity(language_view))
        roman_semantic = semantic.source_evidence(pipeline, self.song, roman_view)
        changed = self.declaration(); changed['corrections'][0]['evidence']['reason'] += ' Additional review note.'
        self.declare(changed)
        annotated = reviewed.prepare(self.song, self.original)
        self.assertEqual(timing_identity(annotated), timing_identity(roman_view))
        self.assertEqual(semantic.source_evidence(pipeline, self.song, annotated), roman_semantic)

    def test_generation_rejects_original_packet_before_semantic_gate(self):
        self.declare()
        with patch.object(pipeline.bhakti_semantic_repair, 'require_acceptance',
                          side_effect=DownstreamReached('generation passed uncorrected source')):
            with self.assertRaisesRegex(ValueError, 'reviewed source'):
                pipeline.generate(self.song, {'slug': self.song.name}, {}, self.original,
                                  {}, {}, {}, write_catalogue_after=False)

    def test_direct_semantics_rejects_original_packet_before_dispatch(self):
        self.declare()
        with patch.object(pipeline.bhakti_semantic_repair, 'complete',
                          side_effect=DownstreamReached('semantics passed uncorrected source')):
            with self.assertRaisesRegex(ValueError, 'reviewed source'):
                pipeline.complete_semantics(self.song, self.original,
                                            {'slug': self.song.name}, self.f.options)

    def test_removing_declaration_cannot_silently_restore_original(self):
        self.declare()
        effective = reviewed.prepare(self.song, self.original)
        self.declaration_path.unlink()
        with self.assertRaises(ValueError):
            reviewed.require_current(self.song, effective)
        with self.assertRaises(ValueError):
            reviewed.prepare(self.song, self.original)


    def source_bound_semantic_fixture(self, effective):
        """Minimal legacy acceptance envelope tests source selection, not review quality."""
        semantic = pipeline.bhakti_semantic_repair
        glosses = {'semantic_repair_version': semantic.VERSION, 'packet': {'glosses': []}}
        translations = {'semantic_repair_version': semantic.VERSION, 'packet': {'translations': []}}
        manifest = {'version': semantic.VERSION, 'status': 'accepted', 'run_id': 'fixture-source-selection',
                    'source_sha256': semantic.digest(semantic.source_evidence(pipeline, self.song, effective)),
                    'gloss_sha256': semantic.digest(glosses), 'translation_sha256': semantic.digest(translations)}
        for name, value in {
            'semantic-repair-required.json': {'run_id': manifest['run_id']},
            'semantic-repair-state.json': {'status': 'accepted', 'run_id': manifest['run_id']},
            'semantic-acceptance.json': manifest,
            '04-glosses.json': glosses, '05-translation.json': translations,
        }.items():
            pipeline.write_json(self.packet_dir / name, value)
        return glosses, translations

    def test_direct_align_holds_uncorrected_source_before_cached_timing(self):
        self.declare()
        with patch.object(pipeline, 'display_occurrences',
                          side_effect=DownstreamReached('timing received uncorrected source')):
            with self.assertRaisesRegex(ValueError, 'reviewed source'):
                pipeline.align(self.song, self.original, self.f.audio, self.f.options)

    def test_semantic_source_evidence_cannot_hash_uncorrected_packet(self):
        self.declare()
        with self.assertRaisesRegex(ValueError, 'reviewed source'):
            pipeline.bhakti_semantic_repair.source_evidence(pipeline, self.song, self.original)

    def test_default_acceptance_loads_current_view_not_raw02(self):
        self.declare()
        effective = reviewed.prepare(self.song, self.original)
        glosses, translations = self.source_bound_semantic_fixture(effective)
        semantic = pipeline.bhakti_semantic_repair
        semantic.require_acceptance(pipeline, self.packet_dir, glosses, translations)
        with self.assertRaisesRegex(ValueError, 'reviewed source'):
            semantic.require_acceptance(pipeline, self.packet_dir, glosses, translations, audited=self.original)
        self.assertEqual(self.original_path.read_bytes(), self.original_bytes)

    def test_hydration_accepts_same_view_but_never_replaces_raw02_with_summary_view(self):
        self.declare()
        effective = reviewed.prepare(self.song, self.original)
        glosses, translations = self.source_bound_semantic_fixture(effective)
        pipeline.write_json(self.packet_dir / 'song-packet.json',
            {'audit': effective, 'glosses': glosses, 'translation': translations})
        pipeline.hydrate_pipeline_artifacts(self.packet_dir)
        self.assertEqual(self.original_path.read_bytes(), self.original_bytes)
        self.original_path.unlink()
        with self.assertRaisesRegex(ValueError, 'reviewed source'):
            pipeline.hydrate_pipeline_artifacts(self.packet_dir)
        self.assertFalse(self.original_path.exists(), 'Derived summary must not become fake original evidence')

    def test_missing_or_corrupted_derived_view_blocks_load_and_consumers(self):
        self.declare()
        effective = reviewed.prepare(self.song, self.original)
        path = self.packet_dir / '02-reviewed-source.json'
        original = path.read_bytes()
        corrupted = copy.deepcopy(effective)
        corrupted['packet']['verified_lines'][0]['roman'] = 'invented'
        for value in (None, corrupted):
            with self.subTest(missing=value is None):
                if value is None:
                    path.unlink()
                else:
                    pipeline.write_json(path, value)
                with self.assertRaisesRegex(ValueError, 'reviewed source'):
                    reviewed.load(self.song)
                with self.assertRaisesRegex(ValueError, 'reviewed source'):
                    reviewed.require_current(self.song, effective)
                with self.assertRaisesRegex(ValueError, 'reviewed source'):
                    pipeline.bhakti_semantic_repair.source_evidence(pipeline, self.song, effective)
                path.write_bytes(original)
        self.assertEqual(self.original_path.read_bytes(), self.original_bytes)

    def test_run_one_feeds_same_derived_view_to_timing_and_semantics(self):
        self.declare()
        observed = []
        def align(song, audited, audio, options):
            observed.append(('timing', copy.deepcopy(audited)))
            return {'sequence': []}
        def semantics(song, audited, job, options):
            observed.append(('semantics', copy.deepcopy(audited)))
            raise DownstreamReached('captured both source consumers')
        # Trim/acquisition are outside this seam; both source stages are actual
        # validated cache reads from setup, and no provider request is permitted.
        with patch.object(pipeline, 'intake', return_value=(self.song, {})), \
             patch.object(pipeline, 'detect_youtube_trim', return_value={}), \
             patch.object(pipeline, 'require_trim_adoption'), \
             patch.object(pipeline, 'apply_lossless_trim'), \
             patch.object(pipeline, 'align', side_effect=align), \
             patch.object(pipeline, 'complete_semantics', side_effect=semantics):
            with self.assertRaises(DownstreamReached):
                pipeline.run_one({'slug': self.song.name, 'source': str(self.f.audio)}, self.f.options)
        self.assertEqual([name for name, _ in observed], ['timing', 'semantics'])
        self.assertEqual(observed[0][1], observed[1][1])
        self.assertEqual(observed[0][1]['packet']['verified_lines'][0]['roman'], 'anadino')
        self.assertEqual(observed[0][1]['packet']['metadata']['languages'], ['Punjabi'])
        self.assertEqual(self.original_path.read_bytes(), self.original_bytes)

    def test_generate_only_dispatch_uses_same_saved_view(self):
        self.declare()
        effective = reviewed.prepare(self.song, self.original)
        self.source_bound_semantic_fixture(effective)
        pipeline.write_json(self.packet_dir / '03-timing.json', {'sequence': []})
        root = self.song.parent
        (root / 'songs').mkdir(exist_ok=True)
        (root / 'songs' / self.song.name).symlink_to(self.song, target_is_directory=True)
        options = copy.copy(self.f.options)
        options.generate_only = True
        options.publish = True
        captures = []
        def generate(song, job, source, audited, timing, glosses, translations, **kwargs):
            reviewed.require_current(song, audited)
            captures.append(copy.deepcopy(audited))
        with patch.object(pipeline, 'ROOT', root), \
             patch.object(pipeline, 'preflight_blocked_reason', return_value=None), \
             patch.object(pipeline, 'write_catalogue'), \
             patch.object(pipeline, 'generate', side_effect=generate):
            status = pipeline._execute_intake_jobs(options, [{'slug': self.song.name}])
        self.assertEqual(status, 0)
        self.assertEqual(captures, [effective])
        self.assertEqual(self.original_path.read_bytes(), self.original_bytes)


    def test_segmented_overlay_holds_instead_of_trusting_file_hash(self):
        original = copy.deepcopy(self.original)
        original.pop('_source_route')
        original['segment_audits'] = [{'segment': {'index': 0}, 'audit': {'packet': {}}}]
        pipeline.write_json(self.original_path, original)
        value = self.declaration()
        value['original_audit_sha256'] = hashlib.sha256(self.original_path.read_bytes()).hexdigest()
        self.declare(value)
        with self.assertRaisesRegex(ValueError, 'reviewed source.*segment'):
            reviewed.prepare(self.song, original)
        original_bytes = self.original_path.read_bytes()
        root = self.song.parent
        (root / 'songs').mkdir(exist_ok=True)
        (root / 'songs' / self.song.name).symlink_to(self.song, target_is_directory=True)
        with patch.object(pipeline, 'ROOT', root), \
             patch.object(pipeline, 'intake', side_effect=DownstreamReached('unsupported original reached intake')):
            with self.assertRaisesRegex(ValueError, 'reviewed source.*segment'):
                pipeline.run_one({'slug': self.song.name, 'source': str(self.f.audio)}, self.f.options)
        self.assertEqual(self.original_path.read_bytes(), original_bytes)

    def test_active_overlay_blocks_source_refresh_before_original_deletion(self):
        self.declare()
        original = self.original_path.read_bytes()
        options = copy.copy(self.f.options)
        options.source_witness_audit = True
        root = self.song.parent
        (root / 'songs').mkdir(exist_ok=True)
        (root / 'songs' / self.song.name).symlink_to(self.song, target_is_directory=True)
        with patch.object(pipeline, 'ROOT', root), \
             patch.object(pipeline, 'intake', side_effect=DownstreamReached('source refresh reached acquisition')):
            with self.assertRaisesRegex(ValueError, 'reviewed source'):
                pipeline.run_one({'slug': self.song.name, 'source': str(self.f.audio)}, options)
        self.assertEqual(self.original_path.read_bytes(), original)

    def test_real_generation_uses_reviewed_language_over_stale_job_languages(self):
        self.check_generated_language(self.declaration(), ['Gurbani'])

    def test_roman_only_generation_preserves_valid_caller_language(self):
        self.check_generated_language(self.declaration(language=False), ['Punjabi'])

    def check_generated_language(self, declaration, job_languages):
        self.declare(declaration)
        effective = reviewed.prepare(self.song, self.original)
        root = self.song.parent
        (root / 'data').mkdir(exist_ok=True)
        for name in ('preserved_terms.json', 'source_credits.json', 'editorial_baselines.json'):
            (root / 'data' / name).write_bytes((pipeline.ROOT / 'data' / name).read_bytes())
        pipeline.write_json(root / 'data/song_tag_overrides.json', {'version': 1, 'songs': {}})
        pipeline.write_json(root / 'data/queue_numbers.json', {'schemaVersion': 1, 'numbers': {}})
        glosses = {'packet': {'glosses': [
            {'id': 'day', 'word_glosses': [{'roman': 'anadino', 'gloss': 'every day'}],
             'grammar_note': '', 'uncertainty': ''},
            {'id': 'name', 'word_glosses': [{'roman': 'nāmu', 'gloss': 'name'}],
             'grammar_note': '', 'uncertainty': ''}]}}
        translations = {'packet': {'translations': [
            {'id': lid, 'literal_english': english, 'segments': [{'text': english, 'word_indices': [0]}],
             'uncertainty': ''} for lid, english in [('day', 'Every day.'), ('name', 'Name.')]]}}
        pipeline.write_json(self.packet_dir / '05-translation.json', translations)
        timing = {'sequence': [{'ref': lid, 'start': float(i), 'end': float(i+1)}
                              for i, lid in enumerate(['day', 'name', 'day'])], 'validation_errors': []}
        job = {'slug': self.song.name, 'title': 'Fixture', 'languages': job_languages, 'subjectTags': []}
        snapshot = copy.deepcopy(job)
        with patch.object(pipeline, 'ROOT', root), \
             patch.object(pipeline, 'QUEUE_NUMBERS_PATH', root / 'data/queue_numbers.json'):
            pipeline.generate(self.song, job, {}, effective, timing, glosses, translations,
                              write_catalogue_after=False)
        data = pipeline.read_packet(self.song / '.transcription/language-review.json')
        self.assertEqual(data['song_languages'], ['Punjabi'])
        self.assertEqual(data['by_line_id'], {'day': 'pa', 'name': 'pa'})
        self.assertIn('"sourceLanguage": "pa"', (self.song / 'data.js').read_text())
        self.assertEqual(job, snapshot)
        self.assertEqual(self.original_path.read_bytes(), self.original_bytes)


    def test_old_registry_correction_holds_without_mutating_routed_audit(self):
        root = self.song.parent
        (root / 'songs').mkdir(exist_ok=True)
        (root / 'songs' / self.song.name).symlink_to(self.song, target_is_directory=True)
        pipeline.write_json(root / 'data/verified_text_corrections.json',
            {'version': 1, 'songs': {self.song.name: {'lines': {'day':
                {'roman': 'anadino', 'verification': 'Reviewed fixture correction.'}}}}})
        original = {p: p.read_bytes() for p in self.packet_dir.rglob('*.json')}
        with patch.object(pipeline, 'ROOT', root), \
             patch.object(pipeline, 'intake', return_value=(self.song, {})), \
             patch.object(pipeline, 'detect_youtube_trim', return_value={}), \
             patch.object(pipeline, 'require_trim_adoption'), \
             patch.object(pipeline, 'apply_lossless_trim'), \
             patch.object(pipeline, 'align', side_effect=DownstreamReached('legacy registry reached timing')):
            with self.assertRaisesRegex(ValueError, 'reviewed source.*migrat'):
                pipeline.run_one({'slug': self.song.name, 'source': str(self.f.audio)}, self.f.options)
        self.assertEqual({p: p.read_bytes() for p in original}, original)


if __name__ == '__main__':
    unittest.main()

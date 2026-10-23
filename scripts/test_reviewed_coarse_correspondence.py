"""Exact existing Patta map must bind complete performance order, not native guesses."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
import tempfile
import shutil
import argparse
import time
from unittest.mock import patch

import bhakti_pipeline as pipeline
import bhakti_library_source_pass as source
import prepare_library_review as readers

FIXTURE = Path(__file__).parent / 'fixtures/patta-reviewed-coarse.json'


class ReviewedCoarseTests(unittest.TestCase):
    def setUp(self):
        records = json.loads(FIXTURE.read_text(encoding='utf-8'))['files']
        self.inputs = {name: record['utf8'].encode('utf-8') for name, record in records.items()}
        for name, record in records.items():
            self.assertEqual(hashlib.sha256(self.inputs[name]).hexdigest(), record['sha256'], name)
        self.reader = readers.load_javascript(self.inputs['original-data.js'])
        self.audit = json.loads(self.inputs['02-transcript-audit.json'])
        self.mapping = json.loads(self.inputs['reviewed-source-map.json'])
        self.assertEqual(hashlib.sha256(self.inputs['original-data.js']).hexdigest(),
                         self.mapping['original_public_sha256'])
        self.assertEqual(hashlib.sha256(self.inputs['02-transcript-audit.json']).hexdigest(),
                         self.mapping['original_audit_sha256'])
        rebuilt=pipeline.merge_audited_segments(self.audit['segment_audits'])
        plan=source.plan_source(self.reader,rebuilt,reviewed_map=self.mapping)
        self.audit['packet']={**rebuilt,'verified_lines':plan['lines'],'performance_order':plan['performance_order']}
        self.occ=pipeline.display_occurrences(self.audit['packet'])
        self.duration=922.721

    def invoke(self):
        return pipeline.long_coarse_sequence(self.audit,self.occ,self.duration,
                                             reviewed_source_map=self.mapping)

    def test_actual_fifty_one_units_resolve_with_full_order_and_no_mutation(self):
        original=copy.deepcopy((self.audit,self.mapping,self.reader,self.occ))
        self.assertEqual(len(self.occ),51)
        self.assertEqual(sum(x['repeats'] for x in self.occ),59)
        self.assertEqual(len(self.audit['packet']['verified_lines']),34)
        result=self.invoke()
        self.assertEqual(len(result),51)
        self.assertEqual([(x['occurrence_id'],x['ref'],x['repeats']) for x in result],
                         [(x['occurrence_id'],x['ref'],x['repeats']) for x in self.occ])
        self.assertTrue(all(x['routing_only'] for x in result))
        self.assertEqual(original,(self.audit,self.mapping,self.reader,self.occ))
        self.assertEqual(result[15]['ref'],self.occ[15]['ref'])

    def test_same_native_text_without_reviewed_authority_does_not_bypass_original_failure(self):
        with self.assertRaisesRegex(RuntimeError,'unmatched'):
            pipeline.long_coarse_sequence(self.audit,self.occ,self.duration)

    def test_duplicate_missing_or_unknown_map_rows_reject(self):
        original=copy.deepcopy(self.mapping)
        for mode in ('duplicate','missing','unknown'):
            self.mapping=copy.deepcopy(original)
            if mode=='duplicate':self.mapping['mapping'].append(copy.deepcopy(self.mapping['mapping'][0]))
            elif mode=='missing':self.mapping['mapping'].pop()
            else:self.mapping['mapping'][0]['new_line_id']='unknown'
            with self.subTest(mode=mode),self.assertRaises((ValueError,RuntimeError)):self.invoke()

    def test_changed_audited_source_or_roman_rejects(self):
        for field in ('audited_source','audited_roman'):
            original=copy.deepcopy(self.mapping)
            self.mapping['mapping'][0][field]+=' changed'
            with self.subTest(field=field),self.assertRaises((ValueError,RuntimeError)):self.invoke()
            self.mapping=original

    def test_changed_native_display_or_baseline_does_not_gain_implicit_equivalence(self):
        for field in ('display','baseline'):
            old_occ,old_map=copy.deepcopy(self.occ),copy.deepcopy(self.mapping)
            if field=='display':self.occ[0]['source_text']='पत्ता बोला नदी से'
            else:self.mapping['mapping'][0]['baseline_line']['source']='पत्ता बोला नदी से'
            with self.subTest(field=field),self.assertRaises((ValueError,RuntimeError)):self.invoke()
            self.occ,self.mapping=old_occ,old_map

    def test_reordered_or_extra_duplicate_performance_rejects(self):
        original=copy.deepcopy(self.occ)
        for mode in ('reordered','duplicate','extra-repeat'):
            self.occ=copy.deepcopy(original)
            if mode=='reordered':self.occ[0],self.occ[1]=self.occ[1],self.occ[0]
            elif mode=='duplicate':self.occ.insert(1,copy.deepcopy(self.occ[0]))
            else:self.occ[0]['repeats']+=1
            with self.subTest(mode=mode),self.assertRaises((ValueError,RuntimeError)):self.invoke()

    def test_ambiguous_same_raw_surface_to_different_stable_id_rejects(self):
        duplicate=copy.deepcopy(self.mapping['mapping'][0])
        duplicate['new_line_id']='ambiguous-extra-raw-id'
        duplicate['old_line_id']='different-stable-id'
        self.mapping['mapping'].append(duplicate)
        # A malformed rebuilt packet with two raw IDs for one exact surface must
        # reach ambiguity validation, not fail merely because the extra ID is absent.
        rebuilt=pipeline.merge_audited_segments(self.audit['segment_audits'])
        raw=copy.deepcopy(rebuilt['verified_lines'][0]);raw['id']=duplicate['new_line_id']
        rebuilt['verified_lines'].append(raw)
        self.mapping['rebuilt_audit_sha256']=hashlib.sha256(
            (json.dumps(rebuilt,ensure_ascii=False,indent=2)+'\n').encode()).hexdigest()
        with patch.object(pipeline,'merge_audited_segments',return_value=rebuilt), \
             self.assertRaisesRegex(ValueError,'ambiguous'):
            self.invoke()

    def test_actual_source_adapter_forwards_only_validated_exact_map(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary);root=base/'input';workspace=base/'candidate';slug='patta-bola-vrksha-se'
            song=root/'songs'/slug;song.mkdir(parents=True)
            (song/'data.js').write_bytes(self.inputs['original-data.js'])
            (song/'index.html').write_text('<html>unchanged original</html>')
            (song/'audio.webm').write_bytes(b'input only; timing boundary is mocked')
            private=song/'.transcription/pipeline';private.mkdir(parents=True)
            for name in ('02-transcript-audit.json','03-timing.json'):
                (private/name).write_bytes(self.inputs[name])
            (root/'data').mkdir();(root/'data/editorial_baselines.json').write_text('{"version":1,"songs":{}}')
            shutil.copytree(root,workspace)
            map_path=base/'map.json';map_path.write_text(json.dumps(self.mapping,ensure_ascii=False))
            options=argparse.Namespace(model=pipeline.MODEL,pro_model='google/gemini-3.1-pro-preview',
                                      timeout=30,source_reuse_maps={slug:str(map_path)})
            captured=[]
            def capture(song,audited,audio,local):
                captured.append((copy.deepcopy(audited),copy.deepcopy(local.timing_reviewed_source_map)))
                raise ValueError('test stopped at timing boundary')
            def run():
                return source.run_source_candidate(root=root,slug=slug,reader=self.reader,
                    workspace=workspace,route_dir=base/'routes',options=options,deadline_at=time.time()+60)
            with patch.object(source,'process_new_targets',return_value={}), \
                 patch.object(source,'fresh_target_errors',return_value=[]), \
                 patch.object(pipeline,'align',side_effect=capture) as align, \
                 patch.object(pipeline.gemini,'call',side_effect=AssertionError('no API in forwarding regression')):
                result=run()
                self.assertEqual(align.call_count,1,result.get("issues"))
                self.assertEqual(captured[0][1],self.mapping)
                self.assertEqual(captured[0][0]['segment_audits'],self.audit['segment_audits'])
                self.assertEqual(len(captured[0][0]['packet']['performance_order']),59)
                changed=copy.deepcopy(self.mapping);changed['mapping'][0]['baseline_line']['english']='unreviewed change'
                map_path.write_text(json.dumps(changed,ensure_ascii=False));align.reset_mock()
                result=run();self.assertEqual(result['status'],'unresolved');align.assert_not_called()
                changed=copy.deepcopy(self.mapping);changed['rebuilt_audit_sha256']='0'*64
                map_path.write_text(json.dumps(changed,ensure_ascii=False))
                result=run();self.assertEqual(result['status'],'unresolved');align.assert_not_called()

    def test_changed_saved_segment_rejects_hash_before_routing(self):
        self.audit['segment_audits'][0]['audit']['packet']['lines'][0]['source_text']+=' अन्य'
        with self.assertRaises((ValueError,RuntimeError)):self.invoke()

if __name__=='__main__':unittest.main()

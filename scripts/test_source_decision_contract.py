"""Actual glossary request capture; no provider or native acquisition calls."""
import argparse
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import bhakti_pipeline as pipeline
import bhakti_source_discovery as discovery

FIXTURE = Path(__file__).parent/'fixtures/source_decision_contract/aruna.json'

class Captured(Exception):
    pass

class SourceDecisionContractTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text())
        self.discovery = copy.deepcopy(self.fixture['source_discovery'])
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.song = Path(self.tmp.name)
        self.options = argparse.Namespace(model='google/gemini-3.7-flash',force=False,timeout=60,
            gloss_batch_size=40,gloss_workers=1,max_attempts=1,
            automatic_source_discovery=self.discovery)
        self.audited = {'packet':{'verified_lines':self.fixture['lines'],
            'metadata':{'languages':['Tamil']},'performance_order':[]}}
        for mocked in (patch.dict(os.environ, {'BHAKTI_AUTO_LEXICAL':'0','BHAKTI_ENGLISH_DISCOVERY':'0'}),
                       patch.object(pipeline.gemini,'key',return_value='OFFLINE'),
                       patch.object(discovery,'acquire_source_candidates',side_effect=AssertionError('No acquisition permitted'))):
            mocked.start();self.addCleanup(mocked.stop)

    def capture(self):
        captured = {}
        def transport(model,key,prompt,**kwargs):
            captured.update(prompt=prompt,schema=kwargs['response_schema'],schema_name=kwargs['schema_name'])
            raise Captured()
        with patch.object(pipeline.gemini,'call',side_effect=transport) as call:
            with self.assertRaises(Captured): pipeline.gloss(self.song,self.audited,self.options)
        self.assertEqual(call.call_count,1)
        self.assertEqual(captured['schema_name'],'bhakti_word_glosses')
        return captured

    @staticmethod
    def parsed(prompt,marker):
        return json.JSONDecoder().raw_decode(prompt.split(marker,1)[1].lstrip())[0]

    def decision_schema(self,captured):
        row=captured['schema']['properties']['glosses']['items']
        self.assertIn('source_discovery_decisions',row['required'])
        return row['properties']['source_discovery_decisions']

    def pairs_from_schema(self,schema):
        pairs=set()
        for branch in schema['items']['anyOf']:
            fields=branch['properties']
            self.assertEqual(set(branch['required']),set(fields))
            self.assertFalse(branch['additionalProperties'])
            for target in fields['target_id']['enum']:
                for entry in fields['entry_id']['enum']:pairs.add((target,entry))
        return pairs

    def test_actual_mixed_gloss_request_names_only_two_real_pairs_and_keeps_misses(self):
        captured=self.capture(); expected={(self.discovery['targets'][0]['id'],entry)
            for entry in self.discovery['targets'][0]['candidate_entry_ids']}
        pairs=self.parsed(captured['prompt'],'SOURCE DECISION PAIRS:\n')
        self.assertEqual({(row['target_id'],row['entry_id']) for row in pairs},expected)
        self.assertEqual(self.pairs_from_schema(self.decision_schema(captured)),expected)
        self.assertEqual(self.decision_schema(captured)['maxItems'],2)
        delivered=self.parsed(captured['prompt'],'SOURCE GLOSS EVIDENCE:\n')
        self.assertEqual(delivered['targets'],self.discovery['targets'])
        self.assertEqual(delivered['gaps'],self.discovery['gaps'])
        self.assertIn('zero decisions',captured['prompt'])
        self.assertIn('lexical_queries',captured['prompt'])
        self.assertIn('source_queries',captured['prompt'])

    def test_all_miss_requires_empty_array_without_erasing_source_gap(self):
        self.discovery['targets']=[row for row in self.discovery['targets'] if not row['candidate_entry_ids']]
        self.discovery['entries']=[];self.discovery['evidence']=[];self.discovery['entry_evidence_ids']={}
        before=copy.deepcopy(self.discovery);captured=self.capture()
        schema=self.decision_schema(captured)
        self.assertEqual(schema['type'],'array');self.assertEqual(schema['maxItems'],0)
        self.assertEqual(schema['items']['type'],'object')
        self.assertNotIn('anyOf',schema['items'])
        self.assertTrue(all('enum' not in field or field['enum'] for field in schema['items']['properties'].values()))
        base={'type':'object','properties':{'translations':{'items':{'type':'object','properties':{'id':{'type':'string'}},'required':['id']}}}}
        original=copy.deepcopy(base)
        self.assertEqual(discovery.extend_schema(base,argparse.Namespace()),original)
        self.assertEqual(base,original)
        self.assertEqual(self.parsed(captured['prompt'],'SOURCE DECISION PAIRS:\n'),[])
        delivered=self.parsed(captured['prompt'],'SOURCE GLOSS EVIDENCE:\n')
        self.assertEqual(delivered['targets'],before['targets']);self.assertEqual(delivered['gaps'],before['gaps'])
        self.assertEqual(self.discovery,before)
        self.assertEqual(discovery.gloss_decision_errors(before,[{'id':row['id'],'source_discovery_decisions':[]}
            for row in self.fixture['lines']]),[])

    def test_schema_preserves_pair_relation_not_target_entry_cross_product(self):
        # Synthetic protocol-only extra target; no linguistic judgment is claimed.
        target=copy.deepcopy(self.discovery['targets'][0]);target['id']='synthetic-second-target'
        entry=copy.deepcopy(self.discovery['entries'][0]);entry['entry_id']='synthetic-second-entry'
        target['candidate_entry_ids']=[entry['entry_id']]
        self.discovery['targets'].append(target);self.discovery['entries'].append(entry)
        self.discovery['entry_evidence_ids'][entry['entry_id']]=[]
        captured=self.capture();pairs=self.pairs_from_schema(self.decision_schema(captured))
        expected={(row['id'],eid) for row in self.discovery['targets'] for eid in row['candidate_entry_ids']}
        self.assertEqual(pairs,expected)
        self.assertNotIn((target['id'],self.discovery['entries'][0]['entry_id']),pairs)

    def test_exact_failed_response_stays_rejected_and_saved_unchanged(self):
        fixture_bytes=FIXTURE.read_bytes()
        raw=self.fixture['failed_packet']; before=copy.deepcopy(raw)
        self.assertTrue(discovery.gloss_decision_errors(self.discovery,raw['glosses']))
        with patch.object(pipeline.gemini,'call',return_value={'packet':copy.deepcopy(raw)}) as call:
            with self.assertRaises((ValueError,RuntimeError)):
                pipeline.gloss(self.song,self.audited,self.options)
        self.assertEqual(call.call_count,1)
        saved=json.loads((self.song/'.transcription/pipeline/gloss-candidate.json').read_text())
        self.assertEqual(saved['packet'],before)
        self.assertEqual(FIXTURE.read_bytes(),fixture_bytes)
        self.assertEqual(self.fixture['failed_packet'],before)

    def test_real_pair_unresolved_remains_a_hold(self):
        target=self.discovery['targets'][0]
        rows=copy.deepcopy(self.fixture['failed_packet']['glosses'])
        # A separate synthetic control: exactly the supplied real pairs, one unresolved.
        for row in rows:
            row['source_discovery_decisions']=[d for d in row['source_discovery_decisions']
                if d['entry_id'] in target['candidate_entry_ids']]
        decision=next(d for row in rows for d in row['source_discovery_decisions'])
        decision['status']='unresolved';decision['relation_kind']='unresolved'
        errors=discovery.gloss_decision_errors(self.discovery,rows)
        self.assertTrue(any('source glossary relation unresolved' in error for error in errors))

    def repeated_population(self, count):
        original=next(line for line in self.fixture['lines'] if line['id']=='line-004')
        original_gloss=next(row for row in self.fixture['failed_packet']['glosses'] if row['id']=='line-004')
        lines=[];glosses=[];targets=[]
        for index in range(count):
            line=copy.deepcopy(original);line['id']='fixture-'+str(index);lines.append(line)
            row=copy.deepcopy(original_gloss);row['id']=line['id'];glosses.append(row)
            target=copy.deepcopy(self.discovery['targets'][0])
            target['id']='target-'+str(index);target['line_id']=line['id'];targets.append(target)
        self.discovery['targets']=targets
        self.discovery['gaps']=[{'kind':'source_lookup_miss','line_id':line['id'],
            'detail':'Synthetic per-line capture control; no semantic judgment.'} for line in lines]
        self.audited['packet']['verified_lines']=lines
        self.options.semantic_full_source=lines
        return {'packet':{'glosses':glosses}}

    def test_gloss_41_line_batches_project_schema_to_actual_20_20_and_1_targets(self):
        glossary=self.repeated_population(41);captured=[];before=copy.deepcopy(self.discovery)
        by_id={row['id']:row for row in glossary['packet']['glosses']}
        def transport(model,key,prompt,**kwargs):
            captured.append({'prompt':prompt,'schema':kwargs['response_schema']})
            lines=self.parsed(prompt,'TARGET LYRICS (return these IDs only):\n')
            if len(lines)==1:raise Captured()
            rows=[]
            for line in lines:
                row=copy.deepcopy(by_id[line['id']])
                target=next(t for t in self.discovery['targets'] if t['line_id']==line['id'])
                row['source_discovery_decisions']=[{'target_id':target['id'],'entry_id':entry,
                    'status':'rejected','attested_form':'','quotation':'','relation_kind':'unresolved',
                    'meaning_applied':'','form_explanation':'','changes_gloss':False,
                    'reason':'Synthetic dispatch fixture: entry is rejected, not a linguistic adjudication.'}
                    for entry in target['candidate_entry_ids']]
                rows.append(row)
            return {'packet':{'glosses':rows}}
        with patch.object(pipeline.gemini,'call',side_effect=transport):
            with self.assertRaises(Captured): pipeline.gloss(self.song,self.audited,self.options)
        self.assertEqual(len(captured),3)
        self.assertEqual(self.discovery,before)
        populations=[]
        for request in captured:
            lines=self.parsed(request['prompt'],'TARGET LYRICS (return these IDs only):\n')
            ids={line['id'] for line in lines};populations.append(len(ids))
            expected={(target['id'],entry) for target in self.discovery['targets']
                if target['line_id'] in ids for entry in target['candidate_entry_ids']}
            schema=self.decision_schema(request)
            self.assertEqual(self.pairs_from_schema(schema),expected)
            self.assertEqual(len(schema['items']['anyOf']),len(ids))
            delivered=self.parsed(request['prompt'],'SOURCE GLOSS EVIDENCE:\n' if 'glosses' in request['schema']['properties'] else 'SOURCE DISCOVERY EVIDENCE:\n')
            self.assertEqual(delivered['gaps'],[gap for gap in before['gaps'] if gap['line_id'] in ids])
        self.assertEqual(sorted(populations),[1,20,20])

    def test_writer_11_line_children_project_schema_to_actual_10_and_1_targets(self):
        glossary=self.repeated_population(11);captured=[];before=copy.deepcopy(self.discovery)
        def transport(model,key,prompt,**kwargs):
            self.assertEqual(kwargs['schema_name'],'bhakti_translation_batch')
            captured.append({'prompt':prompt,'schema':kwargs['response_schema']})
            lines=self.parsed(prompt,'TARGET audited source lines (return these IDs only):\n')
            if len(lines)==1:raise Captured()
            # Only ID arrays advance the existing child dispatcher to its last
            # request. These are not accepted writer/content fixtures.
            return {'packet':{'translations':[{'id':line['id']} for line in lines],
                              'comparison':[{'id':line['id']} for line in lines]}}
        with patch.object(pipeline.gemini,'call',side_effect=transport):
            with self.assertRaises(Captured):
                pipeline.translate(self.song,self.audited,glossary,{'languages':['Tamil']},
                                   self.options,candidate_only=True,defer_review=True)
        self.assertEqual(len(captured),2)
        self.assertEqual(self.discovery,before)
        populations=[]
        for request in captured:
            lines=self.parsed(request['prompt'],'TARGET audited source lines (return these IDs only):\n')
            ids={line['id'] for line in lines};populations.append(len(ids))
            schema=request['schema']['properties']['translations']['items']['properties']['source_discovery_decisions']
            expected={(target['id'],entry) for target in self.discovery['targets']
                if target['line_id'] in ids for entry in target['candidate_entry_ids']}
            self.assertEqual(self.pairs_from_schema(schema),expected)
            self.assertEqual(len(schema['items']['anyOf']),len(ids))
            delivered=self.parsed(request['prompt'],'SOURCE GLOSS EVIDENCE:\n' if 'glosses' in request['schema']['properties'] else 'SOURCE DISCOVERY EVIDENCE:\n')
            self.assertEqual(delivered['gaps'],[gap for gap in before['gaps'] if gap['line_id'] in ids])
        self.assertEqual(populations,[10,1])

if __name__=='__main__':unittest.main()

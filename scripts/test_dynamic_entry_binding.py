"""Saved real glossary references; actual parsers/preparation, no model or HTTP calls."""
import argparse
import copy
import json
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

import bhakti_pipeline as pipeline
import bhakti_lexical_producer as producer
import bhakti_source_discovery as discovery
import bhakti_translation_policy as policy
import dictionary_corpus as corpus
from test_lexical_support import fixture

FIX=Path(__file__).parent/'fixtures/dynamic_entry_binding'

class Capture(Exception): pass

class DynamicSourceEntryBindings(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);_,_,self.wn=fixture(self.root)
        # All original WordNet senses at exact byte offsets for these real queries.
        subset=json.loads((FIX/'wordnet.json').read_text());data_hashes={};index_hashes={}
        for pos,rows in subset['files'].items():
            index=self.wn/('index.'+pos);data=self.wn/('data.'+pos)
            index.write_text(rows['header']+''.join(rows['index_rows']))
            with data.open('wb') as stream:
                stream.write(rows['header'].encode())
                for row in rows['data_rows']:stream.seek(row['offset']);stream.write(row['raw'].encode())
            data_hashes[pos]=hashlib.sha256(data.read_bytes()).hexdigest()
            index_hashes[pos]=hashlib.sha256(index.read_bytes()).hexdigest()
        (self.wn/'manifest.json').write_text(json.dumps({'edition':'3.1','available_pos':list(subset['files']),
            'complete_for_lemmas':subset['complete_for_lemmas'],'source':subset['data_source'],
            'data_sha256':data_hashes,'index_sha256':index_hashes}))
        self.original=json.loads((FIX/'saved-cases.json').read_text())
        self.cases=copy.deepcopy(self.original)
        self.cache=self.root/'lookup'
        shutil.copytree(FIX/'source-discovery',self.cache/'source-discovery')
        self.lexicon=self.root/'lexicon.json';self.lexicon.write_text('{"version":1,"entries":[]}')
        env={'BHAKTI_AUTO_LEXICAL':'1','BHAKTI_ENGLISH_DISCOVERY':'0','BHAKTI_WORDNET_DIR':str(self.wn),
            'BHAKTI_WORDNET_EDITION':'3.1','BHAKTI_LEXICAL_SUPPORT_CACHE':str(self.cache),
            'BHAKTI_LEXICON_PATH':str(self.lexicon),'BHAKTI_LEXICAL_INDEX':'',
            'BHAKTI_SOURCE_WITNESS_ROOTS':json.dumps([str(self.cache/'source-discovery'/name) for name in ('platts-hi','singh-pa')])}
        for manager in (patch.dict(os.environ,env),patch.object(pipeline.gemini,'key',return_value='OFFLINE'),
                patch.object(pipeline.gemini,'call',side_effect=AssertionError('No model calls')),
                patch.object(corpus.urllib.request,'urlopen',side_effect=AssertionError('No source HTTP'))):
            manager.start();self.addCleanup(manager.stop)

    def configure(self,name):
        case=self.cases[name];audit=case['audited'];gloss=case['glosses'];lines=audit['packet']['verified_lines']
        options=argparse.Namespace(model=pipeline.MODEL,force=False,timeout=10,source_discovery_max_requests=0,
            semantic_full_source=lines,semantic_performance_order=audit['packet'].get('performance_order',[]))
        options.lexical_requested_spans=[{'line_id':row['id'],'word_indices':q['word_indices'],'surfaces':q['surfaces'],'reason':q['reason']}
            for row in gloss['packet']['glosses'] for q in row.get('lexical_queries',[])]
        options.source_discovery_budget=discovery.configure_run_budget(self.root/name,time.time()+60,options)
        proposals=[{'line_id':row['id'],**q} for row in gloss['packet']['glosses'] for q in row.get('lexical_queries',[])]
        plan=discovery.source_lookup_plan(lines,proposals,audit['packet']['metadata']['languages'])
        packet=discovery.acquire_source_candidates(plan,self.cache/'source-discovery',max_new_requests=0,
            run_budget=options.source_discovery_budget,opener=lambda *a,**k: (_ for _ in ()).throw(AssertionError('No HTTP')))
        self.assertEqual(discovery.pending_gloss_lines(packet,gloss),[])
        self.assertEqual(discovery.gloss_decision_errors(packet,gloss['packet']['glosses']),[])
        return audit,gloss,options,packet

    def test_saved_real_ids_prepare_and_reach_writer_and_reviewer_without_selecting_rejected_senses(self):
        for name in self.cases:
            with self.subTest(case=name):
                audit,gloss,options,packet=self.configure(name)
                before=copy.deepcopy((audit,gloss,packet))
                local,view=producer.prepare_translation(self.root/name,audit,gloss,options)
                expected={entry['entry_id'] for entry in packet['entries']}
                self.assertEqual({entry['entry_id'] for entry in local.automatic_source_discovery['entries']},expected)
                self.assertEqual(local.automatic_source_discovery['entries'],packet['entries'])
                self.assertEqual(local.automatic_source_discovery['entry_evidence_ids'],packet['entry_evidence_ids'])
                self.assertTrue(expected)
                for old,new in zip(gloss['packet']['glosses'],view['packet']['glosses']):
                    self.assertEqual(new['lexical_queries'],old['lexical_queries'])
                    self.assertEqual(new.get('source_discovery_decisions'),old.get('source_discovery_decisions'))
                    self.assertEqual(new['sense_decisions'],old['sense_decisions'])
                    self.assertTrue(all(not decision['used_evidence_ids'] for decision in new.get('support_decisions',[])))
                prompts=[]
                def capture(model,key,prompt,**kwargs):prompts.append((kwargs['schema_name'],prompt));raise Capture()
                with patch.object(pipeline.gemini,'call',side_effect=capture):
                    with self.assertRaises(Capture):pipeline.translate(self.root/name/'writer',audit,gloss,
                        {'languages':audit['packet']['metadata']['languages']},options,defer_review=True)
                    drafts=[{'id':row['id'],'literal_english':'Fixture.',
                        'segments':[{'text':'Fixture.','word_indices':list(range(len(row['word_glosses'])))}],
                        'source_discovery_decisions':copy.deepcopy(row.get('source_discovery_decisions',[]))}
                        for row in view['packet']['glosses']]
                    with self.assertRaises(Capture):pipeline.independently_review_translations(self.root/name/'review',
                        audit['packet']['verified_lines'],view['packet']['glosses'],drafts,'(none supplied)',local,
                        languages=audit['packet']['metadata']['languages'])
                self.assertEqual([kind for kind,_ in prompts],['bhakti_literal_translation','bhakti_translation_review'])
                for _,prompt in prompts:
                    delivered=json.JSONDecoder().raw_decode(prompt.split('SOURCE DISCOVERY EVIDENCE:\n',1)[1].lstrip())[0]
                    self.assertEqual({entry['entry_id'] for entry in delivered['entries']},expected)
                    for entry in packet['entries']:
                        self.assertEqual(next(e for e in delivered['entries'] if e['entry_id']==entry['entry_id'])['dictionary']['whole_entry_text'],entry['dictionary']['whole_entry_text'])
                if name.startswith('koi'):
                    choices=view['packet']['glosses'][-1]['source_discovery_decisions']
                    self.assertEqual([d['status'] for d in choices],['matched','rejected','rejected'])
                    self.assertEqual(len(expected),3)
                self.assertEqual((audit,gloss,packet),before)
                self.assertEqual(json.loads(Path(options.source_discovery_budget['path']).read_text())['requests_started'],0)
        self.assertEqual(self.cases,self.original)

    def test_wrong_binding_and_unknown_ids_still_fail_before_english_lookup(self):
        for name in self.cases:
            audit,gloss,options,packet=self.configure(name)
            lines=audit['packet']['verified_lines'];languages=audit['packet']['metadata']['languages']
            bindings=policy.token_candidates(lines,languages)
            self.assertTrue(all(not token['candidates'] for row in bindings.values() for token in row))
            for defect in ('unknown','line','span','target-language','entry-language','absent'):
                with self.subTest(case=name,defect=defect):
                    rows=copy.deepcopy(gloss['packet']['glosses']);bad=copy.deepcopy(packet)
                    if defect=='unknown':next(row for row in rows if row['lexical_queries'])['lexical_queries'][0]['source_entry_ids'].append('invented.dictionary.entry')
                    elif defect=='line':bad['targets'][0]['line_id']=lines[0]['id']
                    elif defect=='span':bad['targets'][0]['word_indices']=[0];bad['targets'][0]['surfaces']=[policy.word_tokens(lines[-1])[0]]
                    elif defect=='target-language':bad['targets'][0]['source_language']='sa'
                    elif defect=='entry-language':bad['entries'][0]['language']='sa'
                    elif defect=='absent':bad=None
                    with patch.object(producer,'lookup_english_cached',side_effect=AssertionError('Must reject before English lookup')) as lookup:
                        with self.assertRaisesRegex(ValueError,'bound|language|source|entry'):
                            producer.produce_support(lines,rows,languages,token_candidates=bindings,
                                acquisition_roots=[],wordnet_directory=self.wn,edition='3.1',cache_dir=self.cache,
                                context_lines=lines,performance_order=audit['packet'].get('performance_order',[]),source_discovery=bad)
                        self.assertEqual(lookup.call_count,0)

if __name__=='__main__':unittest.main()

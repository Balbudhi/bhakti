"""Actual audited-word map and unchanged Platts HTTP fixtures; no live calls.

Review-stage tests for the native planning/acquisition/decision prerequisite.
No parser mocks; the opener supplies genuine saved response bytes only.
"""
import copy
import importlib
import io
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from urllib.parse import parse_qs,urlparse

import dictionary_corpus as corpus

FIX=Path(__file__).parent/'fixtures/source_discovery'

class SourceDiscoveryRequirements(unittest.TestCase):
    def setUp(self):
        self.discovery=importlib.import_module('bhakti_source_discovery')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.line=json.loads((FIX/'song-line.json').read_text())
        self.proposal={'line_id':self.line['id'],'word_indices':[3],'surfaces':['bajaraṅga'],
            'source_queries':['वज्र'],'reason':'Investigate the actual compound without choosing a meaning.'}
        self.records={r['query']:r for r in json.loads((FIX/'acquisition.json').read_text())}
        self.calls=[]
        self.budget={'path':self.root/'run-budget.json','max_requests':3,'deadline_at':time.time()+60}
    def opener(self,url,timeout):
        parsed=urlparse(url);params=parse_qs(parsed.query)
        self.assertEqual(parsed.netloc,'dsal.uchicago.edu')
        self.assertEqual(params['matchtype'],['exact'])
        self.assertEqual(params['searchhws'],['yes'])
        query=params['qs'][0];self.calls.append(query)
        return io.BytesIO(corpus.load_cached_witness(FIX,self.records[query]))
    def plan(self):
        return self.discovery.source_lookup_plan([self.line],[self.proposal],['Hindi'])
    def start_budget(self):
        if not getattr(self, 'budget_initialized', False):
            self.budget=self.discovery.configure_run_budget(self.root,self.budget['deadline_at'],
                SimpleNamespace(source_discovery_max_requests=self.budget['max_requests']))
            self.budget_initialized=True

    def acquire(self):
        self.start_budget()
        return self.discovery.acquire_source_candidates(self.plan(),self.root,opener=self.opener,max_new_requests=3,timeout=1,run_budget=self.budget)

    def test_native_first_comes_from_actual_audited_word_map(self):
        before=copy.deepcopy(self.line)
        plan=self.plan();self.assertEqual(plan['gaps'],[])
        target=plan['targets'][0]
        self.assertEqual(target['word_indices'],[3]);self.assertEqual(target['surfaces'],['bajaraṅga'])
        self.assertEqual(target['source_language'],'hi')
        self.assertEqual(target['queries'],[{'text':'बजरंग','origin':'native_surface'},
                                            {'text':'वज्र','origin':'model_hypothesis'}])
        self.assertEqual(self.line,before)

    def test_transcript_without_native_map_keeps_explicit_query_as_hypothesis(self):
        # Actual fresh audited transcript shape, not a reader-only word map.
        self.line={key:self.line[key] for key in ('id','source_text','roman','sourceLanguage','kind')}
        plan=self.plan()
        self.assertEqual(plan['gaps'][0]['kind'],'native_mapping_missing')
        self.assertEqual(plan['targets'][0]['queries'],[{'text':'वज्र','origin':'model_hypothesis'}])
        self.assertEqual(plan['targets'][0]['surfaces'],['bajaraṅga'])
        self.assertEqual(self.calls,[])

    def test_no_native_map_and_no_explicit_query_retains_gap_without_inventing_form(self):
        self.line.pop('sourceWords');self.proposal['source_queries']=[]
        plan=self.plan()
        self.assertEqual(plan['gaps'][0]['kind'],'native_mapping_missing')
        self.assertEqual(plan['targets'],[])
        self.assertEqual(self.calls,[])

    def test_punjabi_surface_does_not_silently_query_hindi_dictionary(self):
        self.line['sourceLanguage']='pa'
        plan=self.plan()
        self.assertEqual(plan['targets'][0]['dictionary_id'],'singh1895')
        self.assertEqual(plan['targets'][0]['source_language'],'pa')
        self.assertFalse(plan['gaps'])

    def test_unsupported_language_retains_adapter_gap_without_fallback(self):
        self.line['sourceLanguage']='vi'
        plan=self.plan()
        self.assertEqual(plan['gaps'][0]['kind'],'source_adapter_unavailable')
        self.assertEqual(plan['targets'],[])

    def test_query_limit_and_source_identity_fail_before_network(self):
        self.proposal['source_queries']=['वज्र','bajra','bajr']
        with self.assertRaises(ValueError):self.plan()
        self.proposal['source_queries']=['वज्र'];self.proposal['surfaces']=['vajra']
        with self.assertRaises(ValueError):self.plan()
        self.assertEqual(self.calls,[])

    def test_real_native_miss_then_compound_entry_remains_hypothesis_and_reuses_cache(self):
        before=copy.deepcopy(self.line)
        first=self.acquire();count=len(self.calls)
        second=self.acquire()
        self.assertEqual(self.calls,['बजरंग','वज्र']);self.assertEqual(count,2)
        self.assertEqual(first,second);self.assertEqual(self.line,before)
        self.assertEqual(len(first['entries']),1)
        entry=first['entries'][0]
        self.assertEqual(entry['source_spellings'],['वज्र'])
        self.assertNotIn('बजरंग',entry['source_spellings'])
        self.assertIn('bajr-ang',entry['dictionary']['whole_entry_text'])
        self.assertIn('Having a hardy frame',entry['dictionary']['whole_entry_text'])
        target=first['targets'][0]
        self.assertEqual(target['candidate_entry_ids'],[entry['entry_id']])
        self.assertEqual(target['selection_status'],'lookup_hypothesis')
        self.assertEqual(target['observations'][0]['status'],'witnessed_miss')
        self.assertTrue(target['observations'][0]['witness_sha256'])

    def test_similar_spelling_boat_result_is_not_a_song_alias_or_selected_meaning(self):
        self.proposal['source_queries']=['bajra']
        result=self.acquire()
        self.assertEqual(len(result['entries']),2)
        self.assertTrue(any('boat' in entry['dictionary']['whole_entry_text'] for entry in result['entries']))
        self.assertEqual(result['targets'][0]['selection_status'],'lookup_hypothesis')
        self.assertEqual(set(result['targets'][0]['candidate_entry_ids']),{entry['entry_id'] for entry in result['entries']})
        for entry in result['entries']:
            self.assertNotIn('बजरंग',entry['source_spellings'])
            self.assertNotIn('bajaraṅga',entry['roman_search_aliases'])

    def test_transport_failure_is_not_a_lexical_miss(self):
        def unavailable(url,timeout):raise OSError('fixture transport failure')
        self.start_budget()
        result=self.discovery.acquire_source_candidates(self.plan(),self.root,opener=unavailable,max_new_requests=3,timeout=1,run_budget=self.budget)
        self.assertEqual(result['entries'],[])
        self.assertTrue(result['gaps'])
        self.assertTrue(all(gap['kind']=='source_transport_error' for gap in result['gaps']))
        self.assertFalse(any(obs['status']=='witnessed_miss' for target in result['targets'] for obs in target['observations']))

    def test_exhausted_free_request_budget_is_explicit_not_silent_truncation(self):
        self.start_budget()
        result=self.discovery.acquire_source_candidates(self.plan(),self.root,opener=self.opener,max_new_requests=1,timeout=1,run_budget=self.budget)
        self.assertEqual(self.calls,['बजरंग'])
        self.assertEqual(result['entries'],[])
        self.assertTrue(any(gap['kind']=='source_discovery_budget' for gap in result['gaps']))

    def test_same_run_quota_survives_sequential_calls_and_cached_hits_are_free(self):
        self.budget['max_requests']=2
        self.acquire();self.assertEqual(self.calls,['बजरंग','वज्र'])
        self.acquire();self.assertEqual(self.calls,['बजरंग','वज्र'])
        self.proposal['source_queries']=['bajra']
        result=self.acquire()
        self.assertEqual(self.calls,['बजरंग','वज्र'])
        self.assertTrue(any(gap['kind']=='source_discovery_budget' for gap in result['gaps']))

    def test_concurrent_different_cache_targets_share_global_request_quota(self):
        from concurrent.futures import ThreadPoolExecutor
        self.budget['max_requests']=1
        self.line.pop('sourceWords')
        first=self.plan();self.proposal['source_queries']=['bajra'];second=self.plan()
        def run(item):
            number,plan=item
            return self.discovery.acquire_source_candidates(plan,self.root/str(number),opener=self.opener,
                max_new_requests=3,timeout=1,run_budget=self.budget)
        self.start_budget()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(run,enumerate([first,second])))
        self.assertEqual(len(self.calls),1)
        self.assertEqual(sum(any(gap['kind']=='source_discovery_budget' for gap in result['gaps']) for result in results),1)

    def test_run_deadline_prevents_next_fetch_but_not_cached_evidence(self):
        clock=[99.0];self.budget['deadline_at']=100.0;timeouts=[]
        def advance(url,timeout):
            timeouts.append(timeout);result=self.opener(url,timeout);clock[0]=101.0;return result
        self.start_budget()
        with patch.object(self.discovery.time,'time',side_effect=lambda:clock[0]):
            result=self.discovery.acquire_source_candidates(self.plan(),self.root,opener=advance,
                max_new_requests=3,timeout=15,run_budget=self.budget)
            self.proposal['source_queries']=[]
            cached=self.acquire()
        self.assertEqual(self.calls,['बजरंग'])
        self.assertEqual(timeouts,[1.0])
        self.assertTrue(any(gap['kind']=='source_discovery_deadline' for gap in result['gaps']))
        self.assertEqual(cached['targets'][0]['observations'][0]['status'],'witnessed_miss')

    def test_existing_run_limits_cannot_be_reset_on_resume(self):
        self.acquire()
        self.budget['max_requests']=30
        self.proposal['source_queries']=['bajra']
        with self.assertRaisesRegex(ValueError,'budget|identity|limit'):
            self.acquire()
        self.assertEqual(self.calls,['बजरंग','वज्र'])

    def test_compound_relation_must_cite_actual_subentry_not_just_root_gloss(self):
        result=self.acquire();target=result['targets'][0];entry=result['entries'][0]
        quote='vajrāng (˚ra+an˚), vulg. vajr-ang, bajr-ang, adj. & s.m. Having a hardy frame, hardy; — an epithet of Hauumān; — a robust or hardy man'
        self.assertIn(quote,entry['dictionary']['whole_entry_text'])
        decision={'target_id':target['id'],'entry_id':entry['entry_id'],'status':'matched',
            'attested_form':'bajr-ang','quotation':quote,'relation_kind':'compound_subentry',
            'meaning_applied':'having a hardy frame','changes_gloss':False,
            'reason':'Model proposal requiring independent source-form and semantic review.'}
        self.assertEqual(self.discovery.discovery_decision_errors(result,[decision]),[])
        wrong=copy.deepcopy(decision);wrong['quotation']='Hard, adamantine'
        self.assertTrue(self.discovery.discovery_decision_errors(result,[wrong]))
        wrong=copy.deepcopy(decision);wrong['relation_kind']='exact_form'
        self.assertTrue(self.discovery.discovery_decision_errors(result,[wrong]))
        wrong=copy.deepcopy(decision);wrong['entry_id']='invented-source'
        self.assertTrue(self.discovery.discovery_decision_errors(result,[wrong]))
        self.assertTrue(self.discovery.discovery_decision_errors(result,[]))

if __name__=='__main__':unittest.main()

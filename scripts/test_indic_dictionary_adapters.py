"""Review-first dictionary contracts using exact saved official HTML, no network/model calls."""
import copy
import html
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import tempfile
import time
from types import SimpleNamespace
import unittest
from urllib.parse import parse_qs,urlparse

import dictionary_corpus as corpus
import bhakti_lexical_producer as producer
import bhakti_source_discovery as source

HERE=Path(__file__).parent/'fixtures'/'indic-dictionaries'
RECORDS=json.loads((HERE/'research-responses.json').read_text())
IDS={'singh':'singh1895','tamil-lex':'madras-tamil-lexicon'}
LANG={'singh':'pa','tamil-lex':'ta'}
WORK={'singh':'Bhai Maya Singh','tamil-lex':'University of Madras'}

def witness(query):return next(row for row in RECORDS if row['query']==query)
def raw(query):return (HERE/witness(query)['path']).read_bytes()

def parse(term,**changes):
    row=witness(term)
    args={'query':term,'url':row['url'],'witness_sha256':row['sha256']};args.update(changes)
    return corpus.parse_dictionary_html(IDS[row['adapter']],raw(term).decode(),**args)

class TextOnly(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[]
    def handle_data(self,data):self.parts.append(data)

def expected_bodies(query):
    # Independent body-only observation: no headword/page/adapter logic. Assert
    # whole entry text survives the structured parser, including every final sense.
    bodies=re.findall(r"<div class=['\"]px-4['\"]>(.*?)</div>",raw(query).decode(),re.S)
    results=[]
    for body in bodies:
        parser=TextOnly();parser.feed(body);parser.close()
        results.append(' '.join(''.join(parser.parts).split()))
    return results

class ActualDictionaryParsers(unittest.TestCase):
    def test_punjabi_entries_keep_entire_definition_and_canonical_citation(self):
        for query,page in [('ਰਸ',957),('ਆਧਾਰ',8)]:
            with self.subTest(query=query):
                rows=parse(query);self.assertEqual(len(rows),1)
                entry=rows[0];self.assertEqual(entry['language'],'pa')
                self.assertIn(query,entry['source_spellings'])
                self.assertEqual(entry['dictionary']['print_page'],page)
                self.assertIn('Bhai Maya Singh',entry['dictionary']['work'])
                self.assertIn('singh_query.py',entry['dictionary']['url'])
                self.assertEqual(entry['dictionary']['whole_entry_text'],expected_bodies(query)[0])
                self.assertTrue(all(s['selection_status']=='unselected' for s in entry['senses']))
                self.assertEqual(entry['dictionary']['witness_sha256'],witness(query)['sha256'])
        self.assertIn('To become juicy, to sweeten and mellow.',parse('ਰਸ')[0]['dictionary']['whole_entry_text'])
        self.assertIn('a patron, a supporter',parse('ਆਧਾਰ')[0]['dictionary']['whole_entry_text'])

    def test_exact_sung_inflections_remain_misses_not_silent_stemming(self):
        for query in ['ਰਸੁ','ਆਧਾਰੇ','ਹਰਿ','அகமும்']:
            with self.subTest(query=query):self.assertEqual(parse(query),[])

    def test_tamil_all_seven_homographs_and_supplement_locus_survive(self):
        entries=parse('அகம்');self.assertEqual(len(entries),7)
        self.assertEqual(len({e['entry_id'] for e in entries}),7)
        self.assertEqual([e['dictionary']['whole_entry_text'] for e in entries],expected_bodies('அகம்'))
        self.assertTrue(all(e['language']=='ta' and 'அகம்' in e['source_spellings'] for e in entries))
        supplement=[e for e in entries if e['dictionary']['print_page']=='S007']
        self.assertTrue(supplement)
        self.assertTrue(all('page=3935' in e['dictionary']['url'] for e in supplement))
        self.assertTrue(any('அகம்¹' in e['dictionary']['headword_text'] for e in entries))
        self.assertTrue(any('அகம்²' in e['dictionary']['headword_text'] for e in entries))
        self.assertIn('Inside',entries[0]['dictionary']['whole_entry_text'])
        self.assertIn('A loc. ending',entries[0]['dictionary']['whole_entry_text'])
        self.assertTrue(all(e['dictionary']['work'].startswith('University of Madras') for e in entries))

    def test_tamil_cave_and_deity_homographs_are_not_collapsed(self):
        entries=parse('குகை');self.assertEqual(len(entries),2)
        self.assertEqual([e['dictionary']['whole_entry_text'] for e in entries],expected_bodies('குகை'))
        main=next(e for e in entries if e['dictionary']['print_page']==954)
        extra=next(e for e in entries if e['dictionary']['print_page']=='S227')
        self.assertIn('Cave, mountain cavern, grotto',main['dictionary']['whole_entry_text'])
        self.assertIn('Pārvatī',extra['dictionary']['whole_entry_text'])
        self.assertIn('page=4155',extra['dictionary']['url'])
        self.assertNotEqual(main['entry_id'],extra['entry_id'])
        self.assertNotIn('குகை¹',main['source_spellings'])

    def test_tamil_particle_entry_preserves_whole_grammar_not_a_single_and_gloss(self):
        entries=parse('உம்');self.assertEqual(len(entries),1)
        self.assertEqual(entries[0]['dictionary']['whole_entry_text'],expected_bodies('உம்')[0])
        self.assertGreater(len(entries[0]['dictionary']['whole_entry_text']),500)
        self.assertIn('உம்',entries[0]['source_spellings'])

    def test_origin_query_and_language_cannot_rebrand_result_or_miss(self):
        for query in ['ਰਸ','ਰਸੁ']:
            record=witness(query)
            with self.subTest(query=query),self.assertRaises(ValueError):
                corpus.parse_dictionary_html('madras-tamil-lexicon',raw(query).decode(),query=query,
                    url=record['url'],witness_sha256=record['sha256'])
            with self.assertRaises(ValueError):parse(query,url=record['url'].replace('dsal.uchicago.edu','example.com'))
            with self.assertRaises(ValueError):parse(query,query='unrelated')
        # Even a rewritten URL cannot turn a Punjabi page into Tamil authority.
        with self.assertRaises(ValueError):
            corpus.parse_dictionary_html('madras-tamil-lexicon',raw('ਰਸ').decode(),query='ਰਸ',
                url=witness('ਰਸ')['url'].replace('singh_query.py','tamil-lex_query.py'),witness_sha256=witness('ਰਸ')['sha256'])

class ActualAcquisition(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.calls=[]
    def opener(self,url,timeout):
        self.calls.append(url);query=parse_qs(urlparse(url).query)['qs'][0]
        return io.BytesIO(raw(query))
    def test_cached_results_and_misses_replay_without_fetch_and_verify_bytes(self):
        for name,query in [('singh','ਰਸ'),('tamil-lex','அகமும்')]:
            directory=self.root/name
            first=corpus.acquire_queries(directory,[query],dictionary_id=IDS[name],opener=self.opener)
            count=len(self.calls)
            self.assertEqual(corpus.acquire_queries(directory,[query],dictionary_id=IDS[name],opener=self.opener),first)
            self.assertEqual(len(self.calls),count)
            self.assertEqual(first[0]['dictionary_id'],IDS[name])
            self.assertEqual(corpus.load_cached_witness(directory,first[0]),raw(query))
            (directory/first[0]['path']).write_bytes(raw(query)+b'changed')
            with self.assertRaises(ValueError):corpus.load_cached_witness(directory,first[0])
    def test_same_query_cannot_reuse_another_dictionary_cache(self):
        directory=self.root/'cache'
        corpus.acquire_queries(directory,['ਰਸ'],dictionary_id='singh1895',opener=self.opener)
        count=len(self.calls)
        with self.assertRaises(ValueError):
            corpus.acquire_queries(directory,['ਰਸ'],dictionary_id='madras-tamil-lexicon',opener=self.opener)
        self.assertEqual(len(self.calls),count)

    def test_actual_witness_revalidation_uses_dictionary_authority_and_preserves_all_entries(self):
        for name,query in [('singh','ਰਸ'),('tamil-lex','அகம்')]:
            with self.subTest(query=query):
                directory=self.root/name
                corpus.acquire_queries(directory,[query],dictionary_id=IDS[name],opener=self.opener)
                entries=parse(query);forged=copy.deepcopy(entries)
                for entry in forged:
                    entry['dictionary'].update(work='Invented work',url='https://example.com/fiction',entry_locator='invented page')
                result=producer.resolve_source_witnesses(forged,[directory])
                self.assertFalse(result['gaps']);self.assertEqual(len(result['evidence']),len(entries))
                for evidence in result['evidence']:
                    self.assertEqual(evidence['language'],LANG[name])
                    self.assertIn(WORK[name],evidence['work'])
                    self.assertIn('dsal.uchicago.edu',evidence['source_url'])
                    self.assertEqual(corpus.sha(evidence['quotation'].encode()),evidence['quotation_sha256'])
                    self.assertIn(evidence['quotation'],raw(query).decode())
                forged[0]['source_spellings']=['invented']
                with self.assertRaises(ValueError):producer.resolve_source_witnesses(forged,[directory])

    def test_both_languages_share_one_run_quota_and_do_not_reset_on_lost_ledger(self):
        lines=[{'id':'pa','sourceLanguage':'pa','source_text':'ਰਸ','roman':'ras'},
               {'id':'ta','sourceLanguage':'ta','source_text':'குகை','roman':'kukai'}]
        proposals=[{'line_id':line['id'],'word_indices':[0],'surfaces':[line['roman']],
                    'source_queries':[line['source_text']]} for line in lines]
        plan=source.source_lookup_plan(lines,proposals,['Punjabi','Tamil'])
        self.assertEqual(len(plan['targets']),2)
        self.assertEqual({t['source_language'] for t in plan['targets']},{'pa','ta'})
        options=SimpleNamespace(source_discovery_max_requests=1)
        budget=source.configure_run_budget(self.root/'run',time.time()+30,options)
        result=source.acquire_source_candidates(plan,self.root/'cache',max_new_requests=4,timeout=1,opener=self.opener,run_budget=budget)
        self.assertEqual(len(self.calls),1)
        self.assertTrue(any(g['kind']=='source_discovery_budget' for g in result['gaps']))
        self.assertEqual({e['language'] for e in result['entries']},{'pa'})
        self.assertIn('singh_query.py',self.calls[0])
        again=source.acquire_source_candidates(plan,self.root/'cache',max_new_requests=4,timeout=1,opener=self.opener,run_budget=budget)
        self.assertEqual(len(self.calls),1);self.assertEqual(again,result)
        Path(budget['path']).unlink()
        with self.assertRaises(ValueError):
            source.acquire_source_candidates(plan,self.root/'cache',max_new_requests=4,timeout=1,opener=self.opener,run_budget=budget)
        self.assertEqual(len(self.calls),1)

if __name__=='__main__':unittest.main()

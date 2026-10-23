import copy
import json
import pathlib
import os
import tempfile
import unittest
from unittest.mock import patch
import bhakti_lexical_retrieval as retrieval
import bhakti_translation_policy as policy

# Independent decoder specifies preservation of the pre-projection evidence.
def expand(packet):
    def strings(value):
        if isinstance(value,dict):
            if set(value)=={'$text'}:return packet['text_blocks'][value['$text']]
            return {k:strings(v) for k,v in value.items()}
        if isinstance(value,list):return [strings(v) for v in value]
        return value
    entries=strings(packet['entries']);by_id={e['entry_id']:e for e in entries}
    tokens={}
    for line,rows in strings(packet['tokens']).items():
        tokens[line]=[]
        for row in rows:
            row=dict(row);row['candidates']=[by_id[eid] for eid in row.pop('candidate_entry_ids')];tokens[line].append(row)
    ranks=[]
    for row in strings(packet['rankings']):
        row=dict(row);row['context']={**strings(packet['contexts'][row.pop('context_ref')]),'surface':row['roman']}
        senses=[]
        for sense in row['senses']:
            entry=by_id[sense['entry_id']];definition=next(s for s in entry['senses'] if s['sense_id']==sense['sense_id'])
            senses.append({**sense,'language':entry['language'],'register':entry['register'],'dictionary':entry['dictionary'],'sense':definition})
        row['senses']=senses;ranks.append(row)
    return entries,tokens,ranks


def sample():
    body='A full source entry with nuanced alternatives and exact accents ā ṛ. '*12
    def entry(eid,lang):return {'entry_id':eid,'language':lang,'register':'poetic','lemma':'man','source_spellings':['मन'],'roman_search_aliases':['man'],'dictionary':{'work':'Witness','url':'https://example.test/entry','whole_entry_text':body},'senses':[{'sense_id':eid+':mind','short_english':body,'dictionary_anchor':body},{'sense_id':eid+':weight','short_english':'a measure of weight','dictionary_anchor':body}]}
    entries=[entry('hi.man','hi'),entry('pa.man','pa')]
    link={'language':'hi','source_form':'मन','roman_form':'man','reason':'explicit witnessed binding','evidence':{'url':'https://example.test/lemma'}}
    tokens={'a':[{'word_index':0,'roman':'man','candidates':[entries[0]],'lemma_evidence':[link]}], 'b':[{'word_index':0,'roman':'man','candidates':[entries[1]]}], 'c':[{'word_index':0,'roman':'unknown','candidates':[]}]}
    ranks=[]
    for lid,entry in zip(['a','b'],entries):
        ranks.append({'line_id':lid,'word_index':0,'roman':'man','context':{'language':entry['language'],'surface':'man','target':{'id':lid,'source_text':'मन','roman':'man'},'performed_context':[{'before':[{'id':'neighbor','source_text':lid+' prior','roman':'prior'}],'after':[]}]},'senses':[{'entry_id':entry['entry_id'],'sense_id':s['sense_id'],'language':entry['language'],'register':entry['register'],'dictionary':entry['dictionary'],'sense':s,'score':None,'status':'query_not_cached'} for s in reversed(entry['senses'])]})
    return entries,tokens,ranks

class CompactTests(unittest.TestCase):
    def test_round_trip_preserves_every_field_alternative_order_lemma_and_context(self):
        original=sample();saved=copy.deepcopy(original)
        packet=retrieval.compact_evidence(*original)
        self.assertEqual(expand(packet),original);self.assertEqual(original,saved)
        self.assertEqual(packet['format'],'bhakti-lexical-evidence-v1')
        self.assertEqual(len(packet['text_blocks']),1)
        self.assertNotEqual(packet['rankings'][0]['context_ref'],packet['rankings'][1]['context_ref'])
        self.assertEqual(packet['tokens']['c'][0]['candidate_entry_ids'],[])

    def test_unindexed_evidence_and_unique_long_text_are_not_lost(self):
        entries,tokens,_=sample();entries[0]['unique_note']='unique explanation '*80
        packet=retrieval.compact_evidence(entries,tokens,None)
        self.assertEqual(expand(packet),(entries,tokens,[]));self.assertEqual(packet['rankings'],[])

    def test_shared_context_does_not_merge_distinct_word_indices_or_drop_score(self):
        entries,tokens,ranks=sample();tokens={'a':[tokens['a'][0],{**tokens['a'][0],'word_index':1}]};ranks=[ranks[0],copy.deepcopy(ranks[0])];ranks[1]['word_index']=1
        ranks[1]['senses'][0].update(score=0.75,status='ranked')
        packet=retrieval.compact_evidence(entries,tokens,ranks)
        self.assertEqual(len(packet['contexts']),1);self.assertEqual(expand(packet),(entries,tokens,ranks))

    def test_conflicting_or_duplicate_evidence_rejected(self):
        for mutation in ['duplicate_entry','foreign_sense','wrong_language','wrong_definition','wrong_context','wrong_index','missing_alternative','duplicate_alternative','stale_token','reserved_ref','missing_token','duplicate_token','wrong_target_id','wrong_context_language','reserved_token_ref','reserved_context_ref']:
            with self.subTest(mutation=mutation):
                e,t,r=sample()
                if mutation=='duplicate_entry':e.append(copy.deepcopy(e[0]))
                elif mutation=='foreign_sense':r[0]['senses'][0]['sense_id']='foreign'
                elif mutation=='wrong_language':r[0]['senses'][0]['language']='sa'
                elif mutation=='wrong_definition':r[0]['senses'][0]['sense']={'sense_id':'bad'}
                elif mutation=='wrong_context':r[0]['context']['surface']='mana'
                elif mutation=='wrong_index':r[0]['word_index']=9
                elif mutation=='missing_alternative':r[0]['senses'].pop()
                elif mutation=='duplicate_alternative':r[0]['senses'].append(copy.deepcopy(r[0]['senses'][0]))
                elif mutation=='stale_token':t['a'][0]['candidates']=[{**e[0],'lemma':'changed'}]
                elif mutation=='reserved_ref':e[0]['dictionary']['note']={'$text':'invented'}
                elif mutation=='missing_token':r.pop()
                elif mutation=='duplicate_token':r.append(copy.deepcopy(r[0]))
                elif mutation=='wrong_target_id':r[0]['context']['target']['id']='other'
                elif mutation=='wrong_context_language':r[0]['context']['language']='sa'
                elif mutation=='reserved_token_ref':t['a'][0]['candidate_entry_ids']=['preexisting']
                elif mutation=='reserved_context_ref':r[0]['context_ref']='preexisting'
                with self.assertRaises(ValueError):retrieval.compact_evidence(e,t,r)

    def test_indexed_empty_rankings_are_missing_evidence_not_unindexed_mode(self):
        entries,tokens,_=sample()
        with self.assertRaises(ValueError):retrieval.compact_evidence(entries,tokens,[])

    def test_real_sqlite_guidance_preserves_candidates_bindings_ranks_and_vector_identity(self):
        entries,_,_=sample();entries=[entries[0]]
        line={'id':'a','source_text':'मन','roman':'man','sourceLanguage':'hi'}
        with tempfile.TemporaryDirectory() as tmp:
            path=pathlib.Path(tmp)/'lexicon.sqlite'
            with retrieval.LexicalIndex(path) as index:
                index.build({'entries':entries})
                context=retrieval.query_context(line,'man',['Hindi'],context_lines=[line],performance_order=[{'ref':'a'}])
                index._save(context,'query',[1.0]*index.space['dimensions'])
                rows=index._rows(entries)
                index._save(rows[0][5],'document',[1.0]*index.space['dimensions'],rows[0][2])
                expected_ranks=[{'line_id':'a','word_index':0,'roman':'man','context':json.loads(context),'senses':index.rank(entries,context)}]
                before=(index.fingerprint(),index.db.execute('SELECT key,space,text,kind,vector FROM vectors ORDER BY key').fetchall())
            clean_env={k:v for k,v in os.environ.items() if not k.startswith('BHAKTI_EMBEDDING_') and k not in {'BHAKTI_LEXICON_PATH','BHAKTI_LEXICAL_INDEX'}}
            with patch.dict(os.environ,{**clean_env,'BHAKTI_LEXICAL_INDEX':str(path)},clear=True),patch.object(retrieval,'EmbeddingClient',side_effect=AssertionError('no API')):
                text=policy.guidance([line],['Hindi'],context_lines=[line],performance_order=[{'ref':'a'}])
                expected_tokens=policy.token_candidates([line],['Hindi'])
                expected_entries=policy.dictionary_candidates([line],['Hindi'])
            packet=json.loads(text.split('COMPACT LEXICAL EVIDENCE (unselected):\n',1)[1])
            self.assertEqual(expand(packet),(expected_entries,expected_tokens,expected_ranks))
            with retrieval.LexicalIndex(path) as index:
                after=(index.fingerprint(),index.db.execute('SELECT key,space,text,kind,vector FROM vectors ORDER BY key').fetchall())
            self.assertEqual(before,after)

    def test_prompt_format_bumps_policy_cache_identity(self):
        self.assertGreater(policy.POLICY_VERSION,3)
        self.assertEqual(policy.policy_payload()['version'],policy.POLICY_VERSION)

    def test_actual_policy_guidance_uses_projection_and_forwards_real_context(self):
        entries,_,ranks=sample();line={'id':'a','source_text':'मन','roman':'man','sourceLanguage':'hi'}
        # Synthetic ranking generated from the same actual token mapping as policy.
        with patch.object(policy,'_lexicon_for',return_value={'entries':[entries[0]]}),patch.object(retrieval,'guidance_rankings',return_value=[ranks[0]]) as ranking:
            text=policy.guidance([line],['Hindi'],context_lines=[line],performance_order=[{'ref':'a'}])
        marker='COMPACT LEXICAL EVIDENCE (unselected):\n'
        self.assertIn(marker,text);self.assertNotIn('SUPPLIED DICTIONARY CANDIDATES (unselected):',text)
        packet=json.loads(text.split(marker,1)[1]);self.assertEqual(expand(packet)[0],[entries[0]])
        self.assertEqual(ranking.call_args.kwargs['context_lines'],[line]);self.assertEqual(ranking.call_args.kwargs['performance_order'],[{'ref':'a'}])
        self.assertIn('retain and adjudicate every alternative',text)

if __name__=='__main__':unittest.main()

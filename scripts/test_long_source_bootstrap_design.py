"""Long source tests: actual segmented calls/cache/merge; fixed acoustic partition only.

Returned words are synthetic; these cases do not test recognition accuracy.
"""
import argparse,copy,json,re,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import bhakti_pipeline as pipeline
import bhakti_model_routes as routes
import bhakti_lexical_retrieval as lexical
from test_generic_source_caller import make_audio

SEGMENTS=[{'index':0,'core_start':0.,'core_end':600.,'clip_start':0.,'clip_end':660.},
          {'index':1,'core_start':600.,'core_end':1200.,'clip_start':540.,'clip_end':1200.}]

def segment_packet(index):
    values=[('मन','man'),('तन','tan'),('राम','rāma')] if index==0 else [('तन','tan'),('राम','rāma'),('नाम','nāma')]
    lines=[{'id':f's{index}-{i}','source_text':native,'roman':roman,'language':'Hindi',
            'kind':'verse','partial':'none','notes':''} for i,(native,roman) in enumerate(values)]
    return {'lines':lines,'performance_order':[{'line_id':row['id'],'occurrence':1} for row in lines], 'uncertainties':[]}

class LongSourceBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.song=Path(self.tmp.name)/'long-source-fixture';self.song.mkdir()
        self.audio=self.song/'audio.m4a';make_audio(self.audio,1200)
        self.options=argparse.Namespace(model=pipeline.MODEL,pro_model=routes.PRO_MODEL,timeout=30,
            force=False,source_witness_audit=False,unit_deadline_at=time.time()+240)
        self.calls=[];self.bad_second_first=False;self.uncertain_second=False;self.all_second_uncertain=False
        self.addCleanup(patch.stopall)
        patch.object(pipeline,'adaptive_audio_segments',return_value=copy.deepcopy(SEGMENTS)).start()
        patch.object(pipeline.source_witness,'acquire',return_value=None).start()
        patch.object(pipeline.source_witness,'write_comparison_report').start()
        patch.object(pipeline.gemini,'key',return_value='fixture-not-a-key').start()
        patch.object(pipeline.gemini,'call',side_effect=self.provider).start()
    def provider(self,model,key,prompt,**kwargs):
        schema=kwargs['schema_name'];audit=schema=='bhakti_segment_audit'
        self.assertIn(schema,('bhakti_segment_transcript','bhakti_segment_audit'))
        self.assertLessEqual(pipeline.gemini.duration_seconds(kwargs['audio']),900.)
        if audit:
            draft=json.JSONDecoder().raw_decode(prompt.split('FIRST TRANSCRIPT:\n',1)[1].lstrip())[0]
            index=int(draft['lines'][0]['id'][1]);value=copy.deepcopy(draft)
        else:
            index=int(re.search(r'This is segment (\d+)',prompt).group(1));value=segment_packet(index)
        self.calls.append(('audit' if audit else 'transcript',index,model))
        if not audit and index==1 and self.bad_second_first and model==self.options.model:
            value['performance_order'][0]['line_id']='not-a-source-id'
        if audit and index==1 and (self.all_second_uncertain or self.uncertain_second and model==self.options.model):
            value['uncertainties']=['masked onset word']
        return {'packet':value,'resolved_model':model}
    def test_only_malformed_firstpass_segment_escalates(self):
        self.bad_second_first=True;raw=pipeline.transcript(self.song,{},self.audio,self.options)
        actual=pipeline.audit_transcript(self.song,raw,self.audio,self.options)
        self.assertCountEqual(self.calls,[('transcript',0,self.options.model),('transcript',1,self.options.model),
            ('transcript',1,self.options.pro_model),('audit',0,self.options.model),('audit',1,self.options.model)])
        rows={r['id']:r['source_text'] for r in actual['packet']['verified_lines']}
        self.assertEqual([rows[r['line_id']] for r in actual['packet']['performance_order']],['मन','तन','राम','नाम'])
    def test_audit_segment_escalates_preserving_all_firstpass_and_successful_peer(self):
        raw=pipeline.transcript(self.song,{},self.audio,self.options)
        first=(self.song/'.transcription/pipeline/01-transcript.json').read_bytes()
        self.uncertain_second=True;actual=pipeline.audit_transcript(self.song,raw,self.audio,self.options)
        self.assertCountEqual(self.calls,[('transcript',0,self.options.model),('transcript',1,self.options.model),
            ('audit',0,self.options.model),('audit',1,self.options.model),('audit',1,self.options.pro_model)])
        self.assertFalse(actual['packet']['uncertainties'])
        self.assertEqual((self.song/'.transcription/pipeline/01-transcript.json').read_bytes(),first)
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('accepted segment replay')):
            self.assertEqual(pipeline.transcript(self.song,{},self.audio,self.options),raw)
            self.assertEqual(pipeline.audit_transcript(self.song,raw,self.audio,self.options),actual)
    def test_terminal_one_segment_failure_retains_successful_audit_peer_for_resume(self):
        raw=pipeline.transcript(self.song,{},self.audio,self.options);self.all_second_uncertain=True
        with self.assertRaises(routes.UnitUnresolved):pipeline.audit_transcript(self.song,raw,self.audio,self.options)
        self.assertCountEqual(self.calls,[('transcript',0,self.options.model),('transcript',1,self.options.model),
            ('audit',0,self.options.model),('audit',1,self.options.model),('audit',1,self.options.pro_model)])
        with patch.object(pipeline.gemini,'call',side_effect=AssertionError('terminal segment cannot reset paid attempts')):
            with self.assertRaises(routes.UnitUnresolved):pipeline.audit_transcript(self.song,raw,self.audio,self.options)

class LongSourceLanguageTests(unittest.TestCase):
    def fixtures(self,overlap=False):
        items=[]
        for index,language in enumerate(['Hindi','Sanskrit']):
            row={'id':f's{index}','source_text':'नाम','roman':'nāma','language':language,'kind':'verse','partial':'none','notes':''}
            segment={'index':index,'core_start':float(index*5),'core_end':float((index+1)*5),
                     'clip_start':float(index*5-1 if overlap and index else index*5),'clip_end':float((index+1)*5+1 if overlap and not index else (index+1)*5)}
            items.append({'segment':segment,'audit':{'packet':{'lines':[row],
                'performance_order':[{'line_id':row['id'],'occurrence':1}],'uncertainties':[]}}})
        return items
    def test_distinct_performances_with_same_surface_keep_language_for_lexical_routing(self):
        result=pipeline.merge_audited_segments(self.fixtures())
        self.assertEqual(len(result['verified_lines']),2)
        byid={row['id']:row for row in result['verified_lines']}
        self.assertEqual([lexical.line_language(byid[event['line_id']],result['metadata']['languages'])
                          for event in result['performance_order']],['hi','sa'])
    def paired_overlap(self, swapped=False):
        items=self.fixtures(overlap=True)
        for index,item in enumerate(items):
            langs=['Hindi','Sanskrit'] if not index or swapped else ['hi','sa']
            if swapped and index:langs.reverse()
            lines=[{'id':f's{index}-{i}','source_text':native,'roman':roman,'language':langs[i],
                    'kind':'verse','partial':'none','notes':''}
                   for i,(native,roman) in enumerate([('राम','rāma'),('नाम','nāma')])]
            item['audit']['packet']={'lines':lines,'performance_order':[
                {'line_id':row['id'],'occurrence':1} for row in lines],'uncertainties':[]}
        return items
    def test_same_language_set_cannot_hide_swapped_per_occurrence_claims_in_overlap(self):
        result=pipeline.merge_audited_segments(self.paired_overlap(swapped=True))
        self.assertTrue(result['uncertainties'],'Hindi/Sanskrit swapped across exact matched words must hold')
    def test_aligned_language_aliases_across_two_line_overlap_remain_compatible(self):
        result=pipeline.merge_audited_segments(self.paired_overlap())
        self.assertFalse(result['uncertainties'])
        self.assertEqual(len(result['performance_order']),2)
        byid={row['id']:row for row in result['verified_lines']}
        self.assertEqual([lexical.line_language(byid[row['line_id']],result['metadata']['languages'])
                          for row in result['performance_order']],['hi','sa'])

    def test_same_overlapping_performance_with_conflicting_language_cannot_silently_merge(self):
        result=pipeline.merge_audited_segments(self.fixtures(overlap=True))
        self.assertTrue(result['uncertainties'],'same overlapping performance has unresolved incompatible language assertions')

if __name__=='__main__':unittest.main()

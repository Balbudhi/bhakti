#!/usr/bin/env python3
"""Offline role-fidelity checks through intake, real generation and both renderers."""
import argparse
import json
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
import bhakti_pipeline as bp
from test_bhakti_pipeline import PipelineTests

ROOT = Path(__file__).resolve().parents[1]

class Credits(HTMLParser):
    def __init__(self, markup):
        super().__init__(); self.rows=[]; self.row=None; self.field=None
        self.feed(markup)
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='div' and attrs.get('class')=='song-credit-entry':
            self.row={'role':'','person':'','hidden':False};self.rows.append(self.row)
        if self.row is not None and tag in ('dt','dd'):
            self.field='role' if tag=='dt' else 'person'
            if tag=='dt':self.row['hidden']='hidden' in attrs
    def handle_data(self, value):
        if self.row is not None and self.field:self.row[self.field]+=value
    def handle_endtag(self, tag):
        if tag in ('dt','dd'):self.field=None
        if tag=='div':self.row=None

# Same VM/DOM seam used by test_all_line_seeks, but metadata rendering is real.
# This checks emitted markup, not native browser layout (release Browser gate).
JS = r'''
const fs=require('node:fs'),vm=require('node:vm');
const meta=JSON.parse(fs.readFileSync(0,'utf8'));
const songMeta={innerHTML:'',querySelectorAll(){return []}};
const title={textContent:''};
const hero={querySelector(s){return s==='.song-title'?title:s==='.song-meta'?songMeta:null},querySelectorAll(){return []}};
const document={querySelector(s){return s==='.song-hero'?hero:null},addEventListener(){}};
const context=vm.createContext({window:{SONG_META:meta,addEventListener(){}},document,
 localStorage:{getItem(){return null}},location:{pathname:'/songs/fixture/'}});
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
vm.runInContext('renderSongMeta()',context);
process.stdout.write(songMeta.innerHTML);
'''

def js_markup(meta):
    return subprocess.run([shutil.which('node') or 'node','-e',JS,str(ROOT/'assets/song.js')],
        input=json.dumps(meta),text=True,capture_output=True,check=True).stdout

class MusicDirectionTests(unittest.TestCase):
    def rows(self, meta):
        python=Credits(bp.page_html(meta,'fixture')).rows
        javascript=Credits(js_markup(meta)).rows
        self.assertEqual(python,javascript,'server and live reader credit roles agree')
        return python
    def test_actual_renderers_preserve_roles_and_fixed_label(self):
        meta={'title':'Fixture','writer':'Tulasīdāsa','singer':'Sharma Bandhu','musicDirector':'Govind & Dinesh'}
        self.assertEqual(self.rows(meta),[
            {'role':'Poet','person':'Tulasīdāsa','hidden':False},
            {'role':'Singer','person':'Sharma Bandhu','hidden':False},
            {'role':'Music direction','person':'Govind & Dinesh','hidden':False}])
        rows=self.rows({**meta,'composer':'Composer Person'})
        self.assertEqual([(r['role'],r['person']) for r in rows[-2:]],
            [('Composer','Composer Person'),('Music direction','Govind & Dinesh')])
    def test_grouping_compact_absent_and_escaping(self):
        base={'title':'Fixture','singer':'One Person'}
        expected=[{'role':'Singer','person':'One Person','hidden':True}]
        self.assertEqual(self.rows(base),expected)
        self.assertEqual(bp.page_html(base,'fixture'),bp.page_html({**base,'musicDirector':''},'fixture'))
        self.assertEqual(js_markup(base),js_markup({**base,'musicDirector':''}))
        self.assertEqual(self.rows({'title':'Fixture','composer':'Govind & Dinesh','musicDirector':'Govind & Dinesh'}),
            [{'role':'Composers · Music direction','person':'Govind & Dinesh','hidden':False}])
        self.assertEqual(self.rows({'title':'Fixture','musicDirector':'A <B> & C'}),
            [{'role':'Music direction','person':'A <B> & C','hidden':False}])
        self.assertEqual(self.rows({'title':'Fixture','musicDirector':'One Person'}),
            [{'role':'Music direction','person':'One Person','hidden':True}])
    def test_optional_song_script_version_reaches_actual_script_tag(self):
        base={'title':'Fixture'}
        self.assertIn('<script src="/assets/song.js?v=touch-20261023"></script>',bp.page_html(base,'fixture'))
        page=bp.page_html({**base,'songAssetVersion':'music-direction-20261115'},'fixture')
        self.assertIn('<script src="/assets/song.js?v=music-direction-20261115"></script>',page)
        self.assertNotIn('/assets/song.js?v=touch-20261023',page)

    def normalise(self, description, override=None):
        metadata={'id':'testfixture','title':'Fixture','description':description,'webpage_url':'https://example.test/fixture'}
        options=argparse.Namespace(song=[],url=['https://example.test/fixture'],batch=None)
        with patch.object(bp,'media_metadata',return_value=metadata),patch.object(bp,'source_credit_override',return_value=override or {}):
            return bp.normalise_jobs(options)[0]
    def test_actual_description_adapter_separates_director_and_composer(self):
        for label in ('Music Director','Music Directors'):
            with self.subTest(label=label):
                job=self.normalise(label+': Govind, Dinesh\nSinger: Sharma Bandhu')
                self.assertEqual(job.get('musicDirector'),'Govind, Dinesh')
                self.assertEqual(job['composer'],'')
        job=self.normalise('Music Director: Govind\nComposer: Dinesh')
        self.assertEqual((job['musicDirector'],job['composer']),('Govind','Dinesh'))
        job=self.normalise('Music Director: Govind',{'musicDirector':'Reviewed Person','composer':'Actual Composer'})
        self.assertEqual((job['musicDirector'],job['composer']),('Reviewed Person','Actual Composer'))
        for label in ('Composer','Composed','Music'):
            self.assertEqual(self.normalise(label+': Existing Music Credit')['composer'],'Existing Music Credit')
    def test_optional_catalogue_field(self):
        base={'title':'Fixture','credit':'Singer','singer':'Singer'}
        before=bp.catalogue_entry(Path('fixture'),base)
        self.assertNotIn('musicDirector',before)
        self.assertEqual(before,bp.catalogue_entry(Path('fixture'),{**base,'musicDirector':'  '}))
        self.assertEqual(bp.catalogue_entry(Path('fixture'),{**base,'musicDirector':' Govind & Dinesh '}),
            {**before,'musicDirector':'Govind & Dinesh'})
    def test_actual_generate_propagates_optional_role_credit_and_alias(self):
        fixture=PipelineTests(methodName='runTest');fixture.setUp()
        try:
            song=fixture.root/'songs'/'music-role-fixture';song.mkdir()
            job={'slug':song.name,'source':'unused','displayTitle':'Fixture','singer':'Sharma Bandhu','languages':['Sanskrit']}
            audited={'packet':{'metadata':{'languages':['Sanskrit']},'uncertainties':[],
                'verified_lines':[{'id':'om','source_text':'ॐ','roman':'oṁ','kind':'invocation'}]}}
            timing={'sequence':[{'ref':'om','start':0.,'end':1.}],'validation_errors':[]}
            glosses={'packet':{'glosses':[{'id':'om','word_glosses':[{'roman':'oṁ','gloss':'Om'}],'grammar_note':'','uncertainty':''}]}}
            translations={'packet':{'translations':[{'id':'om','literal_english':'Om.','segments':[{'text':'Om.','word_indices':[0]}],'uncertainty':''}]}}
            def generate(extra):
                # Scope is metadata propagation through real generation, not paid semantic qualification.
                with patch.object(bp,'publication_errors',return_value=[]):
                    bp.generate(song,{**job,**extra},{},audited,timing,glosses,translations,write_catalogue_after=False)
                raw=(song/'data.js').read_text(); meta=json.loads(raw.split('window.SONG_META = ',1)[1].split(';\n',1)[0])
                return meta,raw,(song/'index.html').read_text()
            baseline=generate({});empty=generate({'musicDirector':''})
            self.assertEqual(baseline,empty)
            self.assertNotIn('musicDirector',baseline[0])
            meta,_,page=generate({'musicDirector':'Govind & Dinesh'})
            self.assertEqual(meta['musicDirector'],'Govind & Dinesh')
            self.assertEqual(meta['composer'],'')
            self.assertIn('Govind & Dinesh',meta['credit'])
            self.assertEqual(Credits(page).rows[-1],{'role':'Music direction','person':'Govind & Dinesh','hidden':False})
            variant,_,_=generate({'musicDirector':'Surjoo Bhattacharya'})
            self.assertEqual(variant['musicDirector'],'Shurjo Bhattacharya')
            self.assertIn('Surjoo Bhattacharya',variant['searchAliases'])
        finally:fixture.tearDown()

if __name__=='__main__':
    unittest.main(defaultTest='MusicDirectionTests')

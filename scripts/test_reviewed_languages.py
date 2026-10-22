"""Reviewed language is source evidence; neither script nor first metadata item decides it."""
import copy
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import bhakti_pipeline as pipeline


def digest(sources):
    return hashlib.sha256(json.dumps(sorted(set(sources)),ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def binding(path,key):
    text=path.read_text(); start=re.search(r'(?:window\.)?'+key+r'\s*=\s*',text).end()
    return json.JSONDecoder().raw_decode(text[start:])[0]


class ReviewedLanguagesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'data').mkdir();(self.root/'songs').mkdir()
        self.registry={'version':1,'songs':{}}
        self.lines=[{'id':'h','source_text':'मन','roman':'man','sourceLanguage':'hi'},
                    {'id':'p','source_text':'असां','roman':'asāṃ','sourceLanguage':'pa'}]
        self.order=[{'ref':'h'},{'ref':'p'}]
        self.save()

    def save(self):
        (self.root/'data/song_language_overrides.json').write_text(json.dumps(self.registry,ensure_ascii=False))

    def register(self,slug='mixed',languages=None,lines=None):
        lines=lines or self.lines
        self.registry['songs'][slug]={'languages':languages or ['Hindi','Punjabi'],
          'performedSourcesSha256':digest([x['source_text'] for x in lines]),
          'lines':[{'source':x['source_text'],'language':x['sourceLanguage'],'reason':'Reviewed grammatical evidence'} for x in lines]}
        self.save()

    def resolve(self,slug='mixed',languages=None,lines=None,order=None):
        # Proposed production-owned API, intentionally absent until reviewed implementation.
        return pipeline.resolve_reviewed_languages(slug,lines if lines is not None else self.lines,
            order if order is not None else self.order,languages if languages is not None else ['Hindi','Punjabi'],root=self.root)

    def test_registered_override_supersedes_stale_song_language(self):
        self.register(); result=self.resolve(languages=['Marathi'])
        self.assertEqual(result['song_languages'],['Hindi','Punjabi'])
        self.assertEqual(result['by_line_id'],{'h':'hi','p':'pa'})
        self.assertEqual(result['review_items'],[])

    def test_registered_assignment_overrides_stale_recognized_audited_code(self):
        self.register()
        stale=copy.deepcopy(self.lines)
        for line in stale:line['sourceLanguage']='mr'
        result=self.resolve(languages=['Marathi'],lines=stale)
        self.assertEqual(result['song_languages'],['Hindi','Punjabi'])
        self.assertEqual(result['by_line_id'],{'h':'hi','p':'pa'})

    def test_registered_override_does_not_hide_unknown_or_malformed_explicit_code(self):
        self.register()
        for value in ['xx',None,False]:
            with self.subTest(value=value):
                lines=copy.deepcopy(self.lines);lines[0]['sourceLanguage']=value
                with self.assertRaises(ValueError):self.resolve(lines=lines)

    def test_explicit_same_script_languages_are_not_collapsed_to_first(self):
        self.lines[0].update(source_text='नमः',sourceLanguage='sa')
        result=self.resolve(languages=['Sanskrit','Punjabi'])
        self.assertEqual(result['by_line_id'],{'h':'sa','p':'pa'})

    def test_known_single_language_can_supply_context_but_mixed_cannot(self):
        for line in self.lines:line.pop('sourceLanguage')
        result=self.resolve(languages=['Hindi'])
        self.assertEqual(result['by_line_id'],{'h':'hi','p':'hi'})
        result=self.resolve()
        self.assertEqual(result['by_line_id'],{'h':'','p':''})
        self.assertEqual({x['id'] for x in result['review_items']},{'h','p'})

    def test_unknown_and_script_labels_do_not_generate_a_language(self):
        lines=[{'id':'x','source_text':'आ','roman':'ā'}]
        for languages in [[],['Unknown'],['Devanagari']]:
            result=self.resolve(languages=languages,lines=lines,order=[{'ref':'x'}])
            self.assertEqual(result['by_line_id'],{'x':''})
            self.assertEqual([x['id'] for x in result['review_items']],['x'])

    def test_explicit_unknown_or_outside_song_language_is_an_error(self):
        for value in ['Devanagari','xx','mr']:
            with self.subTest(value=value):
                lines=copy.deepcopy(self.lines);lines[0]['sourceLanguage']=value
                with self.assertRaises(ValueError):self.resolve(lines=lines)

    def test_source_match_is_exact_canonical_audited_text_not_render_cleanup(self):
        self.register()
        for changed in ['मन ॥१॥','मन ','मन्']:
            lines=copy.deepcopy(self.lines);lines[0]['source_text']=changed
            with self.subTest(source=changed),self.assertRaises(ValueError):self.resolve(lines=lines)

    def test_added_performed_source_or_removed_coverage_blocks(self):
        self.register();lines=self.lines+[{'id':'new','source_text':'तू','roman':'tū','sourceLanguage':'hi'}]
        with self.assertRaises(ValueError):self.resolve(lines=lines,order=self.order+[{'ref':'new'}])
        self.registry['songs']['mixed']['lines'].pop();self.save()
        with self.assertRaises(ValueError):self.resolve()

    def test_renumbered_reordered_repeated_sources_retain_identity(self):
        self.register();lines=copy.deepcopy(self.lines);lines[0]['id']='newh';lines[1]['id']='newp'
        result=self.resolve(lines=lines,order=[{'ref':'newp'},{'ref':'newh'},{'ref':'newh','repeats':3}])
        self.assertEqual(result['by_line_id'],{'newh':'hi','newp':'pa'})

    def test_unperformed_annotation_preserved_but_not_hashed_as_performed(self):
        self.register();lines=self.lines+[{'id':'unused','source_text':'वाणी','roman':'vāṇī','sourceLanguage':'hi'}]
        result=self.resolve(lines=lines)
        self.assertEqual(result['by_line_id']['unused'],'hi')
        # Once sung, previously unreviewed lexical coverage requires review.
        with self.assertRaises(ValueError):self.resolve(lines=lines,order=self.order+[{'ref':'unused'}])

    def test_conflicting_duplicate_source_assignments_are_rejected(self):
        self.register();self.registry['songs']['mixed']['lines'].append({'source':'मन','language':'pa','reason':'Conflicting assignment'})
        self.save()
        with self.assertRaises(ValueError):self.resolve()

    def test_bad_registry_or_performance_reference_fails_without_input_mutation(self):
        original=copy.deepcopy(self.lines)
        for text in ['{', '{"version":1,"songs":[]}', '{"version":2,"songs":{}}']:
            (self.root/'data/song_language_overrides.json').write_text(text)
            with self.assertRaises(ValueError):self.resolve()
        self.save()
        with self.assertRaises(ValueError):self.resolve(order=[{'ref':'missing'}])
        self.assertEqual(self.lines,original)

    def test_missing_registry_is_legacy_no_override_but_unknown_registry_codes_fail(self):
        (self.root/'data/song_language_overrides.json').unlink()
        self.assertEqual(self.resolve()['by_line_id'],{'h':'hi','p':'pa'})
        self.register();self.registry['songs']['mixed']['lines'][0]['language']='xx';self.save()
        with self.assertRaises(ValueError):self.resolve()

    def test_registry_duplicate_json_keys_and_invalid_digest_fail_closed(self):
        (self.root/'data/song_language_overrides.json').write_text('{"version":1,"version":1,"songs":{}}')
        with self.assertRaises(ValueError):self.resolve()
        self.register();self.registry['songs']['mixed']['performedSourcesSha256']='bad';self.save()
        with self.assertRaises(ValueError):self.resolve()

    def test_all_three_reviewed_source_snapshots_preserve_every_line_annotation(self):
        cases=json.loads((Path(__file__).parent/'fixtures/reviewed_language_sources.json').read_text())
        self.assertEqual({x['slug'] for x in cases},{'ghana-shyama-sundara','ghanshyam-sundara','meri-maa-jagdambe-man-jaye'})
        for case in cases:
            with self.subTest(slug=case['slug']):
                by_id={x['id']:x for x in case['lines']}
                self.register(case['slug'],case['languages'],case['lines'])
                self.registry['songs'][case['slug']]['performedSourcesSha256']=digest([by_id[x['ref']]['source_text'] for x in case['order']])
                self.save()
                result=self.resolve(case['slug'],['Marathi'],case['lines'],case['order'])
                self.assertEqual(result['song_languages'],case['languages'])
                self.assertEqual(result['by_line_id'],{x['id']:x['sourceLanguage'] for x in case['lines']})
                self.assertEqual(result['review_items'],[])

    def setup_generator(self):
        main=Path(pipeline.__file__).resolve().parents[1]
        for name in ['preserved_terms.json','editorial_baselines.json','source_credits.json']:
            (self.root/'data'/name).write_text((main/'data'/name).read_text())
        (self.root/'data/song_tag_overrides.json').write_text('{"version":1,"songs":{}}')
        (self.root/'data/queue_numbers.json').write_text('{"schemaVersion":1,"numbers":{}}')
        (self.root/'data/songs.js').write_text('window.BHAKTI_SONGS = [];\n')
        song=self.root/'songs/mixed';song.mkdir()
        audited={'packet':{'metadata':{'languages':['Marathi']},'uncertainties':[],
          'verified_lines':[{'id':x['id'],'source_text':x['source_text'],'roman':x['roman'],'kind':'verse'} for x in self.lines]}}
        glosses={'packet':{'glosses':[{'id':x['id'],'word_glosses':[{'roman':x['roman'],'gloss':meaning}],
          'grammar_note':'','uncertainty':''} for x,meaning in zip(self.lines,['mind','we'])]}}
        translations={'packet':{'translations':[{'id':x['id'],'literal_english':eng,
          'segments':[{'text':eng,'word_indices':[0]}],'uncertainty':''} for x,eng in zip(self.lines,['Mind.','We.'])]}}
        timing={'sequence':[{'ref':'h','start':1.0,'end':2.0},{'ref':'p','start':2.0,'end':4.0}],'validation_errors':[]}
        return song,{'slug':'mixed','title':'Mixed','languages':['Marathi'],'subjectTags':[]},audited,timing,glosses,translations

    def test_real_generation_persists_reviewed_metadata_and_line_split(self):
        song,job,aud,timing,g,t=self.setup_generator()
        with patch.object(pipeline,'ROOT',self.root),patch.object(pipeline,'QUEUE_NUMBERS_PATH',self.root/'data/queue_numbers.json'):
            pipeline.generate(song,job,{},aud,timing,g,t)
            baseline_lines=binding(song/'data.js','SONG_LINES')
            self.register()
            pipeline.generate(song,job,{},aud,timing,g,t)
        self.assertEqual(binding(song/'data.js','SONG_META')['languages'],['Hindi','Punjabi'])
        lines=binding(song/'data.js','SONG_LINES')
        self.assertEqual({k:v['sourceLanguage'] for k,v in lines.items()},{'h':'hi','p':'pa'})
        for key,row in lines.items():
            before=copy.deepcopy(baseline_lines[key]);after=copy.deepcopy(row)
            before.pop('sourceLanguage');after.pop('sourceLanguage');self.assertEqual(before,after)
        self.assertEqual([v['source'] for v in lines.values()],['मन','असां'])
        self.assertEqual([v['roman'] for v in lines.values()],['man','asāṃ'])
        self.assertEqual(binding(song/'data.js','SONG_TIMINGS'),[{'start':1.0,'end':2.0},{'start':2.0,'end':4.0}])
        self.assertEqual([x['ref'] for x in binding(song/'data.js','SONG_SEQUENCE')],['h','p'])
        self.assertEqual(binding(self.root/'data/songs.js','BHAKTI_SONGS')[0]['languageTags'],['Hindi','Punjabi'])
        page=(song/'index.html').read_text();self.assertIn('language-tag">Punjabi</span>',page);self.assertNotIn('language-tag">Marathi</span>',page)

    def test_generation_keeps_ambiguous_language_evidence_private(self):
        song,job,aud,timing,g,t=self.setup_generator()
        job['languages']=['Hindi','Punjabi']
        aud['packet']['metadata']['languages']=['Hindi','Punjabi']
        with patch.object(pipeline,'ROOT',self.root),patch.object(pipeline,'QUEUE_NUMBERS_PATH',self.root/'data/queue_numbers.json'):
            pipeline.generate(song,job,{},aud,timing,g,t)
        lines=binding(song/'data.js','SONG_LINES')
        self.assertEqual({k:v['sourceLanguage'] for k,v in lines.items()},{'h':'','p':''})
        report=json.loads((song/'.transcription/language-review.json').read_text())
        self.assertEqual({item['id'] for item in report['review_items']},{'h','p'})
        page=(song/'index.html').read_text()
        self.assertNotIn('language-review',page)
        self.assertNotIn('.transcription',page)
        for item in report['review_items']:
            self.assertTrue(item['reason'])
            self.assertNotIn(item['reason'],page)

    def test_invalid_registered_source_blocks_before_existing_public_bytes_change(self):
        self.register();song,job,aud,timing,g,t=self.setup_generator();aud['packet']['verified_lines'][0]['source_text']='मन्'
        originals={song/'data.js':b'old-data',song/'index.html':b'old-page',self.root/'data/songs.js':b'old-catalogue'}
        for path,data in originals.items():path.write_bytes(data)
        with patch.object(pipeline,'ROOT',self.root),patch.object(pipeline,'QUEUE_NUMBERS_PATH',self.root/'data/queue_numbers.json'):
            with self.assertRaises((ValueError,RuntimeError)):pipeline.generate(song,job,{},aud,timing,g,t)
        for path,data in originals.items():self.assertEqual(path.read_bytes(),data)

if __name__=='__main__':unittest.main()

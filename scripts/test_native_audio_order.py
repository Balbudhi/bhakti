"""Real media/provenance checks; URL downloading alone is replaced by local copies."""
import copy
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import bhakti_pipeline as pipeline

class NativeAudioOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media=tempfile.TemporaryDirectory();cls.samples=Path(cls.media.name)
        for suffix,codec in [('webm','libopus'),('m4a','aac')]:
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=0.2','-c:a',codec,str(cls.samples/f'audio.{suffix}')],check=True)
    @classmethod
    def tearDownClass(cls):cls.media.cleanup()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.song=self.root/'songs/example';self.source={'id':'abcdefghijk','source_url':'https://www.youtube.com/watch?v=abcdefghijk'}
        self.job={'slug':'example','source':self.source['source_url'],'_source_resolution':{'resolved_url':self.source['source_url']},'_source_metadata':{'id':'abcdefghijk','webpage_url':self.source['source_url'],'title':'Example'}}
    def fixture(self):
        (self.song/'.transcription').mkdir(parents=True)
        for name in ['audio.webm','audio.m4a']:shutil.copy2(self.samples/name,self.song/name)
        self.source['native_audio']={'version':1,'status':'ready','source_id':self.source['id'],'source_url':self.source['source_url'],'sources':[
            {'src':name,'type':mime,'sha256':self.sha(self.song/name),'role':role} for name,mime,role in [('audio.webm','audio/webm; codecs=opus','primary'),('audio.m4a','audio/mp4','compatibility')]]}
        self.save()
    def save(self):pipeline.write_json(self.song/'.transcription/source.json',self.source)
    @staticmethod
    def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
    def test_lower_bitrate_native_opus_remains_first(self):
        self.fixture()
        with patch.object(pipeline,'audio_stream_quality',side_effect=lambda p:(127908 if p.suffix=='.webm' else 129397,True)):
            self.assertEqual(pipeline.preferred_listener_audio(self.song),self.song/'audio.webm')
        self.assertEqual([r['src'] for r in pipeline.native_audio_sources(self.song,required=True)],['audio.webm','audio.m4a'])
    def test_native_receipt_allows_only_verified_interrupted_trim_recovery(self):
        from test_boundary_application import create_audio, accepted_crop
        for failed_name in ('audio.webm','audio.m4a'):
            self.song=self.root/'songs'/failed_name
            self.song.mkdir(parents=True);create_audio(self.song)
            self.source['native_audio']={'version':1,'status':'ready','source_id':self.source['id'],
                'source_url':self.source['source_url'],'sources':[
                    pipeline.native_audio_receipt_entry(self.song/'audio.webm','primary'),
                    pipeline.native_audio_receipt_entry(self.song/'audio.m4a','compatibility')]}
            self.save();artifact=accepted_crop(self.song);replace=Path.replace
            def interrupt(path,destination):
                if Path(destination)==self.song/failed_name:raise OSError('interrupted native stream replacement')
                return replace(path,destination)
            with patch.object(Path,'replace',interrupt),self.assertRaises(OSError):pipeline.apply_lossless_trim(self.song,artifact)
            with self.assertRaises(ValueError):pipeline.native_audio_sources(self.song,required=True)
            current=(self.song/'audio.webm').read_bytes()
            with (self.song/'audio.webm').open('ab') as stream:stream.write(b'changed outside transaction')
            with self.assertRaises(ValueError):pipeline.apply_lossless_trim(self.song,artifact)
            (self.song/'audio.webm').write_bytes(current)
            pipeline.apply_lossless_trim(self.song,artifact)
            self.assertEqual(pipeline.preferred_listener_audio(self.song),self.song/'audio.webm')
    def test_legacy_without_receipt_preserves_existing_behavior(self):
        self.fixture();del self.source['native_audio'];self.save()
        with patch.object(pipeline,'audio_stream_quality',side_effect=lambda p:(127908 if p.suffix=='.webm' else 129397,True)):
            self.assertEqual(pipeline.preferred_listener_audio(self.song),self.song/'audio.m4a')
        with self.assertRaisesRegex(ValueError,'native'):pipeline.native_audio_sources(self.song,required=True)
    def test_receipt_rejects_identity_path_roles_and_actual_bytes(self):
        self.fixture();good=copy.deepcopy(self.source)
        variants=[]
        for key,value in [('source_id','other'),('source_url','https://www.youtube.com/watch?v=other'),('status','pending')]:
            bad=copy.deepcopy(good);bad['native_audio'][key]=value;variants.append(bad)
        for key,value in [('src','../audio.webm'),('sha256','0'*64),('type','audio/mp4'),('role','compatibility')]:
            bad=copy.deepcopy(good);bad['native_audio']['sources'][0][key]=value;variants.append(bad)
        bad=copy.deepcopy(good);bad['native_audio']['sources'].append(copy.deepcopy(bad['native_audio']['sources'][1]));variants.append(bad)
        for bad in variants:
            self.source=bad;self.save()
            with self.subTest(bad=bad),self.assertRaises(ValueError):pipeline.listener_audio_sources(self.song)
    def test_trim_custody_requires_original_and_current_output_hashes(self):
        self.fixture();archive=self.song/'.transcription/original-audio';archive.mkdir()
        sources=[];outputs={}
        for row in self.source['native_audio']['sources']:
            name=row['src'];shutil.copy2(self.song/name,archive/name);sources.append({'src':name,'sha256':row['sha256']})
            # A changed container with the same valid encoded media suffices to test custody.
            with (self.song/name).open('ab') as f:f.write(b'\0')
            outputs[name]={'sha256':self.sha(self.song/name)}
        pipeline.write_json(self.song/'.transcription/trim-originals.json',{'version':2,'sources':sources})
        pipeline.write_json(self.song/'.transcription/trim-applied.json',{'application_version':2,'status':'applied','outputs':outputs})
        self.assertEqual(pipeline.preferred_listener_audio(self.song),self.song/'audio.webm')
        original=(archive/'audio.webm').read_bytes()
        (archive/'audio.webm').write_bytes(b'wrong')
        with self.assertRaisesRegex(ValueError,'identity'):pipeline.listener_audio_sources(self.song)
        (archive/'audio.webm').write_bytes(original)
        with (self.song/'audio.webm').open('ab') as f:f.write(b'x')
        with self.assertRaisesRegex(ValueError,'identity'):pipeline.listener_audio_sources(self.song)
    def test_url_intake_records_primary_and_native_fallback_and_failure_is_durable(self):
        original_run=subprocess.run
        def download(command,**kwargs):
            if command[0]!='yt-dlp':return original_run(command,**kwargs)
            selector=command[command.index('-f')+1];name='audio.webm' if selector=='bestaudio' else 'audio.m4a'
            output=command[command.index('-o')+1].replace('%(ext)s',name.split('.')[-1]);shutil.copy2(self.samples/name,output)
            return subprocess.CompletedProcess(command,0)
        with patch.object(pipeline,'ROOT',self.root),patch.object(pipeline.subprocess,'run',side_effect=download):
            song,source=pipeline.intake(self.job,force=False)
        self.assertEqual(source['native_audio']['status'],'ready')
        self.assertEqual(pipeline.preferred_listener_audio(song),song/'audio.webm')
        shutil.rmtree(self.song)
        def fail_fallback(command,**kwargs):
            if command[0]=='yt-dlp' and command[command.index('-f')+1]=='bestaudio[ext=m4a]':
                raise subprocess.CalledProcessError(1,command)
            if command[0]=='ffmpeg':raise AssertionError('native fallback must not transcode')
            return download(command,**kwargs)
        with patch.object(pipeline,'ROOT',self.root),patch.object(pipeline.subprocess,'run',side_effect=fail_fallback):
            with self.assertRaises(subprocess.CalledProcessError):pipeline.intake(self.job,force=False)
        saved=json.loads((self.song/'.transcription/source.json').read_text())
        self.assertEqual(saved['native_audio']['status'],'pending');self.assertEqual(len(saved['native_audio']['sources']),1)
        shutil.copy2(self.samples/'audio.m4a',self.song/'audio.m4a')
        with patch.object(pipeline,'ROOT',self.root),self.assertRaises(ValueError):pipeline.intake(self.job,force=False)
    def test_cached_metadata_must_match_actual_download_url(self):
        job=copy.deepcopy(self.job);job['_source_metadata']['id']='differentID'
        with patch.object(pipeline,'ROOT',self.root),patch.object(pipeline.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'source identity'):pipeline.intake(job,force=False)
        run.assert_not_called()
        self.assertFalse((self.song/'.transcription/source.json').exists())

    def test_primary_native_aac_is_one_source(self):
        self.fixture();(self.song/'audio.webm').unlink();row=self.source['native_audio']['sources'][1];row['role']='primary';self.source['native_audio']['sources']=[row];self.save()
        self.assertEqual(pipeline.listener_audio_sources(self.song),[{'src':'audio.m4a','type':'audio/mp4'}])

if __name__=='__main__':unittest.main()

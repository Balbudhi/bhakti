"""Real publisher/file staging; simulated release storage, never a network call."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import publish_media_release as media
from bhakti_model_routes import RunFatal

class BoundaryMediaPublication(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.song=self.root/'songs/fixture';self.song.mkdir(parents=True)
        (self.root/'data').mkdir();self.manifest=self.root/'data/media.json'
        self.old=b'original listener bytes';self.new=b'corrected listener bytes'
        self.name='fixture.m4a';self.old_url='https://github.com/fixture/repo/releases/download/media-v1/'+self.name
        self.remote={self.name:self.old};self.uploads=[]
        self.manifest.write_text(json.dumps({'schemaVersion':2,'repository':'fixture/repo','releaseTag':'media-v1',
            'songs':{'fixture':[{'src':self.old_url,'type':'audio/mp4','sha256':hashlib.sha256(self.old).hexdigest()}]}}))
        (self.song/'audio.m4a').write_bytes(self.new)
        (self.song/'data.js').write_text('reader still references '+self.old_url)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(media,'ROOT',self.root).start();mock.patch.object(media,'MANIFEST',self.manifest).start()
        mock.patch('sys.argv',['publish_media_release.py','--repository','fixture/repo','--song','fixture']).start()
        mock.patch.object(media,'release_assets',side_effect=lambda *a:{name:len(data) for name,data in self.remote.items()}).start()
        mock.patch.object(media,'command',side_effect=self.command).start()

    def command(self,*args,**kwargs):
        self.assertEqual(args[:3],('gh','release','upload'))
        files=[Path(arg) for arg in args[3:] if isinstance(arg,str) and Path(arg).is_file()]
        self.assertTrue(files)
        self.uploads.extend(path.name for path in files)
        for path in files:self.remote[path.name]=path.read_bytes()
        return ''

    def invoke(self):
        with contextlib.redirect_stdout(io.StringIO()):return media.main()

    def test_unchanged_legacy_asset_keeps_url_and_does_not_upload(self):
        (self.song/'audio.m4a').write_bytes(self.old)
        old_manifest=json.loads(self.manifest.read_text())
        self.assertEqual(self.invoke(),0)
        self.assertEqual(self.uploads,[])
        self.assertEqual(self.remote,{self.name:self.old})
        self.assertEqual(json.loads(self.manifest.read_text())['songs'],old_manifest['songs'])

    def test_changed_audio_never_replaces_asset_used_by_still_live_reader(self):
        original_reader=(self.song/'data.js').read_bytes()
        self.assertEqual(self.invoke(),0)
        self.assertEqual(self.remote[self.name],self.old,
            'old published reader must keep its original audio while new pages are prepared/deployed')
        row=json.loads(self.manifest.read_text())['songs']['fixture'][0]
        self.assertNotEqual(row['src'],self.old_url)
        self.assertIn(hashlib.sha256(self.new).hexdigest(),row['src'])
        self.assertEqual(self.remote[row['src'].rsplit('/',1)[-1]],self.new)
        self.assertEqual((self.song/'data.js').read_bytes(),original_reader)
        self.assertNotIn(self.name,self.uploads)

    def test_interrupted_manifest_update_reuses_uploaded_immutable_asset_without_old_url_mutation(self):
        old_manifest=self.manifest.read_bytes()
        with mock.patch.object(media,'atomic_json',side_effect=OSError('fixture interruption before manifest commit')):
            with self.assertRaises(OSError):self.invoke()
        self.assertEqual(self.manifest.read_bytes(),old_manifest)
        self.assertEqual(self.remote[self.name],self.old)
        count=len(self.uploads)
        self.assertEqual(self.invoke(),0)
        self.assertEqual(len(self.uploads),count,'resume should reuse the immutable uploaded content')
        self.assertEqual(self.remote[self.name],self.old)

    def test_pending_during_remote_listing_blocks_upload_and_manifest(self):
        before=self.manifest.read_bytes()
        def remote(*args):
            marker=self.song/'.transcription/trim-applied.json';marker.parent.mkdir(parents=True,exist_ok=True)
            marker.write_text('{"status":"pending","adoption":{"status":"pending"}}')
            return {name:len(data) for name,data in self.remote.items()}
        with mock.patch.object(media,'release_assets',side_effect=remote):
            with self.assertRaisesRegex((RuntimeError,ValueError),'(?i)(pending|changed|snapshot|transaction)'):
                self.invoke()
        self.assertEqual(self.uploads,[])
        self.assertEqual(self.manifest.read_bytes(),before)
        self.assertEqual(self.remote,{self.name:self.old})

    def test_atomic_native_replacement_between_hash_and_staging_never_uploads_mislabeled_bytes(self):
        original=media.sha256;replaced=[];before=self.manifest.read_bytes()
        def changed(path):
            result=original(path)
            if not replaced:
                replacement=path.with_suffix('.replacement');replacement.write_bytes(b'newer boundary bytes')
                replacement.replace(path);replaced.append(str(path))
            return result
        try:
            with mock.patch.object(media,'sha256',side_effect=changed):self.invoke()
        except (RuntimeError,ValueError):
            self.assertEqual(self.manifest.read_bytes(),before)
        else:
            row=json.loads(self.manifest.read_text())['songs']['fixture'][0]
            uploaded=self.remote[row['src'].rsplit('/',1)[-1]]
            self.assertEqual(row['sha256'],hashlib.sha256(uploaded).hexdigest())
        for name in self.uploads:
            self.assertIn(hashlib.sha256(self.remote[name]).hexdigest(),name)
        self.assertEqual(self.remote[self.name],self.old)

    def test_interruption_during_manifest_serialization_preserves_old_file_and_resume(self):
        before=self.manifest.read_bytes()
        write=Path.write_text
        def partial_dump(value,handle,*args,**kwargs):
            handle.write('{"schemaVersion": 2, "song')
            handle.flush()
            raise OSError('fixture partial manifest serialization')
        def partial_direct(path,text,*args,**kwargs):
            if path==self.manifest:
                path.write_bytes(text.encode()[:27])
                raise OSError('fixture partial manifest serialization')
            return write(path,text,*args,**kwargs)
        with mock.patch.object(json,'dump',side_effect=partial_dump),mock.patch.object(Path,'write_text',new=partial_direct):
            with self.assertRaises((OSError,RunFatal)):
                self.invoke()
        self.assertEqual(self.manifest.read_bytes(),before,'incomplete replacement must never truncate the public manifest')
        self.assertTrue(self.uploads)
        uploads=list(self.uploads)
        self.assertEqual(self.invoke(),0)
        self.assertEqual(self.uploads,uploads)
        self.assertEqual(self.remote[self.name],self.old)
        value=json.loads(self.manifest.read_text())
        row=value['songs']['fixture'][0]
        self.assertEqual(row['sha256'],hashlib.sha256(self.remote[row['src'].rsplit('/',1)[-1]]).hexdigest())

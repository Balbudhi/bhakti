"""Exact hosted artifact population and shared workflow assembly contract."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
import yaml

ROOT=Path(os.environ.get('BHAKTI_TEST_PIPELINE_ROOT',Path(__file__).resolve().parents[1]))
if not (ROOT/'.github/workflows').is_dir():ROOT=Path.cwd()

class HostedPublicAssembly(unittest.TestCase):
    def test_both_workflows_share_allowlisted_assembly_and_upload_only_site(self):
        for name in ['deploy-pages.yml','run-bhakti-intake.yml']:
            with self.subTest(workflow=name):
                value=yaml.safe_load((ROOT/'.github/workflows'/name).read_text())
                steps=[step for job in value['jobs'].values() for step in job['steps']]
                uploads=[(i,step) for i,step in enumerate(steps) if str(step.get('uses','')).startswith('actions/upload-pages-artifact@')]
                self.assertEqual(len(uploads),1)
                index,upload=uploads[0]
                self.assertEqual(upload.get('with',{}).get('path','_site'),'_site')
                self.assertTrue(any('python3 scripts/assemble_public_site.py' in step.get('run','') for step in steps[:index]),
                    'all deploy paths must use the same maintained allowlist assembler')

    def test_actual_assembler_excludes_all_private_state_and_removes_stale_output(self):
        path=ROOT/'scripts/assemble_public_site.py'
        self.assertTrue(path.is_file(),'shared public site assembler is missing')
        spec=importlib.util.spec_from_file_location('boundary_site_assembler',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            allowed=['index.html','manifest.webmanifest','sw.js','robots.txt','sitemap.xml','CNAME',
                     'data/songs.js','assets/site.css','assets/library.js','assets/icons/play.svg',
                     'songs/fixture/index.html','songs/fixture/data.js']
            forbidden=['AGENTS.md','docs/private.md','scripts/review.py','data/editorial_baselines.json',
                       '.transcription/run/api-ledger.json','songs/fixture/.transcription/review.json',
                       'songs/fixture/audio.m4a','songs/fixture/source-notes.txt','songs/fixture/review-candidate.js']
            for name in allowed+forbidden:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(name)
            stale=root/'_site/private-from-old-build.json';stale.parent.mkdir();stale.write_text('private')
            module.assemble_public_site(root)
            actual={str(path.relative_to(root/'_site')) for path in (root/'_site').rglob('*') if path.is_file()}
            self.assertEqual(actual,set(allowed))
            for name in allowed:self.assertEqual((root/'_site'/name).read_bytes(),(root/name).read_bytes())
            for name in forbidden:self.assertTrue((root/name).is_file(),'assembly must not remove source/private originals')

    def test_global_site_assembly_holds_pending_song_before_replacing_previous_artifact(self):
        path=ROOT/'scripts/assemble_public_site.py'
        self.assertTrue(path.is_file(),'shared public site assembler is missing')
        spec=importlib.util.spec_from_file_location('pending_site_assembler',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);marker=root/'songs/fixture/.transcription/trim-applied.json'
            marker.parent.mkdir(parents=True);marker.write_text('{"status":"pending","application_version":2}')
            previous=root/'_site/index.html';previous.parent.mkdir();previous.write_text('previous accepted artifact')
            with self.assertRaisesRegex((RuntimeError,ValueError),'(?i)(pending|recover|adoption)'):
                module.assemble_public_site(root)
            self.assertEqual(previous.read_text(),'previous accepted artifact')

    def test_completed_transition_between_copies_never_assembles_mixed_reader_bundle(self):
        from unittest import mock
        path=ROOT/'scripts/assemble_public_site.py'
        self.assertTrue(path.is_file())
        spec=importlib.util.spec_from_file_location('interleaved_site_assembler',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);song=root/'songs/fixture';song.mkdir(parents=True)
            for name in (*module.PUBLIC_ROOT_FILES,'data/songs.js','assets/site.css'):
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(name)
            for name in ('index.html','data.js'):(song/name).write_text('old bundle')
            previous=root/'_site/index.html';previous.parent.mkdir();previous.write_text('previous artifact')
            marker=song/'.transcription/trim-applied.json';marker.parent.mkdir()
            marker.write_text('{"status":"applied","operation_id":"old"}')
            copy=module.shutil.copy2
            def transition(source,destination,*args,**kwargs):
                result=copy(source,destination,*args,**kwargs)
                if source==song/'index.html':
                    marker.write_text('{"status":"pending","operation_id":"new"}')
                    for name in ('index.html','data.js'):(song/name).write_text('new bundle')
                    marker.write_text('{"status":"applied","operation_id":"new"}')
                return result
            with mock.patch.object(module.shutil,'copy2',side_effect=transition):
                with self.assertRaisesRegex((RuntimeError,ValueError),'(?i)(changed|snapshot|transaction)'):
                    module.assemble_public_site(root)
            self.assertEqual(previous.read_text(),'previous artifact')

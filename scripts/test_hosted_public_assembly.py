"""Exact hosted artifact population and shared workflow assembly contract."""
import importlib.util
import base64
import hashlib
import json
import re
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
            self.assertEqual(actual,set(allowed) | {"assets/release-map.js"})
            for name in allowed:
                if name != 'sw.js':
                    self.assertEqual((root/'_site'/name).read_bytes(), (root/name).read_bytes())
            self.assertTrue((root/'_site/sw.js').read_text().endswith((root/'sw.js').read_text()))
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


class ReleaseAssembly(unittest.TestCase):
    def test_revisioned_runtime_is_bound_to_copied_bytes_without_mutating_sources(self):
        import assemble_public_site as assembly
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = {
                'index.html': '<html><head><link rel="preconnect" href="https://fonts.gstatic.com"><link rel="stylesheet" href="https://fonts.googleapis.com/css"></head><body><script src="/data/shuffle-profiles.js?v=old"></script><script src="/assets/shuffle.js?v=old"></script><script src="/assets/app.js?v=old"></script></body></html>',
                'songs/example/index.html': '<script src="data.js"></script><script src="/assets/app.js?v=old"></script>',
                'songs/example/data.js': 'window.SONG_LINES = ["preserved lyric"];',
                'assets/app.js': 'window.app = true;',
                'assets/shuffle.js': 'engine', 'assets/shuffle-client.js': 'client',
                'assets/shuffle-worker.js': 'worker', 'data/shuffle-profiles.js': 'profiles',
                'assets/fonts.css': '@font-face {src: url("fonts/extended.woff2");}',
                'assets/fonts/extended.woff2': 'font',
                'data/songs.js': 'catalogue',
                'sw.js': (ROOT / 'sw.js').read_text(),
            }
            for name in assembly.PUBLIC_ROOT_FILES:
                assets.setdefault(name, name)
            for name, body in assets.items():
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(body)
            # Exercise the transformation directly: pairing is independently
            # covered by integration tests; this fixture is not a song catalogue.
            assembly.prepare_release(root)
            config = json.loads((root/'sw.js').read_text().split(' = ', 1)[1].split(';\n', 1)[0])
            for path, url in config['paths'].items():
                self.assertEqual(url, path + '?v=' + hashlib.sha256((root/path.lstrip('/')).read_bytes()).hexdigest())
            html = (root/'index.html').read_text()
            self.assertNotIn('googleapis', html); self.assertNotIn('gstatic', html)
            for tag in re.findall(r'<(?:script|link)\b[^>]*>', html):
                if 'src=' in tag or 'rel="stylesheet"' in tag:
                    resource = re.search(r'(?:src|href)="([^?]+)', tag)[1]
                    expected = base64.b64encode(hashlib.sha256((root/resource.lstrip('/')).read_bytes()).digest()).decode()
                    self.assertIn('integrity="sha256-' + expected + '"', tag)
            self.assertNotRegex(html, r'<script src="/(?:assets/shuffle\.js|data/shuffle-profiles\.js)')
            self.assertLess(html.index('/assets/release-map.js'), html.index('/assets/shuffle-client.js'))
            self.assertLess(html.index('/assets/shuffle-client.js'), html.index('/assets/app.js'))
            self.assertIn(config['paths']['/assets/fonts.css'], html)
            self.assertIn(config['paths']['/assets/fonts/extended.woff2'], (root/'assets/fonts.css').read_text())
            self.assertIn(config['paths']['/songs/example/data.js'], (root/'songs/example/index.html').read_text())
            self.assertEqual((root/'songs/example/data.js').read_text(), assets['songs/example/data.js'])
            for lazy in ['/assets/shuffle.js', '/assets/shuffle-worker.js', '/data/shuffle-profiles.js', '/songs/example/data.js']:
                self.assertNotIn(config['paths'][lazy], config['shell'])
            self.assertIn(config['paths']['/assets/release-map.js'], config['shell'])
            self.assertNotIn('/sw.js', config['paths'])
            self.assertEqual(config['documents']['/index.html'], hashlib.sha256((root/'index.html').read_bytes()).hexdigest())

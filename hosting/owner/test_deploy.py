"""Deployment boundary tests use real files; cPanel/network remain external checks."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


def module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name).resolve()
        self.deploy = module('deploy')
        self.roots = [{'domain': 'example.test', 'documentroot': str(self.home / 'public_html')}]
        (self.home / 'public_html').mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_nonoverlap_and_exact_existing_owner(self):
        public, private = self.deploy.check_layout(self.home, self.roots)
        self.assertEqual(public, self.home / 'bhakti-owner-public')
        self.assertEqual(private, self.home / '.bhakti-owner')
        self.deploy.check_layout(self.home, self.roots + [{'domain': self.deploy.DOMAIN, 'documentroot': str(public)}])
        for root in (self.home, public / 'child', private, private / 'child'):
            with self.subTest(root=root), self.assertRaises(ValueError):
                self.deploy.check_layout(self.home, self.roots + [{'domain': 'other.test', 'documentroot': str(root)}])

    def test_symlink_and_incorrect_owner_mapping_rejected(self):
        (self.home / 'bhakti-owner-public').symlink_to(self.home / 'public_html', target_is_directory=True)
        with self.assertRaises(ValueError):
            self.deploy.check_layout(self.home, self.roots)
        (self.home / 'bhakti-owner-public').unlink()
        with self.assertRaises(ValueError):
            self.deploy.check_layout(self.home, self.roots + [{'domain': self.deploy.DOMAIN, 'documentroot': str(self.home / 'public_html')}])

    def test_unknown_public_file_and_private_mode_rejected(self):
        public, private = self.deploy.check_layout(self.home, self.roots)
        public.mkdir()
        (public / 'unowned.txt').write_text('do not overwrite')
        with self.assertRaises(ValueError):
            self.deploy.check_owned_tree(public, private)
        (public / 'unowned.txt').unlink()
        private.mkdir(mode=0o755)
        with self.assertRaises(ValueError):
            self.deploy.check_owned_tree(public, private)

    def test_private_atomic_write_preserves_on_validation_failure(self):
        destination = self.home / 'private' / 'queue.json'
        self.deploy.write_private(destination, b'first', forbidden_roots=[self.home / 'public_html'])
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        self.deploy.write_private(destination, b'second', forbidden_roots=[self.home / 'public_html'])
        self.assertEqual(destination.read_bytes(), b'second')
        for target in (self.home / 'public_html' / 'queue.json', self.home / 'link' / 'queue.json'):
            if target.parent.name == 'link':
                target.parent.symlink_to(destination.parent, target_is_directory=True)
            with self.assertRaises(ValueError):
                self.deploy.write_private(target, b'unsafe', forbidden_roots=[self.home / 'public_html'])
        self.assertEqual(destination.read_bytes(), b'second')
        outside = self.home / 'outside'
        outside.mkdir()
        with self.assertRaises(ValueError):
            self.deploy.write_private(outside / '..' / 'public_html' / 'leak.json', b'unsafe', forbidden_roots=[self.home / 'public_html'])
        self.assertFalse((self.home / 'public_html' / 'leak.json').exists())
        repository = self.home / 'other-repository'
        repository.mkdir()
        (repository / '.git').mkdir()
        with self.assertRaises(ValueError):
            self.deploy.write_private(repository / 'private' / 'queue.json', b'unsafe', forbidden_roots=[])
        link = destination.parent / 'linked.json'
        link.symlink_to(destination)
        with self.assertRaises(ValueError):
            self.deploy.write_private(link, b'unsafe', forbidden_roots=[])

    def test_known_deployment_symlinks_rejected(self):
        public, private = self.deploy.check_layout(self.home, self.roots)
        public.mkdir()
        private.mkdir(mode=0o700)
        (public / 'owner.cgi').symlink_to(self.home / 'unrelated')
        with self.assertRaises(ValueError):
            self.deploy.check_owned_tree(public, private)
        (public / 'owner.cgi').unlink()
        private.rmdir()
        private.symlink_to(self.home / 'public_html', target_is_directory=True)
        with self.assertRaises(ValueError):
            self.deploy.check_owned_tree(public, private)

    def test_release_hash_rejection_and_private_rollback(self):
        public, private = self.deploy.check_layout(self.home, self.roots)
        public.mkdir()
        private.mkdir(mode=0o700)
        (public / '.htaccess').write_text(self.deploy.DENY)
        first = b'\x7fELFfirst'
        second = b'\x7fELFsecond'
        import hashlib
        self.deploy.install_release(public, private, first, hashlib.sha256(first).hexdigest())
        with self.assertRaises(ValueError):
            self.deploy.install_release(public, private, second, 'wrong')
        self.assertEqual((public / 'owner.cgi').read_bytes(), first)
        self.deploy.install_release(public, private, second, hashlib.sha256(second).hexdigest())
        self.assertEqual((public / 'owner.cgi').read_bytes(), second)
        self.assertEqual((private / 'previous.cgi').read_bytes(), first)
        self.assertEqual((public / 'owner.cgi').stat().st_mode & 0o777, 0o700)
        self.assertEqual((public / '.htaccess').read_text(), self.deploy.APACHE)

    def test_first_activation_rollback_is_retryable_and_stale_rollback_refused(self):
        import hashlib
        public, private = self.deploy.check_layout(self.home, self.roots)
        public.mkdir()
        private.mkdir(mode=0o700)
        (public / '.htaccess').write_text(self.deploy.DENY)
        first, second = b'\x7fELFfirst', b'\x7fELFsecond'
        first_hash, second_hash = hashlib.sha256(first).hexdigest(), hashlib.sha256(second).hexdigest()
        self.deploy.install_release(public, private, first, first_hash)
        self.assertTrue(self.deploy.is_active(public))
        self.deploy.rollback_release(public, private, first_hash)
        self.assertFalse(self.deploy.is_active(public))
        self.deploy.install_release(public, private, second, second_hash)
        self.assertTrue(self.deploy.is_active(public))
        self.assertFalse((private / 'previous.cgi').exists())
        with self.assertRaises(ValueError):
            self.deploy.rollback_release(public, private, first_hash)
        self.assertTrue(self.deploy.is_active(public))
        self.assertEqual((public / 'owner.cgi').read_bytes(), second)

    def test_only_empty_generated_cgi_directory_is_removed(self):
        public = self.home / 'public'
        public.mkdir()
        self.deploy.remove_generated_cgi_directory(public)
        child = public / 'cgi-bin'
        child.mkdir()
        self.deploy.remove_generated_cgi_directory(public)
        self.assertFalse(child.exists())
        child.mkdir()
        (child / 'preserve').write_text('data')
        with self.assertRaises(OSError):
            self.deploy.remove_generated_cgi_directory(public)
        self.assertEqual((child / 'preserve').read_text(), 'data')
        (child / 'preserve').unlink()
        child.rmdir()
        child.symlink_to(self.home / 'public_html', target_is_directory=True)
        with self.assertRaises(ValueError):
            self.deploy.remove_generated_cgi_directory(public)

    def test_cpanel_inventory_requires_complete_success(self):
        raw = {'result': {'status': 1, 'data': {'main_domain': self.roots[0], 'sub_domains': [], 'addon_domains': [], 'parked_domains': []}}}
        self.assertEqual(self.deploy.parse_inventory(raw), self.roots)
        for key in ('main_domain', 'sub_domains', 'addon_domains', 'parked_domains'):
            broken = json.loads(json.dumps(raw))
            del broken['result']['data'][key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.deploy.parse_inventory(broken)

    def test_export_validation_preserves_text_and_rejects_invalid_snapshot(self):
        pull = module('pull')
        good = {'version': 1, 'requests': [{'id': '11111111-1111-4111-8111-111111111111', 'text': '  Song\n', 'createdAt': '2026-10-28T12:00:00Z', 'status': 'queued'}]}
        raw = json.dumps(good).encode()
        self.assertEqual(pull.validate_export(raw), raw)
        for bad in ({'version': 2, 'requests': []}, {'version': 1, 'requests': [{}]}, {'version': 1, 'requests': good['requests'] * 2}, {'version': 1, 'requests': [], 'credentials': []}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                pull.validate_export(json.dumps(bad).encode())


if __name__ == '__main__':
    unittest.main()

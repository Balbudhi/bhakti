"""Local supplied AAC custody, ordinary YouTube policy and bounded audit CLI."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import audit_audio_quality as audit


def ref(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


class AudioQualityLocalExcerptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        base = Path(cls.fixture.name)
        cls.original = base/'supplied.m4a'
        cls.output = base/'cut.m4a'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'aevalsrc=0.2*sin(2*PI*(220*t+11*t*t)):s=48000:d=8',
                        '-c:a', 'aac', str(cls.original)], check=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-ss', '2', '-i', str(cls.original),
                        '-t', '4', '-c:a', 'copy', str(cls.output)], check=True)
        cls.proof = audit.pipeline.trim_packet_evidence(cls.original, cls.output, 2.)

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.song = self.root/'songs'/'excerpt'
        (self.song/'.transcription').mkdir(parents=True)
        shutil.copyfile(self.output, self.song/'audio.m4a')
        self.acceptance = self.root/'accepted.json'
        self.acceptance.write_text(json.dumps({'status': 'root-accepted-broadcast-boundaries',
            'candidateId': 'candidate', 'original': ref(self.original), 'startSeconds': 2., 'endSeconds': 6.}))
        self.receipt = self.root/'receipt.json'
        self.value = {'version': 1, 'status': 'lossless-excerpt-ready', 'candidateId': 'candidate',
            'original': {**ref(self.original), 'provenance': 'user-supplied'},
            'output': ref(self.output), 'boundaryAcceptance': ref(self.acceptance),
            'extraction': {'method': 'stream-copy', 'requestedStartSeconds': 2., 'requestedEndSeconds': 6.,
                'packetSourceOffset': self.proof['packet_source_offset'],
                'outputDurationSeconds': self.proof['duration']}, 'packetEvidence': copy.deepcopy(self.proof)}
        self.source = {'source_url': 'https://www.youtube.com/watch?v=abcdefghijk', 'source_file': 'audio.m4a'}
        self.save()

    def save(self):
        self.receipt.write_text(json.dumps(self.value))
        self.source['local_excerpt'] = ref(self.receipt)
        self.save_source()

    def save_source(self):
        (self.song/'.transcription/source.json').write_text(json.dumps(self.source))

    def run_audit(self, *args):
        output = io.StringIO()
        with patch.object(audit, 'ROOT', self.root), patch.object(sys, 'argv', ['audit_audio_quality.py', *args]), contextlib.redirect_stdout(output):
            code = audit.main()
        return code, json.loads(output.getvalue())

    def test_supplied_stream_copy_with_youtube_provenance_passes(self):
        # The real packet matcher produced this receipt; the audit consumes its
        # hash-bound proof without repeating discovery or invoking a downloader.
        with patch.object(audit.pipeline, 'trim_packet_evidence', side_effect=AssertionError('must reuse evidence')):
            code, report = self.run_audit()
        self.assertEqual(code, 0, report['errors'])
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['songs'][0]['preferred'], 'audio.m4a')

    def test_custody_and_evidence_fail_closed(self):
        changes = [
            ('status', lambda r: r.update(status='pending')),
            ('original hash', lambda r: r['original'].update(sha256='0'*64)),
            ('output hash', lambda r: r['output'].update(sha256='0'*64)),
            ('acceptance hash', lambda r: r['boundaryAcceptance'].update(sha256='0'*64)),
            ('provenance', lambda r: r['original'].update(provenance='downloaded')),
            ('method', lambda r: r['extraction'].update(method='transcode')),
            ('missing proof', lambda r: r.pop('packetEvidence')),
            ('packet count', lambda r: r['packetEvidence'].update(matched_packets=0)),
            ('codec', lambda r: r['packetEvidence']['output_stream'].update(codec_name='mp3')),
            ('NaN', lambda r: r['extraction'].update(packetSourceOffset=float('nan'))),
            ('boolean number', lambda r: r['extraction'].update(requestedStartSeconds=True)),
            ('spread', lambda r: r['packetEvidence'].update(packet_offset_spread=.01)),
            ('end', lambda r: r['extraction'].update(requestedEndSeconds=7.)),
            ('offset', lambda r: r['packetEvidence'].update(packet_source_offset=2.5)),
        ]
        original = copy.deepcopy(self.value)
        for name, change in changes:
            with self.subTest(name=name):
                self.value = copy.deepcopy(original); change(self.value); self.save()
                code, report = self.run_audit()
                self.assertEqual(code, 1)
                self.assertTrue(any('local excerpt' in e.lower() for e in report['errors']), report)

    def test_changed_listener_or_fake_reference_cannot_waive_opus(self):
        with (self.song/'audio.m4a').open('ab') as out:
            out.write(b'changed container')
        code, report = self.run_audit()
        self.assertEqual(code, 1)
        self.assertTrue(any('local excerpt' in e.lower() for e in report['errors']))
        shutil.copyfile(self.output, self.song/'audio.m4a')
        shutil.copyfile(self.output, self.song/'audio.webm')
        self.source['local_excerpt']['sha256'] = '0'*64; self.save_source()
        code, report = self.run_audit()
        self.assertEqual(code, 1)
        self.assertTrue(any('local excerpt' in e.lower() for e in report['errors']))

    def test_missing_receipt_pending_trim_and_boundary_binding(self):
        self.source['local_excerpt']['path'] = str(self.root/'missing.json')
        self.save_source()
        self.assertEqual(self.run_audit()[0], 1)
        self.save()
        marker = self.song/'.transcription/trim-applied.json'
        marker.write_text(json.dumps({'status': 'pending'}))
        self.assertEqual(self.run_audit()[0], 1)
        marker.unlink()
        accepted = json.loads(self.acceptance.read_text())
        for field, value in [('candidateId', 'other'), ('status', 'pending'),
                             ('original', {'path': str(self.original), 'sha256': '0'*64}),
                             ('startSeconds', 3.), ('endSeconds', 7.)]:
            with self.subTest(field=field):
                self.acceptance.write_text(json.dumps({**accepted, field: value}))
                self.value['boundaryAcceptance'] = ref(self.acceptance)
                self.save()
                self.assertEqual(self.run_audit()[0], 1)

    def test_ordinary_youtube_still_requires_opus(self):
        self.source.pop('local_excerpt'); self.save_source()
        code, report = self.run_audit()
        self.assertEqual(code, 1)
        self.assertTrue(any('Opus' in e for e in report['errors']))

    def test_scope_and_help(self):
        other = self.root/'songs'/'unrelated'
        other.mkdir()
        code, report = self.run_audit('--song', 'excerpt', '--song', 'excerpt')
        self.assertEqual(code, 0, report['errors'])
        self.assertEqual([x['slug'] for x in report['songs']], ['excerpt'])
        for value in ('../excerpt', '/tmp', 'missing'):
            with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                self.run_audit('--song', value)
            self.assertEqual(caught.exception.code, 2)

    def test_help_does_not_audit(self):
        with patch.object(audit, 'probe', side_effect=AssertionError('help must not probe')), patch.object(audit.pipeline, 'listener_audio_sources', side_effect=AssertionError('help must not inspect listeners')):
            with self.assertRaises(SystemExit) as caught:
                self.run_audit('--help')
        self.assertEqual(caught.exception.code, 0)


if __name__ == '__main__':
    unittest.main()

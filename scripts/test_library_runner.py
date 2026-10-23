"""Bounded CLI drives real stage/router calls and resumes completed songs privately."""
import copy
import json
import os
from pathlib import Path
from unittest.mock import patch
import unittest

import bhakti_library_pass as library
from test_bhakti_library_pass import SelectivePassTests
from test_library_execution import review


class RunnerTests(SelectivePassTests):
    def provider(self, model, key, prompt, **kwargs):
        # This transport double records each request in the same on-disk ledger
        # inspected by the caller. Atomic reservation/cap tests belong to the
        # real transport suite; this tests actual CLI/stage/resume integration.
        ledger_path = Path(os.environ['BHAKTI_API_RUN_LEDGER'])
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {
            'version': 1, 'budget_usd': float(os.environ['BHAKTI_API_RUN_BUDGET_USD']),
            'max_calls': int(os.environ['BHAKTI_API_RUN_MAX_CALLS']), 'requests': [], 'blocked': False}
        if len(ledger['requests']) >= ledger['max_calls']:
            raise AssertionError('caller dispatched after maximum request count')
        ledger['requests'].append({'id': str(len(ledger['requests'])), 'reservation_usd': 0.2,
                                   'reported_cost_usd': 0.01, 'status': 'parsed'})
        ledger_path.parent.mkdir(parents=True, exist_ok=True); ledger_path.write_text(json.dumps(ledger))
        evidence = json.JSONDecoder().raw_decode(prompt.split('EVIDENCE:\n', 1)[1].lstrip())[0]
        return {'packet': {'reviews': [review(item['source']['id']) for item in evidence]}}

    def command(self, cap=2):
        return ['--root', str(self.root), '--state-dir', str(self.state), '--execute', '--all',
                '--workers', '1', '--budget-usd', '1', '--max-calls', str(cap), '--deadline-seconds', '60']

    def test_real_all_cli_finishes_two_songs_and_resume_has_zero_requests_or_public_changes(self):
        self.add_song('alpha'); self.add_song('beta'); self.commit()
        originals = {slug: (self.root / 'songs' / slug / 'data.js').read_bytes() for slug in ('alpha', 'beta')}
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), patch.object(library.pipeline.gemini, 'call', side_effect=self.provider) as transport:
            self.assertEqual(library.main(self.command()), 0)
            self.assertEqual(library.main(self.command()), 0)
        self.assertEqual(transport.call_count, 2)
        report = json.loads((self.state / 'run.json').read_text())
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(set(report['songs']), {'alpha', 'beta'})
        self.assertTrue(all(row['status'] == 'accepted' for row in report['songs'].values()))
        self.assertEqual(len(json.loads((self.state / 'api-ledger.json').read_text())['requests']), 2)
        self.assertEqual(originals, {slug: (self.root / 'songs' / slug / 'data.js').read_bytes() for slug in originals})

    def test_budgeted_all_queue_stops_before_second_request_without_dropping_remaining_song(self):
        self.add_song('alpha'); self.add_song('beta'); self.commit()
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), patch.object(library.pipeline.gemini, 'call', side_effect=self.provider) as transport:
            self.assertEqual(library.main(self.command(cap=1)), 0)
            self.assertEqual(library.main(self.command(cap=1)), 0)
        self.assertEqual(transport.call_count, 1)
        report = json.loads((self.state / 'run.json').read_text())
        self.assertEqual(report['status'], 'bounded-stop')
        self.assertEqual(report['remaining'], ['beta'])
        self.assertEqual(report['songs']['alpha']['status'], 'accepted')

    def test_completed_resume_rejects_metadata_input_change_without_another_request(self):
        data = self.add_song('alpha'); self.commit()
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), patch.object(library.pipeline.gemini, 'call', side_effect=self.provider) as transport:
            library.main(self.command())
            data['SONG_META']['title'] = 'A changed title'
            from test_bhakti_library_pass import write_js
            write_js(self.root / 'songs/alpha/data.js', data)
            with self.assertRaisesRegex(ValueError, 'frozen run inputs'):
                library.main(self.command())
        self.assertEqual(transport.call_count, 1)

    def test_source_evidence_changed_during_review_cannot_be_marked_accepted(self):
        self.add_song('alpha'); self.commit()
        def mutate_source(*args, **kwargs):
            response = self.provider(*args, **kwargs)
            source = self.root / 'songs/alpha/.transcription/source.json'
            source.write_text('{"source_url":"https://www.youtube.com/watch?v=changed1234"}')
            return response
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), patch.object(library.pipeline.gemini, 'call', side_effect=mutate_source):
            library.main(self.command())
        result = json.loads((self.state / 'run.json').read_text())['songs']['alpha']
        self.assertEqual(result['status'], 'unresolved'); self.assertFalse(result['publicationEligible'])
        self.assertTrue(any('evidence changed' in issue for issue in result['issues']))

    def test_completed_candidate_tampering_is_rejected_on_resume(self):
        self.add_song('alpha'); self.commit()
        with patch.object(library.pipeline.gemini, 'key', return_value='unused'), patch.object(library.pipeline.gemini, 'call', side_effect=self.provider) as transport:
            library.main(self.command())
            result = json.loads((self.state / 'run.json').read_text())['songs']['alpha']
            (Path(result['candidateRoot']) / 'songs/alpha/data.js').write_text('changed candidate')
            with self.assertRaisesRegex(ValueError, 'accepted candidate'):
                library.main(self.command())
        self.assertEqual(transport.call_count, 1)

    def test_explicit_stored_human_translation_is_protected_without_registry_entry(self):
        self.add_song('alpha'); self.commit()
        source = self.root / 'songs/alpha/.transcription/source.json'
        source.write_text(json.dumps({'source_url': 'https://www.youtube.com/watch?v=abcdefghijk',
                                     'providedTranslation': {'one': 'mind'}}))
        with patch.object(library.pipeline.gemini, 'key', side_effect=AssertionError('protected baseline read key')), patch.object(library.pipeline.gemini, 'call', side_effect=AssertionError('protected baseline spent money')):
            library.main(self.command())
        report = json.loads((self.state / 'run.json').read_text())
        self.assertEqual(report['songs']['alpha']['status'], 'protected')
        self.assertFalse(report['songs']['alpha']['publicationEligible'])
        self.assertEqual(report['ledger']['calls'], 0)


if __name__ == '__main__': unittest.main()

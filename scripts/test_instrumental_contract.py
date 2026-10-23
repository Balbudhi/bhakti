"""Instrumental metadata cannot exempt a reference also performed as lyrics."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

import audit_bhakti_contract as audit


class InstrumentalContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader = audit.load_data(audit.ROOT / 'songs/rehna-nahi-isa-desa/data.js')

    def audit_reader(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'data.js').write_text('\n'.join(
                f'window.{key} = {json.dumps(value, ensure_ascii=False)};'
                for key, value in data.items()
            ), encoding='utf-8')
            return audit.audit_song(path)['problems']

    def test_real_verse_with_instrumental_alias_still_requires_all_lyric_fields(self):
        data = copy.deepcopy(self.reader)
        ref = 'verse-3-line-1'
        self.assertTrue(any(e['ref'] == ref and e['section'] == 'verse'
                            for e in data['SONG_SEQUENCE']))
        cue = next(e for e in data['SONG_SEQUENCE'] if e['section'] == 'instrumental')
        cue['ref'] = ref
        data['SONG_LINES'][ref].update(source='', roman='', english='', words=[])
        problems = self.audit_reader(data)
        for field in ('source script', 'IAST', 'literal English', 'word glosses'):
            with self.subTest(field=field):
                self.assertIn(f'{ref} lacks {field}', problems)

    def test_pure_instrumental_allows_nonlexical_descriptive_metadata(self):
        data = copy.deepcopy(self.reader)
        ref = next(e['ref'] for e in data['SONG_SEQUENCE'] if e['section'] == 'instrumental')
        self.assertTrue(all(e['section'] == 'instrumental'
                            for e in data['SONG_SEQUENCE'] if e['ref'] == ref))
        data['SONG_LINES'][ref].update(
            source='[वाद्य-संगीत]', roman='[Instrumental introduction]',
            english='Flute and strings', words=[], sourceWords=[],
        )
        self.assertEqual([p for p in self.audit_reader(data) if p.startswith(ref + ' ')], [])

    def test_pure_instrumental_does_not_require_invented_lyrics(self):
        data = copy.deepcopy(self.reader)
        ref = next(e['ref'] for e in data['SONG_SEQUENCE'] if e['section'] == 'instrumental')
        data['SONG_LINES'][ref].update(
            source='', roman='', english='[Instrumental]', words=[], sourceWords=[],
        )
        self.assertEqual([p for p in self.audit_reader(data) if p.startswith(ref + ' ')], [])


if __name__ == '__main__':
    unittest.main()

"""The local release runner executes the same explicit argv as the workflow."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import song


class SongCheckTests(unittest.TestCase):
    def test_real_workflow_keeps_subject_audit_flag_exactly_once(self):
        commands=song.check_commands((song.ROOT/'.github/workflows/deploy-pages.yml').read_text())
        subject=[c for c in commands if len(c)>1 and c[1]=='scripts/search_song_subjects.py']
        self.assertEqual(subject,[('python3','scripts/search_song_subjects.py','--check')])
        self.assertEqual(commands[0],('python3','scripts/assemble_public_site.py'))
        self.assertEqual(len(commands),len(set(commands)))
        compile_commands=[c for c in commands if c[:3]==('python3','-m','py_compile')]
        self.assertEqual(len(compile_commands),1)
        self.assertIn('scripts/song.py',compile_commands[0])
        self.assertFalse(any('*' in a for a in compile_commands[0]))

    def test_check_invokes_preserved_quoted_arguments_not_shell_tokens(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); (root/'node_modules').mkdir(); (root/'.github/workflows').mkdir(parents=True)
            (root/'.github/workflows/deploy-pages.yml').write_text('''run: |
  python3 scripts/search_song_subjects.py --check
  node scripts/test_example.js --label "two words" # descriptive comment
  python3 scripts/search_song_subjects.py --check
''')
            with patch.object(song,'ROOT',root), patch.object(song.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
                song.check()
            argv=[c.args[0] for c in run.call_args_list]
            self.assertIn(('node','scripts/test_example.js','--label','two words'),argv)
            self.assertEqual(argv.count(('python3','scripts/search_song_subjects.py','--check')),1)
            self.assertFalse(any(c.kwargs.get('shell') for c in run.call_args_list))


if __name__=='__main__':unittest.main()

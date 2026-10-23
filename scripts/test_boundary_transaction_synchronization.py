"""Actual subprocess boundary install must serialize only mutation with publication."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
import bhakti_pipeline as p
import bhakti_boundary_timebase as boundary
from test_boundary_application import create_audio,accepted_crop


class BoundaryTransactionSynchronization(unittest.TestCase):
    def test_publication_lock_blocks_actual_writer_install_after_ffmpeg_preparation(self):
        transaction=getattr(boundary,'boundary_transaction',None)
        self.assertTrue(callable(transaction),'shared boundary/publication transaction lock is missing')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);song=root/'songs/fixture';song.mkdir(parents=True)
            original=create_audio(song);artifact=accepted_crop(song,start=2.137,end=28.341)
            request=root/'boundary.json';request.write_text(json.dumps(artifact))
            code='''import contextlib,json,sys
from pathlib import Path
import bhakti_pipeline as p
actual=p.boundary_transaction
run=p.subprocess.run
prepared=[]
def measured(command,*args,**kwargs):
    result=run(command,*args,**kwargs)
    if command[0]=='ffmpeg':prepared.append(command)
    return result
p.subprocess.run=measured
@contextlib.contextmanager
def observed(song):
    # apply must prepare both formats before it enters the critical section.
    print('install-lock-request:'+str(len(prepared)),flush=True)
    with actual(song):yield
p.boundary_transaction=observed
p.apply_lossless_trim(Path(sys.argv[1]),json.loads(Path(sys.argv[2]).read_text()))
print('applied',flush=True)
'''
            with transaction(song):
                process=subprocess.Popen([sys.executable,'-c',code,str(song),str(request)],
                    env=os.environ.copy(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                self.addCleanup(lambda:process.kill() if process.poll() is None else None)
                readable,_,_=select.select([process.stdout],[],[],20)
                self.assertTrue(readable,'writer must reach mutation lock without waiting during FFmpeg')
                self.assertEqual(process.stdout.readline().strip(),'install-lock-request:2')
                self.assertIsNone(process.poll(),'writer must remain blocked until publication completes')
                self.assertFalse((song/'.transcription/trim-applied.json').exists())
                self.assertEqual({name:(song/name).read_bytes() for name in original},original)
            output,error=process.communicate(timeout=20)
            self.assertEqual(process.returncode,0,error)
            self.assertIn('applied',output)
            self.assertEqual(json.loads((song/'.transcription/trim-applied.json').read_text())['status'],'applied')
            for name,data in original.items():
                self.assertEqual((song/'.transcription/original-audio'/name).read_bytes(),data)

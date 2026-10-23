import argparse
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import bhakti_pipeline as p

class BoundaryCostScope(unittest.TestCase):
    def test_run_one_labels_retained_artifact_cost_as_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            song=Path(tmp);(song/'.transcription'/'pipeline').mkdir(parents=True)
            options=argparse.Namespace(force=False,source_witness_audit=False,refresh_timing=False,model=p.MODEL)
            trim={'usage':{'cost':.05}};raw={'packet':{},'usage':{'cost':.01}};audit={'packet':{}}
            with mock.patch.object(p,'intake',return_value=(song,{})), \
                 mock.patch.object(p,'detect_youtube_trim',return_value=trim), \
                 mock.patch.object(p,'apply_lossless_trim'), \
                 mock.patch.object(p,'preferred_listener_audio',return_value=song/'audio.m4a'), \
                 mock.patch.object(p,'transcript',return_value=raw), \
                 mock.patch.object(p,'audit_transcript',return_value=audit), \
                 mock.patch.object(p,'apply_verified_text_corrections',return_value=False), \
                 mock.patch.object(p,'align',return_value={}), \
                 mock.patch.object(p,'complete_semantics',return_value=({},{})), \
                 mock.patch.object(p,'publication_errors',return_value=[]):
                result=p.run_one({'slug':'example'},options)
            self.assertEqual(result['reported_openrouter_cost'],.06)
            self.assertEqual(result['reported_cost_scope'],'accepted-artifacts-only; bounded ledger is authoritative for charges')
            saved=p.read_packet(song/'.transcription'/'pipeline'/'song-packet.json')
            self.assertEqual(saved['reported_cost_scope'],result['reported_cost_scope'])

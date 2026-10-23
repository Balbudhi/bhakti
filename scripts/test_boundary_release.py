import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import bhakti_pipeline as pipeline
import audit_youtube_trims as audit
from test_boundary_application import create_audio,accepted_crop

class BoundaryRelease(unittest.TestCase):
    def test_v2_applied_trim_passes_but_changed_output_or_wrong_identity_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);song=root/'songs'/'example';song.mkdir(parents=True)
            create_audio(song);artifact=accepted_crop(song)
            pipeline.write_json(song/'.transcription'/'trim-review.json',artifact)
            pipeline.apply_lossless_trim(song,artifact)
            def check():
                with mock.patch.object(audit,'ROOT',root),contextlib.redirect_stdout(io.StringIO()):return audit.main()
            self.assertEqual(check(),0)
            audio=song/'audio.m4a';original=audio.read_bytes();audio.write_bytes(original+b'tampered')
            self.assertEqual(check(),1)
            audio.write_bytes(original)
            marker=pipeline.read_packet(song/'.transcription'/'trim-applied.json')
            marker['source_sha256']='0'*64
            pipeline.write_json(song/'.transcription'/'trim-applied.json',marker)
            self.assertEqual(check(),1)

    def test_pending_restoration_of_whole_original_blocks_even_when_new_evidence_says_keep(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);song=root/'songs'/'example';song.mkdir(parents=True)
            create_audio(song);keep=accepted_crop(song)
            for edge in ('start','end'):
                row=keep[edge];row.pop('verification')
                row['response']['packet'].update(decision='keep',relationship='attached_to_work',
                    boundary=0. if edge=='start' else keep['duration'],excluded_evidence='')
            keep=pipeline.normalize_trim_artifact(keep)
            pipeline.write_json(song/'.transcription'/'trim-review.json',keep)
            pipeline.write_json(song/'.transcription'/'trim-applied.json',{'status':'pending','applied':False})
            with mock.patch.object(audit,'ROOT',root),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(audit.main(),1)

    def test_new_keep_review_does_not_certify_old_cropped_assets_before_restoration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);song=root/'songs'/'example';song.mkdir(parents=True)
            create_audio(song);crop=accepted_crop(song);pipeline.apply_lossless_trim(song,crop)
            keep=accepted_crop(song)
            for edge in ('start','end'):
                row=keep[edge];row.pop('verification')
                row['response']['packet'].update(decision='keep',relationship='attached_to_work',
                    boundary=0. if edge=='start' else keep['duration'],excluded_evidence='')
            keep=pipeline.normalize_trim_artifact(keep)
            pipeline.write_json(song/'.transcription'/'trim-review.json',keep)
            with mock.patch.object(audit,'ROOT',root),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(audit.main(),1)

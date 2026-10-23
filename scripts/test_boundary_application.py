"""Application fixtures have explicit normalized v2 evidence, not absent-error approval."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import bhakti_pipeline as pipeline


def create_audio(song, duration=30.):
    (song/'.transcription').mkdir()
    for suffix, codec in (('m4a','aac'),('webm','libopus')):
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i',
                        f'aevalsrc=0.2*sin(2*PI*(220*t+11*t*t)):s=48000:d={duration}','-c:a',codec,str(song/f'audio.{suffix}')],check=True)
    return {p.name:p.read_bytes() for p in song.glob('audio.*')}


def accepted_crop(song, start=2., end=28.):
    archive=song/'.transcription'/'original-audio'
    audio=pipeline.preferred_listener_audio(song)
    original=archive/audio.name if (archive/audio.name).exists() else audio
    duration=pipeline.gemini.duration_seconds(original)
    artifact={'boundary_contract_version':2,'duration':duration,'source_audio':audio.name,
              'source_sha256':hashlib.sha256(original.read_bytes()).hexdigest()}
    for edge,boundary in [('start',start),('end',end)]:
        packet={'edge':edge,'decision':'trim','boundary':boundary,'outside_type':'promotion',
                'relationship':'unrelated','confidence':'high','reason':'Synthetic accepted evidence.',
                'retained_evidence':'Target performance retained in full.',
                'excluded_evidence':'Unrelated announced channel material.'}
        artifact[edge]={'edge':edge,'clip_start':0.,'clip_end':duration,'response':{'packet':packet},
                        'verification':{'edge':edge,'clip_start':0.,'clip_end':duration,
                                        'response':{'packet':copy.deepcopy(packet)}}}
    return pipeline.normalize_trim_artifact(artifact)


def packets(path):
    out=subprocess.run(['ffprobe','-v','error','-select_streams','a:0','-show_packets',
        '-show_data_hash','sha256','-show_entries','packet=pts_time,data_hash',
        '-of','json',str(path)],check=True,capture_output=True,text=True)
    return json.loads(out.stdout)['packets']


class BoundaryApplication(unittest.TestCase):
    def test_normalized_evidence_preserves_originals_and_reports_measured_packet_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            song=Path(tmp); originals=create_audio(song); artifact=accepted_crop(song)
            self.assertEqual(artifact['status'],'reviewed')
            pipeline.apply_lossless_trim(song,artifact)
            marker=pipeline.read_packet(song/'.transcription'/'trim-applied.json')
            self.assertTrue(marker['applied'])
            for name,original in originals.items():
                archive=song/'.transcription'/'original-audio'/name
                self.assertEqual(archive.read_bytes(),original)
                output=packets(song/name); source=packets(archive)
                # Packet hashes establish source provenance. Timestamps establish
                # the actual container origin; nominal -ss is not the answer.
                matches=[r for r in source if r['data_hash']==output[0]['data_hash']]
                self.assertEqual(len(matches),1)
                expected=float(matches[0]['pts_time'])-float(output[0]['pts_time'])
                self.assertAlmostEqual(marker['outputs'][name]['packet_source_offset'],expected,places=5)
                self.assertEqual(marker['outputs'][name]['sha256'],hashlib.sha256((song/name).read_bytes()).hexdigest())

    def test_blocked_missing_acceptance_and_changed_source_hash_are_rejected_without_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            song=Path(tmp); originals=create_audio(song); artifact=accepted_crop(song)
            bads=[]
            bad=copy.deepcopy(artifact);bad['status']='blocked';bads.append(bad)
            bad=copy.deepcopy(artifact);bad['validation_errors']=['upstream unresolved'];bads.append(bad)
            bad=copy.deepcopy(artifact);bad['source_sha256']='0'*64;bads.append(bad)
            bad=copy.deepcopy(artifact);bad.pop('status');bads.append(bad)
            bad=copy.deepcopy(artifact);bad['end']['response']['packet']['relationship']='uncertain';bads.append(bad)
            for bad in bads:
                with self.subTest(bad=bad.get('status')):
                    with self.assertRaises(RuntimeError):pipeline.apply_lossless_trim(song,bad)
                    self.assertEqual({n:hashlib.sha256(b).hexdigest() for n,b in originals.items()},
                             {n:hashlib.sha256((song/n).read_bytes()).hexdigest() for n in originals})
            self.assertFalse((song/'.transcription'/'trim-applied.json').exists())

    def test_interrupted_two_format_apply_resumes_without_double_crop(self):
        with tempfile.TemporaryDirectory() as tmp:
            song=Path(tmp);originals=create_audio(song);artifact=accepted_crop(song)
            targets=[song/r['src'] for r in pipeline.listener_audio_sources(song)]
            second=targets[1];real_replace=Path.replace;interrupted=False
            def fail_second(self,destination):
                nonlocal interrupted
                if Path(destination)==second and not interrupted:
                    interrupted=True;raise OSError('simulated interruption')
                return real_replace(self,destination)
            with mock.patch.object(Path,'replace',fail_second):
                with self.assertRaisesRegex(OSError,'simulated interruption'):
                    pipeline.apply_lossless_trim(song,artifact)
            for name,original in originals.items():
                self.assertEqual((song/'.transcription'/'original-audio'/name).read_bytes(),original)
            self.assertFalse(pipeline.read_packet(song/'.transcription'/'trim-applied.json').get('applied'))
            pipeline.apply_lossless_trim(song,artifact)
            for path in targets:self.assertAlmostEqual(pipeline.gemini.duration_seconds(path),26.,delta=.2)
            final={name:(song/name).read_bytes() for name in originals}
            pipeline.apply_lossless_trim(song,artifact)
            self.assertEqual(final,{name:(song/name).read_bytes() for name in originals})

    def test_changed_interval_rebuilds_from_archive_and_does_not_reuse_stale_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            song=Path(tmp);originals=create_audio(song)
            pipeline.apply_lossless_trim(song,accepted_crop(song))
            pipeline.apply_lossless_trim(song,accepted_crop(song,start=1.,end=29.))
            for name in originals:self.assertAlmostEqual(pipeline.gemini.duration_seconds(song/name),28.,delta=.2)
            marker=pipeline.read_packet(song/'.transcription'/'trim-applied.json')
            self.assertEqual((marker['trim_start'],marker['trim_end']),(1.,29.))

    def test_output_tamper_after_completion_holds_without_overwriting_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            song=Path(tmp);create_audio(song);artifact=accepted_crop(song)
            pipeline.apply_lossless_trim(song,artifact)
            path=song/'audio.m4a';path.write_bytes(path.read_bytes()+b'changed outside trim transaction')
            changed=path.read_bytes()
            with self.assertRaisesRegex(RuntimeError,'changed|identity|digest'):
                pipeline.apply_lossless_trim(song,artifact)
            self.assertEqual(path.read_bytes(),changed)

    def test_failure_after_archive_before_pending_does_not_archive_trimmed_files_on_resume(self):
        import bhakti_model_routes as routes
        with tempfile.TemporaryDirectory() as tmp:
            song=Path(tmp);originals=create_audio(song);artifact=accepted_crop(song)
            real_atomic=routes.atomic_json
            def fail_pending(path,value):
                if path.name=='trim-applied.json' and value.get('status')=='pending':
                    raise OSError('before pending persistence')
                return real_atomic(path,value)
            with mock.patch.object(routes,'atomic_json',side_effect=fail_pending):
                with self.assertRaisesRegex(OSError,'before pending persistence'):
                    pipeline.apply_lossless_trim(song,artifact)
            self.assertEqual({n:hashlib.sha256(b).hexdigest() for n,b in originals.items()},
                             {n:hashlib.sha256((song/n).read_bytes()).hexdigest() for n in originals})
            pipeline.apply_lossless_trim(song,artifact)
            for name,original in originals.items():
                self.assertEqual((song/'.transcription'/'original-audio'/name).read_bytes(),original)
                self.assertAlmostEqual(pipeline.gemini.duration_seconds(song/name),26.,delta=.2)

    def test_changed_decision_to_keep_restores_originals_instead_of_claiming_trimmed_audio_is_whole(self):
        with tempfile.TemporaryDirectory() as tmp:
            song=Path(tmp);originals=create_audio(song)
            pipeline.apply_lossless_trim(song,accepted_crop(song))
            keep=accepted_crop(song)
            for edge in ('start','end'):
                row=keep[edge];row.pop('verification')
                row['response']['packet'].update(decision='keep',relationship='attached_to_work',
                    boundary=0. if edge=='start' else keep['duration'],excluded_evidence='')
            keep=pipeline.normalize_trim_artifact(keep)
            self.assertEqual(keep['validation_errors'],[])
            pipeline.apply_lossless_trim(song,keep)
            self.assertEqual({n:hashlib.sha256(b).hexdigest() for n,b in originals.items()},
                             {n:hashlib.sha256((song/n).read_bytes()).hexdigest() for n in originals})
            pipeline.apply_lossless_trim(song,keep)
            self.assertEqual({n:hashlib.sha256(b).hexdigest() for n,b in originals.items()},
                             {n:hashlib.sha256((song/n).read_bytes()).hexdigest() for n in originals})

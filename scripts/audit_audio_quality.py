#!/usr/bin/env python3
"""Report listener-audio codec quality and missing YouTube best-stream files."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path

import bhakti_pipeline as pipeline


ROOT = Path(__file__).resolve().parents[1]


def probe(path: Path) -> dict:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                             "format=duration,size,bit_rate:stream=codec_name,sample_rate,channels,bit_rate",
                             "-of", "json", str(path)], check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    stream, fmt = data["streams"][0], data["format"]
    return {"file": path.name, "codec": stream.get("codec_name"), "sample_rate": int(stream.get("sample_rate", 0)),
            "channels": stream.get("channels"), "bit_rate": int(stream.get("bit_rate") or fmt.get("bit_rate") or 0),
            "duration": float(fmt["duration"]), "size": int(fmt["size"])}


def check_local_excerpt(song: Path, source: dict, files: list[Path], hashes: dict) -> None:
    """Authenticate trusted local-intake evidence and detect subsequent drift.

    The intake producer already measured packet identity before adopting this
    receipt. This audit checks its bound bytes and recorded evidence; it does not
    independently repeat packet discovery or authenticate maliciously forged records.
    """
    def digest(path):
        stat = path.stat()
        key = (path.resolve(), stat.st_size, stat.st_mtime_ns)
        if key not in hashes:
            with path.open('rb') as stream:
                hashes[key] = hashlib.file_digest(stream, 'sha256').hexdigest()
        return hashes[key]

    def checked(ref):
        path = Path(ref['path']).expanduser().resolve()
        if not isinstance(ref['sha256'], str) or digest(path) != ref['sha256']:
            raise ValueError('referenced file hash differs')
        return path

    def number(value):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('non-finite or invalid packet measurement')
        return value

    if 'native_audio' in source or files != [song/'audio.m4a']:
        raise ValueError('must be the sole supplied AAC listener source')
    marker = pipeline.read_packet(song/'.transcription/trim-applied.json') or {}
    if not isinstance(marker, dict) or marker.get('status') == 'pending':
        raise ValueError('trim transaction is pending')
    receipt = json.loads(checked(source['local_excerpt']).read_text(encoding='utf-8'))
    if not isinstance(receipt, dict) or receipt.get('version') != 1 or receipt.get('status') != 'lossless-excerpt-ready':
        raise ValueError('receipt is not a ready local excerpt')
    original, output = checked(receipt['original']), checked(receipt['output'])
    if (receipt['original'].get('provenance') != 'user-supplied'
            or original == output or original.suffix.lower() != '.m4a' or output.suffix.lower() != '.m4a'
            or digest(files[0]) != receipt['output']['sha256']):
        raise ValueError('supplied source or current listener bytes differ')
    accepted = json.loads(checked(receipt['boundaryAcceptance']).read_text(encoding='utf-8'))
    if not isinstance(accepted, dict):
        raise ValueError('invalid boundary acceptance')
    extraction, proof = receipt['extraction'], receipt['packetEvidence']
    start, end = number(extraction['requestedStartSeconds']), number(extraction['requestedEndSeconds'])
    offset, duration = number(extraction['packetSourceOffset']), number(extraction['outputDurationSeconds'])
    if (extraction.get('method') != 'stream-copy' or not 0 <= start < end or duration <= 0
            or accepted.get('status') != 'root-accepted-broadcast-boundaries'
            or not receipt.get('candidateId') or receipt['candidateId'] != accepted.get('candidateId')
            or accepted.get('original') != {key: receipt['original'][key] for key in ('path', 'sha256')}
            or number(accepted['startSeconds']) != start or number(accepted['endSeconds']) != end):
        raise ValueError('accepted source, interval or extraction method differs')
    if (type(proof['matched_packets']) is not int or proof['matched_packets'] <= 0
            or proof['source_stream']['codec_name'] != 'aac' or proof['output_stream']['codec_name'] != 'aac'
            or not 0 <= number(proof['packet_offset_spread']) <= .003
            or abs(number(proof['packet_source_offset']) - offset) > .003
            or abs(number(proof['duration']) - duration) > .003
            or abs(offset - start) > .25 or abs(offset + duration - end) > .1):
        raise ValueError('recorded packet evidence differs from accepted extraction')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--song', action='append', help='Audit only this song slug; repeat for multiple songs')
    args = parser.parse_args(argv)
    songs_root = (ROOT/'songs').resolve()
    if args.song:
        songs = []
        for slug in dict.fromkeys(args.song):
            song = songs_root/slug
            if not slug or Path(slug).name != slug or song.resolve().parent != songs_root or not song.is_dir():
                parser.error(f'unknown or invalid song slug: {slug}')
            songs.append(song)
    else:
        songs = sorted(song for song in songs_root.iterdir() if song.is_dir())
    reports, errors, hashes = [], [], {}
    for song in songs:
        try:
            source_path = song/'.transcription/source.json'
            source = json.loads(source_path.read_text(encoding='utf-8')) if source_path.is_file() else {}
            files = [song/item['src'] for item in pipeline.listener_audio_sources(song)]
            if not files:
                errors.append(f'{song.name}: no listener audio')
                continue
            if 'local_excerpt' in source:
                try:
                    check_local_excerpt(song, source, files, hashes)
                except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
                    errors.append(f'{song.name}: invalid local excerpt: {exc}')
            elif 'youtube.com' in str(source.get('source_url', '')) and not (song/'audio.webm').is_file():
                errors.append(f'{song.name}: YouTube source lacks preserved best Opus stream')
            reports.append({'slug': song.name, 'preferred': files[0].name, 'sources': [probe(path) for path in files]})
        except (ValueError, KeyError, TypeError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
            errors.append(f'{song.name}: audio audit failed: {exc}')
    print(json.dumps({'songs': reports, 'errors': errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())

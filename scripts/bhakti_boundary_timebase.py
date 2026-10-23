"""Read-only historical boundary requirements and native decoded-time proofs.

No model calls, source changes, or publication decisions occur here. A measured
mapping carries old timing evidence to a new file only after the existing
source/timing consumer also accepts exact performance lineage.
"""
from __future__ import annotations

from contextlib import contextmanager
from fractions import Fraction
import fcntl
import os
import threading
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile
from typing import Any


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_HELD = threading.local()


@contextmanager
def boundary_transaction(song_dir: Path):
    """Serialize a song's brief install or publication operation across processes.

    Runtime locks are outside immutable song archives, remain on disk, and are
    reentrant within one thread so generation under a caller lock cannot deadlock.
    Model work and FFmpeg preparation never belong in this critical section.
    """
    key = str(Path(song_dir).resolve())
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(key, threading.RLock())
    with lock:
        held = getattr(_HELD, 'paths', set())
        if key in held:
            yield
            return
        directory = Path(tempfile.gettempdir()) / f'bhakti-boundary-locks-{os.getuid()}'
        directory.mkdir(mode=0o700, exist_ok=True)
        path = directory / (hashlib.sha256(key.encode()).hexdigest() + '.lock')
        with path.open('a+b') as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            _HELD.paths = held | {key}
            try:
                yield
            finally:
                _HELD.paths = held
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def boundary_snapshot(song_dir: Path, paths) -> dict[str, str | None]:
    """Bind a consumer's input files and transaction generation under its lock."""
    require_completed_boundary_transaction(song_dir)
    paths = set(Path(path).resolve() for path in paths)
    paths.add((song_dir / '.transcription/trim-applied.json').resolve())
    return {str(path): _digest(path) if path.is_file() else None for path in sorted(paths)}


def require_boundary_snapshot(song_dir: Path, snapshot: dict[str, str | None]) -> None:
    require_completed_boundary_transaction(song_dir)
    if boundary_snapshot(song_dir, [Path(path) for path in snapshot]) != snapshot:
        raise RuntimeError(f'{song_dir.name}: boundary publication snapshot changed')


def require_completed_boundary_transaction(song_dir: Path) -> None:
    """Hold consumers while local audio/source/timing replacements are incomplete.

    This is an interruption gate, not a certificate of acoustic or editorial
    correctness. Legacy completed markers remain eligible for their usual audits.
    """
    path = song_dir / '.transcription/trim-applied.json'
    if not path.exists():
        return
    try:
        marker = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(marker, dict):
            raise ValueError('marker is not an object')
        adoption = marker.get('adoption') or {}
        if not isinstance(adoption, dict):
            raise ValueError('adoption marker is not an object')
    except (OSError, ValueError) as exc:
        raise RuntimeError(f'{song_dir.name}: boundary recovery required; invalid transaction marker') from exc
    if marker.get('status') == 'pending' or adoption.get('status') == 'pending':
        raise RuntimeError(f'{song_dir.name}: pending boundary adoption requires recovery before consumption')


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def _number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError('boolean is not a media time')
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('media time is not finite')
    return value


def classify_historical_boundary_evidence(snapshot: dict[str, Any]) -> dict[str, Any]:
    """List obligations from legacy observations without certifying their inputs.

    A matching duration is a routing clue only. The snapshot's audio hashes
    identify current bytes, not the missing historical model requests.
    """
    artifacts = snapshot.get('artifacts', {})
    review = artifacts.get('trim-review.json') or {}
    marker = artifacts.get('trim-applied.json') or {}
    original_manifest = artifacts.get('trim-originals.json') or {}
    media = snapshot.get('media', {})
    result = {'slug': snapshot.get('slug'), 'publicationEligible': False,
              'original_binding': 'unproven', 'legacy_observation_reusable': False,
              'can_review_original_edges_now': False, 'can_archive_current_master': False,
              'remaining_obligations': [], 'conflicts': []}
    obligations, conflicts = result['remaining_obligations'], result['conflicts']
    if not isinstance(media, dict) or not media or not review:
        result['status'] = 'incomplete-evidence'
        obligations.append('recording-and-boundary-inventory')
        return result
    try:
        duration = _number(review['duration'])
        durations = [_number(item['probe']['format']['duration']) for item in media.values()]
        if duration <= 0 or any(value <= 0 for value in durations):
            raise ValueError('nonpositive recording duration')
    except (KeyError, TypeError, ValueError, OverflowError):
        result['status'] = 'incomplete-evidence'
        obligations.append('recording-duration-evidence')
        return result
    # The marker is an explicit prior mutation record. Duration discrepancies
    # are an additional reason to investigate, never an authenticity proof.
    changed = marker.get('applied') is True
    if original_manifest:
        result['status'] = 'needs-original-verification'
        obligations.append('verify-preserved-originals-and-current-outputs')
    elif changed or any(abs(value - duration) > 0.25 for value in durations):
        result['status'] = 'needs-original-recovery'
        obligations.append('original-audio-identity')
    else:
        result['status'] = 'needs-boundary-review'
        result['can_archive_current_master'] = True
    obligations.append('boundary-source-binding')
    if marker.get('status') == 'pending':
        obligations.insert(0, 'recover-pending-transaction')
    for edge, endpoint in (('start', 0.), ('end', duration)):
        row = review.get(edge) or {}
        packet = (row.get('response') or {}).get('packet') or {}
        try:
            proposal = (_number(row.get('clip_start', 0)) + _number(packet['boundary'])
                        if packet.get('decision') == 'trim' else endpoint)
            normalized = _number(review.get('trim_' + edge, endpoint))
            applied = _number(marker.get('trim_' + edge, endpoint))
            if marker.get('applied') is True and abs(applied - normalized) > .001:
                conflicts.append('applied-' + edge + '-differs')
            if packet.get('decision') == 'trim' and abs(proposal - normalized) > .001:
                conflicts.append('unapplied-' + edge + '-proposal')
        except (TypeError, ValueError, KeyError, OverflowError):
            conflicts.append('invalid-' + edge + '-proposal')
        if packet.get('outside_type') in {'narration', 'spoken', 'speech'}:
            if 'establish-spoken-work-relationship' not in obligations:
                obligations.append('establish-spoken-work-relationship')
    editorial = review.get('editorial_review')
    if isinstance(editorial, dict):
        # Preserve the exact recorded rationale; this inventory does not grant
        # it new authority or turn an audio-only logo claim into visual proof.
        result['retained_editorial_review'] = json.loads(json.dumps(editorial))
        if 'silence' in str(editorial.get('reason', '')).casefold():
            obligations.append('verify-leading-silence-and-entire-prelude')
    return result


def inspect_historical_boundary(song_dir: Path) -> dict[str, Any]:
    """Capture current native files and retained metadata without mutating them."""
    song_dir = Path(song_dir)
    artifacts = {}
    for name in ('trim-review.json', 'trim-applied.json', 'trim-originals.json'):
        path = song_dir / '.transcription' / name
        artifacts[name] = json.loads(path.read_text()) if path.is_file() else None
    media = {}
    for path in sorted(song_dir.glob('audio.*')):
        if not path.is_file():
            continue
        output = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a:0',
            '-show_entries', 'format=duration:stream=codec_name,sample_rate,start_time,duration',
            '-of', 'json', str(path)], capture_output=True, text=True, check=True)
        media[path.name] = {'sha256': _digest(path), 'probe': json.loads(output.stdout)}
    snapshot = {'slug': song_dir.name, 'artifacts': artifacts, 'media': media}
    return {**classify_historical_boundary_evidence(snapshot), 'snapshot': snapshot}


def _decoded_clock(path: Path) -> dict[str, Any]:
    response = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a:0',
        '-show_frames', '-show_streams', '-show_entries',
        'frame=best_effort_timestamp_time,nb_samples:stream=codec_name,sample_rate,channels,channel_layout,time_base,start_time',
        '-of', 'json', str(path)], capture_output=True, text=True, check=True)
    value = json.loads(response.stdout)
    streams, frames = value.get('streams', []), value.get('frames', [])
    if len(streams) != 1 or not frames:
        raise ValueError('native audio has no unique decoded stream/frame clock')
    stream = streams[0]
    rate, channels = int(stream['sample_rate']), int(stream['channels'])
    tick = float(Fraction(stream['time_base']))
    if rate <= 0 or channels <= 0 or not 0 < tick <= 1:
        raise ValueError('invalid native sample rate, channels or timestamp quantum')
    origin = _number(frames[0]['best_effort_timestamp_time'])
    total, error = 0, 0.
    for frame in frames:
        size = frame.get('nb_samples')
        if type(size) is not int or size <= 0:
            raise ValueError('decoded frame has no exact positive sample count')
        timestamp = _number(frame['best_effort_timestamp_time'])
        error = max(error, abs(timestamp - (origin + total / rate)))
        total += size
    # Container times are quantized by their declared time_base; FFprobe's
    # decimal rendering adds at most one microsecond. This is a clock bound,
    # not a tolerance for changing or approximating the decoded waveform.
    clock_bound = tick + 0.000001
    if error > clock_bound:
        raise ValueError('decoded frame timeline has a discontinuity or drift')
    return {'sample_rate': rate, 'channels': channels, 'codec': stream['codec_name'],
            'channel_layout': stream.get('channel_layout'), 'time_base': stream['time_base'],
            'timestamp_quantum_seconds': tick, 'first_frame_pts': origin,
            'decoded_samples': total, 'frame_count': len(frames),
            'max_frame_clock_error_seconds': error, 'frame_clock_bound_seconds': clock_bound}


def _decode(path: Path, destination: Path, clock: dict[str, Any]) -> None:
    # Native rate/channel layout; no resampling, downmix or lossy re-encoding.
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:a:0',
        '-c:a', 'pcm_f32le', '-f', 'f32le', str(destination)], check=True, capture_output=True)
    if destination.stat().st_size != clock['decoded_samples'] * clock['channels'] * 4:
        raise ValueError('decoded PCM length differs from decoded frame sample counts')


def _read_samples(path: Path, start: int, count: int, width: int) -> bytes:
    if start < 0 or count <= 0:
        raise ValueError('sample window is outside decoded audio')
    with path.open('rb') as handle:
        handle.seek(start * width)
        data = handle.read(count * width)
    if len(data) != count * width:
        raise ValueError('sample window exceeds decoded audio')
    return data


def _matching_windows(source: Path, output: Path, before: dict[str, Any], after: dict[str, Any],
                      packet_offset: float) -> tuple[int, list[dict[str, Any]]]:
    rate, width = before['sample_rate'], before['channels'] * 4
    count = after['decoded_samples']
    window = min(4096, count // 12)
    if window < 128:
        raise ValueError('retained recording is too short for separated decoded witnesses')
    # Search radius routes correspondence only; no error of this magnitude is
    # accepted. Every selected window must match exact PCM bytes uniquely.
    radius = math.ceil(rate * .25)
    estimated = round((packet_offset + after['first_frame_pts'] - before['first_frame_pts']) * rate)
    # Keep the decoder-prefix comparison small even for hours-long originals.
    # Later probes still cover the middle and far end; the complete suffix is
    # then compared by streaming, not loaded into memory.
    probes = [min(rate * seconds, count // 4) for seconds in (1, 3, 5)]
    probes.extend([count // 2, count - min(rate, count // 10) - window])
    positions = sorted(set(max(window, min(count - window, position)) for position in probes))
    windows, offsets = [], []
    for position in positions:
        pattern = _read_samples(output, position, window, width)
        left = max(0, position + estimated - radius)
        right = min(before['decoded_samples'], position + estimated + radius + window)
        if right <= left or right - left < window:
            continue
        haystack = _read_samples(source, left, right - left, width)
        matches, cursor = [], 0
        while len(matches) < 2:
            found = haystack.find(pattern, cursor)
            if found < 0:
                break
            if found % width == 0:
                matches.append(left + found // width)
            cursor = found + 1
        if len(matches) != 1:
            continue
        offset = matches[0] - position
        offsets.append(offset)
        windows.append({'source_start': matches[0] / rate, 'output_start': position / rate,
                        'samples': window, 'unique': True, 'offset_samples': offset,
                        'pcm_sha256': hashlib.sha256(pattern).hexdigest()})
    if len(windows) < 3 or len(set(offsets)) != 1:
        raise ValueError('decoded correspondence is ambiguous, absent or has nonconstant offset')
    # Windows must cover separated early, middle and late retained content;
    # several clustered exact matches cannot certify the whole retained span.
    if windows[0]['output_start'] > count / rate * .3 or windows[-1]['output_start'] < count / rate * .7:
        raise ValueError('decoded witnesses do not span both retained edges')
    return offsets[0], windows


def _verify_decoded_suffix(source: Path, output: Path, offset: int, before: dict[str, Any],
                           after: dict[str, Any], first_witness: float) -> tuple[int, str]:
    rate, width = before['sample_rate'], before['channels'] * 4
    total = after['decoded_samples']
    if offset < 0 or offset + total > before['decoded_samples']:
        raise ValueError('output decoded samples extend outside original content')
    first = round(first_witness * rate)
    # Decoder initialization may differ on the first few packets. Locate its
    # exact last mismatching sample; never reuse a syllable inside that prefix.
    left = _read_samples(source, offset, first, width)
    right = _read_samples(output, 0, first, width)
    prefix = 0
    if left != right:
        for index in range(first - 1, -1, -1):
            if left[index * width:(index + 1) * width] != right[index * width:(index + 1) * width]:
                prefix = index + 1
                break
    digest = hashlib.sha256()
    with source.open('rb') as old, output.open('rb') as new:
        old.seek((offset + first) * width)
        new.seek(first * width)
        while chunk := new.read(width * 65536):
            if old.read(len(chunk)) != chunk:
                raise ValueError('decoded content differs inside retained suffix')
            digest.update(chunk)
    return prefix, digest.hexdigest()


def measure_boundary_timebase(original_audio: Path, candidate_audio: Path, *, requested_start: float) -> dict[str, Any]:
    """Prove exact decoded correspondence; return a held result on ambiguity.

    offset_error_seconds is sample resolution, not an acoustic confidence score.
    timeline_error_seconds additionally reports native container quantization.
    The initial unmatched decoder prefix is explicitly excluded from reuse.
    """
    import bhakti_pipeline as pipeline

    original_audio, candidate_audio = Path(original_audio), Path(candidate_audio)
    try:
        requested_start = _number(requested_start)
        if requested_start < 0:
            raise ValueError('requested boundary is negative')
        source_hash, output_hash = _digest(original_audio), _digest(candidate_audio)
        packet = pipeline.trim_packet_evidence(original_audio, candidate_audio, requested_start)
        before, after = _decoded_clock(original_audio), _decoded_clock(candidate_audio)
        if any(before[key] != after[key] for key in ('sample_rate', 'channels', 'codec', 'channel_layout')):
            raise ValueError('native codec, sample rate or channel layout changed')
        with tempfile.TemporaryDirectory(prefix='bhakti-timebase-') as temporary:
            old, new = Path(temporary) / 'original.f32', Path(temporary) / 'candidate.f32'
            _decode(original_audio, old, before)
            _decode(candidate_audio, new, after)
            offset, windows = _matching_windows(old, new, before, after, packet['packet_source_offset'])
            prefix, suffix_hash = _verify_decoded_suffix(old, new, offset, before, after, windows[0]['output_start'])
        rate = before['sample_rate']
        decoded_offset = offset / rate
        timeline_offset = before['first_frame_pts'] + decoded_offset - after['first_frame_pts']
        clock_bound = before['frame_clock_bound_seconds'] + after['frame_clock_bound_seconds'] + 1 / rate
        if abs(timeline_offset - packet['packet_source_offset']) > clock_bound:
            raise ValueError('decoded and packet timeline offsets exceed their measured clock resolution')
        if _digest(original_audio) != source_hash or _digest(candidate_audio) != output_hash:
            raise ValueError('native audio changed during timebase measurement')
        return {'version': 1, 'status': 'verified', 'kind': 'decoded-boundary-timebase',
                'source_sha256': source_hash, 'output_sha256': output_hash,
                'source_clock': before, 'output_clock': after,
                'source_offset_samples': offset, 'decoded_source_offset_seconds': decoded_offset,
                'timeline_source_offset_seconds': timeline_offset,
                'offset_error_seconds': 1 / rate, 'timeline_error_seconds': clock_bound,
                'sample_windows': windows, 'decoded_suffix_sha256': suffix_hash,
                'decoded_suffix_start_seconds': after['first_frame_pts'] + windows[0]['output_start'],
                'verified_output_interval': {'start': after['first_frame_pts'] + prefix / rate,
                                             'end': after['first_frame_pts'] + after['decoded_samples'] / rate},
                'unmatched_decoder_prefix_samples': prefix, 'waveform_tolerance': 'exact-f32le-bytes',
                'packet_evidence': packet, 'issues': []}
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.CalledProcessError) as exc:
        return {'version': 1, 'status': 'unresolved',
                'issues': [{'kind': 'boundary_timebase', 'detail': str(exc)}]}

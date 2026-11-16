#!/usr/bin/env python3
"""Read-only physical audio measurements; these are not musical judgments.

PCM memory is bounded by a chunk plus two boundary windows. Spectral median
retains two Python scalars per1024-sample hop (about8MB for a two-hour recording).
Native-channel loudness precedes the explicitly mono, 16kHz diagnostic stream.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import copy
from fractions import Fraction
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time

try:
    import numpy as np
except ImportError:
    np = None

EXTRACTOR_VERSION = "physical-2"
SAMPLE_RATE = 16000
FRAME_SIZE = 2048
HOP_SIZE = 1024
FILTER_GRAPH_TEMPLATE = ("aformat=sample_fmts=dbl:sample_rates={native_rate}:channel_layouts={native_layout},"
                         "ebur128=peak=true,aresample={diagnostic_rate},aformat=sample_fmts=flt:channel_layouts=mono")


def _fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def recipe_fingerprint(tools: dict, settings: dict) -> str:
    return _fingerprint({"extractorVersion": EXTRACTOR_VERSION, "algorithmFingerprint": audio_method_fingerprint(),
                         "tools": tools, "settings": settings})


def _sha(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _finite_tree(value):
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite_tree(v) for v in value.values())
    if isinstance(value, list):
        return all(_finite_tree(v) for v in value)
    return True


def _atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".audio-", delete=False) as output:
            temporary = Path(output.name)
            json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def _tool_versions() -> dict:
    result = {"numpy": np.__version__ if np is not None else None}
    for name in ("ffmpeg", "ffprobe"):
        binary = shutil.which(name)
        if not binary:
            result[name] = None
            continue
        run = subprocess.run([binary, "-version"], capture_output=True, text=True, timeout=10, check=True)
        result[name] = run.stdout.splitlines()[0]
    return result


def _mp3_packet_duration(path: Path, sample_rate: int) -> dict:
    """Use packet clock counts, not FFprobe's bitrate-estimated MP3 length."""
    run = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                          "packet=duration:packet_side_data=skip_samples,discard_padding:stream=time_base",
                          "-of", "json", str(path)], capture_output=True, text=True, timeout=30, check=True)
    payload = json.loads(run.stdout)
    try:
        clock = Fraction(payload["streams"][0]["time_base"])
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError) as error:
        raise ValueError("invalid MP3 packet time base") from error
    if clock <= 0 or type(sample_rate) is not int or sample_rate <= 0:
        raise ValueError("nonpositive MP3 packet time base or sample rate")

    def integer(value, minimum):
        if type(value) is int:
            result = value
        elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
            result = int(value)
        else:
            raise ValueError("incomplete or noninteger MP3 duration evidence")
        if result < minimum:
            raise ValueError("invalid MP3 duration or padding evidence")
        return result

    packets = payload.get("packets")
    if not isinstance(packets, list) or not packets:
        raise ValueError("no MP3 packet duration evidence")
    ticks = skip = discard = 0
    for packet in packets:
        ticks += integer(packet.get("duration"), 1)
        for side in packet.get("side_data_list", []):
            skip += integer(side.get("skip_samples", 0), 0)
            discard += integer(side.get("discard_padding", 0), 0)
    duration = float(ticks * clock - Fraction(skip + discard, sample_rate))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("nonpositive MP3 retained packet duration")
    return {"durationSeconds": duration,
            "durationEvidence": {"packetCount": len(packets), "durationTicks": ticks,
                                 "timeBase": str(clock), "skipSamples": skip, "discardPadding": discard}}


def _probe(path: Path) -> dict:
    run = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                          "format=duration:stream=codec_name,sample_rate,channels,channel_layout",
                          "-of", "json", str(path)], capture_output=True, text=True, timeout=30, check=True)
    value = json.loads(run.stdout)
    stream = value["streams"][0]
    duration = float(value["format"]["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("no finite positive audio duration")
    channels = int(stream["channels"])
    layout = {1: "mono", 2: "stereo"}.get(channels)
    if not layout:
        raise ValueError("unqualified channel layout; only mono/stereo physical recipe is qualified")
    declared_layout = stream.get("channel_layout")
    if declared_layout and declared_layout != layout:
        raise ValueError("declared channel layout is not qualified mono/stereo")
    media = {"durationSeconds": duration, "codec": stream["codec_name"], "sampleRate": int(stream["sample_rate"]),
             "channels": channels, "channelLayout": layout, "channelLayoutInferred": not bool(declared_layout)}
    if media["codec"] == "mp3":
        media.update(containerDurationSeconds=duration, durationSource="mp3_packet_durations")
        media.update(_mp3_packet_duration(path, media["sampleRate"]))
    return media


def _valid_physical(value: dict, duration: float, window: float) -> bool:
    def number(v):
        return type(v) in (int, float) and math.isfinite(v)
    def feature(v):
        return v is None or number(v)
    try:
        coverage = value["coverageSeconds"]
        count = value["sampleCount"]
        if (value["status"] != "measured" or not number(coverage) or coverage <= 0
            or abs(coverage-duration) > .5 or type(count) is not int or count <= 0
            or abs(count/SAMPLE_RATE-coverage) > 1/SAMPLE_RATE):
            return False
        whole = value["whole"]
        keys = {"integratedLufs", "truePeakDbfs", "rmsDbfs", "centroidHz"}
        if not isinstance(whole, dict) or set(whole) != keys or not all(feature(v) for v in whole.values()):
            return False
        if whole["centroidHz"] is not None and not 0 <= whole["centroidHz"] <= SAMPLE_RATE/2:
            return False
        validity = value["validity"]
        if not isinstance(validity, dict) or set(validity) != keys:
            return False
        for key, measurement in whole.items():
            state = validity[key]
            if not isinstance(state, dict) or state.get("status") != ("undefined" if measurement is None else "measured"):
                return False
            if measurement is None and (not isinstance(state.get("reason"), str) or not state["reason"]):
                return False
        intervals = {"beginning": (0, min(window, coverage)), "body": (0, coverage), "end": (max(0, coverage-window), coverage)}
        if not isinstance(value["profiles"], dict) or set(value["profiles"]) != set(intervals):
            return False
        for name, (start, end) in intervals.items():
            profile = value["profiles"][name]
            if not isinstance(profile, dict) or not all(feature(profile[k]) for k in ("rmsDbfs", "centroidHz")):
                return False
            if not all(number(profile[k]) for k in ("startSeconds", "endSeconds")):
                return False
            if abs(profile["startSeconds"]-start) > 1/SAMPLE_RATE or abs(profile["endSeconds"]-end) > 1/SAMPLE_RATE:
                return False
            if profile["centroidHz"] is not None and not 0 <= profile["centroidHz"] <= SAMPLE_RATE/2:
                return False
        fraction = value["spectralValidFrameFraction"]
        return number(fraction) and 0 <= fraction <= 1
    except (KeyError, TypeError, ValueError):
        return False


def _db_rms(sumsq: float, count: int):
    return 10 * math.log10(sumsq / count) if count and sumsq / count > 1e-30 else None


def _settings(media: dict, window_seconds: float) -> dict:
    return {"sampleRate": SAMPLE_RATE, "frameSize": FRAME_SIZE, "hopSize": HOP_SIZE,
            "windowSeconds": float(window_seconds), "spectralWindow": "numpy.hanning", "centroidAggregation": "median_valid_frames",
            "numericalRmsFloor": 1e-15, "numericalSpectralWeightFloor": 1e-12,
            "filterGraph": FILTER_GRAPH_TEMPLATE.format(native_rate=media["sampleRate"],
                                                         native_layout=media["channelLayout"], diagnostic_rate=SAMPLE_RATE)}


def _decode(path: Path, media: dict, settings: dict) -> dict:
    """Stream diagnostics while draining verbose native loudness logs to disk."""
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-nostats", "-xerror", "-err_detect", "explode",
               "-i", str(path), "-map", "0:a:0", "-vn", "-filter_threads", "1", "-af", settings["filterGraph"],
               "-f", "f32le", "pipe:1"]
    boundary_samples = max(1, round(settings["windowSeconds"] * SAMPLE_RATE))
    head, tail, pending = np.empty(0), np.empty(0), np.empty(0)
    count = 0
    sumsq = 0.0
    frame_start = 0
    centroids, centers = [], []
    total_frames = 0
    hann = np.hanning(FRAME_SIZE)
    frequencies = np.fft.rfftfreq(FRAME_SIZE, 1 / SAMPLE_RATE)

    def spectral(frames, starts):
        nonlocal total_frames
        magnitude = np.abs(np.fft.rfft(frames * hann, axis=1))
        weights = magnitude.sum(axis=1)
        good = weights > 1e-12
        total_frames += len(frames)
        centroids.extend(((magnitude[good] * frequencies).sum(axis=1) / weights[good]).tolist())
        centers.extend(((starts[good] + FRAME_SIZE / 2) / SAMPLE_RATE).tolist())

    timed_out = threading.Event()
    with tempfile.TemporaryFile(mode="w+b") as diagnostics:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=diagnostics)
        def stop():
            timed_out.set()
            process.kill()
        timer = threading.Timer(max(30, min(600, media["durationSeconds"] / 5 + 30)), stop)
        timer.start()
        try:
            while raw := process.stdout.read(65536):
                if len(raw) % 4:
                    raise ValueError("decoder returned incomplete float32 sample")
                samples = np.frombuffer(raw, dtype="<f4").astype(np.float64)
                if not np.isfinite(samples).all():
                    raise ValueError("decoder returned nonfinite samples")
                count += len(samples)
                sumsq += float(np.dot(samples, samples))
                if len(head) < boundary_samples:
                    head = np.concatenate((head, samples[:boundary_samples-len(head)]))
                tail = np.concatenate((tail, samples))[-boundary_samples:]
                pending = np.concatenate((pending, samples))
                if len(pending) >= FRAME_SIZE:
                    frames = np.lib.stride_tricks.sliding_window_view(pending, FRAME_SIZE)[::HOP_SIZE]
                    spectral(frames, frame_start + np.arange(len(frames)) * HOP_SIZE)
                    advance = len(frames) * HOP_SIZE
                    pending = pending[advance:]
                    frame_start += advance
            code = process.wait(timeout=5)
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()
        diagnostics.seek(0, os.SEEK_END)
        diagnostics.seek(max(0, diagnostics.tell() - 20000))
        log = diagnostics.read().decode(errors="replace")
    if timed_out.is_set():
        raise ValueError("audio decoder exceeded bounded runtime")
    if code:
        raise ValueError("audio decode failed: " + log[-1200:])
    if not count:
        raise ValueError("decoder produced no samples")
    duration = count / SAMPLE_RATE
    if abs(duration - media["durationSeconds"]) > .5:
        raise ValueError("decoded coverage disagrees with probed duration by more than0.5seconds")
    if len(pending):
        final = np.pad(pending, (0, FRAME_SIZE-len(pending)))
        spectral(final[None, :], np.array([frame_start]))
        if centers and centers[-1] > duration:
            centers[-1] = duration
    centroids, centers = np.asarray(centroids), np.asarray(centers)

    def profile(begin, end, samples=None):
        selected = centroids[(centers >= begin) & (centers <= end)]
        energy = float(np.dot(samples, samples)) if samples is not None else sumsq
        size = len(samples) if samples is not None else count
        return {"startSeconds": begin, "endSeconds": end, "rmsDbfs": _db_rms(energy, size),
                "centroidHz": float(np.median(selected)) if len(selected) else None}

    summary = log.rsplit("Summary:", 1)[-1]
    def metric(pattern):
        found = re.search(pattern, summary)
        if not found:
            raise ValueError("missing native loudness summary")
        value = float(found.group(1))
        return value if math.isfinite(value) else None
    loudness = metric(r"Integrated loudness:\s*I:\s*([-\w.]+) LUFS")
    peak = metric(r"True peak:\s*Peak:\s*([-\w.]+) dBFS")
    # EBU scanner's -70 startup/below-gate sentinel is not a measurement.
    if loudness is not None and loudness <= -69.9:
        loudness = None
    body = profile(0, duration)
    whole = {"integratedLufs": loudness, "truePeakDbfs": peak, "rmsDbfs": body["rmsDbfs"], "centroidHz": body["centroidHz"]}
    return {"status": "measured", "reason": None, "coverageSeconds": duration, "sampleCount": count,
            "whole": whole, "profiles": {"beginning": profile(0, len(head)/SAMPLE_RATE, head), "body": body,
                                           "end": profile(duration-len(tail)/SAMPLE_RATE, duration, tail)},
            "validity": {key: {"status": "measured" if value is not None else "undefined",
                               "reason": None if value is not None else ("below_loudness_gate_or_too_short" if key == "integratedLufs" else "zero_energy")}
                         for key, value in whole.items()},
            "spectralValidFrameFraction": len(centroids)/total_frames if total_frames else 0,
            "command": command, "nativeLoudnessSummary": summary.strip()}


# Capture the implementation actually imported once, not whatever is on disk
# when a long-running extraction finishes or an old receipt is summarized.
_ALGORITHM_SOURCE_HASH = _fingerprint({fn.__name__: inspect.getsource(fn) for fn in (_mp3_packet_duration, _probe, _decode, _db_rms, _settings)})


def audio_method_fingerprint() -> str:
    """Portable method identity; host versions and native format bind separately."""
    return _fingerprint({"version": EXTRACTOR_VERSION, "sourceHash": _ALGORITHM_SOURCE_HASH,
                         "filterGraphTemplate": FILTER_GRAPH_TEMPLATE,
                         "sampleRate": SAMPLE_RATE, "frameSize": FRAME_SIZE, "hopSize": HOP_SIZE,
                         "profileWindowSeconds": 30.0, "centroidAggregation": "median_valid_frames",
                         "numericalRmsFloor": 1e-15, "numericalSpectralWeightFloor": 1e-12})


def analyze_audio(path: Path, *, expected_sha256: str | None = None, cache_path: Path | None = None,
                  window_seconds: float = 30.0) -> dict:
    """Measure retained bytes, or return an explicit neutral failure receipt."""
    if not isinstance(window_seconds, (float, int)) or not math.isfinite(window_seconds) or window_seconds <= 0:
        raise ValueError("window_seconds must be finite and positive")
    path = Path(path)
    start = time.monotonic()
    result = {"schemaVersion": 1, "extractorVersion": EXTRACTOR_VERSION, "cacheHit": False,
              "algorithmFingerprint": audio_method_fingerprint(),
              "media": {"path": str(path), "identityStatus": "unverified"},
              "components": {"physical": {"status": "failed", "reason": "not_attempted"},
                             "rhythm": {"status": "not_established", "reason": "no_validated_rhythm_method"},
                             "embedding": {"status": "not_run", "reason": "no_qualified_embedding_method"}}}
    try:
        before = path.stat()
        sha = _sha(path)
        result["media"].update(sha256=sha, bytes=before.st_size, identityStatus="match" if expected_sha256 == sha else "unmanifested")
        if expected_sha256 is not None and expected_sha256 != sha:
            result["media"]["identityStatus"] = "mismatch"
            raise ValueError("retained listener audio SHA256 mismatch")
        tools = _tool_versions()
        result["tools"] = tools
        if not all(tools.values()):
            result["components"]["physical"] = {"status": "unavailable", "reason": "required_ffmpeg_ffprobe_or_numpy_unavailable"}
            return result
        media = _probe(path)
        result["media"].update(media)
        settings = _settings(media, window_seconds)
        result["settings"] = settings
        result["recipeFingerprint"] = recipe_fingerprint(tools, settings)
        result["inputFingerprint"] = _fingerprint({"mediaSha256": sha, "recipeFingerprint": result["recipeFingerprint"]})
        if cache_path and Path(cache_path).is_file():
            try:
                cached = json.loads(Path(cache_path).read_text())
                physical = cached["components"]["physical"]
                if (cached.get("inputFingerprint") == result["inputFingerprint"]
                    and cached.get("schemaVersion") == 1 and cached.get("extractorVersion") == EXTRACTOR_VERSION
                    and cached.get("algorithmFingerprint") == result["algorithmFingerprint"]
                    and cached.get("settings") == settings and cached.get("tools") == tools
                    and _finite_tree(cached) and _valid_physical(physical, media["durationSeconds"], window_seconds)):
                    after = path.stat()
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or _sha(path) != sha:
                        raise ValueError("retained media changed during cache validation")
                    cached["cacheHit"] = True
                    cached["media"] = result["media"]
                    cached["runtimeSeconds"] = time.monotonic() - start
                    return cached
            except (OSError, ValueError, KeyError, TypeError):
                pass
        result["components"]["physical"] = _decode(path, media, settings)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or _sha(path) != sha:
            raise ValueError("retained media changed during measurement")
        if not _finite_tree(result):
            raise ValueError("nonfinite measurement result")
        if result["algorithmFingerprint"] != audio_method_fingerprint():
            raise ValueError("analysis method changed during measurement")
        if not _valid_physical(result["components"]["physical"], media["durationSeconds"], window_seconds):
            raise ValueError("physical measurement schema validation failed")
        result["runtimeSeconds"] = time.monotonic() - start
        if cache_path:
            _atomic_json(Path(cache_path), result)
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError) as error:
        result["components"]["physical"] = {"status": "failed", "reason": str(error)}
    finally:
        result["runtimeSeconds"] = time.monotonic() - start
    return result


def audio_summary(receipt: dict) -> dict:
    """Project validated measurements, without granting human or method approval."""
    from bhakti_shuffle_profiles import audio_input_hash, digest
    try:
        media, settings, tools = receipt["media"], receipt["settings"], receipt["tools"]
        physical = receipt["components"]["physical"]
        method_hash = recipe_fingerprint(tools, settings)
        expected_input = _fingerprint({"mediaSha256": media["sha256"], "recipeFingerprint": method_hash})
        if (receipt.get("schemaVersion") != 1 or receipt.get("extractorVersion") != EXTRACTOR_VERSION
            or receipt.get("algorithmFingerprint") != audio_method_fingerprint()
            or settings.get("windowSeconds") != 30.0
            or settings != _settings(media, 30.0)
            or media.get("identityStatus") not in {"match", "unmanifested"}
            or receipt.get("recipeFingerprint") != method_hash or receipt.get("inputFingerprint") != expected_input
            or not _finite_tree(receipt)
            or not _valid_physical(physical, media["durationSeconds"], settings["windowSeconds"])):
            raise ValueError("audio receipt identity, recipe or physical measurement is invalid")
        if not any(v is not None for v in physical["whole"].values()):
            raise ValueError("all physical values undefined; explicit reviewed disposition required")
        return {"inputHash": audio_input_hash(media["sha256"]), "mediaSha256": media["sha256"],
                "assessment": "measured", "outcome": "known", "methodFingerprint": method_hash,
                "method": {"id": "physical", "version": EXTRACTOR_VERSION, "fingerprint": receipt["algorithmFingerprint"]},
                "domain": {k: media[k] for k in ("codec", "sampleRate", "channels", "durationSeconds")},
                "receiptHash": digest(receipt),
                "physical": {"whole": copy.deepcopy(physical["whole"]),
                             "profiles": {name: {k: row[k] for k in ("startSeconds", "endSeconds", "rmsDbfs", "centroidHz")}
                                          for name, row in physical["profiles"].items()}}}
    except (KeyError, TypeError) as error:
        raise ValueError("incomplete audio measurement receipt") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", nargs="?", type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if args.inventory:
        if not args.output_dir or not 1 <= args.workers <= 4:
            parser.error("inventory requires output-dir and1–4workers")
        items = json.loads(args.inventory.read_text())["items"]
        def run(item):
            receipt = analyze_audio(Path(item["path"]), expected_sha256=item.get("expectedSha256"),
                                    cache_path=args.output_dir / item["slug"] / "audio.json")
            return {"slug": item["slug"], "status": receipt["components"]["physical"]["status"],
                    "reason": receipt["components"]["physical"].get("reason"), "runtimeSeconds": receipt["runtimeSeconds"],
                    "cacheHit": receipt["cacheHit"]}
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(run, items))
        _atomic_json(args.output_dir / "run.json", {"results": results})
        print(json.dumps(results, ensure_ascii=False))
        return int(any(r["status"] != "measured" for r in results))
    if not args.audio:
        parser.error("audio or inventory is required")
    receipt = analyze_audio(args.audio, expected_sha256=args.expected_sha256, cache_path=args.output)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False))
    return int(receipt["components"]["physical"]["status"] != "measured")


if __name__ == "__main__":
    raise SystemExit(main())

# Bounded acoustic capability probe — 2026-11-15

Only three existing local listener-source Opus files were analyzed. No originals, repository files, models, packages or credentials were changed. No paid calls, model inference, model downloads or human listening occurred. Inventory/hash/probe work preceded an interruption; the resumed window analysis took 3.03 seconds wall time, about one second per file. This is one warm/local capability measurement, not an all-library performance benchmark.

## Actual tool environment

Default `/opt/homebrew/opt/python@3.14/bin/python3.14`: Python3.14.7, NumPy2.4.6. FFmpeg8.1 and ffprobe available. scipy, librosa, soundfile, essentia, torch, torchaudio, transformers, laion-clap and beat-this absent from this default Python environment. Other environments were not qualified. Full FFmpeg build/version and per-window command are in the JSON.

## Protocol and results

For each file: SHA256 and ffprobe container/stream identity, then five nominal30second windows at 0%,25%,50%,75%,100% of (duration-30). FFmpeg ebur128 peak=true logs window integrated loudness and true peak; the same command decodes a 22050Hz mono float32 diagnostic stream. NumPy computes RMS and Hann-window magnitude spectral centroids (2048samples,512hop), plus frame quantiles and fraction of RMS frames below -50dBFS. Exact formulas, source hashes, media records, commands, decoded duration, raw ebur128 summaries, per-window timing and errors are stored in JSON. Production must explicitly pin and verify the negotiated channel/rate at the loudness stage; this probe did not log the negotiated graph. Nominal boundaries have codec/filter-frame rounding.

| Recording | Duration | Media identity | Sample coverage | Window LUFS, head→tail |
|---|---:|---|---:|---|
| Harivarāsanam |173.321s|Catalogue local first-source audio.webm; no media.json entry|86.5%|-14.9,-15.3,-16.0,-15.7,-15.5|
| Kyā Tan Mā̃jhatā |230.261s|SHA256 matches media.json Opus asset; Live is a catalogue alias, not listening verification|65.1%|-13.2,-12.8,-12.4,-12.0,-10.5|
| Sampūrṇa Sundarakāṇḍa |7228.381s|SHA256 matches media.json Opus asset|2.08%|-17.0,-13.9,-13.4,-13.9,-22.1|

All15windows decoded and produced finite metrics. The long recording illustrates why five windows are not a full-recording summary: they cover only2.08%. Its middle versus tail level/centroid differs, but no cause (applause, spoken passage, musical change, silence) was established. Kyā Tan Mā̃jhatā returned positive true-peak estimates (+0.4to+0.6dBFS); this is a scanner output, not proof of audible clipping or a repair instruction.

## Capability matrix

|Feature|State now|Meaning / boundary|
|---|---|---|
|Media identity,duration,codec,channels,sample rate|Measured on3files|Local SHA/manifest consistency; no remote fetch|
|Per-window integrated loudness/true peak|Measured15windows with FFmpeg|Specified analysis signal, not whole-track normalization or emotional energy; production needs explicit graph config|
|Frame RMS quantiles and amplitude spread|Measured with NumPy|Amplitude statistics of mono diagnostic samples, not perceived intensity|
|Low-level frame fraction|Measured with chosen -50dBFS threshold|Not calibrated silence, speech or applause detection|
|Spectral centroid quantiles|Measured with NumPy|Magnitude-spectrum center of mass, not instrument, mood or timbre category|
|Full-file loudness/dynamic contour|Supported by existing FFmpeg in principle; not run|Requires full decode and qualification; cannot average the five LUFS values|
|Onset,pulse,BPM,beat/downbeat/tala|Not produced|Need dedicated extractor plus annotated validation; successful install is not correctness|
|Audio/music embeddings|Not available in qualified default environment|Need selected checkpoint, license, download/setup and domain validation|
|Mood,devotional emotion,instrumentation,raga|No qualified output|Require independent evidence/model evaluation; do not infer from low-level proxies|
|Good next-song score|Not qualified|Needs listening evaluation, not merely a working extractor|

## New-intake attestation proposal

Make analysis attestation mandatory, not particular acoustic values. Link to final retained listener-source SHA, audio-source version and trim offset; record extractor/tool versions, command/config, analyzed intervals, coverage, runtime, stage status and diagnostic reason. Each field has separate measurement status and musical-validity status. Permitted neutral states include not_applicable (e.g. no stable meter when reviewed), not_established (no ground truth), unsupported, insufficient_coverage, extraction_failed and stale_media_hash. Never convert unknown BPM to0, infer unmetered from extraction failure, or exclude a recording from shuffle. A changed media hash invalidates cached features. Publication can require attestation completion while allowing honest unknown features; correctness of optional musical labels is a separate gate.

If later adding a model/API, first qualify one concrete input/output contract and representative gold annotations; use the project's established provider only after the task authorizes that work. Existing audio-transcription capability does not establish calibrated BPM, mood or transition scores. No API is necessary for the numeric features demonstrated here.

## Interpretation and primary reference

[FFmpeg ebur128 documentation](https://ffmpeg.org/ffmpeg-filters.html#ebur128) identifies its momentary, short-term and integrated loudness outputs and true-peak scanning. The stored LUFS values describe sampled filtered audio; RMS and spectral centroid definitions are explicitly provided in the JSON, and were computed directly, not via an installed MIR library. No claim of musical-label accuracy follows from finite numeric output. Human beat/section/transition annotation is still required for future model qualification. This bounded probe establishes cheap reproducible extraction of physical descriptors now, not that any descriptor improves shuffle.

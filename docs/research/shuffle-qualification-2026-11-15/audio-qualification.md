# Audio measurement qualification — 15 November 2026

The current 353-recording library has 353 successful physical measurement receipts covering 45.267193 hours of retained listener audio. After the initial population, only new recordings were processed; all prior receipt files remained byte-identical. Each run used four local CPU workers without cache reuse or paid API calls. Original recordings were preserved.

| Recordings newly measured | Elapsed seconds | Sampled peak aggregate RSS, KiB |
| --- | ---: | ---: |
| Initial 340 | 445.518 | 423,888 |
| Next 5 | 7.559 | 430,224 |
| Next 4 | 3.620 | 428,832 |
| Latest 4 | 5.801 | 432,304 |

Memory was sampled every 250 milliseconds; these observations are not guaranteed ceilings.

Each receipt binds the retained file’s SHA-256 identity, the imported extraction implementation, DSP settings, native audio format and tool versions. Source identity is checked before and after processing. The method fingerprint is recorded when extracting; an old receipt cannot acquire a newer implementation’s identity during publication. Cache validation rejects changed bytes, settings, method identity, malformed measurements and incomplete coverage. A separate adoption check rehashes actual retained files against the current reader manifest and receipts, verifies qualification evidence hashes, and applies the strict profile policy to sanitized summaries.

The accepted measurement method is `physical-2`, fingerprint `a6e2ae13d4def2cc8a93a509efb7e7720302ddfb698a5f8ac91ab067deeacc29`; its evidence revision is `physical-v2-complete-353-20261115`. The measured domain comprises 125 AAC, 168 Opus and 60 MP3 recordings; 172 use 44.1 kHz and 181 use 48 kHz. All are stereo. Durations range from 39.732245 to 7228.381 seconds. The largest difference between independent probed duration and decoded coverage was 47.912 milliseconds. All whole-recording quantities were defined in this population; undefined future measurements remain null rather than invented zeros.

Full retained streams supply native-channel integrated loudness and true peak, plus explicitly diagnostic 16 kHz mono RMS and median spectral centroid. Beginning and ending profiles cover up to 30 seconds each; the body profile covers the whole decoded recording. These are physical measurements, not validated labels for mood, musical energy, instrumentation or listener preference. Mono downmixing can cancel antiphase content, and the diagnostic spectrum contains no frequencies above 8 kHz. Native-channel loudness is measured before that downmix.

Twenty-six discriminating tests passed on Python 3.14/NumPy 2.4 and Python 3.12/NumPy 2.5. Actual decoder fixtures cover amplitude, frequency, stereo cancellation, silence, short remainders, changing boundaries, long logging, detectable corruption, source mutation, stale caches and invalid evidence. An independently reviewed 32-recording pilot preceded full extraction. The first full run exposed eight MP3 duration failures: bitrate-estimated container headers were wrong by 0.524–1.807 seconds. Physical-2 instead sums integer packet durations in the exact stream time base and subtracts decoder skip/discard padding. All eight then agreed with full decoded duration within 25.6 microseconds. The decoder-error handling and coverage tolerance were unchanged; a targeted eleven-recording repair check passed before the final complete run.

Rhythm remains unqualified. Initially, Beat This 1.1.0 installed and imported but both official small-model download routes returned HTTP 500. The [subsequent rhythm follow-up](rhythm-followup.md) recovered an author-confirmed checkpoint and completed inference on the same three excerpts; download failure is no longer the blocker. A bounded librosa 0.11 baseline recovered synthetic 60/120/180-beat-per-minute pulse controls with F1 scores .981/.990/.987 at 70-millisecond matching tolerance. Three real excerpts produced candidates without independent devotional beat annotations; they do not establish usable BPM accuracy. Silence or a steady tone producing no detected beats is not proof of being unmetered. No production beat or embedding fields were accepted.

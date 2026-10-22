# Together audio qualification: Gurbāṇī pilot

2026-10-22. **Not qualified for transcription verification or first-syllable timing.**
The six successful inference responses contain material omissions and corrupted
words. This invalidates the proposed Whisper-to-text-reconciler route for this
release. No source text, public page, performance order, or timing was changed.
This finding is specific to the tested model, settings, and recordings; it is
not a claim about every Together audio model or possible configuration.

## Scope and acceptance

The pilot tested `openai/whisper-large-v3` against three existing recordings.
Each recording supplied two 60-second windows offset by 20 seconds, leaving a
40-second common interval. Acceptance required intelligible source-script
transcription, retention of the expected sung occurrences, and usable onset
evidence consistent across the overlapping views. Material omitted occurrences,
unresolved lexical corruption, or unavailable first-word evidence prevent
clearance. Agreement between two ASR outputs alone does not verify the recording.

Comparisons below use the repository's pre-existing `SONG_LINES`,
`SONG_SEQUENCE`, and `SONG_TIMINGS` as the candidate baseline. Those timestamps
are listening locators, not newly validated ground truth. The reviewer did not
listen afresh during this pilot. No exact word error rate is claimed.

## Requests and reproducibility

Endpoint: `POST https://api.together.ai/v1/audio/transcriptions`.
Successful transport header: `User-Agent: Bhakti-song-processing/1.0`.
Authentication used the configured owner-only credential internally; credential
contents and location are deliberately absent from this report and artifacts.

Each source was the song-local `audio.webm`. The model-only clip was generated
with FFmpeg using `-ss OFFSET -i SOURCE -t 60 -vn -ac 1 -ar 16000 -c:a pcm_s16le`.
The unchanged listener master was retained. Multipart fields, in order:

- `model=openai/whisper-large-v3`
- `language=pa`
- `response_format=verbose_json`
- `temperature=0`
- `timestamp_granularities[]=word`
- `timestamp_granularities[]=segment`
- `file`: the PCM WAV, MIME `audio/wav`

There was no decoding prompt and no canonical lyric supplied to Whisper.
Concurrency was capped at two; the first corrected request had to succeed
before the remaining five were submitted. The initial six requests used Python
urllib's default User-Agent and all returned HTTP 403 with `error code: 1010`.
After that transport failure, six explicitly authorized requests with the named
User-Agent all returned HTTP 200. No further audio requests were made.
Thus 12 HTTP attempts occurred, six with returned inference output, representing
six minutes of successfully submitted clips. Actual billing was not measured.
The diagnostic script was kept at `/tmp/probe_together_audio.py`, outside the
production code. No unused production adapter was added.

| Song | Absolute window (s) | HTTP | Returned segments | Returned words |
| --- | ---: | ---: | ---: | ---: |
| `gagan-mein-thaal` | 0–60 | 200 | 2 | 0 |
| `gagan-mein-thaal` | 20–80 | 200 | 3 | 0 |
| `gur-satgur-ka-jo-sikh-akhaye` | 0–60 | 200 | 12 | 0 |
| `gur-satgur-ka-jo-sikh-akhaye` | 20–80 | 200 | 11 | 0 |
| `mera-man-lochai` | 810–870 | 200 | 10 | 0 |
| `mera-man-lochai` | 830–890 | 200 | 11 | 0 |

## Material findings

- **Gagan, 0–60 seconds:** the response has an empty-text segment from
  3.068 to 33.068 seconds and entirely omits the candidate opening
  `ਗਗਨ ਮੈ ਥਾਲੁ …` (baseline first onset 2.88 seconds). Its only nonempty
  segment starts with `ਮਲੇ ਆਨ ਲੋ …`, and the text ends in U+FFFD, a replacement
  character. The offset-20 view does not recover an independent complete
  opening and also corrupts source words.
- **Gur Satgur, both windows:** the repeated refrain is substantially corrupted,
  including `ਸਿਤਕ` / `ਸੇਖ ਖਾਰ` / `ਇੱਕਿ ਅਕਾ` for candidate `ਸਿਖੁ ਅਖਾਏ`.
  The 0–60 response contains no segment after 48.452 seconds, whereas the
  stored sequence places another refrain onset at 51.75 seconds. This is a
  baseline disagreement requiring listening, not permission to delete the line.
- **Merā Manu Locai, both windows:** the disputed `ਪ੍ਰੇਮ` versus canonical
  `ਪ੍ਰਿਅ` is reduced to `ਪੇ`, which does not settle the distinction. The
  candidate `ਪੰਥੁ ਨਿਹਾਰੈ ਕਾਮਨੀ` around 845.208 seconds is reduced to `ਹਾਰੇ`
  in both views. The offset-830 response also ends with an empty-text segment
  at absolute 888.428–890 seconds, near the candidate Nānak closing line.
  Repeated loss in both passes demonstrates why agreement is insufficient.

All six responses returned `words: []`. The attempted multipart array syntax
may have been ignored; scalar `timestamp_granularities=word` was not tested.
Therefore this experiment does **not** establish that Together lacks word
timestamps. The independent omission/corruption findings already fail the
transcription acceptance condition, so a timestamp-format probe would not
qualify this route and no additional audio call was made.

A text model could produce fluent canonical text from these outputs, but doing
so would supply missing acoustic evidence from scripture. It must not be called
an independent listening audit or marked as verified performance transcription.
Existing disputed readings and first-syllable checks remain unresolved.

## Evidence

Raw responses, parameters, absolute offsets, clip hashes, source-master hashes,
and transport status are stored locally under each song's ignored
`.transcription/together-pilot/` directory. `offset-N.json` retains the original
403 response; `offset-N-named-ua.json` retains the successful response.
`offset-N.wav` is the exact submitted clip. These files are intentionally not
public song content. Hashes below cover the successful evidence JSON files;
each JSON also records SHA-256 values for its audio source and clip.

| Local evidence path | SHA-256 |
| --- | --- |
| `songs/gagan-mein-thaal/.transcription/together-pilot/offset-0-named-ua.json` | `c7c811bacddbc16f6c6a8eabd1e2e5313d15f6b8d08b74046a50ec87d5d0ae4a` |
| `songs/gagan-mein-thaal/.transcription/together-pilot/offset-20-named-ua.json` | `440a3e12336d1892c845d7631206bb75797a00e6ab52cf2ba83345277a50841c` |
| `songs/gur-satgur-ka-jo-sikh-akhaye/.transcription/together-pilot/offset-0-named-ua.json` | `d02ee15677b472587a2e4ea982ca39d0690a8c35d8acc9c203770c8f61c99b3a` |
| `songs/gur-satgur-ka-jo-sikh-akhaye/.transcription/together-pilot/offset-20-named-ua.json` | `3f904bf8069225d72fbde04839fd5e800d7df9dbe6baf27608a24f9567268f0f` |
| `songs/mera-man-lochai/.transcription/together-pilot/offset-810-named-ua.json` | `0248d67c8f8981995df9697e6bce43de27c29d2bc05b09f08cff08b34a9936e6` |
| `songs/mera-man-lochai/.transcription/together-pilot/offset-830-named-ua.json` | `2adcea5488a13555c374a0fd5981837ebb2a2f74d18208a0c080268ec5d447e5` |

The compact diagnostic summary is local at
`/tmp/bhakti-together-whisper-pilot-summary.json`.

## Provider documentation

The [Together transcription API reference](https://docs.together.ai/reference/audio-transcriptions)
documents Whisper transcription, decoding-bias prompts, verbose JSON, and
segment/word timestamp granularity. Its
[transcription guide](https://docs.together.ai/docs/inference/transcription/overview)
lists input formats and request limits. The
[Qwen3.7-Plus model page](https://www.together.ai/models/qwen37-plus)
lists text and image input, not audio. Documentation establishes the offered
interfaces; the saved pilot responses establish this qualification result.

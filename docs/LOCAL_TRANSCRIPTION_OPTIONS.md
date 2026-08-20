# Local transcription options

This is an offline evaluation record for the Bhakti pipeline. No local model
may replace Gemini unless it matches the reviewed devotional-song corpus with
no missing, hallucinated, reordered, or mistranscribed lyric.

## 2026-08-20 Mac benchmark

Hardware: Apple M4 Max, 40-core GPU, 128 GB unified memory.

`mlx-community/Qwen3-ASR-1.7B-bf16` was tested through `mlx-audio` on the full
Hindi `Yeh Garv Bharā Mastak Merā` recording and a Punjabi Duniya excerpt.
Upstream Qwen3-ASR officially claims support for Hindi and for “singing voice,
songs with BGM,” so it is the right open-weight candidate to test first on this
machine. It was fast (about 5.8 seconds for 4:48 of Hindi audio, roughly
50× real time; about 5.5 GB peak MLX memory), but failed the accuracy gate:

- full-song Hindi normalized character error was about 5.3% with material word
  substitutions (`khōṭā`→`choṭā`, malformed phrases, and omitted particles);
- a second 30-second chunk configuration worsened error to about 7.2%; and
- Punjabi was rendered in Devanagari with multiple incorrect lyric words.

Therefore Qwen3-ASR is rejected as a production transcript source for this
corpus despite its broader official language/song claims. The 4 GB model cache
and isolated 399 MB environment were removed after the benchmark. VibeVoice
was also removed without benchmarking because it is a general speech/meeting
ASR model, not a singing-lyrics model.

Current specialized singing models do not solve the Indic requirement:
VocalParse is Chinese-focused, and MOSS-Music reports strong lyrics ASR on
MUSDB18/MIR-1K/Opencpop rather than Hindi, Marathi, Punjabi, Kannada, or
Sanskrit. They are research leads, not acceptable fallbacks.

## Recommended evaluation order

1. **Qwen3-ASR 1.7B + Qwen3-ForcedAligner 0.6B** — rejected for transcription
   after the benchmark above. The aligner also officially supports eleven
   languages that do not include the required Indic set, so it is not a general
   local timing solution here.
2. **Generic VTT/speech models (Whisper, VibeVoice, Canary-Qwen)** — not
   production candidates for this corpus. Speech benchmarks and VTT output do
   not establish accurate sung lyrics, repetitions, call-and-response order,
   or Indic first-syllable timing.

## LM Studio

LM Studio can import local models and expose a local server, but its published
import documentation alone does not establish that every ASR architecture is
audio-runnable in the app. Do not label Qwen3-ASR “LM Studio supported” until
an actual local audio transcription test passes. Keep the ASR runner separate
from the chat model runtime if needed.

## Evaluation gate

For a candidate local model, test the same five short excerpts used by the
cloud pipeline: a refrain return, a verse boundary, a spoken invocation, a
wordless ālāp, and a line with Punjabi/Hindi/Kannada ambiguity. Compare
source-script transcript, romanization, sequence order, first-syllable
timestamps, and total cost/latency. Promote only if it does not introduce a
new unresolved line or timing error.

## Sources

- Qwen3-ASR and ForcedAligner: https://github.com/QwenLM/Qwen3-ASR
- Qwen3-ASR technical report: https://arxiv.org/abs/2601.21337
- faster-whisper: https://github.com/SYSTRAN/faster-whisper
- NVIDIA Canary-Qwen 2.5B: https://huggingface.co/nvidia/canary-qwen-2.5b
- LM Studio local-model import: https://www.lmstudio.ai/docs/cli/local-models/import
- MLX Qwen3-ASR conversion: https://huggingface.co/mlx-community/Qwen3-ASR-1.7B-bf16
- VocalParse: https://github.com/pymaster17/VocalParse
- MOSS-Music 8B: https://huggingface.co/OpenMOSS-Team/MOSS-Music-8B-Instruct

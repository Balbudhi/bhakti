# Local transcription options

This is an offline fallback for the Bhakti processing pipeline. It does not
replace the current Gemini review path until it is benchmarked on the same
devotional recordings.

## Recommended evaluation order

1. **Qwen3-ASR 1.7B + Qwen3-ForcedAligner 0.6B** — first candidate for local
   multilingual song transcription and word/line timing. Qwen describes the
   ASR family as supporting multilingual speech, music/song recognition,
   language detection, and timestamp prediction. Run it through its native
   tooling or a dedicated local wrapper; do not assume a generic chat runtime
   can accept its audio architecture.
2. **faster-whisper / Whisper large-v3** — mature offline fallback with broad
   tooling and segment/word timestamps. It is useful as a baseline, not proof
   of a final devotional lyric.
3. **NVIDIA Canary-Qwen 2.5B** — strong open ASR candidate, particularly for
   English. Evaluate it before using it for Hindi, Punjabi, Kannada, Sanskrit,
   or sung call-and-response material.

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

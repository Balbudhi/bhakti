# Gemini model qualification

Status: **retain `google/gemini-3.7-flash` through OpenRouter as the production baseline.** This bounded comparison did not establish a consistently better replacement. Do not adopt its draft lyrics, glosses, or English automatically.

The calls ran on 22 October 2026 UTC. The private evidence directory is named `/tmp/bhakti-model-comparison20261023`; its date label is not the execution date. It contains the frozen oracle, prompts, requests, raw responses, parsed packets, usage journal, and final summary. No public reader was changed by this comparison.

## Method and limits

Both models used the same native audio clips, prompt, and schema, high reasoning, temperature zero, and the standard Google AI Studio endpoint through OpenRouter. Provider fallbacks, flex, and priority were excluded. At most two calls ran concurrently; each request had one attempt. Routing price ceilings were $0.75 per million input tokens and $3.75 per million output tokens.

The two audio excerpts were:

- Gagan Mein Thaal: seconds 0–60, including lead/response repetition and a clipped ending.
- Mera Man Lochai: seconds 810–870, including the disputed *pria/prema* passage and *pagu*.

An initially planned Gur Satgur excerpt was deferred to keep the corrected run within its $2 aggregate budget. First-pass audio prompts did not receive the existing transcript or scripture. The frozen public-reader excerpts supplied comparison evidence only: their timing and transcription had not been independently checked by fresh listening. Agreement with them or between models therefore does not establish audio accuracy. No timing calls were made.

Each model also reconstructed glosses for four written passages: Gagan's flower/light image, Gur Satgur's causative *japāvai*, Har Jiyo's sin-cutting agent, and Jo Nar's merging subject. A separate call then derived English from that model's glosses and semantic frames. Exact source-token/index checks preceded translation. These small qualification schemas did not execute the complete production pipeline or its independent adversarial review.

## Observed results

| Request | Result | Elapsed | Reported cost |
| --- | --- | ---: | ---: |
| 3.7, Gagan, initial 16,384 output cap | Truncated JSON; `MAX_TOKENS` | 124.8 s | $0.06263025 |
| 3.7, Gagan, corrected 65,536 cap | Complete packet | 165.6 s | $0.08774025 |
| 3.8, Gagan, 65,536 cap | Complete packet | 250.8 s | $0.13475025 |
| 3.7, Mera, 65,536 cap | Exceeded intended 300-second wall limit; process terminated | Over 300 s | Unknown; $0.26 reserved |
| 3.8, Mera, 65,536 cap | Complete packet | 51.5 s | $0.02803275 |
| 3.7, four-line gloss packet | Complete packet | 42.4 s | $0.02274975 |
| 3.8, four-line gloss packet | Complete packet | 47.0 s | $0.02422725 |
| 3.7, gloss-derived English | Complete packet | 53.6 s | $0.03187350 |
| 3.8, gloss-derived English | Complete packet | 41.1 s | $0.02517975 |

There were nine requests and seven schema-valid packets. Reported charges total **$0.41718375**. Retaining the full reservation for the terminated request gives an accounted ceiling of **$0.67718375**. The unknown request is not treated as free, cancelled upstream, or refunded.

The initial Gagan failure was diagnosed from its saved raw response: 15,725 reasoning tokens consumed most of the 16,384-token allowance. The corrected 3.7 response used 22,056 reasoning tokens; 3.8 used 34,203. Increasing the output allowance was a response to observed truncation, not a different transcription task.

For Gagan, both models returned the same six lead/response occurrences and identified the clipped final vowel. They differed over written representation of *malaānalo* and final orthographic vowels. Both reported *so/su* variation. These remain listening questions. 3.8 supplied approximate timestamps despite the no-timing instruction; they are not verified starts.

For Mera, 3.8 recovered eleven occurrences, including a partial pickup and the *panthu nihārai kāmanī* passage omitted by the earlier Together Whisper pilot. It explicitly retained uncertainty around *pria/pre*. The 3.7 timeout prevents a paired quality judgment on this excerpt.

## Editorial findings

All eight English lines reconstructed from their segments and covered every word index. Nevertheless, the outputs contained substantive defects:

- Both models made the purified mind the sin-cutting agent in Har Jiyo. The prior source review attaches that power to the divine essence experienced in the verse. Both models reported full fidelity despite this discrepancy.
- 3.8 turned Gagan's blossoming vegetation into “luminous lights,” losing the reviewed flower/light relationship. 3.7 stayed closer to the reviewed image.
- Both supplied merely “Nanak” and “Govinda” as proper-name popups instead of explaining identity or relationship.
- 3.8 preserved the direct causative in *japāvai*; 3.7's “inspires others to chant” weakened it.

These findings support independent source review, meaningful hover checks, and a separate adversarial review. Numeric index coverage and model self-reported fidelity are insufficient. The comparison text must not replace the reviewed public text.

## Operational decision

Retain 3.7 as the baseline. 3.8 is a useful alternate candidate for a specific blocked audio passage, but this small sample does not justify a library-wide model switch. Gemini 4 Argon was researched but was not called.

The audio experiment also demonstrated that `urllib.request.urlopen(..., timeout=300)` is a socket-operation timeout, not a total request deadline. A pending 3.7 request exceeded the intended wall limit and had to be terminated. The four later text calls used a separate subprocess per request with an enforced wall deadline. Production needs an equivalent bounded transport before its timeout can be described as a hard wall limit; a timed-out future alone does not stop a running network request. Preserve raw responses before parsing and retain unknown-outcome cost reservations.

Primary capability references: [Google 3.8 Flash documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash), [Google audio understanding](https://ai.google.dev/gemini-api/docs/audio), and [OpenRouter audio transport](https://openrouter.ai/docs/guides/overview/multimodal/audio). These establish supported inputs and interfaces, not superiority on sung Gurbāṇī or precise syllable timing.

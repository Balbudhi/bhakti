"""Frozen October 2026 source-observation request for evidence migration only.
Never dispatch with this contract. Compare retained requests before adopting old
paid observations. The production request remains owned by bhakti_pipeline.
"""
import json
from typing import Any
import source_witness

PIPELINE_SHA = 'ff47f063352606caf0590fd83fdc5d0ae26b1ad0af34c4006abf87f772514cd9'
ADAPTER_SHA = 'ef3bbd32098ba00cba08aba4eaac2be5dc1da2de6225db681b87edf45cd8214e'

def segment_transcript_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {
        "lines": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "source_text": {"type": "string"}, "roman": {"type": "string"},
            "language": {"type": "string"}, "kind": {"type": "string"}, "partial": {"type": "string"},
            "notes": {"type": "string"}},
            "required": ["id", "source_text", "roman", "language", "kind", "partial", "notes"],
            "additionalProperties": False}},
        "performance_order": {"type": "array", "items": {"type": "object", "properties": {
            "line_id": {"type": "string"}, "occurrence": {"type": "integer"}},
            "required": ["line_id", "occurrence"], "additionalProperties": False}},
        "uncertainties": {"type": "array", "items": {"type": "string"}},
    }, "required": ["lines", "performance_order", "uncertainties"], "additionalProperties": False}

def audio_audit_clip_contract() -> dict[str, Any]:
    """Only settings consumed by the source-audit audio clip encoder."""
    return {"version": 1, "codec": "aac", "bitrate": "192k", "seek_precision": 3}

def audio_audit_request_contract(
    first: dict[str, Any], segment: dict[str, Any], *, witness=None,
    source_first: bool = False, source_context=None,
) -> dict[str, Any]:
    """Exact source-audio request, shared by cache identity and dispatch."""
    witness_context = source_witness.prompt_context(witness, first.get("lines", []))
    observation_prompt = ""
    if source_context is not None:
        observation_prompt = ("\nSOURCE OBSERVATION CONTEXT (competing source evidence, not accepted lyrics):\n"
            + json.dumps(source_context, ensure_ascii=False)
            + "\nCheck these alternatives and prior hearings against the complete attached audio. "
              "An omission hypothesis is not permission to insert unperformed text. "
              "Preserve uncertainty when readings cannot be distinguished.\n")
    source_first_context = ""
    if source_first:
        exact_lines = [{"source_text": line.get("source_text", "")}
                       for line in first.get("lines", [])]
        source_first_context = f"""
SOURCE-CONTROLLED AUDIT:
The first pass selected its text from an identified original witness. Do not rewrite, normalize, or replace its source text. Every returned `source_text` must exactly copy one item from the first-pass source list below. Use the audio only to confirm presence, order, overlap status, and an audible variant that must be reported as uncertainty.

First-pass source lines:
{json.dumps(exact_lines, ensure_ascii=False)}
"""
    prompt = f"""This is the required second transcription pass for one segment of a long devotional recording. Audit the entire first-pass transcript below against the complete attached segment. Use the first transcript as your working draft; do not start over.

Be extremely careful not to miss, hallucinate, reorder, or silently correct any sung, spoken, lead, response, invocation, refrain, pickup, repeated, or closing line. Preserve overlap text because local code reconciles it. For Indic source text, retain the natural script and give a consistent scholarly ISO 15919/IAST-style romanization with accurate vowel length, retroflexion, aspiration, and language-appropriate pronunciation. For Punjabi and other north-Indic readings use consistent IAST e/o, not mixed ē/ō; preserve nasalization and final orthographic vowels, and use only Latin-script letters in the roman field. Do not apply this e/o convention to Dravidian-language distinctions. Do not translate or estimate timestamps. Mark genuine uncertainty rather than guessing.

Segment audio: absolute source seconds {segment['clip_start']:.3f}–{segment['clip_end']:.3f}; core {segment['core_start']:.3f}–{segment['core_end']:.3f}.

FIRST TRANSCRIPT:
{json.dumps(first, ensure_ascii=False)}
{witness_context}
{source_first_context}{observation_prompt}

Return strict JSON:
{{"lines":[{{"id":"segment-{segment['index']}-line-000","source_text":"","roman":"","language":"","kind":"invocation|refrain|verse|bridge|closing|spoken|instrumental|uncertain","partial":"none|leading|trailing","notes":""}}],"performance_order":[{{"line_id":"","occurrence":1}}],"uncertainties":[]}}"""
    return {"version": 1, "prompt": prompt,
            "response_schema": segment_transcript_schema(), "schema_name": "bhakti_segment_audit",
            "reasoning_effort": "high", "max_completion_tokens": 32768,
            "clip": audio_audit_clip_contract()}

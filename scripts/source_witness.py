#!/usr/bin/env python3
"""Private, evidence-preserving textual-witness support for song transcription.

Public readers never ship a third-party witness text.  This module fetches an
identified public working witness into the ignored review packet, extracts its
verse lines, and supplies only relevant excerpts to the *second*, audio-aware
transcription pass.  The recording remains the authority for its performance.
"""

from __future__ import annotations

import html
import json
import re
import subprocess
import tempfile
import unicodedata
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEVANAGARI = re.compile(r"[\u0900-\u097f]")
PAGE_CHROME = {"सभी कष्टों की पीड़ा से निवारण का मूल मंत्र", "प्रथम पृष्ठ", "अगला पृष्ठ >>"}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def registry() -> dict[str, Any]:
    return _read_json(ROOT / "data" / "source_witnesses.json")


def record_for_slug(slug: str) -> dict[str, Any] | None:
    value = registry().get("works", {}).get(slug)
    return value if isinstance(value, dict) else None


def cache_path(song_dir: Path) -> Path:
    return song_dir / ".transcription" / "witnesses" / "textual-witness.json"


def _clean_line(value: str) -> str:
    value = html.unescape(value).replace("\xa0", " ")
    value = re.sub(r"[ \t\f\v]+", " ", value).strip()
    return value


def _extract_pustak_page(document: str) -> list[str]:
    """Extract verse text, never commentary, from one Pustak reader page."""
    region = re.search(r'id=["\']freeread["\'][^>]*>(.*?)(?:<div id=["\']dynaJs|<script)', document,
                       flags=re.IGNORECASE | re.DOTALL)
    if not region:
        return []
    fragment = region.group(1)
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.IGNORECASE)
    fragment = re.sub(r"</(?:p|h[1-6]|div)\s*>", "\n", fragment, flags=re.IGNORECASE)
    plain = html.unescape(re.sub(r"<[^>]+>", "", fragment)).replace("\xa0", " ")
    # `भावार्थ` begins the edition's prose explanation, which must not be
    # mistaken for lines sung in this recording.
    plain = plain.split("भावार्थ", 1)[0]
    lines: list[str] = []
    for raw_candidate in plain.split("\n"):
        # This reader renders two verse lines inside one span. Split only at
        # the danda, not on commas/hyphens inside a line.
        for candidate in re.split(r"(?<=[।॥])\s*", raw_candidate):
            candidate = _clean_line(candidate)
            if not candidate or candidate in PAGE_CHROME or not DEVANAGARI.search(candidate):
                continue
            if candidate in {"हनुमानबाहुक", "श्रीगणेशाय नम:", "श्रीजानकीवल्लभो विजयते"}:
                lines.append(candidate)
                continue
            # Keep verse headers only when they include actual text; bare `। 1 ।`
            # is not a lyric and only harms alignment.
            if len(re.sub(r"[^\u0900-\u097f]", "", candidate)) < 3:
                continue
            lines.append(candidate)
    return lines


def _fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Bhakti-source-witness-audit/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def _fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Bhakti-source-witness-audit/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _extract_pdf_text_range(text: str, start_marker: str, end_marker: str = "") -> list[str]:
    """Extract only a configured Devanagari text range from a PDF conversion.

    A marker range is intentionally narrow: a PDF's foreword, questions, and
    prose commentary are not candidate song lines.  This is a working witness,
    so the caller still sends the excerpt only to the audio-aware second pass.
    """
    # PDF text extraction often turns a visual space into one or more
    # newlines. Match marker words across arbitrary whitespace while retaining
    # the original text after the boundary.
    def marker_match(value: str, marker: str, position: int = 0) -> re.Match[str] | None:
        pattern = r"\s*".join(re.escape(part) for part in re.split(r"\s+", marker.strip()) if part)
        return re.search(pattern, value[position:])

    start_match = marker_match(text, start_marker)
    if not start_match:
        return []
    start = start_match.start()
    fragment = text[start:]
    if end_marker:
        end_match = marker_match(fragment, end_marker)
        if end_match:
            fragment = fragment[:end_match.start()]
    lines: list[str] = []
    for raw in fragment.splitlines():
        for candidate in re.split(r"(?<=[।॥])\s*", raw):
            candidate = _clean_line(candidate)
            if not candidate or not DEVANAGARI.search(candidate):
                continue
            # Page artefacts such as a bare verse number are not text evidence.
            if len(re.sub(r"[^\u0900-\u097f]", "", candidate)) < 3:
                continue
            lines.append(candidate)
    return lines


def _extract_html_pre_text_range(document: str, start_marker: str, end_marker: str = "") -> list[str]:
    """Extract a bounded Devanagari verse range from a source-text ``<pre>``.

    Sanskrit Documents serves the verified poem as a single text block followed
    by unrelated ITRANS metadata.  Selecting the content block and an explicit
    marker range keeps titles, site chrome, and metadata out of the private
    witness cache while retaining the edition's lineation.
    """
    match = re.search(r'<pre[^>]+(?:id=["\']content["\']|class=["\'][^"\']*stotra[^"\']*)[^>]*>(.*?)</pre>',
                      document, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    text = html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).replace("\xa0", " ")
    start = text.find(start_marker)
    if start < 0:
        return []
    text = text[start:]
    if end_marker:
        end = text.find(end_marker)
        if end < 0:
            return []
        end += len(end_marker)
        text = text[:end]
    lines: list[str] = []
    for raw in text.splitlines():
        candidate = _clean_line(raw)
        if candidate and DEVANAGARI.search(candidate) and len(re.sub(r"[^\u0900-\u097f]", "", candidate)) >= 3:
            lines.append(candidate)
    return lines


def _acquire_pdf_text_range(record: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch a registered PDF and retain only the configured lyric range."""
    url = str(record["url"])
    with tempfile.TemporaryDirectory(prefix="bhakti-witness-pdf-") as temporary:
        pdf = Path(temporary) / "witness.pdf"
        pdf.write_bytes(_fetch_bytes(url))
        converted = subprocess.run(
            ["pdftotext", "-layout", str(pdf), "-"], check=True, capture_output=True, text=True,
        ).stdout
    text = _extract_pdf_text_range(converted, str(record["start_marker"]), str(record.get("end_marker") or ""))
    page = int(record.get("page", 0) or 0)
    pages = [{"page": page, "url": url, "line_count": len(text)}]
    return pages, [{"page": page, "url": url, "text": line} for line in text]


def _acquire_html_pre_text_range(record: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    url = str(record["url"])
    text = _extract_html_pre_text_range(_fetch(url), str(record["start_marker"]), str(record.get("end_marker") or ""))
    pages = [{"page": 1, "url": url, "line_count": len(text)}]
    return pages, [{"page": 1, "url": url, "text": line} for line in text]


def acquire(song_dir: Path, slug: str, *, refresh: bool = False) -> dict[str, Any] | None:
    """Acquire a registered public witness into ignored local review evidence."""
    record = record_for_slug(slug)
    if not record:
        return None
    path = cache_path(song_dir)
    cached = _read_json(path)
    if cached and not refresh:
        return cached
    if record.get("retriever") == "pdf-text-range":
        pages, lines = _acquire_pdf_text_range(record)
        result = {
            "schema_version": 1,
            "work": slug,
            "witness": record,
            "pages": pages,
            "lines": lines,
            "acquisition_note": "Private comparison cache. Do not publish this text or treat it as a critical edition.",
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    if record.get("retriever") == "html-pre-text-range":
        pages, lines = _acquire_html_pre_text_range(record)
        result = {
            "schema_version": 1,
            "work": slug,
            "witness": record,
            "pages": pages,
            "lines": lines,
            "acquisition_note": "Private comparison cache. Do not publish this text or treat it as a critical edition.",
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    if record.get("retriever") != "pustak-ebook-pages":
        raise RuntimeError(f"unsupported source-witness retriever: {record.get('retriever')!r}")
    pages: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    for number in range(int(record["first_page"]), int(record["last_page"]) + 1):
        url = str(record["base_url"]).format(page=number)
        page_lines = _extract_pustak_page(_fetch(url))
        pages.append({"page": number, "url": url, "line_count": len(page_lines)})
        lines.extend({"page": number, "url": url, "text": text} for text in page_lines)
    result = {
        "schema_version": 1,
        "work": slug,
        "witness": record,
        "pages": pages,
        "lines": lines,
        "acquisition_note": "Private comparison cache. Do not publish this text or treat it as a critical edition.",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def _signature(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    return "".join(ch for ch in decomposed if ch.isalnum() and not unicodedata.combining(ch))


def relevant_excerpt(witness: dict[str, Any] | None, draft_lines: list[dict[str, Any]], *, limit: int = 54) -> list[dict[str, Any]]:
    """Return witness lines near the audio draft without pretending they match."""
    if not witness:
        return []
    candidates = witness.get("lines", [])
    if not isinstance(candidates, list):
        return []
    requested = [_signature(str(line.get("source_text") or line.get("roman") or "")) for line in draft_lines]
    selected: set[int] = set()
    for needle in requested:
        if len(needle) < 4:
            continue
        best_index, best_score = -1, 0.0
        for index, candidate in enumerate(candidates):
            haystack = _signature(str(candidate.get("text") or ""))
            if not haystack:
                continue
            # A compact edit-ratio avoids requiring an external fuzzy-match
            # package and intentionally keeps ambiguous lines out of context.
            import difflib
            score = difflib.SequenceMatcher(None, needle, haystack).ratio()
            if score > best_score:
                best_index, best_score = index, score
        if best_index >= 0 and best_score >= 0.45:
            selected.update(range(max(0, best_index - 1), min(len(candidates), best_index + 2)))
    if not selected:
        return []
    return [candidates[index] for index in sorted(selected)[:limit]]


def prompt_context(witness: dict[str, Any] | None, draft_lines: list[dict[str, Any]]) -> str:
    excerpt = relevant_excerpt(witness, draft_lines)
    if not excerpt:
        return ""
    record = witness.get("witness", {})
    citations = "\n".join(f"- p. {row['page']}: {row['text']}" for row in excerpt)
    return f"""\nIDENTIFIED TEXTUAL WITNESS (secondary evidence only):
{record.get('title', 'Untitled witness')} — {record.get('verification_status', 'working witness')}
{record.get('comparison_policy', '')}
Relevant pages/lines:
{citations}

Use this only to notice possible mishearings in the first draft. Listen to the attached audio before accepting any reading. If the performance audibly differs, preserve the performance and state that in `changes`; if neither reading can be established, add an uncertainty rather than choosing text silently.\n"""


def write_comparison_report(song_dir: Path, slug: str, audited: dict[str, Any]) -> dict[str, Any] | None:
    """Write a deterministic, non-authoritative mismatch queue for human/API audit."""
    witness = acquire(song_dir, slug)
    if not witness:
        return None
    lines = audited.get("packet", {}).get("verified_lines", [])
    excerpt = relevant_excerpt(witness, lines, limit=100000)
    candidate_lines = witness.get("lines", [])
    findings: list[dict[str, Any]] = []
    import difflib
    for line in lines:
        source = str(line.get("source_text") or "")
        needle = _signature(source)
        if len(needle) < 4:
            continue
        best: dict[str, Any] | None = None
        best_score = 0.0
        for candidate in candidate_lines:
            score = difflib.SequenceMatcher(None, needle, _signature(str(candidate.get("text") or ""))).ratio()
            if score > best_score:
                best, best_score = candidate, score
        if best is not None and 0.45 <= best_score < 0.94:
            findings.append({"line_id": line.get("id"), "audio_draft": source,
                             "witness_text": best.get("text"), "page": best.get("page"),
                             "url": best.get("url"), "similarity": round(best_score, 3),
                             "disposition": "needs audio-aware witness audit"})
    report = {
        "schema_version": 1,
        "work": slug,
        "witness_status": witness.get("witness", {}).get("verification_status"),
        "policy": witness.get("witness", {}).get("comparison_policy"),
        "audited_line_count": len(lines),
        "relevant_witness_line_count": len(excerpt),
        "findings": findings,
    }
    path = song_dir / ".transcription" / "witnesses" / "comparison-report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report

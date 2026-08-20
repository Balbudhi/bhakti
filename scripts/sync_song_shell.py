#!/usr/bin/env python3
"""Synchronize PWA and cache-version markup across existing song pages."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    for path in sorted((ROOT / "songs").glob("*/index.html")):
        text = path.read_text(encoding="utf-8")
        for pattern in (
            r'^\s*<meta name="theme-color"[^>]*>\s*\n?',
            r'^\s*<link rel="icon"[^>]*>\s*\n?',
            r'^\s*<link rel="apple-touch-icon"[^>]*>\s*\n?',
            r'^\s*<link rel="manifest"[^>]*>\s*\n?',
        ):
            text = re.sub(pattern, "", text, flags=re.MULTILINE)
        pwa = ('\n  <meta name="theme-color" content="#6b0e16" />\n'
               '  <link rel="icon" type="image/svg+xml" href="../../assets/favicon.svg" />\n'
               '  <link rel="apple-touch-icon" href="../../assets/favicon.png" />\n'
               '  <link rel="manifest" href="../../manifest.webmanifest" />\n')
        viewport = re.search(r'<meta name="viewport"[^>]*>', text)
        if not viewport:
            raise RuntimeError(f"missing viewport metadata in {path}")
        text = text[:viewport.end()] + pwa + text[viewport.end():]
        text = re.sub(r'\n<meta name="robots"', '\n  <meta name="robots"', text)
        text = re.sub(r'^[ \t]*<a class="song-home".*?</a>[ \t]*\n?', '', text,
                      flags=re.DOTALL | re.MULTILINE)
        text = text.replace('  <main class="song-page">\n<header',
                            '  <main class="song-page">\n    <header')
        text = text.replace('  <div class="audio-player" id="audioPlayer">\n<button class="ap-btn"',
                            '  <div class="audio-player" id="audioPlayer">\n    <button class="ap-btn"')
        home = ('    <a class="song-home" href="/" aria-label="All songs" title="All songs">'
                '<svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true">'
                '<path d="M4 10.5 12 4l8 6.5V20h-5v-6H9v6H4v-9.5Z" fill="none" '
                'stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg></a>\n')
        text = text.replace('  <div class="audio-player" id="audioPlayer">\n',
                            '  <div class="audio-player" id="audioPlayer">\n' + home, 1)
        if 'id="apTime"' not in text:
            time = ('    <div class="ap-time" id="apTime" aria-label="Playback time">'
                    '<span id="apElapsed">0:00</span><span class="ap-time-sep">/</span>'
                    '<span class="ap-time-total" id="apDuration">—:—</span></div>\n')
            progress = re.search(r'^\s*<div class="ap-progress"[^\n]*\n', text, flags=re.MULTILINE)
            if not progress:
                raise RuntimeError(f"missing audio progress element in {path}")
            text = text[:progress.end()] + time + text[progress.end():]
        text = re.sub(r'<script src="data\.js(?:\?[^\"]*)?"></script>',
                      '<script src="data.js?v=contract-20260820-5"></script>', text)
        text = re.sub(r'<script src="\.\./\.\./assets/song\.js(?:\?[^\"]*)?"></script>',
                      '<script src="../../assets/song.js?v=contract-20260820-5"></script>', text)
        registration = '<script>if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");</script>'
        if registration not in text:
            text = text.replace("</body>", f"  {registration}\n</body>")
        path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

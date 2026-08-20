#!/usr/bin/env python3
"""Synchronize PWA and cache-version markup across existing song pages."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    for path in sorted((ROOT / "songs").glob("*/index.html")):
        text = path.read_text(encoding="utf-8")
        icon = re.search(r'\s*<link rel="icon"[^>]*>\s*', text)
        if not icon:
            raise RuntimeError(f"missing favicon link in {path}")
        pwa = ('\n  <meta name="theme-color" content="#6b0e16" />\n'
               '  <link rel="icon" type="image/svg+xml" href="../../assets/favicon.svg" />\n'
               '  <link rel="apple-touch-icon" href="../../assets/favicon.png" />\n'
               '  <link rel="manifest" href="../../manifest.webmanifest" />\n')
        text = text[:icon.start()] + pwa + text[icon.end():]
        text = re.sub(r'<script src="data\.js(?:\?[^\"]*)?"></script>',
                      '<script src="data.js?v=contract-20260820"></script>', text)
        text = re.sub(r'<script src="\.\./\.\./assets/song\.js(?:\?[^\"]*)?"></script>',
                      '<script src="../../assets/song.js?v=contract-20260820"></script>', text)
        registration = '<script>if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");</script>'
        if registration not in text:
            text = text.replace("</body>", f"  {registration}\n</body>")
        path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

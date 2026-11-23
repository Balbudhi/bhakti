#!/usr/bin/env python3
"""Build the self-hosted reader fonts from upstream OFL variable sources.

    uv run --with fonttools --with brotli python scripts/build_reader_fonts.py SOURCE_DIR

SOURCE_DIR holds the google/fonts variable TTFs named in FONTS. Each family
becomes one file: a letter and its combining marks must come from the same
face, or the browser draws the whole cluster in a larger system font. The
upstream mark anchors also put a tilde on top of a macron (ā̃); raise them.
"""
from __future__ import annotations

from pathlib import Path
import sys

from fontTools import subset
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables import otTables
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parents[1]
FONTS = {
    'EBGaramond.ttf': 'eb-garamond-normal.woff2',
    'CormorantGaramond.ttf': 'cormorant-garamond-normal.woff2',
    'CormorantGaramond-Italic.ttf': 'cormorant-garamond-italic.woff2',
    'Inter.ttf': 'inter-normal.woff2',
}
# The same set is declared as unicode-range in assets/fonts.css.
RANGES = ((0x0000, 0x017F), (0x0192, 0x0192), (0x0218, 0x021B), (0x0259, 0x0259),
          (0x02B0, 0x02FF), (0x0300, 0x036F), (0x1E00, 0x1EFF), (0x2000, 0x206F),
          (0x20A0, 0x20C0), (0x2113, 0x2113), (0x2122, 0x2122), (0x2190, 0x2193),
          (0x2212, 0x2212), (0x2215, 0x2215), (0x221A, 0x221A), (0xFEFF, 0xFEFF), (0xFFFD, 0xFFFD))
FEATURES = ['kern', 'mark', 'mkmk', 'ccmp', 'locl', 'liga', 'calt', 'rlig',
            'lnum', 'onum', 'pnum', 'tnum', 'frac', 'numr', 'dnom']
MACRON_VOWELS = 'āēīōūĀĒĪŌŪ'


def bounds(font, name):
    glyphs = font.getGlyphSet()
    pen = BoundsPen(glyphs)
    glyphs[name].draw(pen)
    return pen.bounds


def mark_base_subtables(font):
    for lookup in font['GPOS'].table.LookupList.Lookup:
        for table in lookup.SubTable:
            table = table.ExtSubTable if lookup.LookupType == 9 else table
            if getattr(table, 'LookupType', lookup.LookupType) == 4:
                yield table


def stack_tilde_on_macron(font):
    """Anchor the combining tilde clear of the macron on every long vowel."""
    cmap = font.getBestCmap()
    tilde = cmap[0x0303]
    gap = round(font['head'].unitsPerEm * 0.045)
    _, tilde_bottom, _, _ = tilde_box = bounds(font, tilde)
    tables = [t for t in mark_base_subtables(font) if tilde in t.MarkCoverage.glyphs]
    # The first lookup covering a base wins, so write every one that covers it.
    for vowel in MACRON_VOWELS:
        base = cmap[ord(vowel)]
        left, _, right, top = bounds(font, base)
        covering = [t for t in tables if base in t.BaseCoverage.glyphs]
        for table in covering or tables[:1]:
            mark = table.MarkArray.MarkRecord[table.MarkCoverage.glyphs.index(tilde)]
            if base not in table.BaseCoverage.glyphs:
                record = otTables.BaseRecord()
                record.BaseAnchor = [None] * table.ClassCount
                order = font.getReverseGlyphMap()
                at = sum(order[g] < order[base] for g in table.BaseCoverage.glyphs)
                table.BaseCoverage.glyphs.insert(at, base)
                table.BaseArray.BaseRecord.insert(at, record)
                table.BaseArray.BaseCount += 1
            record = table.BaseArray.BaseRecord[table.BaseCoverage.glyphs.index(base)]
            old = record.BaseAnchor[mark.Class]
            raised = mark.MarkAnchor.YCoordinate + top + gap - tilde_bottom
            if old is not None and old.YCoordinate >= raised:
                continue
            anchor = otTables.Anchor()
            anchor.Format = 1
            anchor.YCoordinate = round(raised)
            anchor.XCoordinate = round((left + right) / 2 + mark.MarkAnchor.XCoordinate
                                       - (tilde_box[0] + tilde_box[2]) / 2)
            record.BaseAnchor[mark.Class] = anchor


def build(source: Path, target: Path):
    font = TTFont(source)
    options = subset.Options(flavor='woff2', layout_features=FEATURES, notdef_outline=True,
                             name_IDs=['*'], glyph_names=False)
    tool = subset.Subsetter(options)
    tool.populate(unicodes=[c for low, high in RANGES for c in range(low, high + 1)])
    tool.subset(font)
    if any(axis.axisTag == 'opsz' for axis in font['fvar'].axes):
        # The optical size the site already used; only weight stays variable.
        font = instantiateVariableFont(font, {'opsz': 14})
    stack_tilde_on_macron(font)
    font.flavor = 'woff2'
    font.save(target)


if __name__ == '__main__':
    for source, target in FONTS.items():
        build(Path(sys.argv[1]) / source, ROOT / 'assets/fonts' / target)
        print(target, (ROOT / 'assets/fonts' / target).stat().st_size)

"""Quality regressions found on real publisher PDFs (2020 Wiley history paper)."""

from __future__ import annotations

import io

import pikepdf
import pytest

from pdfcopy.cluster import Line
from pdfcopy.glyphs import (
    Glyph,
    _merge_spacing_marks,
    load_font_cid_maps,
)
from pdfcopy.serialize import _line_with_spaces, line_space_cut


def _glyph(text: str, x0: float, x1: float, size: float = 10.0) -> Glyph:
    return Glyph(
        text=text, x0=x0, y0=100.0, x1=x1, y1=100.0 + size,
        fontname="Test", size=size, page=0,
    )


def _line(words: list[tuple[str, float, float]], size: float = 10.0) -> Line:
    return Line(glyphs=[_glyph(t, a, b, size) for t, a, b in words], page=0)


def test_line_space_cut_splits_letter_spaced_byline():
    # Word gaps 3.0 vs intra-word gaps ~1.0 (tracked small caps, 12pt)
    pairs = [("J", 0, 8), ("U", 9, 17), ("L", 18, 25), ("I", 26, 32), ("E", 33, 41),
             ("M", 44, 54), (".", 55, 58), ("B", 61, 70)]
    line = _line(pairs, size=12)
    cut = line_space_cut(line)
    assert cut is not None and 1.5 < cut < 3.0
    assert _line_with_spaces(line) == "JULIE M. B"


def test_line_space_cut_rejects_uniform_tracking():
    # Evenly spaced letters (A B S T R A C T): no clear split, no spaces
    pairs = [(ch, i * 12, i * 12 + 8) for i, ch in enumerate("ABSTRACT")]
    line = _line(pairs, size=10)
    cut = line_space_cut(line)
    assert cut is None


def _words_line(text: str, word_gap: float, size: float = 9.0) -> Line:
    """Letters of each word are contiguous glyphs; words separated by word_gap."""
    glyphs: list[Glyph] = []
    x = 0.0
    for word in text.split():
        for ch in word:
            glyphs.append(_glyph(ch, x, x + size * 0.5, size))
            x += size * 0.5
        x += word_gap
    return Line(glyphs=glyphs, page=0)


def test_byline_and_tight_body_get_spaces():
    # 9pt body: word gap 1.6 must become a space (old fixed threshold missed it)
    line = _words_line("How have the digital humanities", word_gap=1.6, size=9)
    assert _line_with_spaces(line) == "How have the digital humanities"


def test_letter_spaced_byline_gets_spaces():
    # 12pt tracked byline: intra-word gaps 1.0, word gaps 3.0
    glyphs: list[Glyph] = []
    x = 0.0
    for word in ("JULIE", "M.", "BIRKHOLZ"):
        for ch in word:
            glyphs.append(_glyph(ch, x, x + 6, size=12))
            x += 7.0  # 1.0 tracked gap inside the word
        x += 2.0  # word gaps end up 3.0 total
    line = Line(glyphs=glyphs, page=0)
    assert _line_with_spaces(line) == "JULIE M. BIRKHOLZ"


def test_merge_spacing_marks_attaches_by_geometry_not_stream_order():
    # TeX draws the accent after the *first* O in the stream, but it sits on N
    base = _glyph("M", 0, 8)
    o1 = _glyph("O", 8, 16)
    n = _glyph("N", 16, 25)
    accent = Glyph(
        text="\u02dc", x0=18, y0=112.0, x1=23, y1=116.0,
        fontname="Accent", size=10.0, page=0,
    )
    o2 = _glyph("O", 25, 33)
    merged = _merge_spacing_marks([base, o1, accent, n, o2])
    assert "".join(g.text for g in merged) == "MOÑO"


def test_differences_and_decorative_glyphs_decode(tmp_path):
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    page.Resources = pikepdf.Dictionary(
        Font=pikepdf.Dictionary(
            F1=pikepdf.Dictionary(
                Type=pikepdf.Name.Font,
                Subtype=pikepdf.Name.Type1,
                BaseFont="KBKLBL+MTSY",
                Encoding=pikepdf.Dictionary(
                    Differences=[2, pikepdf.Name("/circlecopyrt"), 61, pikepdf.Name("/equal")],
                ),
            ),
            F2=pikepdf.Dictionary(
                Type=pikepdf.Name.Font,
                Subtype=pikepdf.Name.Type1,
                BaseFont="KBKOCL+LCIRCLE10",
                Encoding=pikepdf.Dictionary(
                    Differences=[2, pikepdf.Name("/a114")],
                ),
            ),
        )
    )
    buf = io.BytesIO()
    pdf.save(buf)
    maps = load_font_cid_maps(buf.getvalue())
    assert maps["KBKLBL+MTSY"][2] == "©"
    assert maps["KBKOCL+LCIRCLE10"][2] == "○"


@pytest.mark.parametrize(
    "raw,expected",
    [("n\u0303", "ñ"), ("MERON\u02dcO", "MERON\u02dcO")],
)
def test_nfc_only_through_line_join(raw, expected):
    # _line_with_spaces NFC-composes combining sequences kept as separate glyphs
    glyphs = [_glyph(ch, i * 6, i * 6 + 5) for i, ch in enumerate(raw)]
    line = Line(glyphs=glyphs, page=0)
    text = _line_with_spaces(line)
    import unicodedata

    assert unicodedata.is_normalized("NFC", text)

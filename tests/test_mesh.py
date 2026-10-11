from __future__ import annotations

from pathlib import Path

import pytest

from pdfcopy.extract import extract
from pdfcopy.mesh import (
    MeshChar,
    select_text,
    sentence_end_indices,
    sentences_from_layouts,
    sentences_to_html,
    split_sentences,
)
from pdfcopy.writeback import fix_pdf

ROOT = Path(__file__).resolve().parents[1]
NARROW = ROOT / "corpus" / "fixtures" / "13-narrow-column.pdf"

MIDDLE = (
    "The middle sentence is the one a reviewer actually wants, even when it wraps "
    "twice in the column."
)


def _chars(text: str) -> list[MeshChar]:
    out = []
    x = 0.0
    for i, ch in enumerate(text):
        width = 3.0 if ch == " " else 7.0
        out.append(
            MeshChar(
                text=ch,
                x0=x,
                y0=10.0,
                x1=x + width,
                y1=20.0,
                size=11.0,
                page=0,
                kind="space" if ch == " " else "glyph",
                index=i,
            )
        )
        x += width
    return out


def test_sentence_end_latin_skips_abbrev_and_decimals():
    text = "See Dr. Smith at 3.14 pm. Then go."
    ends = sentence_end_indices(text)
    sentences = split_sentences(_chars(text), "body", 0, "p0-b0")
    assert [item.text for item in sentences] == [
        "See Dr. Smith at 3.14 pm.",
        "Then go.",
    ]
    assert ends


def test_sentence_end_cjk():
    text = "第一句。第二句！第三句？"
    sentences = split_sentences(_chars(text), "body", 0, "p0-b0")
    assert [item.text for item in sentences] == ["第一句。", "第二句！", "第三句？"]


def test_narrow_column_splits_three_sentences():
    if not NARROW.exists():
        pytest.skip("fixtures not generated")
    result = extract(NARROW)
    sentences = sentences_from_layouts(result.layouts)
    bodies = [item for item in sentences if item.role == "body"]
    assert len(bodies) == 3
    assert bodies[1].text == MIDDLE
    assert all("\n" not in item.text for item in bodies)
    overlay = result.overlay["pages"][0]["sentences"]
    assert len(overlay) == 3
    assert overlay[1]["text"] == MIDDLE


def test_narrow_column_bbox_selects_middle_sentence():
    if not NARROW.exists():
        pytest.skip("fixtures not generated")
    result = extract(NARROW)
    sentences = sentences_from_layouts(result.layouts)
    mid = next(item for item in sentences if item.text == MIDDLE)
    glyphs = mid.glyphs
    assert len(glyphs) >= 8
    a = glyphs[len(glyphs) // 3]
    b = glyphs[(2 * len(glyphs)) // 3]
    bbox = (min(a.x0, b.x0), min(a.y0, b.y0), max(a.x1, b.x1), max(a.y1, b.y1))
    got = select_text(sentences, mid.page, bbox)
    assert got == MIDDLE
    assert "\n" not in got
    assert "Page" not in got
    assert "first sentence" not in got
    assert "last sentence" not in got
    html = sentences_to_html([mid])
    assert html.startswith("<p>")
    assert MIDDLE in html
    assert "<br" not in html


def test_fixed_pdf_span_actualtext_has_middle_sentence(tmp_path: Path):
    import pikepdf

    if not NARROW.exists():
        pytest.skip("fixtures not generated")
    dest = tmp_path / "13.fixed.pdf"
    fix_pdf(NARROW, dest)
    pdf = pikepdf.Pdf.open(dest)
    try:
        raw = pdf.pages[0].Contents.read_bytes()
    finally:
        pdf.close()
    encoded = ("<feff" + MIDDLE.encode("utf-16-be").hex() + ">").encode("ascii")
    assert encoded in raw
    assert b"/Span << /ActualText" in raw or b"/Span<<" in raw

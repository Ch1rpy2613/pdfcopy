from __future__ import annotations

import re
from pathlib import Path

import pytest

from pdfcopy.readertext import reader_copy_text
from pdfcopy.textutil import normalize_expected
from pdfcopy.writeback import fix_pdf

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpus"
READER_FIXTURES = [
    "01-invoice-header-footer",
    "02-two-column-article",
    "05-chinese-no-tounicode",
    "13-narrow-column",
    "18-fake-spaces",
]
MIDDLE = (
    "The middle sentence is the one a reviewer actually wants, even when it wraps "
    "twice in the column."
)


@pytest.mark.parametrize("stem", READER_FIXTURES)
def test_fixed_pdf_copies_as_paragraphs(stem, tmp_path: Path):
    src = CORPUS / "fixtures" / f"{stem}.pdf"
    expected = CORPUS / "expected" / f"{stem}.txt"
    if not src.exists():
        pytest.skip("fixtures not generated")
    dest = tmp_path / f"{stem}.fixed.pdf"
    fix_pdf(src, dest)
    got = re.sub(r"\n+", "\n", reader_copy_text(dest))
    want = re.sub(r"\n+", "\n", normalize_expected(expected.read_text(encoding="utf-8")))
    assert "Page 1 of" not in got
    assert "第 1 页" not in got
    assert got == want


def test_narrow_column_reader_has_no_soft_breaks(tmp_path: Path):
    src = CORPUS / "fixtures" / "13-narrow-column.pdf"
    if not src.exists():
        pytest.skip("fixtures not generated")
    dest = tmp_path / "13.fixed.pdf"
    fix_pdf(src, dest)
    naive_original = reader_copy_text(src)
    fixed = reader_copy_text(dest)
    assert "\n" in naive_original
    assert "\n" not in fixed
    assert "Page" in naive_original
    assert "Page" not in fixed
    assert MIDDLE in fixed


def test_copy_mesh_uses_glyph_sized_runs(tmp_path: Path):
    """Invisible letters sit on the ink, not a squeezed paragraph slab."""
    import pikepdf
    from pikepdf import Operator

    src = CORPUS / "fixtures" / "13-narrow-column.pdf"
    if not src.exists():
        pytest.skip("fixtures not generated")
    dest = tmp_path / "13.fixed.pdf"
    fix_pdf(src, dest)
    pdf = pikepdf.Pdf.open(dest)
    try:
        sizes: list[float] = []
        for operands, operator in pikepdf.parse_content_stream(pdf.pages[0]):
            if operator == Operator("Tf") and len(operands) >= 2:
                name = str(operands[0])
                if name in {"/PDFCopy", "PDFCopy"}:
                    sizes.append(float(operands[1]))
        raw = pdf.pages[0].Contents.read_bytes()
    finally:
        pdf.close()
    assert len(sizes) > 40
    assert max(sizes) < 20.0
    assert min(sizes) > 6.0
    assert b"/Span" in raw
    assert b"/Artifact BMC" in raw


def test_default_keeps_ink_outline_is_optional(tmp_path: Path):
    import pikepdf

    src = CORPUS / "fixtures" / "13-narrow-column.pdf"
    if not src.exists():
        pytest.skip("fixtures not generated")
    kept = tmp_path / "kept.pdf"
    outlined = tmp_path / "outlined.pdf"
    fix_pdf(src, kept)
    fix_pdf(src, outlined, outline=True)

    def page_bytes(path: Path) -> bytes:
        pdf = pikepdf.Pdf.open(path)
        try:
            return pdf.pages[0].Contents.read_bytes()
        finally:
            pdf.close()

    kept_raw = page_bytes(kept)
    outlined_raw = page_bytes(outlined)
    assert b"/Artifact BMC" in kept_raw
    assert b"The first sentence" in kept_raw
    assert b"The first sentence" not in outlined_raw
    assert b"/PDFCopy" in kept_raw
    assert b"/PDFCopy" in outlined_raw

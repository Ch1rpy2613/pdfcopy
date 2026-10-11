from __future__ import annotations

import json
from pathlib import Path

import pikepdf
import pytest
from pikepdf import Name

from pdfcopy.writeback import fix_pdf

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "corpus" / "fixtures" / "05-chinese-no-tounicode.pdf"


def test_fix_writes_overlay_and_markinfo(tmp_path: Path):
    src = ROOT / "corpus" / "fixtures" / "03-contract-wrapped.pdf"
    if not src.exists():
        pytest.skip("fixtures not generated")
    dest = tmp_path / "fixed.pdf"
    fix_pdf(src, dest)
    pdf = pikepdf.open(dest)
    assert pdf.Root.get(Name.MarkInfo) is not None
    assert Name.PieceInfo in pdf.Root
    assert Name.PDFCopy in pdf.Root.PieceInfo
    stream = pdf.Root.PieceInfo.PDFCopy.Private.Data
    overlay = json.loads(bytes(stream.read_bytes()).decode("utf-8"))
    assert overlay["spec"] == "pdfcopy-overlay"
    assert overlay["pages"]
    assert "sentences" in overlay["pages"][0]
    assert overlay["pages"][0]["sentences"]
    assert Name.StructTreeRoot in pdf.Root
    pdf.close()


def test_fix_restores_tounicode(tmp_path: Path):
    if not FIXTURE.exists():
        pytest.skip("fixtures not generated")
    dest = tmp_path / "cn.fixed.pdf"
    fix_pdf(FIXTURE, dest)
    pdf = pikepdf.open(dest)
    found = False
    for page in pdf.pages:
        fonts = page.get("/Resources", {}).get("/Font", {})
        for _, font in fonts.items():
            if Name.ToUnicode in font:
                data = font.ToUnicode.read_bytes()
                if b"beginbfchar" in data or b"beginbfrange" in data:
                    found = True
    pdf.close()
    assert found

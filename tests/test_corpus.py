from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdfcopy.extract import extract
from pdfcopy.textutil import normalize_expected

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpus"
MANIFEST = CORPUS / "manifest.json"


def _fixtures():
    if not MANIFEST.exists():
        pytest.skip("corpus/manifest.json missing — run scripts/generate_corpus.py")
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return data["fixtures"]


@pytest.mark.parametrize("item", _fixtures(), ids=lambda item: item["file"])
def test_fixture_matches_expected(item):
    pdf = CORPUS / "fixtures" / item["file"]
    expected_path = CORPUS / "expected" / (Path(item["file"]).stem + ".txt")
    assert pdf.exists(), pdf
    expected = expected_path.read_text(encoding="utf-8")
    result = extract(pdf)
    if expected.strip().startswith("# pdfcopy:scanned"):
        assert result.scanned
        assert result.text == ""
        return
    got = normalize_expected(result.text)
    want = normalize_expected(expected)
    assert got == want


def test_naive_copy_keeps_line_breaks_on_narrow_column():
    pdf = CORPUS / "fixtures" / "13-narrow-column.pdf"
    if not pdf.exists():
        pytest.skip("fixtures not generated")
    result = extract(pdf)
    assert "\n" in result.naive_text
    assert "\n" not in result.text

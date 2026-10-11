"""What a typical reader copies from a PDF's text operators."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import pikepdf
from pdfminer.high_level import extract_text
from pikepdf import Name, Operator

from pdfcopy.textutil import normalize_expected

Source = str | Path | BinaryIO

BLOCK_TAGS = {"P", "H1", "H2", "H3", "H4", "H5", "H6", "L", "LI", "Table", "Code", "H"}


def reader_copy_text(source: Source) -> str:
    """Extract text the way a fixed file should paste: block ActualText first."""
    data = _read_all(source)
    marked = _block_actual_texts(data)
    if marked:
        return normalize_expected("\n\n".join(marked))
    text = extract_text(BytesIO(data)) or ""
    return normalize_expected(text)


def _read_all(source: Source) -> bytes:
    if hasattr(source, "read"):
        data = source.read()
        if hasattr(source, "seek"):
            try:
                source.seek(0)
            except OSError:
                pass
        return data
    return Path(source).read_bytes()


def _block_actual_texts(data: bytes) -> list[str]:
    """Collect ActualText on paragraph-level tags, ignoring nested /Span."""
    pdf = pikepdf.Pdf.open(BytesIO(data))
    out: list[str] = []
    try:
        for page in pdf.pages:
            for operands, operator in pikepdf.parse_content_stream(page):
                if operator != Operator("BDC") or len(operands) < 2:
                    continue
                tag = str(operands[0]).lstrip("/")
                if tag not in BLOCK_TAGS:
                    continue
                props = operands[1]
                actual = _read_actual_text(props)
                if actual:
                    out.append(actual)
    except Exception:
        return []
    finally:
        pdf.close()
    return out


def _read_actual_text(props) -> str:
    if not isinstance(props, pikepdf.Dictionary):
        return ""
    if Name.ActualText not in props:
        return ""
    value = props[Name.ActualText]
    if isinstance(value, bytes):
        if value.startswith(b"\xfe\xff"):
            return value.decode("utf-16-be", errors="replace")
        return value.decode("utf-8", errors="replace")
    text = str(value)
    if text.startswith("\ufeff"):
        return text.lstrip("\ufeff")
    return text

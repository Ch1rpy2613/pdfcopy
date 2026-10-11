"""Public extraction API."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

from pdfcopy.cluster import PageLayout, cluster_document
from pdfcopy.glyphs import PageGlyphs, extract_glyphs
from pdfcopy.overlay import build_overlay
from pdfcopy.serialize import naive_serialize, serialize_layouts, serialize_page

Source = str | Path | BinaryIO


@dataclass(slots=True)
class ExtractResult:
    text: str
    naive_text: str
    pages: list[str]
    layouts: list[PageLayout]
    glyphs: list[PageGlyphs]
    overlay: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def scanned(self) -> bool:
        return bool(self.glyphs) and all(not page.has_text_layer for page in self.glyphs)


def extract(source: Source) -> ExtractResult:
    glyphs = extract_glyphs(source)
    layouts = cluster_document(glyphs)
    text = serialize_layouts(layouts)
    naive = naive_serialize(layouts)
    page_texts = [serialize_page(layout) for layout in layouts]
    warnings: list[str] = []
    if all(not page.has_text_layer for page in glyphs):
        warnings.append(
            "This PDF has no text layer (likely a scan). pdfcopy v1 does not OCR."
        )
    elif not text.strip():
        warnings.append("No copyable text could be reconstructed from the glyph stream.")
    return ExtractResult(
        text=text,
        naive_text=naive,
        pages=page_texts,
        layouts=layouts,
        glyphs=glyphs,
        overlay=build_overlay(layouts),
        warnings=warnings,
    )


def extract_text(source: Source) -> str:
    return extract(source).text

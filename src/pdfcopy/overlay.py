"""Public overlay written back into a standard PDF (PieceInfo + embedded JSON)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pdfcopy.cluster import PageLayout
from pdfcopy.mesh import sentences_from_layouts, sentences_to_overlay
from pdfcopy.serialize import serialize_block

SPEC_ID = "pdfcopy-overlay"
SPEC_VERSION = "1.0"
SPEC_URL = "https://github.com/Ch1rpy2613/pdfcopy/blob/main/docs/CONVENTION.md"


def build_overlay(layouts: list[PageLayout]) -> dict[str, Any]:
    pages = []
    for layout in layouts:
        blocks = []
        for block in layout.blocks:
            x0, y0, x1, y1 = block.bbox
            soft: list[list[float]] = []
            for line in block.lines[:-1]:
                soft.append([round(line.x1, 3), round(line.ymid, 3)])
            spaces: list[list[float]] = []
            for line in block.lines:
                glyphs = line.glyphs
                for i in range(1, len(glyphs)):
                    gap = glyphs[i].x0 - glyphs[i - 1].x1
                    if gap > 0.28 * max(glyphs[i].size, glyphs[i - 1].size):
                        spaces.append(
                            [
                                round((glyphs[i - 1].x1 + glyphs[i].x0) / 2, 3),
                                round(line.ymid, 3),
                            ]
                        )
            blocks.append(
                {
                    "id": f"p{block.page}-b{block.reading_order}",
                    "role": _role_to_pdf(block.role),
                    "readingOrder": block.reading_order,
                    "bbox": [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)],
                    "text": serialize_block(block),
                    "softBreaks": soft,
                    "spaces": spaces,
                    "column": block.column,
                }
            )
        artifacts = []
        for line in layout.lines:
            if line.role in {"header", "footer", "page_number"}:
                artifacts.append(
                    {
                        "role": "artifact",
                        "artifactType": "pagination"
                        if line.role == "page_number"
                        else line.role,
                        "bbox": [
                            round(line.x0, 3),
                            round(line.y0, 3),
                            round(line.x1, 3),
                            round(line.y1, 3),
                        ],
                        "text": "".join(g.text for g in line.glyphs),
                    }
                )
        page_sentences = sentences_to_overlay(sentences_from_layouts([layout]))
        pages.append(
            {
                "index": layout.page.index,
                "width": round(layout.page.width, 3),
                "height": round(layout.page.height, 3),
                "hasTextLayer": layout.page.has_text_layer,
                "blocks": blocks,
                "sentences": page_sentences,
                "artifacts": artifacts,
            }
        )
    return {
        "spec": SPEC_ID,
        "version": SPEC_VERSION,
        "url": SPEC_URL,
        "created": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "pages": pages,
    }


def _role_to_pdf(role: str) -> str:
    return {
        "heading": "h",
        "body": "p",
        "list": "l",
        "table": "table",
        "code": "code",
    }.get(role, "p")

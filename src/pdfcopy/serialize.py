"""Turn clustered blocks into the text a human wants on the clipboard."""

from __future__ import annotations

import re
import unicodedata

from pdfcopy.cluster import Block, Line, PageLayout
from pdfcopy.glyphs import Glyph

CJK_RANGES = (
    ("\u3300", "\u33ff"),
    ("\u3400", "\u4dbf"),
    ("\u4e00", "\u9fff"),
    ("\uf900", "\ufaff"),
    ("\ufe30", "\ufe4f"),
    ("\u3040", "\u30ff"),
    ("\u31f0", "\u31ff"),
    ("\uac00", "\ud7af"),
    ("\u3000", "\u303f"),
    ("\uff00", "\uffef"),
)
CJK_PUNCT = set("，。、；：？！「」『』（）【】《》—…·")
LATIN_JOIN_HYPHEN = set("-‐‑‒–­")


def is_cjk(char: str) -> bool:
    if not char:
        return False
    ch = char[0]
    if ch in CJK_PUNCT:
        return True
    return any(start <= ch <= end for start, end in CJK_RANGES)


def is_cjk_punct(char: str) -> bool:
    return bool(char) and char[0] in CJK_PUNCT


def serialize_layouts(layouts: list[PageLayout]) -> str:
    pages = [serialize_page(layout) for layout in layouts]
    pages = [page for page in pages if page]
    return _normalize("\n\n".join(pages))


def serialize_page(layout: PageLayout) -> str:
    if not layout.page.has_text_layer and not layout.blocks:
        return ""
    chunks = [serialize_block(block) for block in layout.blocks]
    chunks = [c for c in chunks if c]
    return _normalize("\n\n".join(chunks))


def serialize_line(line: Line) -> str:
    """One visual line, with spaces inferred from glyph gaps."""
    return _line_with_spaces(line).rstrip()


def serialize_block(block: Block) -> str:
    if block.role in {"table", "code"}:
        return "\n".join(_line_with_spaces(line).rstrip() for line in block.lines).rstrip()
    if block.role == "list":
        return _serialize_list(block)
    paragraph = _join_lines(block.lines)
    if block.role == "heading":
        return paragraph.strip()
    return paragraph.strip()


def _serialize_list(block: Block) -> str:
    items: list[str] = []
    current: list[Line] = []
    for line in block.lines:
        preview = "".join(g.text for g in line.glyphs).lstrip()
        starts = bool(re.match(r"^([\u2022•·▪‣◦\-–—*＊]|\(?\d+[.)、]|（\d+）)", preview))
        if starts and current:
            items.append(_join_lines(current))
            current = [line]
        else:
            current.append(line)
    if current:
        items.append(_join_lines(current))
    return "\n".join(item.strip() for item in items if item.strip())


def _join_lines(lines: list[Line]) -> str:
    if not lines:
        return ""
    pieces: list[str] = [_line_with_spaces(lines[0]).rstrip()]
    for prev, cur in zip(lines, lines[1:]):
        left = pieces[-1]
        right = _line_with_spaces(cur).strip()
        if not right:
            continue
        pieces[-1] = _join_soft_break(left, right)
    return "".join(pieces) if len(pieces) == 1 else pieces[0]


def _join_soft_break(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    left_ch = left[-1]
    right_ch = right[0]
    if left_ch in LATIN_JOIN_HYPHEN and right_ch.islower():
        return left[:-1] + right
    if is_cjk(left_ch) and is_cjk(right_ch):
        return left + right
    if is_cjk(left_ch) and right_ch.isascii() and right_ch.isalnum():
        return left + right
    if left_ch.isascii() and left_ch.isalnum() and is_cjk(right_ch):
        return left + right
    if left_ch.isspace() or right_ch.isspace():
        return left + right
    if is_cjk_punct(left_ch) or is_cjk_punct(right_ch):
        return left + right
    if left_ch in "([{\"'“‘" or right_ch in ")].,;:!?\"'”’":
        return left + right
    return left + " " + right


def _line_with_spaces(line: Line) -> str:
    if not line.glyphs:
        return ""
    parts: list[str] = []
    prev: Glyph | None = None
    for glyph in line.glyphs:
        if prev is not None:
            gap = glyph.x0 - prev.x1
            if _needs_space(prev, glyph, gap):
                if not (parts and parts[-1].endswith(" ")) and not glyph.text.startswith(" "):
                    parts.append(" ")
        parts.append(glyph.text)
        prev = glyph
    return "".join(parts)


def _needs_space(prev: Glyph, cur: Glyph, gap: float) -> bool:
    left = prev.text[-1] if prev.text else ""
    right = cur.text[0] if cur.text else ""
    if not left or not right:
        return False
    if left.isspace() or right.isspace():
        return False
    if is_cjk(left) and is_cjk(right):
        # A real word space in CJK is rare; only keep a large visual hole.
        return gap > max(prev.size, cur.size) * 0.85
    if is_cjk_punct(left) or is_cjk_punct(right):
        return False
    if is_cjk(left) and right.isascii() and right.isalnum():
        return gap > max(prev.size, cur.size) * 0.5
    if left.isascii() and left.isalnum() and is_cjk(right):
        return gap > max(prev.size, cur.size) * 0.5
    typical = max(prev.width, cur.width, prev.size * 0.45, 1.0)
    return gap > typical * 0.28


def naive_serialize(layouts: list[PageLayout]) -> str:
    """What most readers put on the clipboard: one visual line, one newline."""
    pages: list[str] = []
    for layout in layouts:
        lines = []
        for line in sorted(layout.lines, key=lambda item: (-item.ymid, item.x0)):
            lines.append(_line_with_spaces(line).rstrip())
        pages.append("\n".join(line for line in lines if line))
    return "\n\n".join(p for p in pages if p)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

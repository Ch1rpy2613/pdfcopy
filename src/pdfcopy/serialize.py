"""Turn clustered blocks into the text a human wants on the clipboard."""

from __future__ import annotations

import re
import unicodedata

from pdfcopy.cluster import Block, Line, PageLayout
from pdfcopy.glyphs import Glyph
from pdfcopy.textutil import decompose_ligatures

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
    """Document text: narrative first (soft wraps joined), notes at the end."""
    body_chunks: list[tuple[str, str]] = []
    note_chunks: list[str] = []
    for layout in layouts:
        for block in layout.blocks:
            chunk = serialize_block(block)
            if not chunk:
                continue
            if block.role == "footnote":
                note_chunks.append(chunk)
            else:
                body_chunks.append((chunk, block.role))
    body = _join_narrative(body_chunks)
    if note_chunks:
        notes = _join_narrative([(c, "footnote") for c in note_chunks])
        text = f"{body}\n\n{notes}" if body else notes
    else:
        text = body
    return _normalize(text)


def serialize_page(layout: PageLayout) -> str:
    if not layout.page.has_text_layer and not layout.blocks:
        return ""
    body = [(serialize_block(b), b.role) for b in layout.blocks if b.role != "footnote"]
    notes = [serialize_block(b) for b in layout.blocks if b.role == "footnote"]
    body = [(c, r) for c, r in body if c]
    notes = [c for c in notes if c]
    text = _join_narrative(body)
    if notes:
        joined = "\n\n".join(notes)
        text = f"{text}\n\n{joined}" if text else joined
    return _normalize(text)


_SENTENCE_END = tuple(".!?。！？…")
_WEAK_END = tuple(",;、，")
_OPENERS = tuple("\"'“‘([{")
# Structural blocks must never melt into a paragraph.
_NO_JOIN_ROLES = {"table", "code", "list"}


def _join_narrative(chunks: list[tuple[str, str]]) -> str:
    """Join body fragments that were split by columns, pages, or footnotes."""
    if not chunks:
        return ""
    out: list[str] = [chunks[0][0]]
    prev_role = chunks[0][1]
    for chunk, role in chunks[1:]:
        prev = out[-1]
        if _should_join(prev, prev_role, chunk, role):
            out[-1] = _join_soft_break(prev.rstrip(), chunk.lstrip())
        else:
            out.append(chunk)
            prev_role = role
    return "\n\n".join(out)


def _should_join(prev: str, prev_role: str, chunk: str, role: str) -> bool:
    if not _continues_paragraph(prev, chunk):
        return False
    if _may_join_roles(prev_role, role):
        return True
    # Hyphen seam across a role change (list item wrap, footnote stub).
    left = prev.rstrip()
    right = chunk.lstrip()
    return bool(left) and left[-1] in LATIN_JOIN_HYPHEN and bool(right) and right[0].islower()


def _may_join_roles(left: str, right: str) -> bool:
    if left in _NO_JOIN_ROLES or right in _NO_JOIN_ROLES:
        return False
    # A heading may wrap onto the next heading line, never into body prose.
    if left == "heading" or right == "heading":
        return left == right == "heading"
    return True


def _continues_paragraph(left: str, right: str) -> bool:
    if not left or not right:
        return False
    l = left.rstrip()
    r = right.lstrip()
    if not l or not r:
        return False
    lch, rch = l[-1], r[0]
    # Labels, headings, and table captions end with ':' — keep them separate.
    if lch in ":":
        return False
    if rch in _OPENERS or rch.isupper():
        return False
    # Soft hyphen at a block seam: "inter-" + "national".
    if lch in LATIN_JOIN_HYPHEN and rch.islower():
        return True
    if l.endswith("...") or l.endswith("…"):
        return rch.islower() or is_cjk(rch)
    if lch in _SENTENCE_END:
        return False
    if rch in _WEAK_END or lch in _WEAK_END:
        return rch.islower() or is_cjk(rch)
    if is_cjk(lch) and is_cjk(rch):
        return True
    if lch.isalnum() and rch.islower():
        return True
    return False


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
    cut = line_space_cut(line)
    parts: list[str] = []
    prev: Glyph | None = None
    for glyph in line.glyphs:
        if prev is not None:
            gap = glyph.x0 - prev.x1
            if _needs_space(prev, glyph, gap, cut):
                if not (parts and parts[-1].endswith(" ")) and not glyph.text.startswith(" "):
                    parts.append(" ")
        parts.append(glyph.text)
        prev = glyph
    return unicodedata.normalize("NFC", "".join(parts))


def line_space_cut(line: Line) -> float | None:
    """Adaptive word-space threshold for this line, or None to use the default.

    Letter-spaced headings and tightly set body text both defeat any fixed
    multiple of glyph width: the reliable signal is a line's own gap
    distribution, which splits into a tight intra-word cluster and a loose
    word-space cluster. The cut is the midpoint of the biggest jump.
    """
    size = line.size or 0.0
    if size <= 0 or len(line.glyphs) < 6:
        return None
    gaps: list[float] = []
    prev: Glyph | None = None
    for glyph in line.glyphs:
        if prev is not None:
            left = prev.text[-1:] if prev.text else ""
            right = glyph.text[:1] if glyph.text else ""
            if left and right and not left.isspace() and not right.isspace():
                gaps.append(round(glyph.x0 - prev.x1, 3))
        prev = glyph
    if len(gaps) < 4:
        return None
    xs = sorted(gaps)
    floor = size * 0.11  # a real space is at least ~an eighth of an em
    best_jump, best_cut = 0.0, None
    for a, b in zip(xs[:-1], xs[1:]):
        if b < floor or a > size * 0.5:
            continue
        jump = b - a
        if jump > best_jump and jump >= size * 0.06:
            upper = [g for g in xs if g >= b]
            if len(upper) >= 2 or (len(upper) == 1 and b >= size * 0.2):
                best_jump = jump
                best_cut = (a + b) / 2
    return best_cut


def _needs_space(prev: Glyph, cur: Glyph, gap: float, cut: float | None = None) -> bool:
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
    if cut is not None and gap > cut:
        return True
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
    text = unicodedata.normalize("NFC", decompose_ligatures(text))
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

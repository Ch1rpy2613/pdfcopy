"""Sentence lock: split reconstructed paragraphs into sentences with glyph boxes."""

from __future__ import annotations

from dataclasses import dataclass

from pdfcopy.cluster import Block, Line, PageLayout
from pdfcopy.glyphs import Glyph
from pdfcopy.serialize import (
    _join_soft_break,
    _needs_space,
    is_cjk,
    serialize_block,
    serialize_line,
)

LATIN_JOIN_HYPHEN = set("-‐‑‒–­")
CJK_STOP = set("。！？；")
LATIN_STOP = set(".!?")
ABBREV = {
    "mr",
    "mrs",
    "ms",
    "dr",
    "prof",
    "sr",
    "jr",
    "inc",
    "ltd",
    "co",
    "corp",
    "vs",
    "etc",
    "eg",
    "ie",
    "no",
    "fig",
    "vol",
    "pp",
    "al",
    "st",
    "ave",
    "jan",
    "feb",
    "mar",
    "apr",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
}


@dataclass(slots=True)
class MeshChar:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    page: int
    kind: str  # glyph | space | softjoin
    index: int = 0

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)


@dataclass(slots=True)
class Sentence:
    text: str
    chars: list[MeshChar]
    role: str
    page: int
    block_id: str
    index: int

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        boxes = [c.bbox for c in self.chars if c.kind == "glyph"]
        if not boxes:
            boxes = [c.bbox for c in self.chars]
        if not boxes:
            return (0.0, 0.0, 0.0, 0.0)
        return (
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )

    @property
    def glyphs(self) -> list[MeshChar]:
        return [c for c in self.chars if c.kind == "glyph"]


def sentences_from_layouts(layouts: list[PageLayout]) -> list[Sentence]:
    out: list[Sentence] = []
    for layout in layouts:
        for block in layout.blocks:
            out.extend(sentences_from_block(block))
    return out


def sentences_from_block(block: Block) -> list[Sentence]:
    block_id = f"p{block.page}-b{block.reading_order}"
    if block.role in {"table", "code"}:
        return _line_units(block, block_id)
    if block.role == "heading":
        chars = flatten_block(block)
        text = serialize_block(block)
        return [
            Sentence(
                text=text,
                chars=chars,
                role=block.role,
                page=block.page,
                block_id=block_id,
                index=0,
            )
        ]
    chars = flatten_block(block)
    if not chars:
        return []
    if block.role == "list":
        return _split_list_items(block, chars, block_id)
    return split_sentences(chars, block.role, block.page, block_id)


def flatten_block(block: Block) -> list[MeshChar]:
    chars: list[MeshChar] = []
    lines = block.lines
    for i, line in enumerate(lines):
        line_chars = flatten_line(line)
        if i and chars and line_chars:
            glue, drop_hyphen = _soft_join_glue(chars, line_chars)
            if drop_hyphen:
                chars = _drop_trailing_hyphen(chars)
            if glue:
                prev = chars[-1]
                nxt = line_chars[0]
                chars.append(
                    MeshChar(
                        text=glue,
                        x0=prev.x1,
                        y0=prev.y0,
                        x1=prev.x1 + max(prev.size * 0.3, 1.0),
                        y1=prev.y1,
                        size=prev.size,
                        page=prev.page,
                        kind="softjoin",
                    )
                )
        chars.extend(line_chars)
    for n, item in enumerate(chars):
        item.index = n
    return chars


def flatten_line(line: Line) -> list[MeshChar]:
    out: list[MeshChar] = []
    prev: Glyph | None = None
    for glyph in line.glyphs:
        if prev is not None and _needs_space(prev, glyph, glyph.x0 - prev.x1):
            gap_x0 = prev.x1
            gap_x1 = glyph.x0
            out.append(
                MeshChar(
                    text=" ",
                    x0=gap_x0,
                    y0=min(prev.y0, glyph.y0),
                    x1=gap_x1,
                    y1=max(prev.y1, glyph.y1),
                    size=max(prev.size, glyph.size),
                    page=glyph.page,
                    kind="space",
                )
            )
        if glyph.text:
            out.append(
                MeshChar(
                    text=glyph.text,
                    x0=glyph.x0,
                    y0=glyph.y0,
                    x1=glyph.x1,
                    y1=glyph.y1,
                    size=glyph.size,
                    page=glyph.page,
                    kind="glyph",
                )
            )
        prev = glyph
    return out


def _soft_join_glue(left: list[MeshChar], right: list[MeshChar]) -> tuple[str, bool]:
    left_text = "".join(c.text for c in left)
    right_text = "".join(c.text for c in right).lstrip()
    joined = _join_soft_break(left_text.rstrip(), right_text)
    expected = left_text.rstrip() + right_text
    if left_text.rstrip().endswith(tuple(LATIN_JOIN_HYPHEN)) and joined == left_text.rstrip()[:-1] + right_text:
        return "", True
    if joined == expected:
        return "", False
    if joined == left_text.rstrip() + " " + right_text:
        return " ", False
    extra = joined[len(left_text.rstrip()) : len(joined) - len(right_text)]
    return extra, False


def _drop_trailing_hyphen(chars: list[MeshChar]) -> list[MeshChar]:
    for i in range(len(chars) - 1, -1, -1):
        if chars[i].kind == "softjoin":
            continue
        if chars[i].text and chars[i].text[-1] in LATIN_JOIN_HYPHEN:
            trimmed = chars[i].text[:-1]
            if trimmed:
                chars[i].text = trimmed
            else:
                chars.pop(i)
            break
    return chars


def split_sentences(
    chars: list[MeshChar],
    role: str,
    page: int,
    block_id: str,
) -> list[Sentence]:
    text = "".join(c.text for c in chars)
    if not text.strip():
        return []
    ends = sentence_end_indices(text)
    spans: list[tuple[int, int]] = []
    start = 0
    for end in ends:
        while start < end and text[start].isspace():
            start += 1
        if start < end:
            spans.append((start, end))
        start = end
    while start < len(text) and text[start].isspace():
        start += 1
    if start < len(text):
        spans.append((start, len(text)))
    if not spans:
        spans = [(0, len(text))]

    index_map = _char_index_map(chars)
    sentences: list[Sentence] = []
    for si, (a, b) in enumerate(spans):
        piece = text[a:b].strip()
        if not piece:
            continue
        mesh = _slice_chars(chars, index_map, a, b)
        sentences.append(
            Sentence(
                text=piece,
                chars=mesh,
                role=role,
                page=page,
                block_id=block_id,
                index=si,
            )
        )
    return sentences


def sentence_end_indices(text: str) -> list[int]:
    ends: list[int] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in CJK_STOP:
            ends.append(i + 1)
        elif ch in LATIN_STOP and not _is_decimal(text, i) and not _is_abbrev(text, i):
            j = i + 1
            while j < n and text[j] in "\"'”’)」』":
                j += 1
            if j >= n:
                ends.append(j)
            elif text[j].isspace() and _looks_like_next_sentence(text, j):
                ends.append(i + 1)
        i += 1
    return ends


def _looks_like_next_sentence(text: str, space_at: int) -> bool:
    k = space_at
    while k < len(text) and text[k].isspace():
        k += 1
    if k >= len(text):
        return True
    ch = text[k]
    return ch.isupper() or is_cjk(ch) or ch in "\"'“‘「『("


def _is_decimal(text: str, i: int) -> bool:
    return i > 0 and text[i - 1].isdigit() and i + 1 < len(text) and text[i + 1].isdigit()


def _is_abbrev(text: str, i: int) -> bool:
    j = i - 1
    while j >= 0 and text[j].isalpha():
        j -= 1
    word = text[j + 1 : i]
    if not word:
        return False
    if len(word) == 1:
        return True
    return word.lower().rstrip(".") in ABBREV


def _char_index_map(chars: list[MeshChar]) -> list[int]:
    mapping: list[int] = []
    for i, item in enumerate(chars):
        mapping.extend([i] * len(item.text))
    return mapping


def _slice_chars(chars: list[MeshChar], index_map: list[int], start: int, end: int) -> list[MeshChar]:
    if start >= end or start >= len(index_map):
        return []
    end = min(end, len(index_map))
    lo = index_map[start]
    hi = index_map[end - 1]
    return chars[lo : hi + 1]


def _line_units(block: Block, block_id: str) -> list[Sentence]:
    out: list[Sentence] = []
    for i, line in enumerate(block.lines):
        text = serialize_line(line)
        if not text:
            continue
        out.append(
            Sentence(
                text=text,
                chars=flatten_line(line),
                role=block.role,
                page=block.page,
                block_id=block_id,
                index=i,
            )
        )
    return out


def _split_list_items(block: Block, chars: list[MeshChar], block_id: str) -> list[Sentence]:
    # One locked unit per list item (already joined across wraps).
    from pdfcopy.serialize import _serialize_list

    items = [part.strip() for part in _serialize_list(block).split("\n") if part.strip()]
    if len(items) <= 1:
        return split_sentences(chars, block.role, block.page, block_id) or [
            Sentence(
                text=serialize_block(block),
                chars=chars,
                role=block.role,
                page=block.page,
                block_id=block_id,
                index=0,
            )
        ]
    text = "".join(c.text for c in chars)
    index_map = _char_index_map(chars)
    cursor = 0
    out: list[Sentence] = []
    for i, item in enumerate(items):
        pos = text.find(item, cursor)
        if pos < 0:
            pos = cursor
            end = min(len(text), pos + len(item))
        else:
            end = pos + len(item)
        out.append(
            Sentence(
                text=item,
                chars=_slice_chars(chars, index_map, pos, end),
                role=block.role,
                page=block.page,
                block_id=block_id,
                index=i,
            )
        )
        cursor = end
    return out


def boxes_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def select_sentences(
    sentences: list[Sentence],
    page: int,
    bbox: tuple[float, float, float, float],
) -> list[Sentence]:
    hit = []
    for sentence in sentences:
        if sentence.page != page:
            continue
        if any(boxes_overlap(ch.bbox, bbox) for ch in sentence.glyphs) or boxes_overlap(
            sentence.bbox, bbox
        ):
            hit.append(sentence)
    return hit


def select_text(
    sentences: list[Sentence],
    page: int,
    bbox: tuple[float, float, float, float],
) -> str:
    hit = select_sentences(sentences, page, bbox)
    if not hit:
        return ""
    parts: list[str] = []
    prev: Sentence | None = None
    for sentence in hit:
        if prev is not None and (
            sentence.block_id != prev.block_id or sentence.role in {"table", "code", "list"}
        ):
            parts.append("\n\n" if sentence.block_id != prev.block_id else "\n")
        elif parts:
            parts.append(" ")
        parts.append(sentence.text)
        prev = sentence
    return "".join(parts).strip()


def sentences_to_overlay(sentences: list[Sentence]) -> list[dict]:
    payload = []
    for sentence in sentences:
        x0, y0, x1, y1 = sentence.bbox
        payload.append(
            {
                "id": f"{sentence.block_id}-s{sentence.index}",
                "blockId": sentence.block_id,
                "role": _overlay_role(sentence.role),
                "page": sentence.page,
                "index": sentence.index,
                "text": sentence.text,
                "bbox": [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)],
                "glyphs": [
                    {
                        "t": ch.text,
                        "bbox": [
                            round(ch.x0, 3),
                            round(ch.y0, 3),
                            round(ch.x1, 3),
                            round(ch.y1, 3),
                        ],
                    }
                    for ch in sentence.chars
                    if ch.kind in {"glyph", "space"}
                ],
            }
        )
    return payload


def _overlay_role(role: str) -> str:
    return {
        "heading": "h",
        "body": "p",
        "list": "l",
        "table": "table",
        "code": "code",
    }.get(role, "p")


def sentences_to_html(sentences: list[Sentence]) -> str:
    """Clipboard HTML: real blocks, not a stack of visual lines."""
    if not sentences:
        return ""
    groups: list[list[Sentence]] = []
    for sentence in sentences:
        if groups and groups[-1][-1].block_id == sentence.block_id:
            groups[-1].append(sentence)
        else:
            groups.append([sentence])
    parts: list[str] = []
    for group in groups:
        role = group[0].role
        texts = [_escape_html(item.text) for item in group]
        if role == "heading":
            parts.append(f"<h1>{texts[0]}</h1>")
        elif role == "list":
            items = "".join(f"<li>{text}</li>" for text in texts)
            parts.append(f"<ul>{items}</ul>")
        elif role == "table":
            rows = "".join(f"<tr><td>{text}</td></tr>" for text in texts)
            parts.append(f"<table>{rows}</table>")
        elif role == "code":
            parts.append("<pre>" + "\n".join(texts) + "</pre>")
        else:
            parts.append(f"<p>{' '.join(texts)}</p>")
    return "".join(parts)


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

"""Turn a bag of glyph coordinates into lines, columns, and blocks."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from statistics import median

from pdfcopy.glyphs import Glyph, PageGlyphs

PAGE_NUMBER_RE = re.compile(
    r"""(?ix)
    ^\s*(
        (page\s*)?\d+\s*(of|/)\s*\d+
        | -\s*\d+\s*-
        | \d+\s*/\s*\d+
        | 第\s*\d+\s*页(\s*共\s*\d+\s*页)?
        | page\s*\d+
    )\s*$
    """
)
ARTIFACT_HINT = re.compile(
    r"(?i)(confidential|internal use|draft|not for distribution|"
    r"内部资料|机密|仅供|第\s*\d+\s*页|page\s+\d+)"
)
BULLET_RE = re.compile(
    r"""(?x)
    ^\s*(
        [\u2022\u2023\u25E6\u2043\u2219•·▪‣◦\-–—*＊]
        |\(?\d+[.)、]
        |\(?[a-zA-Z][.)]
        |（[0-9一二三四五六七八九十]+）
        |[①②③④⑤⑥⑦⑧⑨⑩]
    )\s+
    """
)


@dataclass(slots=True)
class Line:
    glyphs: list[Glyph]
    page: int
    column: int = 0
    role: str = "body"  # body | header | footer | page_number | heading | list | table | code

    @property
    def text_raw(self) -> str:
        return "".join(g.text for g in self.glyphs)

    @property
    def ymid(self) -> float:
        return sum(g.ymid for g in self.glyphs) / len(self.glyphs)

    @property
    def y0(self) -> float:
        return min(g.y0 for g in self.glyphs)

    @property
    def y1(self) -> float:
        return max(g.y1 for g in self.glyphs)

    @property
    def x0(self) -> float:
        return min(g.x0 for g in self.glyphs)

    @property
    def x1(self) -> float:
        return max(g.x1 for g in self.glyphs)

    @property
    def size(self) -> float:
        return median(g.size for g in self.glyphs)

    @property
    def fontname(self) -> str:
        return Counter(g.fontname for g in self.glyphs).most_common(1)[0][0]


@dataclass(slots=True)
class Block:
    lines: list[Line]
    role: str
    page: int
    column: int
    reading_order: int = 0

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (
            min(line.x0 for line in self.lines),
            min(line.y0 for line in self.lines),
            max(line.x1 for line in self.lines),
            max(line.y1 for line in self.lines),
        )


@dataclass(slots=True)
class PageLayout:
    page: PageGlyphs
    lines: list[Line] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)


def cluster_document(pages: list[PageGlyphs]) -> list[PageLayout]:
    layouts = [_cluster_page(page) for page in pages]
    _mark_repeating_artifacts(layouts)
    for layout in layouts:
        _assign_line_roles(layout)
        layout.blocks = _lines_to_blocks(layout)
        _assign_reading_order(layout)
    return layouts


def _cluster_page(page: PageGlyphs) -> PageLayout:
    layout = PageLayout(page=page)
    if not page.glyphs:
        return layout
    usable = [g for g in page.glyphs if g.text != ""]
    if not usable:
        return layout
    lines = _group_lines(usable)
    _assign_columns(lines, page.width)
    layout.lines = lines
    return layout


def _group_lines(glyphs: list[Glyph]) -> list[Line]:
    ordered = sorted(glyphs, key=lambda g: (-g.ymid, g.x0))
    sizes = [g.size for g in ordered]
    typical = median(sizes) if sizes else 12.0
    lines: list[list[Glyph]] = []
    for glyph in ordered:
        placed = False
        for bucket in lines:
            ref = bucket[0]
            tol = max(0.32 * max(glyph.size, ref.size, typical), 2.0)
            if abs(glyph.ymid - ref.ymid) <= tol:
                bucket.append(glyph)
                placed = True
                break
        if not placed:
            lines.append([glyph])
    out: list[Line] = []
    for bucket in lines:
        bucket.sort(key=lambda g: g.x0)
        page_width = max(g.x1 for g in glyphs) + 8
        for piece in _split_column_islands(bucket, page_width):
            out.append(Line(glyphs=piece, page=piece[0].page))
    out.sort(key=lambda line: (-line.ymid, line.x0))
    return out


def _split_column_islands(glyphs: list[Glyph], page_width: float) -> list[list[Glyph]]:
    """Split a shared baseline into two column lines; keep table/form rows intact."""
    if len(glyphs) < 2:
        return [glyphs]
    gaps = [(glyphs[i].x0 - glyphs[i - 1].x1, i) for i in range(1, len(glyphs))]
    gap, idx = max(gaps, key=lambda item: item[0])
    split_x = (glyphs[idx - 1].x1 + glyphs[idx].x0) / 2
    wide = [g for g, _ in gaps if g > 16]
    if len(wide) >= 2:
        return [glyphs]
    in_gutter = page_width * 0.32 < split_x < page_width * 0.68
    if gap > 16 and in_gutter:
        return [glyphs[:idx], glyphs[idx:]]
    return [glyphs]


def _assign_columns(lines: list[Line], page_width: float) -> None:
    rightish = [line for line in lines if line.x0 > page_width * 0.46]
    leftish = [
        line
        for line in lines
        if line.x1 < page_width * 0.55 and (line.x1 - line.x0) < page_width * 0.5
    ]
    if len(rightish) >= 2 and len(leftish) >= 2:
        for line in lines:
            line.column = 1 if line.x0 > page_width * 0.46 else 0
        return
    gutter = _find_gutter(lines, page_width)
    if gutter is None:
        for line in lines:
            line.column = 0
        return
    left_end, right_start = gutter
    for line in lines:
        if line.x1 <= left_end + 2:
            line.column = 0
        elif line.x0 >= right_start - 2:
            line.column = 1
        else:
            line.column = 0


def _find_gutter(lines: list[Line], page_width: float) -> tuple[float, float] | None:
    """Find a vertical gap that many lines do not cross — a two-column gutter."""
    margin = page_width * 0.12
    lo = margin
    hi = page_width - margin
    if hi <= lo:
        return None
    bins = 48
    step = (hi - lo) / bins
    hits = [0] * bins
    candidates = [line for line in lines if (line.x1 - line.x0) < page_width * 0.72]
    if len(candidates) < 6:
        return None
    for line in candidates:
        for i in range(bins):
            x = lo + (i + 0.5) * step
            if line.x0 <= x <= line.x1:
                hits[i] += 1
    # Prefer a low-hit run near the page center.
    center = bins // 2
    best: tuple[int, int, int] | None = None
    i = 0
    while i < bins:
        if hits[i] <= max(1, len(candidates) * 0.08):
            j = i
            while j < bins and hits[j] <= max(1, len(candidates) * 0.08):
                j += 1
            run = j - i
            if run >= 2:
                mid = (i + j) / 2
                score = run * 2 - abs(mid - center) * 0.15
                if best is None or score > best[0]:
                    best = (int(score * 100), i, j)
            i = j
        else:
            i += 1
    if best is None:
        return None
    _, start, end = best
    mid_index = (start + end) / 2
    if abs(mid_index - center) > bins * 0.28:
        return None
    left_end = lo + start * step
    right_start = lo + end * step
    if right_start - left_end < page_width * 0.03:
        return None
    # Must actually separate a useful number of lines.
    left_n = sum(1 for line in candidates if line.x1 <= left_end + 4)
    right_n = sum(1 for line in candidates if line.x0 >= right_start - 4)
    if left_n < 3 or right_n < 3:
        return None
    return left_end, right_start


def _mark_repeating_artifacts(layouts: list[PageLayout]) -> None:
    if len(layouts) < 2:
        return
    signatures: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for layout in layouts:
        for idx, line in enumerate(layout.lines):
            key = _line_signature(line)
            if key:
                signatures[key].append((layout.page.index, idx))
    repeats = {
        key
        for key, locs in signatures.items()
        if len({page for page, _ in locs}) >= 2 and _short_running_header(key)
    }
    for layout in layouts:
        for line in layout.lines:
            if _line_signature(line) not in repeats:
                continue
            y_ratio = line.ymid / max(layout.page.height, 1)
            if (y_ratio < 0.09 or y_ratio > 0.93) and line.size <= 10:
                line.role = "header" if y_ratio > 0.5 else "footer"


def _short_running_header(key: str) -> bool:
    return len(key) <= 80


def _line_signature(line: Line) -> str:
    text = re.sub(r"\s+", " ", "".join(g.text for g in line.glyphs)).strip()
    text = re.sub(r"\d+", "#", text)
    return text.lower()


def _assign_line_roles(layout: PageLayout) -> None:
    if not layout.lines:
        return
    height = layout.page.height
    body_sizes = [line.size for line in layout.lines]
    body_size = median(body_sizes)
    widths = [line.x1 - line.x0 for line in layout.lines]
    typical_width = median(widths) if widths else layout.page.width * 0.7

    for line in layout.lines:
        if line.role in {"header", "footer"}:
            continue
        text = _preview_text(line)
        y_ratio = line.ymid / max(height, 1)
        compact = re.sub(r"\s+", " ", text).strip()
        if PAGE_NUMBER_RE.match(compact):
            line.role = "page_number"
            continue
        in_band = y_ratio > 0.93 or y_ratio < 0.07
        if in_band and ARTIFACT_HINT.search(compact):
            line.role = "header" if y_ratio > 0.5 else "footer"
            continue
        if in_band and line.size < body_size * 0.85 and len(compact) < 48:
            line.role = "header" if y_ratio > 0.5 else "footer"
            continue
        if _is_code_line(line, text):
            line.role = "code"
            continue
        if _is_table_line(line, typical_width):
            line.role = "table"
            continue
        if BULLET_RE.match(text.lstrip()) or compact.startswith(("•", "-", "–", "*")):
            line.role = "list"
            continue
        if line.size >= body_size * 1.16 and (line.x1 - line.x0) < layout.page.width * 0.88:
            line.role = "heading"
            continue


def _preview_text(line: Line) -> str:
    # Lightweight spacing so role regexes can see words.
    parts: list[str] = []
    for i, glyph in enumerate(line.glyphs):
        if i:
            gap = glyph.x0 - line.glyphs[i - 1].x1
            if gap > 0.28 * max(glyph.size, line.glyphs[i - 1].size):
                parts.append(" ")
        parts.append(glyph.text)
    return "".join(parts)


def _is_code_line(line: Line, text: str) -> bool:
    name = line.fontname.lower()
    if any(token in name for token in ("mono", "courier", "consolas", "menlo", "code")):
        return True
    stripped = text.rstrip()
    return bool(re.match(r"^\s{0,8}(def |class |import |from |#include |function )", stripped))


def _is_table_line(line: Line, typical_width: float) -> bool:
    if len(line.glyphs) < 4:
        return False
    gaps = [line.glyphs[i].x0 - line.glyphs[i - 1].x1 for i in range(1, len(line.glyphs))]
    large = [g for g in gaps if g > max(line.size * 1.35, 10)]
    span = line.x1 - line.x0
    if len(large) >= 2 and span > typical_width * 0.5:
        return True
    if len(large) == 1 and large[0] > line.size * 2.2 and span > typical_width * 0.35:
        return True
    return False


def _lines_to_blocks(layout: PageLayout) -> list[Block]:
    body = [line for line in layout.lines if line.role not in {"header", "footer", "page_number"}]
    if not body:
        return []
    # Reading order: full-width headings first in y-order; two-column bands
    # read left column then right column for the same y-range.
    bands = _column_bands(body)
    blocks: list[Block] = []
    for band in bands:
        by_col: dict[int, list[Line]] = defaultdict(list)
        for line in band:
            by_col[line.column].append(line)
        for col in sorted(by_col):
            col_lines = sorted(by_col[col], key=lambda line: -line.ymid)
            blocks.extend(_paragraphs_in_column(col_lines, layout))
    return blocks


def _column_bands(lines: list[Line]) -> list[list[Line]]:
    """Split the page into y-bands so a title above two columns is read first."""
    if not lines:
        return []
    has_right = any(line.column == 1 for line in lines)
    if not has_right:
        return [sorted(lines, key=lambda line: -line.ymid)]

    sorted_lines = sorted(lines, key=lambda line: -line.ymid)
    # A full-width line (column 0 spanning most of the page) breaks bands.
    bands: list[list[Line]] = []
    current: list[Line] = []
    for line in sorted_lines:
        wide = line.column == 0 and _looks_full_width(line, lines)
        if wide and current and any(item.column == 1 for item in current):
            bands.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        bands.append(current)
    return bands


def _looks_full_width(line: Line, peers: list[Line]) -> bool:
    page_width = max(p.x1 for p in peers) - min(p.x0 for p in peers)
    if line.role == "heading":
        return True
    if (line.x1 - line.x0) <= page_width * 0.72:
        return False
    glyphs = line.glyphs
    if len(glyphs) >= 2:
        gap = max(glyphs[i].x0 - glyphs[i - 1].x1 for i in range(1, len(glyphs)))
        if gap > 16:
            return False
    return True


def _paragraphs_in_column(lines: list[Line], layout: PageLayout) -> list[Block]:
    if not lines:
        return []
    heights = [line.y1 - line.y0 for line in lines]
    line_h = median(heights) if heights else 12.0
    page_width = layout.page.width
    body = [line for line in lines if line.role in {"body", "list"}] or lines
    widths = sorted(line.x1 - line.x0 for line in body)
    med = widths[len(widths) // 2]
    typical = [line for line in body if (line.x1 - line.x0) <= med * 1.35] or body
    col_left = min(line.x0 for line in typical)
    col_width = max(med, 1.0)
    col_right = col_left + col_width

    groups: list[list[Line]] = [[lines[0]]]
    for prev, cur in zip(lines, lines[1:]):
        gap = prev.y0 - cur.y1
        if _hard_break(prev, cur, gap, line_h, col_width, col_right, page_width):
            groups.append([cur])
        else:
            groups[-1].append(cur)

    blocks: list[Block] = []
    for group in groups:
        role = group[0].role if all(line.role == group[0].role for line in group) else "body"
        if role == "heading" and len(group) > 1:
            # Only the first oversized line is the heading.
            blocks.append(
                Block(lines=[group[0]], role="heading", page=layout.page.index, column=group[0].column)
            )
            rest = group[1:]
            rest_role = rest[0].role if rest else "body"
            if rest_role == "heading":
                rest_role = "body"
            blocks.append(
                Block(lines=rest, role=rest_role, page=layout.page.index, column=rest[0].column)
            )
        else:
            blocks.append(
                Block(lines=group, role=role, page=layout.page.index, column=group[0].column)
            )
    return blocks


def _hard_break(
    prev: Line,
    cur: Line,
    gap: float,
    line_h: float,
    col_width: float,
    col_right: float,
    page_width: float,
) -> bool:
    if prev.role != cur.role and {prev.role, cur.role} & {"table", "code", "list", "heading"}:
        return True
    if cur.role in {"heading", "table", "code"} and prev.role != cur.role:
        return True
    if gap > line_h * 1.35:
        return True
    if prev.role in {"table", "code"} and cur.role != prev.role:
        return True
    if cur.role in {"table", "code"} and prev.role != cur.role:
        return True
    if prev.role in {"table", "code"} and cur.role == prev.role:
        return False
    if cur.role == "list" and prev.role != "list":
        return True
    if prev.role == "list" and cur.role == "list":
        return False
    prev_fill = (prev.x1 - min(prev.x0, col_right - col_width)) / col_width
    # A short last line usually means the author finished the paragraph.
    # A narrow column also leaves short lines in the middle of a sentence
    # ("this narrow" / "measure."), so keep going when the next line
    # continues mid-sentence.
    if prev_fill < 0.82 and not _ends_with_hyphen(prev) and cur.role != "list":
        if cur.x0 > prev.x0 + prev.size * 0.8:
            return True
        if _continues_sentence(prev, cur):
            return False
        if prev.role != "list":
            return True
    return False


def _continues_sentence(prev: Line, cur: Line) -> bool:
    from pdfcopy.serialize import is_cjk

    left = "".join(glyph.text for glyph in prev.glyphs).rstrip()
    right = "".join(glyph.text for glyph in cur.glyphs).lstrip()
    if not left or not right:
        return False
    end, start = left[-1], right[0]
    if end in "。！？；":
        return False
    if end in ".?!" and (start.isupper() or start in "\"'“‘"):
        return False
    if start.islower():
        return True
    if end in ",;:、，" and not start.isupper():
        return True
    return is_cjk(start) and end not in ".?!"


def _looks_list_wrap(prev: Line, cur: Line) -> bool:
    if prev.role != "list":
        return False
    return cur.x0 >= prev.x0 + prev.size * 0.6 and not BULLET_RE.match(_preview_text(cur).lstrip())


def _ends_with_hyphen(line: Line) -> bool:
    text = "".join(g.text for g in line.glyphs).rstrip()
    return text.endswith(("-", "‐", "‑", "‒", "–", "­"))


def _assign_reading_order(layout: PageLayout) -> None:
    for i, block in enumerate(layout.blocks):
        block.reading_order = i

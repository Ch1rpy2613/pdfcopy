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
# Footnote / endnote markers: "1 ", "1.", "1)", "a)", "i.", "*", "†", "‡"
# Single letters need punctuation: "a " is an English word, not a note marker.
FOOTNOTE_START = re.compile(
    r"""(?x)
    ^(
        \d{1,3}[\s.)\u00a0]
      | [*\u2020\u2021\u00a7\u00b6][\s.]?
      | [a-z][.)]
      | [ivx]{1,5}[.)]
    )
    """
)
BULLET_RE = re.compile(
    r"""(?x)
    ^\s*(
        [\u2022\u2023\u25E6\u2043\u2219•·▪‣◦\-–—*＊]
        |\(?\d{1,2}[.)、]
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
    role: str = "body"  # body | header | footer | page_number | heading | list | table | code | footnote

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
        _mark_footnotes(layout)
        layout.blocks = _lines_to_blocks(layout)
        _assign_reading_order(layout)
    return layouts


def _cluster_page(page: PageGlyphs) -> PageLayout:
    layout = PageLayout(page=page)
    if not page.glyphs:
        return layout
    usable = [g for g in page.glyphs if g.text != ""]
    upright = [g for g in usable if g.upright]
    rotated = [g for g in usable if not g.upright]
    if upright:
        raw = _group_lines_raw(upright)
        # Spread exports draw past the MediaBox; columns live in the ink bbox.
        content_w = max(
            page.width,
            max((g.x1 for g in upright), default=0.0) - min((g.x0 for g in upright), default=0.0),
        )
        gutter = _find_gutter(raw, content_w)
        lines = _split_on_gutter(raw, gutter)
        _assign_columns(lines, content_w, gutter)
    else:
        lines = []
    # Rotated margin text (DOI sidebars, vertical running heads) reads
    # top-down at a fixed x; keep it out of the horizontal body lines.
    lines.extend(_vertical_lines(rotated))
    layout.lines = lines
    return layout


def _vertical_lines(glyphs: list[Glyph]) -> list[Line]:
    if not glyphs:
        return []
    columns: list[list[Glyph]] = []
    for glyph in sorted(glyphs, key=lambda g: -g.ymid):
        for bucket in columns:
            ref = bucket[0]
            tol = max(ref.size * 0.3, 1.5)
            if abs(glyph.xmid - ref.xmid) <= tol:
                bucket.append(glyph)
                break
        else:
            columns.append([glyph])
    out: list[Line] = []
    for bucket in columns:
        bucket.sort(key=lambda g: (-g.y0, g.x0))
        out.append(Line(glyphs=bucket, page=bucket[0].page, role="footer"))
    return out


def _group_lines_raw(glyphs: list[Glyph]) -> list[Line]:
    """Bucket glyphs by baseline. Column islands are split later."""
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
        out.append(Line(glyphs=bucket, page=bucket[0].page))
    out.sort(key=lambda line: (-line.ymid, line.x0))
    return out


def _split_on_gutter(
    lines: list[Line], gutter: tuple[float, float] | None
) -> list[Line]:
    """Cut shared baselines at the column gutter; leave table/form rows whole."""
    if gutter is None:
        return lines
    left_end, right_start = gutter
    out: list[Line] = []
    for line in lines:
        pieces = _cut_at_gutter(line.glyphs, left_end, right_start)
        for piece in pieces:
            out.append(Line(glyphs=piece, page=line.page, role=line.role))
    out.sort(key=lambda line: (-line.ymid, line.x0))
    return out


def _cut_at_gutter(
    glyphs: list[Glyph], left_end: float, right_start: float
) -> list[list[Glyph]]:
    if len(glyphs) < 2:
        return [glyphs]
    # Column islands can end well left of the gutter (ragged right). Accept
    # any dominant mid-page gap near the gutter, not just ones inside it.
    lo = left_end - 90
    hi = right_start + 90
    best: tuple[float, int] | None = None
    for i in range(1, len(glyphs)):
        gap = glyphs[i].x0 - glyphs[i - 1].x1
        mid = (glyphs[i - 1].x1 + glyphs[i].x0) / 2
        if mid < lo or mid > hi:
            continue
        if best is None or gap > best[0]:
            best = (gap, i)
    if best is None:
        return [glyphs]
    gap, idx = best
    other = [glyphs[i].x0 - glyphs[i - 1].x1 for i in range(1, len(glyphs)) if i != idx]
    second = max(other) if other else 0.0
    # A real gutter dwarfs word spaces. Two similar cell walls stay a row.
    if gap < 10 or gap < second * 1.6:
        return [glyphs]
    left, right = glyphs[:idx], glyphs[idx:]
    if len(left) < 2 or len(right) < 2:
        return [glyphs]
    return [left, right]


def _group_lines(glyphs: list[Glyph]) -> list[Line]:
    return _group_lines_raw(glyphs)


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


def _assign_columns(
    lines: list[Line], page_width: float, gutter: tuple[float, float] | None = None
) -> None:
    rightish = [line for line in lines if line.x0 > page_width * 0.46]
    leftish = [
        line
        for line in lines
        if line.x1 < page_width * 0.55 and (line.x1 - line.x0) < page_width * 0.5
    ]
    if gutter is None and len(rightish) >= 2 and len(leftish) >= 2:
        for line in lines:
            line.column = 1 if line.x0 > page_width * 0.46 else 0
        return
    if gutter is None:
        gutter = _find_gutter(lines, page_width)
    if gutter is None:
        for line in lines:
            line.column = 0
        return
    left_end, right_start = gutter
    mid = (left_end + right_start) / 2
    for line in lines:
        if line.x1 <= mid:
            line.column = 0
        elif line.x0 >= mid:
            line.column = 1
        else:
            line.column = 0


def _find_gutter(lines: list[Line], page_width: float) -> tuple[float, float] | None:
    """Find the column gutter between line spans or glued baselines.

    Two complementary signals:
    - wide mid-line gap (a baseline glued across the gutter)
    - a vertical coverage hole (columns already drawn as separate lines)
    """
    if not lines:
        return None
    xs0 = [line.x0 for line in lines]
    xs1 = [line.x1 for line in lines]
    ink0, ink1 = min(xs0), max(xs1)
    span = max(ink1 - ink0, page_width, 1.0)
    voted = _gutter_from_gaps(lines, ink0, ink1, span)
    holed = _gutter_from_holes(lines, ink0, ink1)
    return voted or holed


def _gutter_from_gaps(
    lines: list[Line], ink0: float, ink1: float, span: float
) -> tuple[float, float] | None:
    lo = ink0 + span * 0.18
    hi = ink1 - span * 0.18
    if hi <= lo:
        return None
    votes: Counter[int] = Counter()
    for line in lines:
        glyphs = line.glyphs
        if len(glyphs) < 4:
            continue
        best: tuple[float, float] | None = None
        for i in range(1, len(glyphs)):
            gap = glyphs[i].x0 - glyphs[i - 1].x1
            mid = (glyphs[i - 1].x1 + glyphs[i].x0) / 2
            if gap < 10 or mid < lo or mid > hi:
                continue
            # Form fields have huge label/value holes; column gutters do not.
            if gap > span * 0.12:
                continue
            if best is None or gap > best[0]:
                best = (gap, mid)
        if best is None:
            continue
        gap, mid = best
        others = [
            glyphs[i].x0 - glyphs[i - 1].x1
            for i in range(1, len(glyphs))
            if abs((glyphs[i - 1].x1 + glyphs[i].x0) / 2 - mid) > 1
        ]
        second = max(others) if others else 0.0
        if gap < 14 or gap < second * 1.5:
            continue
        votes[int(mid // 10)] += 1
    return _cluster_votes(votes)


def _gutter_from_holes(
    lines: list[Line], ink0: float, ink1: float
) -> tuple[float, float] | None:
    """A channel where almost no line has ink is a column gutter.

    Only fires when both sides look like real columns (several full-height
    residents), so invoice label/value holes stay whole.
    """
    if ink1 - ink0 < 80:
        return None
    bins = 40
    step = (ink1 - ink0) / bins
    if step <= 0:
        return None
    hits = [0] * bins
    residents = [line for line in lines if line.x1 - line.x0 <= (ink1 - ink0) * 0.88]
    if len(residents) < 6:
        return None
    for line in residents:
        for i in range(bins):
            x = ink0 + (i + 0.5) * step
            if line.x0 <= x <= line.x1:
                hits[i] += 1
    best: tuple[int, int] | None = None
    i = 0
    while i < bins:
        if hits[i] <= 1:
            j = i
            while j < bins and hits[j] <= 1:
                j += 1
            run = j - i
            if run >= 2 and (best is None or run > best[1]):
                best = (i, run)
            i = j
        else:
            i += 1
    if best is None:
        return None
    start, run = best
    mid = ink0 + (start + run / 2) * step
    width = max(step * (run / 2 + 0.5), 12)
    left_end, right_start = mid - width, mid + width
    left_n = sum(1 for line in residents if line.x1 <= mid)
    right_n = sum(1 for line in residents if line.x0 >= mid)
    # A real two-column band has several lines on each side of the channel.
    if left_n < 3 or right_n < 3:
        return None
    return left_end, right_start


def _cluster_votes(votes: Counter[int]) -> tuple[float, float] | None:
    if not votes:
        return None
    positions = [bucket * 10 + 5 for bucket, n in votes.items() for _ in range(n)]
    if not positions:
        return None
    best_mid = max(
        positions,
        key=lambda p: sum(1 for q in positions if abs(q - p) <= 36),
    )
    count = sum(1 for q in positions if abs(q - best_mid) <= 36)
    if count < 2:
        return None
    mid = best_mid
    width = 18
    return mid - width, mid + width


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
            if (y_ratio < 0.10 or y_ratio > 0.90) and line.size <= 10:
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
    content = [
        line
        for line in layout.lines
        if line.role not in {"header", "footer", "page_number"}
    ]
    if not content:
        content = list(layout.lines)
    # Character-weighted mode survives a page of small footnotes under body text.
    body_size = _dominant_size(content) or median(line.size for line in content)
    widths = [line.x1 - line.x0 for line in content]
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
        in_band = y_ratio > 0.90 or y_ratio < 0.07
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
        if _is_bullet_line(text, compact):
            line.role = "list"
            continue
        if (
            line.size >= body_size * 1.16
            and (line.x1 - line.x0) < layout.page.width * 0.88
            and len(compact) <= 100
        ):
            line.role = "heading"
            continue
    _promote_list_wraps(layout)


def _promote_list_wraps(layout: PageLayout) -> None:
    """A line that continues a bullet stays list; otherwise lists shred.

    Track the last list line per column — a shared baseline from the other
    column must not reset the continuation.
    """
    lines = sorted(layout.lines, key=lambda line: (-line.ymid, line.column, line.x0))
    prev_by_col: dict[int, Line] = {}
    for line in lines:
        if line.role == "list":
            prev_by_col[line.column] = line
            continue
        prev = prev_by_col.get(line.column)
        if (
            prev is not None
            and prev.role == "list"
            and line.role == "body"
            and _continues_sentence(prev, line)
        ):
            text = _preview_text(line).lstrip()
            compact = re.sub(r"\s+", " ", text).strip()
            if not _is_bullet_line(text, compact):
                line.role = "list"
                prev_by_col[line.column] = line
                continue
        prev_by_col[line.column] = line


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


def _is_bullet_line(text: str, compact: str) -> bool:
    stripped = text.lstrip()
    if stripped.startswith(("•", "▪", "‣", "◦", "·")):
        return True
    if stripped.startswith(("*", "-")):
        return len(compact) <= 120
    # Em dash bullets are rare; an em dash mid-sentence is common.
    if stripped.startswith(("–", "—")):
        if len(compact) > 90:
            return False
        rest = stripped[1:].lstrip()
        # "– should also be…" continues a sentence; list items usually capitalize.
        return bool(rest) and not rest[0].islower()
    return bool(BULLET_RE.match(stripped))


def _dominant_size(lines: list[Line]) -> float:
    """Body font size: the largest size that carries a real share of the page.

    A character-weighted mode alone loses to a page whose footnotes are longer
    than its body. Taking the largest size with >=25% of the characters keeps
    narrative size over note size and over one-off display faces.
    """
    if not lines:
        return 0.0
    weights: Counter[float] = Counter()
    total = 0
    for line in lines:
        n = max(len(line.glyphs), 1)
        weights[round(line.size, 1)] += n
        total += n
    if not weights:
        return 0.0
    shared = [size for size, w in weights.items() if w >= total * 0.25]
    if shared:
        return max(shared)
    return weights.most_common(1)[0][0]


def _mark_footnotes(layout: PageLayout) -> None:
    """Footnotes sit in the bottom band, smaller than the narrative, often numbered."""
    height = max(layout.page.height, 1)
    candidates = [
        line
        for line in layout.lines
        if line.role not in {"header", "footer", "page_number", "heading", "table", "code"}
    ]
    if len(candidates) < 3:
        return
    body_size = _dominant_size(candidates)
    if body_size <= 0:
        return
    small_cut = body_size * 0.92
    for line in candidates:
        if line.role == "footnote":
            continue
        y_ratio = line.ymid / height
        text = _preview_text(line).strip()
        small = line.size < small_cut
        marked = bool(FOOTNOTE_START.match(text))
        if marked and line.size <= body_size * 1.06 and y_ratio < 0.55:
            line.role = "footnote"
        elif small and y_ratio < 0.36:
            line.role = "footnote"
        elif small and y_ratio < 0.22:
            line.role = "footnote"


def _is_code_line(line: Line, text: str) -> bool:
    name = line.fontname.lower()
    mono = any(token in name for token in ("mono", "courier", "consolas", "menlo", "code"))
    stripped = text.rstrip()
    # Real code starts, not English prose like "from other disciplines…"
    # or "public sphere".
    strong = re.match(
        r"""(?x)^\s{0,8}(
            def\s+\w
          | class\s+\w
          | import\s+\w
          | from\s+[\w.]+\s+import\s+
          | \#include\s
          | function\s+\w
          | (public|private|protected)\s+(static\s+|class\s+|void\s+|final\s+)
          | (const|let|var)\s+\w+\s*=
        )""",
        stripped,
    )
    if strong:
        return True
    if mono and len(stripped) < 200:
        return True
    return False


def _is_table_line(line: Line, typical_width: float) -> bool:
    if len(line.glyphs) < 4:
        return False
    gaps = [line.glyphs[i].x0 - line.glyphs[i - 1].x1 for i in range(1, len(line.glyphs))]
    large = [g for g in gaps if g > max(line.size * 1.35, 10)]
    span = line.x1 - line.x0
    if len(large) >= 2 and span > typical_width * 0.5:
        return True
    if len(large) == 1 and large[0] > line.size * 2.2 and span > typical_width * 0.35:
        # Form row: label | value. Prose with one footnote gap has a long cell.
        cut = gaps.index(large[0])
        left = "".join(g.text for g in line.glyphs[: cut + 1]).strip()
        right = "".join(g.text for g in line.glyphs[cut + 1 :]).strip()
        return len(left) <= 40 and len(right) <= 40
    return False


def _lines_to_blocks(layout: PageLayout) -> list[Block]:
    body = [
        line
        for line in layout.lines
        if line.role not in {"header", "footer", "page_number", "footnote"}
    ]
    notes = [line for line in layout.lines if line.role == "footnote"]
    blocks: list[Block] = []
    blocks.extend(_blocks_from_lines(body, layout))
    blocks.extend(_blocks_from_lines(notes, layout))
    return blocks


def _blocks_from_lines(body: list[Line], layout: PageLayout) -> list[Block]:
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
    if page_width <= 0:
        return False
    if (line.x1 - line.x0) <= page_width * 0.72:
        return False
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
    if all(line.role == "footnote" for line in lines):
        return _split_footnotes(lines, layout)
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
        if role == "footnote":
            blocks.extend(_split_footnotes(group, layout))
            continue
        if role == "heading" and len(group) > 1:
            if all(line.role == "heading" for line in group):
                # Multi-line title wrap — one heading, not heading + body.
                blocks.append(
                    Block(
                        lines=group,
                        role="heading",
                        page=layout.page.index,
                        column=group[0].column,
                    )
                )
                continue
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


def _split_footnotes(lines: list[Line], layout: PageLayout) -> list[Block]:
    """One block per footnote: a new marker starts a new note."""
    if not lines:
        return []
    groups: list[list[Line]] = [[lines[0]]]
    for prev, cur in zip(lines, lines[1:]):
        text = _preview_text(cur).strip()
        gap = prev.y0 - cur.y1
        starts_new = bool(FOOTNOTE_START.match(text)) and gap < (prev.y1 - prev.y0) * 2.2
        if starts_new:
            groups.append([cur])
        else:
            groups[-1].append(cur)
    return [
        Block(lines=group, role="footnote", page=layout.page.index, column=group[0].column)
        for group in groups
    ]


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

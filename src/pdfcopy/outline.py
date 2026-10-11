"""Turn painted text operators into paths so extractors no longer see the old letters."""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

import pikepdf
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont
from pikepdf import Name, Operator
from pikepdf.objects import Object

from pdfcopy.glyphs import _collect_font_map

IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

SHOW_OPS = {b"Tj", b"TJ", b"'", b'"'}
TEXT_STATE_OPS = {
    b"Tc",
    b"Tw",
    b"Tz",
    b"TL",
    b"Tf",
    b"Tr",
    b"Ts",
    b"Td",
    b"TD",
    b"Tm",
    b"T*",
    b"BT",
    b"ET",
}

STANDARD_SUBSTITUTES = {
    "Helvetica": (
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ),
    "Helvetica-Bold": (
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ),
    "Helvetica-Oblique": (
        "/System/Library/Fonts/Supplemental/Arial Italic.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
        "C:/Windows/Fonts/ariali.ttf",
    ),
    "Times-Roman": (
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "/Library/Fonts/Times New Roman.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "C:/Windows/Fonts/times.ttf",
    ),
    "Times-Bold": (
        "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
        "/Library/Fonts/Times New Roman Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "C:/Windows/Fonts/timesbd.ttf",
    ),
    "Times-Italic": (
        "/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf",
        "/Library/Fonts/Times New Roman Italic.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
        "C:/Windows/Fonts/timesi.ttf",
    ),
    "Times-BoldItalic": (
        "/System/Library/Fonts/Supplemental/Times New Roman Bold Italic.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-BoldItalic.ttf",
        "C:/Windows/Fonts/timesbi.ttf",
    ),
    "Courier": (
        "/System/Library/Fonts/Supplemental/Courier New.ttf",
        "/Library/Fonts/Courier New.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "C:/Windows/Fonts/cour.ttf",
    ),
    "Courier-Bold": (
        "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
        "C:/Windows/Fonts/courbd.ttf",
    ),
}


def compose(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, ...]:
    a1, b1, c1, d1, e1, f1 = a
    a2, b2, c2, d2, e2, f2 = b
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def apply_m(m: tuple[float, ...], x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


class _PathPen(BasePen):
    def __init__(self, glyph_set, mapper):
        super().__init__(glyph_set)
        self.mapper = mapper
        self.ops: list = []

    def _moveTo(self, pt):
        x, y = self.mapper(*pt)
        self.ops.append(([x, y], Operator("m")))

    def _lineTo(self, pt):
        x, y = self.mapper(*pt)
        self.ops.append(([x, y], Operator("l")))

    def _curveToOne(self, p1, p2, p3):
        pts = []
        for p in (p1, p2, p3):
            pts.extend(self.mapper(*p))
        self.ops.append((pts, Operator("c")))

    def _closePath(self):
        self.ops.append(([], Operator("h")))


class _FontFace:
    def __init__(self, font: TTFont, cid_to_uni: dict[int, str] | None = None):
        self.tt = font
        self.glyph_set = font.getGlyphSet()
        self.upem = font["head"].unitsPerEm
        self.order = font.getGlyphOrder()
        self.best = font.getBestCmap() or {}
        self.cid_to_uni = cid_to_uni or {}
        hmtx = font["hmtx"].metrics
        self.widths = {name: metrics[0] for name, metrics in hmtx.items()}

    def glyph_name(self, char: str, cid: int | None = None) -> str | None:
        if cid is not None and 0 <= cid < len(self.order):
            return self.order[cid]
        cp = ord(char) if char else -1
        name = self.best.get(cp)
        if name:
            return name
        if char and char in self.glyph_set:
            return char
        return ".notdef" if ".notdef" in self.glyph_set else None

    def width(self, name: str) -> float:
        return float(self.widths.get(name, self.upem * 0.5))

    def draw(self, name: str, mapper) -> list:
        if name not in self.glyph_set:
            return []
        pen = _PathPen(self.glyph_set, mapper)
        self.glyph_set[name].draw(pen)
        if not pen.ops:
            return []
        return pen.ops + [([], Operator("f"))]


@lru_cache(maxsize=16)
def _open_ttc(path: str, index: int) -> bytes:
    return Path(path).read_bytes()


def _load_substitute(base: str) -> _FontFace | None:
    key = base.split("+")[-1]
    paths = STANDARD_SUBSTITUTES.get(key, ())
    for path in paths:
        if not Path(path).exists():
            continue
        try:
            if path.endswith(".ttc"):
                font = TTFont(path, fontNumber=0)
            else:
                font = TTFont(path)
            return _FontFace(font)
        except Exception:
            continue
    return None


def _face_from_pdf_font(font) -> _FontFace | None:
    blob = None
    descriptor = font.get(Name.FontDescriptor)
    if descriptor is None:
        descendants = font.get(Name.DescendantFonts)
        if descendants:
            try:
                child = descendants[0]
                descriptor = child.get(Name.FontDescriptor)
            except Exception:
                descriptor = None
    if descriptor is not None:
        for key in (Name.FontFile2, Name.FontFile3, Name.FontFile):
            if key in descriptor:
                try:
                    blob = descriptor[key].read_bytes()
                    break
                except Exception:
                    blob = None
    if blob:
        try:
            maps: dict[str, dict[int, str]] = {}
            _collect_font_map(font, maps)
            cid = {}
            for table in maps.values():
                cid.update(table)
            return _FontFace(TTFont(io.BytesIO(blob)), cid_to_uni=cid)
        except Exception:
            pass
    base = str(font.get(Name.BaseFont, "")).lstrip("/")
    return _load_substitute(base)


def _as_bytes(value) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("latin-1", errors="replace")
    if isinstance(value, pikepdf.String):
        return bytes(value)
    return bytes(str(value), "latin-1", errors="replace")


def _decode_show(raw: bytes, face: _FontFace | None, identity: bool) -> list[tuple[str, int | None]]:
    out: list[tuple[str, int | None]] = []
    if identity:
        for i in range(0, len(raw) - 1, 2):
            cid = (raw[i] << 8) | raw[i + 1]
            ch = ""
            if face and cid in face.cid_to_uni:
                ch = face.cid_to_uni[cid]
            elif face and face.best:
                # cmap is unicode->name; invert via gid if possible
                if cid < len(face.order):
                    name = face.order[cid]
                    for cp, gname in face.best.items():
                        if gname == name:
                            ch = chr(cp)
                            break
            out.append((ch or "\ufffd", cid))
        return out
    text = raw.decode("cp1252", errors="replace")
    for ch in text:
        out.append((ch, None))
    return out


def _is_identity_font(font) -> bool:
    enc = font.get(Name.Encoding)
    return str(enc) in {"/Identity-H", "/Identity-V"} or Name.DescendantFonts in font


class _TextState:
    def __init__(self):
        self.Tm = IDENTITY
        self.Tlm = IDENTITY
        self.font_name = ""
        self.size = 12.0
        self.char_space = 0.0
        self.word_space = 0.0
        self.scale = 100.0
        self.leading = 0.0
        self.rise = 0.0
        self.face: _FontFace | None = None
        self.identity = False

    def copy(self) -> _TextState:
        other = _TextState()
        other.__dict__.update(self.__dict__)
        return other


def neutralize_page_text(pdf: pikepdf.Pdf, page) -> bool:
    """Replace Tj/TJ with glyph outlines. Returns True if every show op was replaced."""
    try:
        instructions = list(pikepdf.parse_content_stream(page))
    except Exception:
        return False
    fonts = {}
    resources = page.get("/Resources", {})
    raw_fonts = resources.get("/Font", {}) if resources else {}
    for name, font in raw_fonts.items():
        fonts[str(name)] = font

    gs_stack: list[tuple] = []
    ctm = IDENTITY
    text = _TextState()
    in_text = False
    out: list = []
    all_ok = True

    def emit(operands, op):
        out.append((list(operands), op))

    for operands, op in instructions:
        key = bytes(op) if not isinstance(op, bytes) else op
        if key == b"q":
            gs_stack.append((ctm, text.copy()))
            emit(operands, op)
            continue
        if key == b"Q":
            if gs_stack:
                ctm, text = gs_stack.pop()
            emit(operands, op)
            continue
        if key == b"cm" and len(operands) >= 6:
            ctm = compose(ctm, tuple(float(x) for x in operands[:6]))
            emit(operands, op)
            continue
        if key == b"BT":
            in_text = True
            text.Tm = IDENTITY
            text.Tlm = IDENTITY
            continue
        if key == b"ET":
            in_text = False
            continue
        if key == b"Tf" and len(operands) >= 2:
            text.font_name = str(operands[0])
            text.size = float(operands[1])
            font = fonts.get(text.font_name)
            text.face = _face_from_pdf_font(font) if font is not None else _load_substitute(text.font_name)
            text.identity = _is_identity_font(font) if font is not None else False
            continue
        if key == b"Tc" and operands:
            text.char_space = float(operands[0])
            continue
        if key == b"Tw" and operands:
            text.word_space = float(operands[0])
            continue
        if key == b"Tz" and operands:
            text.scale = float(operands[0])
            continue
        if key == b"TL" and operands:
            text.leading = float(operands[0])
            continue
        if key == b"Ts" and operands:
            text.rise = float(operands[0])
            continue
        if key == b"Tr":
            continue
        if key == b"Tm" and len(operands) >= 6:
            text.Tm = text.Tlm = tuple(float(x) for x in operands[:6])
            continue
        if key == b"Td" and len(operands) >= 2:
            tx, ty = float(operands[0]), float(operands[1])
            text.Tlm = compose(text.Tlm, (1, 0, 0, 1, tx, ty))
            text.Tm = text.Tlm
            continue
        if key == b"TD" and len(operands) >= 2:
            tx, ty = float(operands[0]), float(operands[1])
            text.leading = -ty
            text.Tlm = compose(text.Tlm, (1, 0, 0, 1, tx, ty))
            text.Tm = text.Tlm
            continue
        if key == b"T*":
            text.Tlm = compose(text.Tlm, (1, 0, 0, 1, 0, -text.leading))
            text.Tm = text.Tlm
            continue
        if key in SHOW_OPS:
            if key == b"'":
                text.Tlm = compose(text.Tlm, (1, 0, 0, 1, 0, -text.leading))
                text.Tm = text.Tlm
            if key == b'"' and len(operands) >= 3:
                text.word_space = float(operands[0])
                text.char_space = float(operands[1])
                text.Tlm = compose(text.Tlm, (1, 0, 0, 1, 0, -text.leading))
                text.Tm = text.Tlm
                operands = operands[2:]
            ok = _show_to_paths(operands, text, out)
            all_ok = all_ok and ok
            if not ok:
                # Keep the original show so the ink does not vanish.
                emit(operands if key != b'"' else operands, Operator("Tj"))
            continue
        if in_text and key in TEXT_STATE_OPS:
            continue
        emit(operands, op)

    try:
        page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(out))
    except Exception:
        return False
    return all_ok


def _show_to_paths(operands, text: _TextState, out: list) -> bool:
    if text.face is None:
        return False
    items: list = []
    if len(operands) == 1 and not isinstance(operands[0], (list, pikepdf.Array)):
        items.append(operands[0])
    elif operands and isinstance(operands[0], (list, pikepdf.Array)):
        items.extend(list(operands[0]))
    else:
        items.extend(operands)

    for item in items:
        if isinstance(item, (int, float)) or type(item).__name__ == "Decimal":
            adj = float(item)
            dx = -adj / 1000.0 * text.size * (text.scale / 100.0)
            text.Tm = compose(text.Tm, (1, 0, 0, 1, dx, 0))
            continue
        raw = _as_bytes(item)
        pairs = _decode_show(raw, text.face, text.identity)
        for ch, cid in pairs:
            name = text.face.glyph_name(ch, cid)
            if not name:
                return False

            def mapper(x, y, _text=text, _face=text.face):
                s = _text.size / _face.upem
                hs = _text.scale / 100.0
                return apply_m(_text.Tm, x * s * hs, y * s + _text.rise)

            out.extend(text.face.draw(name, mapper))
            adv = text.face.width(name) / text.face.upem * text.size * (text.scale / 100.0)
            adv += text.char_space
            if ch == " ":
                adv += text.word_space
            text.Tm = compose(text.Tm, (1, 0, 0, 1, adv, 0))
    return True


# Silence unused Object import if type checkers want it.
_ = Object

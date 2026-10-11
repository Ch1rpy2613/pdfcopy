"""Pull glyphs, boxes, and font identity out of a PDF page."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Iterator

import pikepdf
from fontTools.ttLib import TTFont
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTChar, LTFigure, LTPage
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pdfminer.pdftypes import resolve1
from pikepdf import Name

CID_TEXT = re.compile(r"^\(cid:(\d+)\)$")
# Spacing look-alikes of combining marks: publishers decompose ñ into
# "n" + a tilde drawn as its own glyph.
SPACING_MARKS = {
    "\u02dc": "\u0303",  # small tilde -> combining tilde
    "\u02c7": "\u030c",  # caron
    "\u02c6": "\u0302",  # modifier circumflex
    "\u02d8": "\u0306",  # breve
    "\u02d9": "\u0307",  # dot above
    "\u02da": "\u030a",  # ring above
    "\u02dd": "\u030b",  # double acute
    "\u00a8": "\u0308",  # diaeresis
    "\u00af": "\u0304",  # macron
    "\u00b4": "\u0301",  # acute
    "\u02cb": "\u0300",  # grave
    "\u02ca": "\u0301",
}
DINGBATS = {
    108: "•",
    117: "•",
    118: "•",
    119: "•",
    127: "•",
    183: "•",
}

UNI_NAME = re.compile(
    r"^(?:uni|UNI)([0-9A-Fa-f]{4,6})$|^u([0-9A-Fa-f]{4,6})$|^cid(\d+)$"
)


@dataclass(slots=True)
class Glyph:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    fontname: str
    size: float
    page: int
    cid: int | None = None
    glyph_name: str | None = None
    upright: bool = True

    @property
    def width(self) -> float:
        return max(self.x1 - self.x0, 0.01)

    @property
    def height(self) -> float:
        return max(self.y1 - self.y0, 0.01)

    @property
    def xmid(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def ymid(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass(slots=True)
class PageGlyphs:
    index: int
    width: float
    height: float
    glyphs: list[Glyph] = field(default_factory=list)
    has_text_layer: bool = True


def _walk(obj) -> Iterator[LTChar]:
    if isinstance(obj, LTChar):
        yield obj
        return
    children = getattr(obj, "_objs", None)
    if not children:
        return
    for child in children:
        if isinstance(child, LTFigure):
            yield from _walk(child)
        else:
            yield from _walk(child)


def _char_text(char: LTChar, font_maps: dict[str, dict[int, str]]) -> str:
    raw = char.get_text()
    fontname = str(getattr(char, "fontname", "") or "")
    cid_match = CID_TEXT.match(raw or "")
    if cid_match:
        cid = int(cid_match.group(1))
        mapped = _lookup_cid(font_maps, fontname, cid)
        if mapped:
            return mapped
        return DINGBATS.get(cid, raw)
    if raw and raw != "\x00" and not _looks_like_replacement(raw):
        if "dingbat" in fontname.lower() or "zapf" in fontname.lower():
            if len(raw) == 1 and ord(raw) in DINGBATS:
                return DINGBATS[ord(raw)]
            if raw == "l":
                return "•"
        return raw
    name = getattr(char, "fontname", "") or ""
    decoded = decode_glyph_name(getattr(char, "cidname", None) or "")
    if decoded:
        return decoded
    spec = getattr(char, "_text", None)
    if spec and spec not in {"\x00", ""}:
        return spec
    from_name = decode_glyph_name(name.rsplit("+", 1)[-1])
    return from_name or raw or ""


def _lookup_cid(font_maps: dict[str, dict[int, str]], fontname: str, cid: int) -> str:
    if not font_maps:
        return ""
    short = fontname.split("+")[-1]
    for key in (fontname, short):
        if key in font_maps and cid in font_maps[key]:
            return font_maps[key][cid]
    # Last resort: unique hit across embedded fonts.
    hits = {table[cid] for table in font_maps.values() if cid in table}
    if len(hits) == 1:
        return hits.pop()
    return ""


def _looks_like_replacement(text: str) -> bool:
    return bool(text) and all(ch in "\ufffd\x00?" for ch in text)


def decode_glyph_name(name: str) -> str:
    if not name:
        return ""
    name = name.split("+")[-1]
    match = UNI_NAME.match(name)
    if match:
        hex_part = match.group(1) or match.group(2)
        if hex_part:
            try:
                return chr(int(hex_part, 16))
            except ValueError:
                return ""
    adobe = {
        "space": " ",
        "hyphen": "-",
        "minus": "-",
        "period": ".",
        "comma": ",",
        "colon": ":",
        "semicolon": ";",
        "slash": "/",
        "backslash": "\\",
        "parenleft": "(",
        "parenright": ")",
        "bracketleft": "[",
        "bracketright": "]",
        "quoteleft": "‘",
        "quoteright": "’",
        "quotedblleft": "“",
        "quotedblright": "”",
        "endash": "–",
        "emdash": "—",
        "ellipsis": "…",
        "bullet": "•",
        "dagger": "†",
        "fi": "fi",
        "fl": "fl",
        "ff": "ff",
        "ffi": "ffi",
        "ffl": "ffl",
        # TeX symbol names that publishers compose symbols from
        "circlecopyrt": "©",
        "copyright": "©",
        "openbullet": "◦",
        "circlemultiply": "⊗",
        "circleplus": "⊕",
    }
    if name in adobe:
        return adobe[name]
    try:
        from fontTools.agl import toUnicode

        mapped = toUnicode(name)
    except Exception:
        return ""
    return mapped if mapped and mapped != name else ""


def _open_source(source: str | Path | BinaryIO) -> io.BytesIO:
    if hasattr(source, "read"):
        data = source.read()
        if hasattr(source, "seek"):
            try:
                source.seek(0)
            except OSError:
                pass
        return io.BytesIO(data)
    return io.BytesIO(Path(source).read_bytes())


def _merge_spacing_marks(glyphs: list[Glyph]) -> list[Glyph]:
    """Fold accent glyphs onto the letter they geometrically sit on.

    TeX-era publishers decompose ñ into a base letter plus a tilde drawn as
    its own glyph, and the accent may precede or follow its target in the
    content stream — only the x-overlap says who carries it.
    """
    import unicodedata

    marks = [i for i, g in enumerate(glyphs) if g.text in SPACING_MARKS]
    if not marks:
        return list(glyphs)
    base = list(glyphs)
    dropped: set[int] = set()
    for mi in marks:
        m = base[mi]
        best, best_score = -1, 0.0
        for j, g in enumerate(base):
            if j == mi or j in dropped:
                continue
            if g.page != m.page or not g.text or not g.text[-1].isalnum():
                continue
            overlap = min(g.x1, m.x1) - max(g.x0, m.x0)
            if overlap <= 0:
                continue
            score = overlap - abs(g.xmid - m.xmid) * 0.01
            if score > best_score:
                best, best_score = j, score
        if best < 0:
            continue
        prev = base[best]
        combined = unicodedata.normalize("NFC", prev.text + SPACING_MARKS[m.text])
        if combined == prev.text + m.text:
            continue
        base[best] = Glyph(
            text=combined,
            x0=prev.x0,
            y0=min(prev.y0, m.y0),
            x1=max(prev.x1, m.x1),
            y1=max(prev.y1, m.y1),
            fontname=prev.fontname,
            size=max(prev.size, m.size),
            page=prev.page,
        )
        dropped.add(mi)
    return [g for i, g in enumerate(base) if i not in dropped]


def extract_glyphs(source: str | Path | BinaryIO) -> list[PageGlyphs]:
    """Return every painted character on every page, in PDF user space."""
    buf = _open_source(source)
    raw = buf.getvalue() if isinstance(buf, io.BytesIO) else None
    font_maps = load_font_cid_maps(raw if raw is not None else buf)
    try:
        if raw is not None:
            buf.seek(0)
        pages: list[PageGlyphs] = []
        for index, page in enumerate(extract_pages(buf)):
            assert isinstance(page, LTPage)
            glyphs: list[Glyph] = []
            for char in _walk(page):
                text = _char_text(char, font_maps)
                if text is None:
                    continue
                glyphs.append(
                    Glyph(
                        text=text,
                        x0=float(char.x0),
                        y0=float(char.y0),
                        x1=float(char.x1),
                        y1=float(char.y1),
                        fontname=str(getattr(char, "fontname", "") or ""),
                        size=float(getattr(char, "size", 0) or (char.y1 - char.y0)),
                        page=index,
                        upright=bool(getattr(char, "upright", True)),
                    )
                )
            glyphs = _merge_spacing_marks(glyphs)
            pages.append(
                PageGlyphs(
                    index=index,
                    width=float(page.width),
                    height=float(page.height),
                    glyphs=glyphs,
                    has_text_layer=bool(glyphs),
                )
            )
        if not pages:
            # Still emit an empty page so callers can report "scanned".
            buf.seek(0)
            pages = _empty_pages(buf)
        return pages
    finally:
        buf.close()


def _empty_pages(buf: BinaryIO) -> list[PageGlyphs]:
    try:
        parser = PDFParser(buf)
        doc = PDFDocument(parser)
        out: list[PageGlyphs] = []
        for index, page in enumerate(PDFPage.create_pages(doc)):
            box = resolve1(page.mediabox) if page.mediabox else [0, 0, 612, 792]
            out.append(
                PageGlyphs(
                    index=index,
                    width=float(box[2] - box[0]),
                    height=float(box[3] - box[1]),
                    glyphs=[],
                    has_text_layer=False,
                )
            )
        return out or [PageGlyphs(index=0, width=612, height=792, has_text_layer=False)]
    except Exception:
        return [PageGlyphs(index=0, width=612, height=792, has_text_layer=False)]


def load_font_cid_maps(source: bytes | BinaryIO | None) -> dict[str, dict[int, str]]:
    if source is None:
        return {}
    data = source if isinstance(source, bytes) else source.read()
    if hasattr(source, "seek"):
        try:
            source.seek(0)
        except OSError:
            pass
    maps: dict[str, dict[int, str]] = {}
    try:
        pdf = pikepdf.open(io.BytesIO(data))
    except Exception:
        return maps
    try:
        seen: set = set()
        for font in _iter_page_fonts(pdf.Root.get(Name.Pages, None)):
            # Direct (non-indirect) font dicts all share objgen (0, 0);
            # key those by BaseFont instead of skipping them as duplicates.
            gen = font.objgen
            key = gen if gen != (0, 0) else ("direct", str(font.get(Name.BaseFont, "")))
            if key in seen:
                continue
            seen.add(key)
            _collect_font_map(font, maps)
    finally:
        pdf.close()
    return maps


def _iter_page_fonts(node):
    """Every /Font on the page tree — resources are inherited, so walk it all."""
    if node is None:
        return
    resources = node.get(Name.Resources, None)
    if resources is not None:
        fonts = resources.get(Name.Font, None)
        if fonts is not None:
            try:
                for _, font in fonts.items():
                    yield font
            except Exception:
                pass
    kids = node.get(Name.Kids, None)
    if kids is not None:
        for kid in kids:
            yield from _iter_page_fonts(kid)


def _collect_font_map(font, maps: dict[str, dict[int, str]]) -> None:
    names = []
    base = font.get(Name.BaseFont, None)
    if base is not None:
        names.append(str(base).lstrip("/"))
        names.append(str(base).lstrip("/").split("+")[-1])
    blob = _font_file_bytes(font)
    descendants = font.get(Name.DescendantFonts, None)
    if descendants:
        try:
            child = descendants[0]
            blob = blob or _font_file_bytes(child)
            child_base = child.get(Name.BaseFont, None)
            if child_base is not None:
                names.append(str(child_base).lstrip("/"))
                names.append(str(child_base).lstrip("/").split("+")[-1])
        except Exception:
            pass
    table: dict[int, str] = {}
    # /Differences maps character codes to glyph names even when ToUnicode
    # is missing — publisher symbol fonts (© circles, bullets) decode here.
    decorative_hint = any("circ" in n.lower() for n in names) if names else False
    for code, gname in _differences_map(font).items():
        text = decode_glyph_name(gname) or _decorative_glyph(gname, decorative_hint)
        if text:
            table[code] = text
    if blob:
        base_hint = names[-1] if names else ""
        for extra in (ttf_cmap_table(blob), cff_encoding_map(blob, base_hint)):
            if extra:
                for code, text in extra.items():
                    table.setdefault(code, text)
    if not table:
        return
    for name in names:
        merged = dict(maps.get(name, {}))
        merged.update(table)
        maps[name] = merged


def _decorative_glyph(name: str, decorative_hint: bool) -> str:
    """TeX circle fonts name their glyphs a1..aN with no AGL meaning."""
    if decorative_hint and re.fullmatch(r"a\d+", name):
        return "○"
    return ""


def cff_encoding_map(font_bytes: bytes, base_hint: str = "") -> dict[int, str]:
    """Decode a bare Type1C font's built-in encoding (code -> unicode)."""
    try:
        from fontTools.cffLib import CFFFontSet

        cff = CFFFontSet()
        cff.decompile(io.BytesIO(font_bytes), None)
        top = cff[cff.fontNames[0]]
        enc = getattr(top, "Encoding", None)
        if enc is None:
            return {}
        if isinstance(enc, list):
            # index is the character code; the entry is the glyph name
            pairs = list(enumerate(enc))
        else:
            codes = getattr(enc, "codes", None) or []
            glyph_names = getattr(enc, "names", None) or []
            pairs = zip(codes, glyph_names)
        mapping: dict[int, str] = {}
        decorative = "circ" in base_hint.lower()
        for code, name in pairs:
            if not name or name == ".notdef":
                continue
            text = decode_glyph_name(name) or _decorative_glyph(name, decorative)
            if text:
                mapping[code] = text
        return mapping
    except Exception:
        return {}


def _differences_map(font) -> dict[int, str]:
    """Character code -> glyph NAME from /Encoding /Differences."""
    encoding = font.get(Name.Encoding, None)
    if encoding is None or not hasattr(encoding, "get"):
        return {}
    differences = encoding.get(Name.Differences, None)
    if differences is None:
        return {}
    mapping: dict[int, str] = {}
    code = 0
    try:
        items = list(differences)
    except Exception:
        return {}
    for item in items:
        try:
            code = int(item)
            continue
        except (TypeError, ValueError):
            pass
        mapping[code] = str(item).lstrip("/")
        code += 1
    return mapping


def _font_file_bytes(font) -> bytes | None:
    descriptor = font.get(Name.FontDescriptor, None)
    if descriptor is None:
        return None
    for key in (Name.FontFile2, Name.FontFile3, Name.FontFile):
        if key in descriptor:
            try:
                return descriptor[key].read_bytes()
            except Exception:
                return None
    return None


def ttf_cmap_table(font_bytes: bytes) -> dict[int, str]:
    """Best-effort cmap from an embedded TrueType/OpenType font."""
    mapping: dict[int, str] = {}
    try:
        font = TTFont(io.BytesIO(font_bytes))
    except Exception:
        return mapping
    try:
        cmap = font.getBestCmap() or {}
        # cmap is unicode -> glyph name; invert via glyph order when possible
        glyph_order = font.getGlyphOrder()
        name_to_gid = {name: i for i, name in enumerate(glyph_order)}
        for cp, name in cmap.items():
            gid = name_to_gid.get(name)
            if gid is not None:
                mapping[gid] = chr(cp)
            mapping[cp] = chr(cp)
    except Exception:
        return mapping
    finally:
        try:
            font.close()
        except Exception:
            pass
    return mapping



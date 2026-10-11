"""Copy mesh: original ink stays; each sentence is a glyph-aligned invisible lock."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import pikepdf
from fontTools.ttLib import TTFont
from pikepdf import Array, Dictionary, Name

from pdfcopy.cluster import PageLayout
from pdfcopy.extract import ExtractResult
from pdfcopy.mesh import MeshChar, Sentence, sentences_from_block
from pdfcopy.serialize import serialize_block

LAYER_FONT = "/PDFCopy"
CJK_FONT_CANDIDATES = [
    # macOS
    ("/System/Library/Fonts/PingFang.ttc", 0),
    ("/System/Library/Fonts/STHeiti Light.ttc", 0),
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
    # Linux (Noto CJK / WQY)
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
    ("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc", 0),
    ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", 0),
    # Windows
    ("C:/Windows/Fonts/msyh.ttc", 0),
    ("C:/Windows/Fonts/simhei.ttf", 0),
    ("/System/Library/Fonts/Supplemental/Times New Roman.ttf", 0),
    ("/Library/Fonts/Arial.ttf", 0),
]
LATIN_FONT_CANDIDATES = [
    ("/System/Library/Fonts/Supplemental/Times New Roman.ttf", 0),
    ("/Library/Fonts/Arial.ttf", 0),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", 0),
    # Linux
    ("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
    # Windows
    ("C:/Windows/Fonts/times.ttf", 0),
    ("C:/Windows/Fonts/arial.ttf", 0),
]


@dataclass(slots=True)
class LayerMark:
    page_index: int
    mcid: int
    role: str
    text: str


def apply_copy_layer(
    pdf: pikepdf.Pdf,
    result: ExtractResult,
    outline: bool = False,
) -> list[LayerMark]:
    """Write a glyph-aligned copy mesh. Original ink stays unless outline=True."""
    if result.scanned:
        return []
    used = _collect_layer_text(result)
    if not used.strip():
        return []
    encoder = _embed_layer_font(pdf, used)
    marks: list[LayerMark] = []
    for page, layout in zip(pdf.pages, result.layouts):
        if outline:
            from pdfcopy.outline import neutralize_page_text

            neutralize_page_text(pdf, page)
        marks.extend(_append_layer(pdf, page, layout, encoder))
        _ensure_font_resource(page, encoder.font_obj)
    return marks


def _collect_layer_text(result: ExtractResult) -> str:
    parts = [" "]
    for layout in result.layouts:
        for block in layout.blocks:
            parts.append(serialize_block(block))
            for sent in sentences_from_block(block):
                parts.append(sent.text)
                parts.append("".join(char.text for char in sent.chars))
    return "".join(parts)


class _Encoder:
    def __init__(
        self,
        font_obj,
        uni_to_gid: dict[int, int],
        simple: bool,
        gid_widths: dict[int, int] | None = None,
    ):
        self.font_obj = font_obj
        self.uni_to_gid = uni_to_gid
        self.simple = simple
        self.gid_widths = gid_widths or {}

    def string_width(self, text: str, size: float) -> float:
        total = 0.0
        for ch in text:
            gid = self.uni_to_gid.get(32 if ch == "\n" else ord(ch), 0)
            total += self.gid_widths.get(gid, 500)
        return total * size / 1000.0

    def pdf_string(self, text: str) -> str:
        if self.simple:
            escaped = (
                text.replace("\\", "\\\\")
                .replace("(", "\\(")
                .replace(")", "\\)")
                .replace("\r", " ")
                .replace("\n", "\\n")
            )
            # WinAnsi-ish: keep latin-1 where possible.
            try:
                escaped.encode("latin-1")
                return f"({escaped})"
            except UnicodeEncodeError:
                pass
        out = bytearray()
        for ch in text:
            if ch == "\n":
                gid = self.uni_to_gid.get(ord(" "), 0)
            else:
                gid = self.uni_to_gid.get(ord(ch), 0)
            out.append((gid >> 8) & 0xFF)
            out.append(gid & 0xFF)
        return "<" + out.hex() + ">"


def _find_face_font(text: str) -> tuple[str, int]:
    need_cjk = any(ord(ch) > 0x24F for ch in text)
    if need_cjk:
        for path, index in CJK_FONT_CANDIDATES:
            if "Times" in path or "Arial" in path:
                continue
            if Path(path).exists():
                return path, index
    for path, index in LATIN_FONT_CANDIDATES:
        if Path(path).exists():
            return path, index
    for path, index in CJK_FONT_CANDIDATES:
        if Path(path).exists():
            return path, index
    raise FileNotFoundError("No TrueType font available for the copy layer")


def _embed_layer_font(pdf: pikepdf.Pdf, text: str) -> _Encoder:
    path, index = _find_face_font(text)
    raw = Path(path).read_bytes()
    font = TTFont(io.BytesIO(raw) if not path.endswith(".ttc") else path, fontNumber=index)
    chars = {ch for ch in text if ch != "\n"} | {" "}
    from fontTools import subset

    options = subset.Options(
        layout_features=["*"],
        name_IDs=[0, 1, 2, 3, 4, 5, 6],
        notdef_outline=True,
        recommended_glyphs=True,
    )
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text="".join(sorted(chars)))
    subsetter.subset(font)
    buf = io.BytesIO()
    font.save(buf)
    font_bytes = buf.getvalue()
    subset_font = TTFont(io.BytesIO(font_bytes))
    order = subset_font.getGlyphOrder()
    cmap = subset_font.getBestCmap() or {}
    uni_to_gid = {}
    name_to_gid = {name: i for i, name in enumerate(order)}
    for cp, name in cmap.items():
        if name in name_to_gid:
            uni_to_gid[cp] = name_to_gid[name]
    uni_to_gid.setdefault(32, name_to_gid.get("space", 0))

    widths = []
    upem = subset_font["head"].unitsPerEm
    hmtx = subset_font["hmtx"].metrics
    for name in order:
        w = hmtx.get(name, (upem // 2, 0))[0]
        widths.append(int(w * 1000 / upem))

    font_file = pdf.make_stream(font_bytes)
    font_file[Name.Length1] = len(font_bytes)

    descriptor = Dictionary()
    descriptor[Name.Type] = Name.FontDescriptor
    descriptor[Name.FontName] = Name.PDFCopy
    descriptor[Name.Flags] = 4
    descriptor[Name.ItalicAngle] = 0
    descriptor[Name.Ascent] = 800
    descriptor[Name.Descent] = -200
    descriptor[Name.CapHeight] = 700
    descriptor[Name.StemV] = 80
    descriptor[Name.FontBBox] = Array([-200, -200, 1200, 1000])
    descriptor[Name.FontFile2] = font_file

    cid_info = Dictionary()
    cid_info[Name.Registry] = "Adobe"
    cid_info[Name.Ordering] = "Identity"
    cid_info[Name.Supplement] = 0

    cid_font = Dictionary()
    cid_font[Name.Type] = Name.Font
    cid_font[Name.Subtype] = Name.CIDFontType2
    cid_font[Name.BaseFont] = Name.PDFCopy
    cid_font[Name.CIDSystemInfo] = cid_info
    cid_font[Name.FontDescriptor] = descriptor
    cid_font[Name.DW] = 500
    cid_font[Name.W] = Array([0, Array(widths)])
    cid_font[Name.CIDToGIDMap] = Name.Identity

    from pdfcopy.writeback import _build_tounicode_cmap

    mapping = {gid: chr(cp) for cp, gid in uni_to_gid.items() if gid}
    mapping[0] = " "
    tounicode = pdf.make_stream(_build_tounicode_cmap(mapping).encode("ascii", errors="ignore"))
    type0 = Dictionary()
    type0[Name.Type] = Name.Font
    type0[Name.Subtype] = Name.Type0
    type0[Name.BaseFont] = Name.PDFCopy
    type0[Name.Encoding] = Name("/Identity-H")
    type0[Name.DescendantFonts] = Array([cid_font])
    type0[Name.ToUnicode] = tounicode
    font_obj = pdf.make_indirect(type0)
    gid_widths = {i: w for i, w in enumerate(widths)}
    return _Encoder(font_obj, uni_to_gid, simple=False, gid_widths=gid_widths)


def _ensure_font_resource(page, font_obj) -> None:
    if Name.Resources not in page:
        page.Resources = Dictionary()
    resources = page.Resources
    if Name.Font not in resources:
        resources.Font = Dictionary()
    resources.Font[Name.PDFCopy] = font_obj


def _pdf_actual_text(text: str) -> str:
    """UTF-16BE hex string so ActualText can carry real Unicode."""
    return "<feff" + text.encode("utf-16-be").hex() + ">"


def _glyph_ops(encoder: _Encoder, char: MeshChar) -> list[str]:
    shown = char.text.replace("\n", " ")
    if not shown:
        return []
    width = max(char.x1 - char.x0, 0.35)
    size = max(char.size, 4.0)
    run_width = encoder.string_width(shown, size)
    tz = 100.0
    if run_width > 0.01:
        tz = max(1.0, min(20000.0, 100.0 * width / run_width))
    return [
        "BT",
        "3 Tr",
        f"{LAYER_FONT} {size:.3f} Tf",
        f"{tz:.2f} Tz",
        f"1 0 0 1 {char.x0:.3f} {char.y0:.3f} Tm",
        f"{encoder.pdf_string(shown)} Tj",
        "ET",
    ]


def _sentence_ops(encoder: _Encoder, sent: Sentence) -> list[str]:
    ops = [
        f"/Span << /ActualText {_pdf_actual_text(sent.text)} >> BDC",
    ]
    for char in sent.chars:
        ops.extend(_glyph_ops(encoder, char))
    ops.append("EMC")
    return ops


def _append_layer(pdf: pikepdf.Pdf, page, layout: PageLayout, encoder: _Encoder) -> list[LayerMark]:
    if not layout.blocks:
        return []
    chunks = ["q"]
    marks: list[LayerMark] = []
    mcid = 0
    for block in layout.blocks:
        if block.role == "header":
            continue
        text = serialize_block(block)
        if not text:
            continue
        role = {
            "heading": "H1",
            "list": "L",
            "table": "Table",
            "code": "Code",
        }.get(block.role, "P")
        chunks.append(
            f"/{role} << /MCID {mcid} /ActualText {_pdf_actual_text(text)} >> BDC"
        )
        sentences = sentences_from_block(block)
        if sentences:
            for sent in sentences:
                chunks.extend(_sentence_ops(encoder, sent))
        else:
            for line in block.lines:
                for glyph in line.glyphs:
                    if not glyph.text:
                        continue
                    chunks.extend(
                        _glyph_ops(
                            encoder,
                            MeshChar(
                                text=glyph.text,
                                x0=glyph.x0,
                                y0=glyph.y0,
                                x1=glyph.x1,
                                y1=glyph.y1,
                                size=glyph.size,
                                page=glyph.page,
                                kind="glyph",
                            ),
                        )
                    )
        chunks.append("EMC")
        marks.append(
            LayerMark(page_index=layout.page.index, mcid=mcid, role=role, text=text)
        )
        mcid += 1
    chunks.append("Q")
    layer = "\n".join(chunks) + "\n"

    original = b""
    contents = page.get("/Contents")
    if contents is not None:
        if isinstance(contents, pikepdf.Array):
            for item in contents:
                original += item.read_bytes()
        else:
            original += contents.read_bytes()
    wrapped = b"/Artifact BMC\n" + original + b"\nEMC\n" + layer.encode("latin-1", errors="replace")
    page.Contents = pdf.make_stream(wrapped)
    page[Name.StructParents] = layout.page.index
    return marks


def write_marked_structure(pdf: pikepdf.Pdf, result: ExtractResult, marks: list[LayerMark]) -> None:
    """Bind the structure tree to copy-layer MCIDs."""
    if not marks:
        return
    by_page: dict[int, list[LayerMark]] = {}
    for mark in marks:
        by_page.setdefault(mark.page_index, []).append(mark)

    document_kids = Array()
    parent_nums = Array()
    for page_index, page in enumerate(pdf.pages):
        page_marks = by_page.get(page_index, [])
        kids = Array()
        for mark in page_marks:
            elem = Dictionary()
            elem[Name.Type] = Name.StructElem
            elem[Name.S] = Name("/" + mark.role)
            try:
                elem[Name.Pg] = page.obj
            except Exception:
                pass
            elem[Name.K] = mark.mcid
            if mark.text:
                try:
                    elem[Name.Alt] = mark.text[:4096]
                except Exception:
                    pass
            kids.append(elem)
            document_kids.append(elem)
        if kids:
            parent_nums.append(page_index)
            parent_nums.append(kids)
            page[Name.StructParents] = page_index

    if not document_kids:
        return
    document = Dictionary()
    document[Name.Type] = Name.StructElem
    document[Name.S] = Name.Document
    document[Name.K] = document_kids
    parent_tree = Dictionary()
    parent_tree[Name.Nums] = parent_nums
    root = Dictionary()
    root[Name.Type] = Name.StructTreeRoot
    root[Name.K] = document
    root[Name.ParentTree] = parent_tree
    pdf.Root.StructTreeRoot = root

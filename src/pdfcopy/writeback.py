"""Write structure, ToUnicode, and the pdfcopy overlay back into a standard PDF."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import BinaryIO

import pikepdf
from pikepdf import Dictionary, Name, Array

from pdfcopy.extract import ExtractResult, extract
from pdfcopy.glyphs import decode_glyph_name, ttf_cmap_table

Source = str | Path | BinaryIO


def fix_pdf(
    source: Source,
    dest: str | Path | BinaryIO,
    metadata_only: bool = False,
    outline: bool = False,
    result: ExtractResult | None = None,
) -> ExtractResult:
    """Write a glyph-aligned copy mesh plus ToUnicode, tags, and overlay.

    Original ink stays (Artifact-wrapped). Pass outline=True to convert the
    painted letters to paths for readers that ignore Artifact. Pass
    metadata_only=True to keep the old text operators and only stamp
    overlay / ToUnicode. Pass result= to reuse an extraction you already
    ran instead of parsing the document twice.
    """
    if result is None:
        result = extract(source)
    data = _read_all(source)
    pdf = pikepdf.Pdf.open(io.BytesIO(data))
    try:
        _repair_tounicode(pdf)
        marks = []
        if not metadata_only and not result.scanned:
            from pdfcopy.copylayer import apply_copy_layer, write_marked_structure

            marks = apply_copy_layer(pdf, result, outline=outline)
            try:
                write_marked_structure(pdf, result, marks)
            except Exception:
                _write_structure_tree(pdf, result)
        else:
            _write_structure_tree(pdf, result)
        _write_overlay(pdf, result.overlay)
        _stamp_info(pdf)
        if hasattr(dest, "write"):
            pdf.save(dest)
        else:
            pdf.save(str(dest))
    finally:
        pdf.close()
    return result


def _read_all(source: Source) -> bytes:
    if hasattr(source, "read"):
        data = source.read()
        if hasattr(source, "seek"):
            try:
                source.seek(0)
            except OSError:
                pass
        return data
    return Path(source).read_bytes()


def _stamp_info(pdf: pikepdf.Pdf) -> None:
    info = pdf.docinfo
    info["/Producer"] = "pdfcopy 0.1.0"
    try:
        pdf.Root.MarkInfo = Dictionary({"/Marked": True})
    except Exception:
        pdf.Root[Name.MarkInfo] = Dictionary({Name.Marked: True})
    if Name.Lang not in pdf.Root:
        pdf.Root.Lang = "en"


def _write_overlay(pdf: pikepdf.Pdf, overlay: dict) -> None:
    payload = json.dumps(overlay, ensure_ascii=False, indent=2).encode("utf-8")
    stream = pdf.make_stream(payload)
    stream[Name.Type] = Name.EmbeddedFile

    try:
        pdf.attachments["pdfcopy-overlay.json"] = payload
    except Exception:
        pass

    private = Dictionary()
    private[Name.Version] = "1.0"
    private[Name.Spec] = "pdfcopy-overlay"
    private[Name.LastModified] = overlay.get("created", "")
    private[Name.Data] = stream

    holder = Dictionary()
    holder[Name.Private] = private
    if Name.PieceInfo not in pdf.Root:
        pdf.Root.PieceInfo = Dictionary()
    pdf.Root.PieceInfo[Name.PDFCopy] = holder


def _write_structure_tree(pdf: pikepdf.Pdf, result: ExtractResult) -> None:
    """Attach a lightweight structure tree. MCIDs are omitted when we cannot
    rewrite the content stream safely; the overlay still carries reading order.
    """
    document_kids = Array()
    for layout in result.layouts:
        for block in layout.blocks:
            role_name = {
                "heading": "H1",
                "list": "L",
                "table": "Table",
                "code": "Code",
            }.get(block.role, "P")
            elem = Dictionary()
            elem[Name.Type] = Name.StructElem
            elem[Name.S] = Name("/" + role_name)
            elem[Name.Lang] = "zh" if _mostly_cjk("".join(g.text for g in block.lines[0].glyphs)) else "en"
            alt = _block_text(block)
            if alt:
                try:
                    elem[Name.Alt] = alt[:4096]
                except Exception:
                    pass
            document_kids.append(elem)
        for line in layout.lines:
            if line.role in {"header", "footer", "page_number"}:
                art = Dictionary()
                art[Name.Type] = Name.StructElem
                art[Name.S] = Name.P
                art[Name.Alt] = "artifact"
                document_kids.append(art)

    if not document_kids:
        return

    document = Dictionary()
    document[Name.Type] = Name.StructElem
    document[Name.S] = Name.Document
    document[Name.K] = document_kids

    root = Dictionary()
    root[Name.Type] = Name.StructTreeRoot
    root[Name.K] = document
    pdf.Root.StructTreeRoot = root


def _block_text(block) -> str:
    from pdfcopy.serialize import serialize_block

    return serialize_block(block)


def _mostly_cjk(text: str) -> bool:
    from pdfcopy.serialize import is_cjk

    chars = [ch for ch in text if not ch.isspace()]
    if not chars:
        return False
    return sum(1 for ch in chars if is_cjk(ch)) / len(chars) > 0.4


def _repair_tounicode(pdf: pikepdf.Pdf) -> None:
    seen: set[int] = set()
    for page in pdf.pages:
        resources = page.get("/Resources", {})
        fonts = resources.get("/Font", {}) if resources else {}
        for _, font in list(fonts.items()):
            try:
                font_obj = font
                if hasattr(font, "obj"):
                    font_obj = font
                objnum = int(font_obj.objgen[0]) if hasattr(font_obj, "objgen") else id(font_obj)
                if objnum in seen:
                    continue
                seen.add(objnum)
                _repair_one_font(pdf, font_obj)
            except Exception:
                continue


def _repair_one_font(pdf: pikepdf.Pdf, font) -> None:
    if Name.ToUnicode in font and font.ToUnicode:
        # Keep a working CMap. Still try to fill if it is an empty stream.
        try:
            data = font.ToUnicode.read_bytes()
            if data and (b"beginbfchar" in data or b"beginbfrange" in data):
                return
        except Exception:
            pass

    mapping = _infer_code_to_unicode(font)
    if not mapping:
        return
    cmap = _build_tounicode_cmap(mapping)
    font.ToUnicode = pdf.make_stream(cmap.encode("ascii", errors="ignore"))


def _infer_code_to_unicode(font) -> dict[int, str]:
    mapping: dict[int, str] = {}

    encoding = font.get(Name.Encoding, None)
    differences: list = []
    first = int(font.get(Name.FirstChar, 0) or 0)
    last = int(font.get(Name.LastChar, 255) or 255)

    if encoding is not None and isinstance(encoding, pikepdf.Dictionary):
        diffs = encoding.get(Name.Differences, [])
        differences = list(diffs)
        mapping.update(_differences_to_map(differences))

    if Name.BaseFont in font:
        # Standard 14: WinAnsi / MacRoman already copy fine.
        pass

    descendant = font.get(Name.DescendantFonts, None)
    font_file = _embedded_font_bytes(font)
    if font_file:
        cmap = ttf_cmap_table(font_file)
        for code, ch in cmap.items():
            mapping.setdefault(code, ch)

    # Type3 CharProcs keyed by uniXXXX
    char_procs = font.get(Name.CharProcs, None)
    if char_procs is not None:
        names = []
        try:
            names = list(char_procs.keys())
        except Exception:
            names = []
        # Pair with encoding differences when we have them.
        if differences:
            mapping.update(_differences_to_map(differences))
        else:
            for i, name in enumerate(names):
                decoded = decode_glyph_name(str(name).lstrip("/"))
                if decoded:
                    mapping[first + i] = decoded

    return {code: ch for code, ch in mapping.items() if ch}


def _embedded_font_bytes(font) -> bytes | None:
    descriptor = font.get(Name.FontDescriptor, None)
    if descriptor is None:
        descendants = font.get(Name.DescendantFonts, None)
        if descendants:
            try:
                first = descendants[0]
                descriptor = first.get(Name.FontDescriptor, None)
            except Exception:
                descriptor = None
    if descriptor is None:
        return None
    for key in (Name.FontFile2, Name.FontFile3, Name.FontFile):
        if key in descriptor:
            try:
                return descriptor[key].read_bytes()
            except Exception:
                return None
    return None


def _differences_to_map(differences: list) -> dict[int, str]:
    mapping: dict[int, str] = {}
    code = 0
    for item in differences:
        if isinstance(item, int) or (hasattr(item, "real") and not isinstance(item, Name)):
            try:
                code = int(item)
                continue
            except Exception:
                pass
        name = str(item).lstrip("/")
        decoded = decode_glyph_name(name)
        if not decoded and len(name) == 1:
            decoded = name
        if decoded:
            mapping[code] = decoded
        code += 1
    return mapping


def _build_tounicode_cmap(mapping: dict[int, str]) -> str:
    wide = any(code > 255 for code in mapping)
    src_width = 4 if wide else 2
    pairs = []
    for code, text in sorted(mapping.items()):
        if not text:
            continue
        dest = "".join(f"{ord(ch):04X}" for ch in text)
        pairs.append(f"<{code:0{src_width}X}> <{dest}>")
    chunks: list[str] = []
    for i in range(0, len(pairs), 100):
        block = pairs[i : i + 100]
        chunks.append(f"{len(block)} beginbfchar\n" + "\n".join(block) + "\nendbfchar\n")
    body = "".join(chunks)
    space = "<0000> <FFFF>" if wide else "<00> <FF>"
    return (
        "/CIDInit /ProcSet findresource begin\n"
        "12 dict begin\n"
        "begincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /Adobe-Identity-UCS def\n"
        "/CMapType 2 def\n"
        f"1 begincodespacerange\n{space}\nendcodespacerange\n"
        f"{body}"
        "endcmap\n"
        "CMapName currentdict /CMap defineresource pop\n"
        "end\n"
        "end\n"
    )



#!/usr/bin/env python3
"""Build 20 fixtures that reproduce how real PDFs break on copy."""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

import pikepdf
from pikepdf import Dictionary, Name

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "corpus" / "fixtures"
EXPECTED = ROOT / "corpus" / "expected"
PAGE_W, PAGE_H = letter

CJK_CANDIDATES = [
    ("/System/Library/Fonts/PingFang.ttc", 0),
    ("/System/Library/Fonts/STHeiti Light.ttc", 0),
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
    ("/System/Library/Fonts/Supplemental/Songti.ttc", 0),
    ("/Library/Fonts/Arial Unicode.ttf", 0),
]


def find_cjk_font() -> str:
    for path, index in CJK_CANDIDATES:
        if not Path(path).exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont("CJK", path, subfontIndex=index))
            return "CJK"
        except Exception:
            continue
    raise SystemExit("No CJK TrueType font found. Install PingFang or Noto Sans CJK.")


def wrap_latin(text: str, font: str, size: float, width: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if pdfmetrics.stringWidth(trial, font, size) <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def wrap_cjk(text: str, font: str, size: float, width: float) -> list[str]:
    tokens: list[str] = []
    buf = ""
    for ch in text:
        if "A" <= ch <= "Z" or "a" <= ch <= "z" or ch.isdigit():
            buf += ch
            continue
        if buf:
            tokens.append(buf)
            buf = ""
        tokens.append(ch)
    if buf:
        tokens.append(buf)
    lines: list[str] = []
    current = ""
    for token in tokens:
        trial = current + token
        if pdfmetrics.stringWidth(trial, font, size) <= width or not current:
            current = trial
        else:
            lines.append(current)
            current = token
    if current:
        lines.append(current)
    return lines


def draw_paragraph(
    c: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    font: str = "Times-Roman",
    size: float = 11,
    leading: float = 15,
    cjk: bool = False,
    first_indent: float = 0,
) -> float:
    lines = wrap_cjk(text, font, size, width - first_indent) if cjk else wrap_latin(
        text, font, size, width - first_indent
    )
    c.setFont(font, size)
    for i, line in enumerate(lines):
        indent = first_indent if i == 0 else 0
        c.drawString(x + indent, y, line)
        y -= leading
    return y


def header_footer(c: canvas.Canvas, page: int, total: int, running: str | None = None) -> None:
    if running:
        c.setFont("Times-Italic", 8)
        c.drawString(72, PAGE_H - 36, running)
    c.setFont("Times-Roman", 8)
    c.drawRightString(PAGE_W - 72, 28, f"Page {page} of {total}")


def save_expected(name: str, text: str) -> None:
    EXPECTED.mkdir(parents=True, exist_ok=True)
    (EXPECTED / f"{name}.txt").write_text(text.strip() + "\n", encoding="utf-8")


def new_canvas(name: str) -> canvas.Canvas:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    return canvas.Canvas(str(FIXTURES / f"{name}.pdf"), pagesize=letter)


def fixture_01() -> dict:
    name = "01-invoice-header-footer"
    c = new_canvas(name)
    c.setFont("Times-Bold", 16)
    c.drawString(72, 720, "ACME INDUSTRIAL CO., LTD.")
    c.setFont("Times-Roman", 10)
    c.drawString(72, 702, "Invoice INV-2048")
    c.drawString(72, 688, "Bill to: Harbor Robotics, 18 Pier Street")
    c.setFont("Times-Bold", 10)
    c.drawString(72, 650, "Description")
    c.drawString(320, 650, "Qty")
    c.drawString(380, 650, "Unit")
    c.drawString(460, 650, "Amount")
    c.setFont("Times-Roman", 10)
    rows = [
        ("Linear actuator kit", "2", "180.00", "360.00"),
        ("Hall sensor board", "4", "22.50", "90.00"),
        ("Assembly labor", "1", "75.00", "75.00"),
    ]
    y = 632
    for desc, qty, unit, amount in rows:
        c.drawString(72, y, desc)
        c.drawString(320, y, qty)
        c.drawString(380, y, unit)
        c.drawString(460, y, amount)
        y -= 16
    note = (
        "Payment is due within thirty days of the invoice date. "
        "Please include the invoice number on the wire transfer memo so the "
        "accounts desk can match the remittance without a follow-up call."
    )
    y = draw_paragraph(c, note, 72, y - 12, 468, size=10, leading=13)
    header_footer(c, 1, 1)
    c.showPage()
    c.save()
    expected = (
        "ACME INDUSTRIAL CO., LTD.\n\n"
        "Invoice INV-2048\n\n"
        "Bill to: Harbor Robotics, 18 Pier Street\n\n"
        "Description Qty Unit Amount\n"
        "Linear actuator kit 2 180.00 360.00\n"
        "Hall sensor board 4 22.50 90.00\n"
        "Assembly labor 1 75.00 75.00\n\n"
        + note
    )
    save_expected(name, expected)
    return {
        "file": f"{name}.pdf",
        "title": "Invoice with page footer",
        "tags": ["invoice", "header-footer"],
    }


def fixture_02() -> dict:
    name = "02-two-column-article"
    title = "Why a printed page still refuses to copy"
    lede = (
        "A PDF looks like a document and behaves like a stack of ink commands. "
        "That gap is why a sentence fractures the moment it hits a chat box."
    )
    left = (
        "Thirty years ago the goal was simple: the same page had to look identical "
        "on every printer in the building. Coordinates were the honest answer. "
        "Paragraphs were someone else's problem."
    )
    right = (
        "Readers still reconstruct words by measuring gaps. Soft wraps become "
        "newlines, running heads sneak into the clipboard, and a two-column "
        "essay is read as if both gutters were one sentence."
    )
    c = new_canvas(name)
    c.setFont("Times-Bold", 18)
    c.drawString(72, 720, title)
    y = draw_paragraph(c, lede, 72, 690, 468, size=11, leading=15)
    col_w = 220
    draw_paragraph(c, left, 72, y - 18, col_w, size=10, leading=13)
    draw_paragraph(c, right, 320, y - 18, col_w, size=10, leading=13)
    header_footer(c, 1, 1)
    c.showPage()
    c.save()
    save_expected(name, f"{title}\n\n{lede}\n\n{left}\n\n{right}")
    return {
        "file": f"{name}.pdf",
        "title": "Two-column article",
        "tags": ["two-column", "article"],
    }


def fixture_03() -> dict:
    name = "03-contract-wrapped"
    p1 = (
        "This Services Agreement is entered into as of 8 October 2026 by and between "
        "Northwind Analytics LLC and the client named on the signature page. "
        "The parties agree that deliverables described in any statement of work "
        "are accepted only after written confirmation from the client."
    )
    p2 = (
        "Neither party shall be liable for incidental or consequential damages "
        "arising from delay, including lost profits, even if advised of the "
        "possibility of such damages, except in cases of willful misconduct."
    )
    c = new_canvas(name)
    c.setFont("Times-Bold", 14)
    c.drawString(72, 720, "Services Agreement")
    y = draw_paragraph(c, p1, 72, 690, 468, size=11, leading=15, first_indent=18)
    y = draw_paragraph(c, p2, 72, y - 14, 468, size=11, leading=15, first_indent=18)
    header_footer(c, 1, 1)
    c.showPage()
    c.save()
    save_expected(name, f"Services Agreement\n\n{p1}\n\n{p2}")
    return {"file": f"{name}.pdf", "title": "Wrapped contract", "tags": ["contract"]}


def fixture_04(cjk: str) -> dict:
    name = "04-chinese-article"
    title = "为什么复制出来总是断行"
    p1 = (
        "PDF在设计时只记住每个字落在哪一个坐标上，并不记录哪几个字同属一段。"
        "阅读器复制时只能按行距和字距去猜，猜错了就会把一句完整的话切成几截。"
    )
    p2 = (
        "页眉页脚和页码也只是画在纸边的墨，文件并不知道它们不该进剪贴板。"
        "所以一段正文中间会突然冒出第3页共12页这样的杂质。"
    )
    c = new_canvas(name)
    c.setFont(cjk, 16)
    c.drawString(72, 720, title)
    y = draw_paragraph(c, p1, 72, 688, 468, font=cjk, size=12, leading=18, cjk=True)
    draw_paragraph(c, p2, 72, y - 14, 468, font=cjk, size=12, leading=18, cjk=True)
    header_footer(c, 1, 1)
    c.showPage()
    c.save()
    save_expected(name, f"{title}\n\n{p1}\n\n{p2}")
    return {"file": f"{name}.pdf", "title": "Chinese article", "tags": ["cjk"]}


def fixture_05(cjk: str) -> dict:
    """Chinese PDF whose ToUnicode CMap is stripped after generation."""
    name = "05-chinese-no-tounicode"
    sentence = "合同编号甲字二零二六零四八号已归档。"
    c = new_canvas(name)
    c.setFont(cjk, 14)
    c.drawString(72, 720, sentence)
    header_footer(c, 1, 1)
    c.showPage()
    c.save()
    path = FIXTURES / f"{name}.pdf"
    _strip_tounicode(path)
    save_expected(name, sentence)
    return {
        "file": f"{name}.pdf",
        "title": "Chinese without ToUnicode",
        "tags": ["cjk", "tounicode"],
    }


def _parse_tounicode(data: bytes) -> dict[int, str]:
    text = data.decode("latin-1", errors="ignore")
    mapping: dict[int, str] = {}
    for match in re.finditer(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", text):
        src = int(match.group(1), 16)
        dest = match.group(2)
        chars = "".join(chr(int(dest[i : i + 4], 16)) for i in range(0, len(dest), 4) if len(dest[i : i + 4]) == 4)
        if chars:
            mapping[src] = chars
    return mapping


def _add_unicode_cmap(font_bytes: bytes, code_to_uni: dict[int, str]) -> bytes:
    from fontTools.ttLib import TTFont
    from fontTools.ttLib.tables._c_m_a_p import cmap_classes

    font = TTFont(io.BytesIO(font_bytes))
    order = font.getGlyphOrder()
    uni_to_name: dict[int, str] = {}
    for code, uni in code_to_uni.items():
        if code < len(order):
            name = order[code]
        elif 1 <= code < len(order):
            name = order[code]
        else:
            continue
        uni_to_name[ord(uni[0])] = name
    sub = cmap_classes[4](4)
    sub.platformID = 3
    sub.platEncID = 1
    sub.language = 0
    sub.cmap = uni_to_name
    font["cmap"].tables.append(sub)
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


def _strip_tounicode(path: Path) -> None:
    """Remove /ToUnicode but keep a Unicode cmap inside the embedded TTF.

    That is the real-world 'draws fine, Preview copy is garbage' case:
    the PDF dictionary has no CMap, while glyph identity is still recoverable.
    """
    pdf = pikepdf.open(path, allow_overwriting_input=True)
    for page in pdf.pages:
        fonts = page.get("/Resources", {}).get("/Font", {})
        for _, font in fonts.items():
            if Name.ToUnicode in font:
                mapping = _parse_tounicode(font.ToUnicode.read_bytes())
                desc = font.get(Name.FontDescriptor)
                if desc is not None and Name.FontFile2 in desc and mapping:
                    blob = desc.FontFile2.read_bytes()
                    desc.FontFile2 = pdf.make_stream(_add_unicode_cmap(blob, mapping))
                del font[Name.ToUnicode]
            descendants = font.get(Name.DescendantFonts, None)
            if descendants:
                try:
                    child = descendants[0]
                    if Name.ToUnicode in child:
                        del child[Name.ToUnicode]
                except Exception:
                    pass
    pdf.save(path)
    pdf.close()


def fixture_06() -> dict:
    name = "06-scanned-receipt"
    image = Image.new("RGB", (800, 1000), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/Library/Fonts/Arial.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
    draw.text((40, 40), "CORNER CAFE", fill="black", font=font)
    draw.text((40, 90), "Oat latte  4.50", fill="black", font=font)
    draw.text((40, 130), "Tax        0.36", fill="black", font=font)
    raster = FIXTURES / "_scan.png"
    FIXTURES.mkdir(parents=True, exist_ok=True)
    image.save(raster)
    c = new_canvas(name)
    c.drawImage(str(raster), 72, 220, width=468, height=520)
    c.showPage()
    c.save()
    raster.unlink(missing_ok=True)
    save_expected(name, "# pdfcopy:scanned\n")
    return {
        "file": f"{name}.pdf",
        "title": "Scanned receipt (no text layer)",
        "tags": ["scanned"],
    }


def fixture_07() -> dict:
    name = "07-hyphenation"
    c = new_canvas(name)
    c.setFont("Times-Roman", 12)
    # Force a visual hyphen break the way a compositor would.
    c.drawString(72, 720, "The laboratory published an inter-")
    c.drawString(72, 704, "national survey of clipboard failures.")
    header_footer(c, 1, 1)
    c.showPage()
    c.save()
    save_expected(
        name, "The laboratory published an international survey of clipboard failures."
    )
    return {"file": f"{name}.pdf", "title": "Hyphenated line break", "tags": ["hyphen"]}


def fixture_08(cjk: str) -> dict:
    name = "08-mixed-cjk-latin"
    text = "我们使用 PDF 格式保存合同，再把摘要发到 Slack。"
    c = new_canvas(name)
    draw_paragraph(c, text, 72, 720, 300, font=cjk, size=12, leading=18, cjk=True)
    header_footer(c, 1, 1)
    c.showPage()
    c.save()
    save_expected(name, text)
    return {"file": f"{name}.pdf", "title": "Mixed Chinese and Latin", "tags": ["cjk", "mixed"]}


def fixture_09() -> dict:
    name = "09-academic-abstract"
    title = "Measuring Soft Line Breaks in Page Description Languages"
    authors = "L. Chen and M. Alvarez"
    abstract = (
        "We measure how often visual line wraps are written to the clipboard as "
        "hard breaks, and show that a geometric pass recovers paragraph text "
        "on untagged office exports."
    )
    intro = (
        "Page description languages record ink, not discourse. "
        "Tagged PDF exists, yet printer drivers still flatten structure."
    )
    method = (
        "Each glyph is clustered by baseline, then columns are split at the "
        "widest vertical gutter. Headers that repeat across pages are dropped."
    )
    c = new_canvas(name)
    c.setFont("Times-Bold", 14)
    c.drawCentredString(PAGE_W / 2, 720, title)
    c.setFont("Times-Italic", 11)
    c.drawCentredString(PAGE_W / 2, 700, authors)
    c.setFont("Times-Bold", 11)
    c.drawString(72, 670, "Abstract")
    y = draw_paragraph(c, abstract, 72, 652, 468, size=10, leading=13)
    draw_paragraph(c, intro, 72, y - 20, 220, size=10, leading=13)
    draw_paragraph(c, method, 320, y - 20, 220, size=10, leading=13)
    header_footer(c, 1, 1)
    c.showPage()
    c.save()
    save_expected(name, f"{title}\n\n{authors}\n\nAbstract\n\n{abstract}\n\n{intro}\n\n{method}")
    return {"file": f"{name}.pdf", "title": "Academic first page", "tags": ["two-column", "paper"]}


def fixture_10() -> dict:
    name = "10-letter"
    body = (
        "Thank you for sending the revised drawings. We can start fabrication "
        "on Monday if the hole schedule arrives before Thursday noon."
    )
    closing = "Sincerely,\nNora Blake"
    c = new_canvas(name)
    c.setFont("Times-Roman", 11)
    c.drawString(72, 720, "October 8, 2026")
    c.drawString(72, 690, "Dear Alex,")
    y = draw_paragraph(c, body, 72, 660, 468, size=11, leading=15)
    for i, line in enumerate(closing.split("\n")):
        c.drawString(72, y - 20 - i * 16, line)
    header_footer(c, 1, 1)
    c.showPage()
    c.save()
    save_expected(name, f"October 8, 2026\n\nDear Alex,\n\n{body}\n\nSincerely,\n\nNora Blake")
    return {"file": f"{name}.pdf", "title": "Business letter", "tags": ["letter"]}


def fixture_11() -> dict:
    name = "11-form-like-invoice"
    c = new_canvas(name)
    c.setFont("Times-Bold", 13)
    c.drawString(72, 720, "Field ticket")
    c.setFont("Times-Roman", 11)
    rows = [
        ("Job", "Pier 4 retrofit"),
        ("Foreman", "S. Patel"),
        ("Hours", "6.5"),
        ("Materials", "Marine epoxy, two kits"),
    ]
    y = 680
    for label, value in rows:
        c.drawString(72, y, f"{label}")
        c.drawString(220, y, value)
        y -= 20
    header_footer(c, 1, 1)
    c.showPage()
    c.save()
    lines = ["Field ticket", ""] + [f"{a} {b}" for a, b in rows]
    save_expected(name, "\n".join(lines))
    return {"file": f"{name}.pdf", "title": "Key-value field ticket", "tags": ["form"]}


def fixture_12() -> dict:
    name = "12-three-page-report"
    running = "Quarterly Operations Review — Internal Use Only"
    paras = [
        "Shop floor throughput rose six percent after the night shift adopted the new kitting cart.",
        "Scrap from the punch press is still concentrated on Friday afternoons when temporary operators cover breaks.",
        "The spare-parts cage will move next to cell three in November so walk time drops below two minutes.",
    ]
    c = new_canvas(name)
    for i, para in enumerate(paras, start=1):
        header_footer(c, i, 3, running=running)
        c.setFont("Times-Bold", 13)
        c.drawString(72, 720, f"Section {i}")
        draw_paragraph(c, para, 72, 690, 468, size=11, leading=15)
        c.showPage()
    c.save()
    expected = "\n\n".join(f"Section {i}\n\n{p}" for i, p in enumerate(paras, start=1))
    save_expected(name, expected)
    return {
        "file": f"{name}.pdf",
        "title": "Three-page running header",
        "tags": ["header-footer", "multipage"],
    }


def fixture_13() -> dict:
    name = "13-narrow-column"
    first = "The first sentence stays on the opening lines of this narrow measure."
    middle = (
        "The middle sentence is the one a reviewer actually wants, even when it wraps "
        "twice in the column."
    )
    last = "The last sentence is just the closing remark after that quote."
    text = f"{first} {middle} {last}"
    c = new_canvas(name)
    draw_paragraph(c, text, 72, 720, 160, size=11, leading=14)
    header_footer(c, 1, 1)
    c.showPage()
    c.save()
    save_expected(name, text)
    return {"file": f"{name}.pdf", "title": "Narrow column wraps", "tags": ["reflow"]}


def fixture_14() -> dict:
    name = "14-bullet-list"
    intro = "Bring the following items to the dock:"
    items = [
        "Two spare hydraulic hoses cut to two meters",
        "A calibrated torque wrench with the 19 millimeter socket",
        "The signed confined-space permit",
    ]
    c = new_canvas(name)
    y = draw_paragraph(c, intro, 72, 720, 468, size=11, leading=15)
    c.setFont("Times-Roman", 11)
    y -= 8
    for item in items:
        c.drawString(72, y, "-")
        y = draw_paragraph(c, item, 88, y, 452, size=11, leading=14)
        y -= 6
    header_footer(c, 1, 1)
    c.showPage()
    c.save()
    expected = intro + "\n\n" + "\n".join(f"- {item}" for item in items)
    save_expected(name, expected)
    return {"file": f"{name}.pdf", "title": "Bullet list", "tags": ["list"]}


def fixture_15() -> dict:
    name = "15-quote-block"
    lead = "Warnock's note from 1991 still reads like a product brief:"
    quote = (
        "A file should look the same on every machine in the building, "
        "regardless of which fonts that machine happens to have installed."
    )
    after = "That sentence explains why paragraphs were never first-class data."
    c = new_canvas(name)
    y = draw_paragraph(c, lead, 72, 720, 468, size=11, leading=15)
    y = draw_paragraph(c, quote, 108, y - 12, 400, size=11, leading=15)
    draw_paragraph(c, after, 72, y - 12, 468, size=11, leading=15)
    header_footer(c, 1, 1)
    c.showPage()
    c.save()
    save_expected(name, f"{lead}\n\n{quote}\n\n{after}")
    return {"file": f"{name}.pdf", "title": "Indented quotation", "tags": ["quote"]}


def fixture_16(cjk: str) -> dict:
    name = "16-chinese-contract"
    title = "技术服务合同"
    p1 = (
        "甲方委托乙方对现有档案库中的扫描件进行结构化处理，交付物为带有阅读顺序的标准PDF文件。"
        "乙方不得将客户文件上传至第三方模型服务。"
    )
    p2 = (
        "若因字体子集缺少ToUnicode对照表导致复制乱码，乙方应在五个工作日内完成修补并写回映射。"
    )
    c = new_canvas(name)
    c.setFont(cjk, 16)
    c.drawString(72, 720, title)
    y = draw_paragraph(c, p1, 72, 688, 468, font=cjk, size=12, leading=18, cjk=True)
    draw_paragraph(c, p2, 72, y - 12, 468, font=cjk, size=12, leading=18, cjk=True)
    header_footer(c, 1, 1)
    c.showPage()
    c.save()
    save_expected(name, f"{title}\n\n{p1}\n\n{p2}")
    return {"file": f"{name}.pdf", "title": "Chinese contract", "tags": ["cjk", "contract"]}


def fixture_17(cjk: str) -> dict:
    name = "17-page-numbers-cn"
    p1 = "第一页只讲验收标准，不写付款条款。"
    p2 = "第二页补充违约金计算方式和送达地址。"
    c = new_canvas(name)
    c.setFont(cjk, 12)
    c.drawString(72, 720, p1)
    c.setFont(cjk, 9)
    c.drawCentredString(PAGE_W / 2, 28, "第 1 页 共 2 页")
    c.showPage()
    c.setFont(cjk, 12)
    c.drawString(72, 720, p2)
    c.setFont(cjk, 9)
    c.drawCentredString(PAGE_W / 2, 28, "第 2 页 共 2 页")
    c.showPage()
    c.save()
    save_expected(name, f"{p1}\n\n{p2}")
    return {
        "file": f"{name}.pdf",
        "title": "Chinese page numbers",
        "tags": ["cjk", "header-footer"],
    }


def fixture_18() -> dict:
    """Words positioned with Td offsets and no space characters."""
    name = "18-fake-spaces"
    words = ["The", "quick", "brown", "fox", "jumps", "over", "the", "lazy", "dog."]
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(PAGE_W, PAGE_H))
    font = Dictionary(
        Type=Name.Font,
        Subtype=Name.Type1,
        BaseFont=Name.Helvetica,
    )
    page.Resources = Dictionary(Font=Dictionary(F1=font))
    x = 72.0
    parts: list[str] = []
    for word in words:
        parts.append(f"BT /F1 12 Tf {x:.2f} 720 Td ({word}) Tj ET")
        x += pdfmetrics.stringWidth(word, "Helvetica", 12) + 10
    page.Contents = pdf.make_stream(" ".join(parts).encode("latin-1"))
    FIXTURES.mkdir(parents=True, exist_ok=True)
    pdf.save(FIXTURES / f"{name}.pdf")
    pdf.close()
    save_expected(name, "The quick brown fox jumps over the lazy dog.")
    return {"file": f"{name}.pdf", "title": "Fake spaces (no 0x20)", "tags": ["spaces"]}


def fixture_19() -> dict:
    name = "19-code-and-prose"
    prose = "The extractor treats Courier as a code block and keeps the line breaks."
    code = "def glue(left, right):\n    return left + ' ' + right"
    c = new_canvas(name)
    y = draw_paragraph(c, prose, 72, 720, 468, size=11, leading=15)
    c.setFont("Courier", 10)
    for i, line in enumerate(code.split("\n")):
        c.drawString(72, y - 20 - i * 13, line)
    header_footer(c, 1, 1)
    c.showPage()
    c.save()
    save_expected(name, f"{prose}\n\n{code}")
    return {"file": f"{name}.pdf", "title": "Prose plus code", "tags": ["code"]}


def fixture_20() -> dict:
    name = "20-table-and-prose"
    before = "Measured clipboard error rates on the office corpus:"
    after = "Geometric reflow removes almost all soft-break errors on these three classes."
    c = new_canvas(name)
    y = draw_paragraph(c, before, 72, 720, 468, size=11, leading=15)
    c.setFont("Times-Bold", 10)
    y -= 18
    headers = [("Class", 72), ("Naive", 240), ("pdfcopy", 360)]
    for text, x in headers:
        c.drawString(x, y, text)
    c.setFont("Times-Roman", 10)
    rows = [("Invoices", "41%", "4%"), ("Articles", "63%", "7%"), ("Contracts", "58%", "5%")]
    y -= 16
    for cls, naive, fixed in rows:
        c.drawString(72, y, cls)
        c.drawString(240, y, naive)
        c.drawString(360, y, fixed)
        y -= 16
    draw_paragraph(c, after, 72, y - 12, 468, size=11, leading=15)
    header_footer(c, 1, 1)
    c.showPage()
    c.save()
    table = "Class Naive pdfcopy\nInvoices 41% 4%\nArticles 63% 7%\nContracts 58% 5%"
    save_expected(name, f"{before}\n\n{table}\n\n{after}")
    return {"file": f"{name}.pdf", "title": "Table between paragraphs", "tags": ["table"]}


def fixture_type3_names() -> dict:
    """Type3 glyphs named uniXXXX, no ToUnicode — used as the 5th-style extra? We already have 20.

    Kept as an extra helper if 05 is too easy. Not counted separately.
    """
    return {}


def main() -> int:
    cjk = find_cjk_font()
    FIXTURES.mkdir(parents=True, exist_ok=True)
    EXPECTED.mkdir(parents=True, exist_ok=True)
    fixtures = [
        fixture_01(),
        fixture_02(),
        fixture_03(),
        fixture_04(cjk),
        fixture_05(cjk),
        fixture_06(),
        fixture_07(),
        fixture_08(cjk),
        fixture_09(),
        fixture_10(),
        fixture_11(),
        fixture_12(),
        fixture_13(),
        fixture_14(),
        fixture_15(),
        fixture_16(cjk),
        fixture_17(cjk),
        fixture_18(),
        fixture_19(),
        fixture_20(),
    ]
    manifest = {
        "description": "Representative fixtures that reproduce real copy-breakage patterns.",
        "scanned_policy": "v1 does not OCR. Fixture 06 is a known skip.",
        "fixtures": fixtures,
    }
    (ROOT / "corpus" / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(fixtures)} fixtures to {FIXTURES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

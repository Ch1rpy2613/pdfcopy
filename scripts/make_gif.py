#!/usr/bin/env python3
"""Six-second GIF: same sentence, two pastes — broken lines vs one line."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from pdfcopy.extract import extract
from pdfcopy.mesh import sentences_from_layouts

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "corpus" / "fixtures" / "13-narrow-column.pdf"
OUT = ROOT / "docs" / "copy-vs-pdfcopy.gif"

MIDDLE = (
    "The middle sentence is the one a reviewer actually wants, even when it wraps "
    "twice in the column."
)

W, H = 1280, 560
PAGE_BOTTOM = 286
CLIP_TOP = 310

RED = "#b3352a"
GREEN = "#1f6d4a"
INK = "#1b1814"
PAPER = "#f7eee6"
AMBER = "#e4c4b0"


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Geneva.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _newline_mark(draw: ImageDraw.ImageDraw, x: int, y: int, color: str) -> None:
    """A small hook after a fragment: 'a hard line break lives here'."""
    draw.line((x, y, x, y + 8), fill=color, width=2)
    draw.line((x - 8, y + 8, x, y + 8), fill=color, width=2)


def main() -> int:
    if not PDF.exists():
        print("generate the corpus first", file=sys.stderr)
        return 1
    result = extract(PDF)
    sentences = sentences_from_layouts(result.layouts)
    if not any(item.text == MIDDLE for item in sentences):
        print("middle sentence missing from fixture 13", file=sys.stderr)
        return 1

    naive_lines = [line for line in result.naive_text.split("\n") if line.strip()]
    page_lines = [line for line in naive_lines if not line.startswith("Page")]
    page_noise = next((line for line in naive_lines if line.startswith("Page")), "Page 1 of 1")

    # The visual fragments a typical reader pastes for the middle sentence.
    start = next(i for i, line in enumerate(naive_lines) if "middle" in line.lower())
    frags: list[str] = []
    acc: list[str] = []
    for line in naive_lines[start:]:
        if line.startswith("Page"):
            break
        frags.append(line)
        acc.extend(line.split())
        if " ".join(acc) == MIDDLE:
            break
    mid_page_idx = [i for i, line in enumerate(page_lines) if line in frags]

    title = _font(22)
    body = _font(16)
    paste = _font(17)
    caption = _font(14)

    # Right paste box is wide enough to hold the sentence as ONE line.
    right_x0, right_x1 = 512, W - 28
    one_size = 17
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    while one_size > 11 and probe.textlength(MIDDLE, font=_font(one_size)) > right_x1 - right_x0 - 56:
        one_size -= 1
    one_line_font = _font(one_size)

    steps = 14
    frames: list[Image.Image] = []
    for i in range(steps):
        image = Image.new("RGB", (W, H), "#f4efe4")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, W // 2 - 1, PAGE_BOTTOM), fill=PAPER)
        draw.line((0, PAGE_BOTTOM, W, PAGE_BOTTOM), fill=INK, width=2)
        draw.line((W // 2, 0, W // 2, PAGE_BOTTOM), fill=INK, width=2)
        draw.text((28, 16), "Typical reader", font=title, fill=RED)
        draw.text((W // 2 + 28, 16), "Sentence lock", font=title, fill=GREEN)

        # Same page on both sides; the right side grows an amber drag.
        grow = min(1.0, max(0.0, (i - 2) / 8))
        y = 54
        for n, line in enumerate(page_lines[:10]):
            draw.text((28, y), line, font=body, fill=INK)
            draw.text((W // 2 + 28, y), line, font=body, fill=INK)
            if mid_page_idx and mid_page_idx[0] <= n <= mid_page_idx[-1] and grow > 0:
                tw = draw.textlength(line, font=body)
                right = 28 + tw * (0.2 + 0.8 * grow)
                draw.rectangle((W // 2 + 26, y - 1, W // 2 + right, y + 19), fill=AMBER)
                draw.text((W // 2 + 28, y), line, font=body, fill=INK)
            y += 22

        # Paste results: same sentence, different shape.
        lx0, lx1 = 28, 488
        draw.rectangle((lx0, CLIP_TOP, lx1, H - 20), fill="#faece6", outline=RED, width=1)
        draw.rectangle((right_x0, CLIP_TOP, right_x1, H - 20), fill="#e9f4ee", outline=GREEN, width=1)
        draw.text((lx0 + 14, CLIP_TOP + 10), "Paste (typical)", font=caption, fill=RED)
        draw.text((right_x0 + 14, CLIP_TOP + 10), "Paste (pdfcopy)", font=caption, fill=GREEN)

        if i >= 5:
            frac = min(1.0, (i - 4) / 6)
            shown = max(1, int(len(frags) * frac))
            cy = CLIP_TOP + 44
            for line in frags[:shown]:
                draw.text((lx0 + 14, cy), line, font=paste, fill=INK)
                _newline_mark(draw, lx0 + 18 + int(draw.textlength(line, font=paste)), cy + 4, RED)
                cy += 28
            if frac >= 0.99:
                draw.text((lx0 + 14, cy + 6), page_noise, font=paste, fill=RED)
                draw.text(
                    (lx0 + 14, H - 48),
                    f"{len(frags)} hard line breaks + page number",
                    font=caption,
                    fill=RED,
                )

            locked = MIDDLE[: max(1, int(len(MIDDLE) * frac))]
            ly = CLIP_TOP + 52
            draw.text((right_x0 + 28, ly), locked, font=one_line_font, fill=INK)
            if frac >= 0.99:
                draw.text(
                    (right_x0 + 28, ly + 34),
                    "one line, no breaks, no page junk",
                    font=caption,
                    fill=GREEN,
                )
        frames.append(image)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        OUT,
        save_all=True,
        append_images=frames[1:],
        duration=420,
        loop=0,
    )
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

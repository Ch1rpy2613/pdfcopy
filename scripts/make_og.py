#!/usr/bin/env python3
"""Social preview card: 1280x640 PNG for link unfurls."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "og-image.png"

W, H = 1280, 640
BG = "#0d1117"
PANEL_L = "#1a0f10"
PANEL_R = "#0f1a12"
RED = "#f85149"
GREEN = "#3fb950"
WHITE = "#e6edf3"
MUTED = "#9da7b3"
BLUE = "#58a6ff"

BROKEN = [
    "The middle sentence is the one a",
    "reviewer actually wants, even",
]
LOCKED = [
    "The middle sentence is the one a",
    "reviewer actually wants, even when it",
    "wraps twice in the column.",
]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def main() -> int:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)

    logo = _font(84)
    tag = _font(30)
    label = _font(26)
    body = _font(25)
    url = _font(26)

    draw.text((72, 56), "pdfcopy", font=logo, fill=WHITE)
    draw.text((76, 158), "Drag across a wrap. Paste one sentence.", font=tag, fill=MUTED)

    lx0, ly0, lx1, ly1 = 72, 240, 608, 500
    rx0, ry0, rx1, ry1 = 672, 240, 1208, 500
    draw.rounded_rectangle((lx0, ly0, lx1, ly1), 14, fill=PANEL_L, outline=RED, width=2)
    draw.rounded_rectangle((rx0, ry0, rx1, ry1), 14, fill=PANEL_R, outline=GREEN, width=2)

    draw.text((lx0 + 28, ly0 + 24), "Typical copy", font=label, fill=RED)
    draw.text((rx0 + 28, ry0 + 24), "pdfcopy", font=label, fill=GREEN)

    y = ly0 + 78
    for line in BROKEN:
        draw.text((lx0 + 28, y), line, font=body, fill=MUTED)
        y += 38
    draw.text((lx0 + 28, y + 10), "Page 3 of 12", font=body, fill=RED)

    y = ry0 + 78
    for line in LOCKED:
        draw.text((rx0 + 28, y), line, font=body, fill=WHITE)
        y += 38
    draw.text((rx0 + 28, y + 10), "— one sentence, no line breaks", font=body, fill=GREEN)

    draw.text((72, 556), "github.com/Ch1rpy2613/pdfcopy", font=url, fill=BLUE)
    draw.text((1208 - draw.textlength("offline · no GPU · MIT", font=url), 556),
              "offline · no GPU · MIT", font=url, fill=MUTED)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT, optimize=True)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

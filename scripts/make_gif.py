#!/usr/bin/env python3
"""Eight-second GIF: drag across a wrap, paste one sentence."""

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


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Geneva.ttf",
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


def main() -> int:
    if not PDF.exists():
        print("generate the corpus first", file=sys.stderr)
        return 1
    result = extract(PDF)
    sentences = sentences_from_layouts(result.layouts)
    mid = next((item for item in sentences if item.text == MIDDLE), None)
    if mid is None:
        print("middle sentence missing from fixture 13", file=sys.stderr)
        return 1
    naive_lines = [line for line in result.naive_text.split("\n") if line.strip()]
    page_lines = [line for line in naive_lines if not line.startswith("Page")]
    broken_copy = [line for line in naive_lines if "middle" in line.lower() or line.startswith("Page")]
    if len(broken_copy) < 2:
        broken_copy = naive_lines[:4] + [naive_lines[-1]]

    width, height = 920, 460
    title = _font(20)
    body = _font(15)
    memo = _font(16)
    frames: list[Image.Image] = []
    steps = 16
    mid_start = next((i for i, line in enumerate(page_lines) if "middle" in line.lower()), 2)
    mid_lines = [
        i
        for i, line in enumerate(page_lines)
        if any(word in line.lower() for word in ("middle", "reviewer", "wraps", "twice", "column"))
    ]
    if not mid_lines:
        mid_lines = [mid_start, mid_start + 1]

    for i in range(steps):
        image = Image.new("RGB", (width, height), "#f4efe4")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, width // 2 - 1, height), fill="#f7eee6")
        draw.line((width // 2, 0, width // 2, height), fill="#1b1814", width=2)
        draw.text((22, 16), "Typical reader", font=title, fill="#7a2e1b")
        draw.text((width // 2 + 22, 16), "Sentence lock", font=title, fill="#1f4d3a")

        y = 52
        line_h = 20
        for n, line in enumerate(page_lines[:12]):
            draw.text((22, y), line, font=body, fill="#1b1814")
            draw.text((width // 2 + 22, y), line, font=body, fill="#1b1814")
            if n in mid_lines or n == mid_lines[0] or (mid_lines and n == mid_lines[-1]):
                grow = min(1.0, max(0.0, (i - 2) / 8))
                if grow > 0 and n >= min(mid_lines) and n <= max(mid_lines):
                    tw = draw.textlength(line, font=body)
                    right = 22 + tw * (0.2 + 0.8 * grow)
                    draw.rectangle(
                        (width // 2 + 20, y - 1, width // 2 + right, y + line_h - 3),
                        fill="#e4c4b0",
                    )
                    draw.text((width // 2 + 22, y), line, font=body, fill="#1b1814")
            y += line_h

        clip_top = 300
        draw.rectangle((18, clip_top, width // 2 - 18, height - 18), outline="#7a2e1b", width=1)
        draw.rectangle(
            (width // 2 + 18, clip_top, width - 18, height - 18), outline="#1f4d3a", width=1
        )
        draw.text((24, clip_top + 8), "WeChat / Notes", font=body, fill="#7a2e1b")
        draw.text((width // 2 + 24, clip_top + 8), "WeChat / Notes", font=body, fill="#1f4d3a")

        if i >= 6:
            cy = clip_top + 32
            frac = min(1.0, (i - 5) / 6)
            shown_broken = broken_copy[: max(1, int(len(broken_copy) * frac))]
            for line in shown_broken:
                draw.text((24, cy), line, font=memo, fill="#7a2e1b")
                cy += 20
            locked = MIDDLE[: max(1, int(len(MIDDLE) * frac))]
            ly = clip_top + 32
            for line in _wrap(draw, locked, memo, width // 2 - 56):
                draw.text((width // 2 + 24, ly), line, font=memo, fill="#1b1814")
                ly += 22
        frames.append(image)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        OUT,
        save_all=True,
        append_images=frames[1:],
        duration=500,
        loop=0,
    )
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

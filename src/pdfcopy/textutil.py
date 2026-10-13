"""Shared wrapping helpers for fixture generation and tests."""

from __future__ import annotations

import re
import unicodedata

# Latin presentation ligatures that publishers embed as a single glyph.
# Clipboard text should be the letters a person typed. ß/æ/œ stay put.
_LIGATURES = str.maketrans(
    {
        "\ufb00": "ff",
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
        "\ufb05": "st",
        "\ufb06": "st",
        "\u0132": "IJ",
        "\u0133": "ij",
        "\u017f": "s",  # long s
    }
)


def decompose_ligatures(text: str) -> str:
    """Expand typographic ligatures to plain letters without touching CJK."""
    if not text:
        return text
    return text.translate(_LIGATURES)


def normalize_expected(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

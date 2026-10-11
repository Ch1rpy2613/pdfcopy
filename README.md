# pdfcopy

[![CI](https://github.com/Ch1rpy2613/pdfcopy/actions/workflows/ci.yml/badge.svg)](https://github.com/Ch1rpy2613/pdfcopy/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](pyproject.toml)
[![GitHub stars](https://img.shields.io/github/stars/Ch1rpy2613/pdfcopy?style=social)](https://github.com/Ch1rpy2613/pdfcopy/stargazers)

**Drag across a wrap. Paste one sentence.**

划过自动折行的那几个字，贴出来是一句完整的话。

![Select through a wrap, paste one sentence](docs/copy-vs-pdfcopy.gif)

A PDF is a stack of “draw these outlines at (x, y)” commands. It does not store sentences. Most readers put a `\n` on the clipboard at every visual wrap, drag in `Page 3 of 12`, and — when ToUnicode is missing — paste `????`.

pdfcopy rebuilds the sentence a person meant to copy, then writes it back as a **copy mesh**: each visible letter gets an invisible twin at the same box, soft wraps become spaces, and each sentence carries `/ActualText`. Offline. No GPU.

```bash
pip install -e ".[demo]"
pdfcopy extract contract.pdf
pdfcopy serve --open
```

Open the demo desk: drag a PDF onto the lit page, or hit the narrow-column sample. Drag across a wrap — amber highlight follows the ink, the note card on the right is the locked sentence. Copy writes `text/plain` and `text/html`. Flip to **断行** for the staircase.

## What it does

- Infers spaces from glyph gaps (many PDFs never write `U+0020`)
- Splits reconstructed paragraphs into sentences (CJK `。！？；`, Latin `.?!` with abbrev/decimal guards)
- Joins soft wraps; keeps list items, tables, and code
- Stitches hyphenated line ends (`inter-` + `national`)
- Drops running heads and `第 3 页 共 12 页`
- Leaves CJK characters unspaced; keeps a space around Latin
- Writes a **glyph-aligned copy mesh** into a standard PDF so other readers’ Ctrl+C can lock a sentence
- Keeps original ink (Artifact-wrapped); `--outline` is optional for readers that ignore Artifact
- Also repairs ToUnicode, a structure tree, and a public [overlay convention](docs/CONVENTION.md)

It does not invent a new format. Acrobat and Preview still open the file. After `pdfcopy fix`, a two-word drag through a wrap pastes the sentence, not five line fragments.

## Commands

```bash
pdfcopy extract paper.pdf           # reconstructed text on stdout
pdfcopy extract paper.pdf --naive   # what most readers copy
pdfcopy extract paper.pdf --page 2
pdfcopy fix paper.pdf -o paper.fixed.pdf
pdfcopy fix paper.pdf -o paper.fixed.pdf --outline   # path-out the original letters
pdfcopy info scan.pdf
```

Scanned pages have no text layer. v1 reports that and stops. It does not OCR.

## Corpus

`corpus/` holds 20 fixtures — invoice, two-column article, contract, Chinese without ToUnicode, scan, fake spaces — each with expected paste text.

Fixture `13-narrow-column` is the proof: typical copy is a staircase plus `Page 1 of 1`; a bbox over the middle sentence pastes that sentence only, with no `\n`.

```bash
python scripts/generate_corpus.py
pytest
python scripts/make_gif.py
```

## Status

Sentence lock is the product. Merge/split/sign/OCR are someone else’s toolbox.

MIT license.

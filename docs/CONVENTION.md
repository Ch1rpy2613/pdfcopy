# pdfcopy overlay 1.0

pdfcopy never invents a new file format. It writes reconstruction data back into a **standard PDF** so Acrobat, Preview, and browsers still open the file.

The important writeback is the **copy mesh**. Original letters stay as ink, wrapped in `/Artifact` so extractors skip the printer stream. Each reconstructed sentence is written again as glyph-aligned invisible text (`3 Tr`) at the same boxes, with real spaces at soft wraps, nested `/Span` `/ActualText` for the sentence, and an outer paragraph `/ActualText` for select-all. Preview and Adobe can copy the locked sentence. Chrome often ignores ActualText; the demo (and overlay) do their own hit-testing.

Pass `--outline` to convert original letters to paths when a reader refuses to honor Artifact.

Three metadata layers sit beside it:

1. **ToUnicode CMap** on fonts that can be recovered from glyph names or an embedded TrueType cmap. This is what stops Chinese copy from turning into `????`.
2. **Structure tree** (`StructTreeRoot`) with paragraph / heading / list / table / artifact roles. Headers, footers, and page numbers are marked as artifacts so they stay off the clipboard.
3. **This overlay** — reading order, sentences, glyph boxes, soft wraps, and inferred spaces — stored where PDF already allows private application data.

Readers that do not know the overlay still see the original ink. Readers that do can paste a sentence instead of a stack of visual lines.

## Where it lives

| Location | Name | Purpose |
| --- | --- | --- |
| `Catalog.PieceInfo.PDFCopy.Private.Data` | stream | Canonical JSON |
| `Catalog.Names.EmbeddedFiles` | `pdfcopy-overlay.json` | Same JSON, easy to unzip |
| `Catalog.MarkInfo.Marked` | `true` | File claims structure |
| `Catalog.StructTreeRoot` | tree | Tagged PDF roles |

`PieceInfo` is the Adobe-era hook for application private data. Another tool can ignore it without breaking the page.

## JSON shape

```json
{
  "spec": "pdfcopy-overlay",
  "version": "1.0",
  "url": "https://github.com/Ch1rpy2613/pdfcopy/blob/main/docs/CONVENTION.md",
  "created": "2026-10-08T00:00:00+00:00",
  "pages": [
    {
      "index": 0,
      "width": 612.0,
      "height": 792.0,
      "hasTextLayer": true,
      "blocks": [
        {
          "id": "p0-b0",
          "role": "p",
          "readingOrder": 0,
          "bbox": [72.0, 640.0, 540.0, 720.0],
          "text": "A reconstructed paragraph.",
          "softBreaks": [[540.12, 704.4]],
          "spaces": [[120.5, 704.4]],
          "column": 0
        }
      ],
      "sentences": [
        {
          "id": "p0-b0-s0",
          "blockId": "p0-b0",
          "role": "p",
          "page": 0,
          "index": 0,
          "text": "The middle sentence is the one a reviewer actually wants, even when it wraps twice in the column.",
          "bbox": [72.0, 680.0, 232.0, 734.0],
          "glyphs": [
            {"t": "T", "bbox": [72.0, 720.0, 79.0, 734.0]}
          ]
        }
      ],
      "artifacts": [
        {
          "role": "artifact",
          "artifactType": "pagination",
          "bbox": [480.0, 24.0, 540.0, 36.0],
          "text": "Page 1 of 2"
        }
      ]
    }
  ]
}
```

### Roles

| `role` | Meaning |
| --- | --- |
| `p` | Body paragraph / sentence |
| `h` | Heading |
| `l` | List |
| `table` | Row-preserving table |
| `code` | Keep visual line breaks |
| `artifact` | Header, footer, or page number |

`softBreaks` are `[x, y]` points at the end of a visual line that should **not** become `\n` on the clipboard. `spaces` are gaps that were drawn as a move, not as `U+0020`. `sentences` are the copy-mesh units: drag any glyph box, paste `text` (no soft wraps, no running heads).

Coordinates are PDF user space, origin at the bottom-left of the page, matching the content stream.

## What this is not

It is not a new extension, a new magic number, or a replacement for PDF/UA. If a driver already wrote a correct structure tree, pdfcopy keeps the ink and only fills gaps (missing ToUnicode, missing reading order).

Scanned pages have `hasTextLayer: false`. Version 1 does not OCR them.

## Reading the overlay

```python
import json, pikepdf

pdf = pikepdf.open("doc.fixed.pdf")
data = pdf.Root.PieceInfo.PDFCopy.Private.Data.read_bytes()
overlay = json.loads(data)
```

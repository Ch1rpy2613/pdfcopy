# Corpus

Twenty fixtures that reproduce the copy failures people hit in invoices, papers, contracts, and old Chinese PDFs.

They are generated — not scraped — so the expected paste text can live in git and CI can fail when reflow regresses. Each file is a stand-in for a real class of document, not a substitute for someone’s contract.

```
python scripts/generate_corpus.py
```

| File | What breaks in a typical reader |
| --- | --- |
| `01-invoice-header-footer` | `Page 1 of 1` lands in the clipboard |
| `02-two-column-article` | Columns are read as one zigzag sentence |
| `03-contract-wrapped` | Soft wraps become hard returns |
| `04-chinese-article` | CJK lines pick up spaces or breaks |
| `05-chinese-no-tounicode` | ToUnicode stripped; copy needs a rebuilt CMap |
| `06-scanned-receipt` | No text layer — v1 does not OCR |
| `07-hyphenation` | `inter-` + `national` should become one word |
| `08-mixed-cjk-latin` | Need a space around `PDF`, none between han |
| `09-academic-abstract` | Title, abstract, then two-column body |
| `10-letter` | Ordinary prose wrap |
| `11-form-like-invoice` | Label / value islands |
| `12-three-page-report` | Running header repeats on every page |
| `13-narrow-column` | Almost every few words wrap |
| `14-bullet-list` | List items must keep their newlines |
| `15-quote-block` | Indented quotation vs body |
| `16-chinese-contract` | Long CJK legal paragraphs |
| `17-page-numbers-cn` | `第 x 页 共 y 页` |
| `18-fake-spaces` | Words are positioned; there is no `0x20` |
| `19-code-and-prose` | Courier lines stay broken |
| `20-table-and-prose` | Table rows stay rows |

`06` is a documented skip. The expected file is `# pdfcopy:scanned`.

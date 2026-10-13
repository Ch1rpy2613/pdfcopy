"""Audit pdfcopy extract quality across a directory of paper PDFs.

For each PDF, report metrics that flag the copy failures we care about:
soft wraps left as hard newlines, page furniture mixed into body, space
inference errors, CJK spacing, hyphenation, and naive-vs-reconstructed delta.

Usage:
  python scripts/audit_papers.py /path/to/papers [--out report.md] [--top N]
"""

from __future__ import annotations

import argparse
import re
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pdfcopy.extract import extract  # noqa: E402

PAGE_FURNITURE = re.compile(
    r"(?i)(page\s+\d+(\s+of\s+\d+)?|\d+\s*/\s*\d+|第\s*\d+\s*页|"
    r"downloaded from|https?://\S+|doi:\s*\S+|copyright)"
)
HARD_WRAP_SUSPECT = re.compile(r"[a-z,;:—-]\n[a-z]")
MID_SENT_BLANK = re.compile(r"[a-z,;:—-]\n\n[a-z]")
LIGATURE = re.compile("[\ufb00-\ufb06]")
CJK_SPACE = re.compile(r"[\u4e00-\u9fff]\s+[\u4e00-\u9fff]")
MULTI_SPACE = re.compile(r"[^\n] {3,}")
LONELY_HYPHEN = re.compile(r"\w-\n\w")
EMPTY_RUN = re.compile(r"\n{3,}")
MOJIBAKE = re.compile(r"[\ufffd\u0000-\u0008]")


@dataclass
class Report:
    path: Path
    pages: int = 0
    chars: int = 0
    naive_chars: int = 0
    sentences: int = 0
    blocks: int = 0
    scanned: bool = False
    warnings: list[str] = field(default_factory=list)
    error: str = ""
    metrics: dict[str, float] = field(default_factory=dict)
    samples: dict[str, str] = field(default_factory=dict)

    @property
    def score(self) -> float:
        if self.error or self.scanned:
            return 0.0
        return self.metrics.get("problem_density", 999.0)


def _sample(text: str, match: re.Match, radius: int = 40) -> str:
    a = max(0, match.start() - radius)
    b = min(len(text), match.end() + radius)
    return text[a:b].replace("\n", "\\n")


def audit_one(path: Path) -> Report:
    rep = Report(path=path)
    try:
        result = extract(path)
    except Exception:
        rep.error = traceback.format_exc(limit=2).strip()
        return rep

    text = result.text
    naive = result.naive_text
    rep.pages = len(result.pages)
    rep.chars = len(text)
    rep.naive_chars = len(naive)
    rep.scanned = bool(result.scanned)
    rep.warnings = list(result.warnings)

    overlay = result.overlay or {}
    pages = overlay.get("pages", [])
    rep.sentences = sum(len(p.get("sentences", [])) for p in pages)
    rep.blocks = sum(len(p.get("blocks", [])) for p in pages)

    if rep.scanned or not text.strip():
        return rep

    problems = 0

    furniture = list(PAGE_FURNITURE.finditer(text))
    problems += len(furniture)
    if furniture:
        rep.samples["furniture"] = _sample(text, furniture[0])

    wraps = list(HARD_WRAP_SUSPECT.finditer(text))
    problems += len(wraps) * 2
    if wraps:
        rep.samples["hard_wrap"] = _sample(text, wraps[0])

    mids = list(MID_SENT_BLANK.finditer(text))
    problems += len(mids) * 2
    if mids:
        rep.samples["mid_blank"] = _sample(text, mids[0])

    ligs = list(LIGATURE.finditer(text))
    problems += len(ligs)
    if ligs:
        rep.samples["ligature"] = _sample(text, ligs[0])

    hyph = list(LONELY_HYPHEN.finditer(text))
    problems += len(hyph)
    if hyph:
        rep.samples["hyphen"] = _sample(text, hyph[0])

    cjk = list(CJK_SPACE.finditer(text))
    problems += len(cjk)
    if cjk:
        rep.samples["cjk_space"] = _sample(text, cjk[0])

    gaps = list(MULTI_SPACE.finditer(text))
    problems += len(gaps)
    if gaps:
        rep.samples["gap"] = _sample(text, gaps[0])

    bad = list(MOJIBAKE.finditer(text))
    problems += len(bad)
    if bad:
        rep.samples["mojibake"] = _sample(text, bad[0])

    blanks = list(EMPTY_RUN.finditer(text))
    problems += len(blanks)

    naive_nl = naive.count("\n")
    text_nl = text.count("\n")
    rep.metrics["naive_nl"] = naive_nl
    rep.metrics["text_nl"] = text_nl
    rep.metrics["wrap_drop"] = (naive_nl - text_nl) / max(naive_nl, 1)

    long_sent = 0
    for p in pages:
        for s in p.get("sentences", []):
            if len(s.get("text", "")) > 500:
                long_sent += 1
    problems += long_sent
    rep.metrics["long_sentences"] = long_sent

    rep.metrics["problems"] = problems
    rep.metrics["problem_density"] = problems * 1000.0 / max(rep.chars, 1)
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args(argv)

    pdfs = sorted(args.root.glob("*.pdf"))
    print(f"auditing {len(pdfs)} PDFs under {args.root}", file=sys.stderr)

    reports = [audit_one(p) for p in pdfs]
    reports.sort(key=lambda r: (-r.metrics.get("problems", 0) if not r.error and not r.scanned else 0), reverse=True)

    lines = ["# pdfcopy paper audit", ""]
    ok = sum(1 for r in reports if not r.error and not r.scanned and r.metrics.get("problems", 0) == 0)
    err = sum(1 for r in reports if r.error)
    scan = sum(1 for r in reports if r.scanned)
    with_problems = sum(1 for r in reports if not r.error and not r.scanned and r.metrics.get("problems", 0) > 0)
    lines.append(f"files={len(reports)} clean={ok} with_problems={with_problems} scanned={scan} errors={err}")
    lines.append("")
    lines.append("## Worst offenders")
    lines.append("")
    shown = 0
    for r in reports:
        if shown >= args.top:
            break
        if r.error:
            lines.append(f"### ERROR {r.path.name}")
            lines.append("```")
            lines.append(r.error[:500])
            lines.append("```")
            lines.append("")
            shown += 1
            continue
        if r.scanned:
            continue
        probs = int(r.metrics.get("problems", 0))
        if probs == 0:
            continue
        lines.append(f"### {r.path.name}  problems={probs} density={r.score:.2f}/1k chars")
        lines.append(
            f"- pages={r.pages} chars={r.chars} sentences={r.sentences} blocks={r.blocks} "
            f"wrap_drop={r.metrics.get('wrap_drop', 0):.2f}"
        )
        if r.warnings:
            lines.append(f"- warnings: {r.warnings[:3]}")
        for k, v in r.samples.items():
            lines.append(f"- sample[{k}]: `{v}`")
        lines.append("")
        shown += 1

    lines.append("## All files")
    lines.append("")
    lines.append("| file | pages | chars | sentences | problems | density | wrap_drop |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for r in reports:
        if r.error:
            lines.append(f"| {r.path.name} | - | - | - | ERR | - | - |")
        elif r.scanned:
            lines.append(f"| {r.path.name} | {r.pages} | - | - | SCAN | - | - |")
        else:
            lines.append(
                f"| {r.path.name} | {r.pages} | {r.chars} | {r.sentences} | "
                f"{int(r.metrics.get('problems', 0))} | {r.score:.2f} | "
                f"{r.metrics.get('wrap_drop', 0):.2f} |"
            )

    text = "\n".join(lines) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Command-line entry: extract, fix, serve."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pdfcopy import __version__
from pdfcopy.extract import extract
from pdfcopy.writeback import fix_pdf


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pdfcopy",
        description="Sentence lock: copy a sentence through a wrap, not broken lines.",
    )
    parser.add_argument("--version", action="version", version=f"pdfcopy {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    extract_p = sub.add_parser("extract", help="Print reconstructed paste text")
    extract_p.add_argument("pdf", type=Path)
    extract_p.add_argument("--page", type=int, default=None, help="1-based page number")
    extract_p.add_argument(
        "--naive",
        action="store_true",
        help="Emit visual-line breaks the way most readers copy",
    )
    extract_p.add_argument("--json", action="store_true", help="Dump overlay JSON")

    fix_p = sub.add_parser("fix", help="Write a sentence-lock copy mesh into a standard PDF")
    fix_p.add_argument("pdf", type=Path)
    fix_p.add_argument("-o", "--output", type=Path, required=True)
    fix_p.add_argument(
        "--metadata-only",
        action="store_true",
        help="Skip the copy layer; only write overlay / ToUnicode / tags",
    )
    fix_p.add_argument(
        "--outline",
        action="store_true",
        help="Convert original letters to paths (default keeps ink, wrapped as Artifact)",
    )

    serve_p = sub.add_parser("serve", help="Open the side-by-side demo")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8765)
    serve_p.add_argument("--open", action="store_true")

    info_p = sub.add_parser("info", help="Show warnings and page counts")
    info_p.add_argument("pdf", type=Path)

    args = parser.parse_args(argv)
    if args.cmd == "extract":
        return _cmd_extract(args)
    if args.cmd == "fix":
        return _cmd_fix(args)
    if args.cmd == "serve":
        return _cmd_serve(args)
    if args.cmd == "info":
        return _cmd_info(args)
    return 1


def _cmd_extract(args: argparse.Namespace) -> int:
    result = extract(args.pdf)
    if args.json:
        sys.stdout.write(json.dumps(result.overlay, ensure_ascii=False, indent=2) + "\n")
        return 0
    text = result.naive_text if args.naive else result.text
    if args.page is not None:
        idx = args.page - 1
        if idx < 0 or idx >= len(result.pages):
            sys.stderr.write(f"page {args.page} out of range (1-{len(result.pages)})\n")
            return 2
        text = result.naive_text if args.naive else result.pages[idx]
        if args.naive:
            # naive_serialize is whole-document; re-extract page via overlay-less path
            from pdfcopy.serialize import naive_serialize

            text = naive_serialize([result.layouts[idx]])
    sys.stdout.write(text)
    if text and not text.endswith("\n"):
        sys.stdout.write("\n")
    for warning in result.warnings:
        sys.stderr.write(f"warning: {warning}\n")
    return 0


def _cmd_fix(args: argparse.Namespace) -> int:
    result = fix_pdf(
        args.pdf,
        args.output,
        metadata_only=args.metadata_only,
        outline=args.outline,
    )
    sys.stderr.write(f"wrote {args.output} ({len(result.pages)} page(s))\n")
    for warning in result.warnings:
        sys.stderr.write(f"warning: {warning}\n")
    return 0


def _cmd_info(args: argparse.Namespace) -> int:
    result = extract(args.pdf)
    info = {
        "pages": len(result.pages),
        "has_text_layer": any(page.has_text_layer for page in result.glyphs),
        "scanned": result.scanned,
        "warnings": result.warnings,
        "characters": len(result.text),
    }
    sys.stdout.write(json.dumps(info, ensure_ascii=False, indent=2) + "\n")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    from pdfcopy.server import serve

    serve(host=args.host, port=args.port, open_browser=args.open)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

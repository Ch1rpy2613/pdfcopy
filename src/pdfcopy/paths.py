"""Locate the web UI and corpus: wheel assets, repo checkout, or cwd."""

from __future__ import annotations

from pathlib import Path


def _packaged_root() -> Path | None:
    """Assets bundled into the wheel at pdfcopy/_web and pdfcopy/_corpus."""
    here = Path(__file__).resolve().parent
    if (here / "_web" / "index.html").exists() or (here / "_corpus" / "manifest.json").exists():
        return here
    return None


def repo_root() -> Path:
    packaged = _packaged_root()
    if packaged is not None:
        return packaged
    here = Path(__file__).resolve()
    candidates = [here.parents[2], here.parents[1], Path.cwd()]
    for parent in here.parents:
        candidates.append(parent)
    for path in candidates:
        if (path / "web" / "index.html").exists():
            return path
        if (path / "corpus" / "manifest.json").exists():
            return path
    return Path.cwd()


def web_dir() -> Path:
    root = repo_root()
    for name in ("web", "_web"):
        if (root / name / "index.html").exists():
            return root / name
    return root / "web"


def corpus_dir() -> Path:
    root = repo_root()
    for name in ("corpus", "_corpus"):
        if (root / name / "manifest.json").exists():
            return root / name
    return root / "corpus"

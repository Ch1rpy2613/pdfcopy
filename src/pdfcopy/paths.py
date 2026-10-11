"""Locate the repo-root web UI and corpus when running from source."""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
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
    return repo_root() / "web"


def corpus_dir() -> Path:
    return repo_root() / "corpus"

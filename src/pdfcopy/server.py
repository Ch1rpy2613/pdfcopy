"""Local demo: original page on the left, reconstructed paste on the right."""

from __future__ import annotations

import io
import json
import webbrowser
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from pdfcopy.extract import extract
from pdfcopy.paths import corpus_dir, web_dir
from pdfcopy.readertext import reader_copy_text
from pdfcopy.writeback import fix_pdf


def create_app():

    app = FastAPI(title="pdfcopy", version="0.1.0")
    static = web_dir()
    fixtures = corpus_dir() / "fixtures"

    @app.get("/")
    def index():
        page = static / "index.html"
        if not page.exists():
            raise HTTPException(500, "web/index.html missing — run from the repo")
        return FileResponse(page)

    @app.get("/convention")
    def convention():
        from pdfcopy.paths import repo_root

        path = repo_root() / "docs" / "CONVENTION.md"
        if not path.exists():
            raise HTTPException(404, "convention missing")
        return FileResponse(path, media_type="text/plain")

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/corpus")
    def list_corpus():
        manifest = corpus_dir() / "manifest.json"
        if not manifest.exists():
            return {"fixtures": []}
        return json.loads(manifest.read_text(encoding="utf-8"))

    @app.get("/api/corpus/{name}")
    def corpus_pdf(name: str):
        path = _safe_fixture(fixtures, name)
        return FileResponse(path, media_type="application/pdf")

    @app.get("/api/corpus/{name}/expected")
    def corpus_expected(name: str):
        expected = corpus_dir() / "expected" / (Path(name).stem + ".txt")
        if not expected.exists():
            raise HTTPException(404, "no expected text")
        return Response(expected.read_text(encoding="utf-8"), media_type="text/plain")

    @app.post("/api/extract")
    async def api_extract(request: Request):
        data = await _read_upload(request)
        result = extract(io.BytesIO(data))
        reader_text = ""
        if not result.scanned:
            fixed = io.BytesIO()
            try:
                fix_pdf(io.BytesIO(data), fixed)
                reader_text = reader_copy_text(io.BytesIO(fixed.getvalue()))
            except Exception:
                reader_text = result.text
        return JSONResponse(
            {
                "text": result.text,
                "naive_text": result.naive_text,
                "reader_text": reader_text,
                "pages": result.pages,
                "warnings": result.warnings,
                "scanned": result.scanned,
                "overlay": result.overlay,
            }
        )

    @app.post("/api/fix")
    async def api_fix(request: Request):
        data = await _read_upload(request)
        out = io.BytesIO()
        fix_pdf(io.BytesIO(data), out)
        return Response(
            out.getvalue(),
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=fixed.pdf"},
        )

    if static.exists():
        app.mount("/static", StaticFiles(directory=static), name="static")
    return app


async def _read_upload(request: Request) -> bytes:
    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        raise HTTPException(400, "file field required")
    data = await upload.read()
    if not data:
        raise HTTPException(400, "empty file")
    return data


def _safe_fixture(root: Path, name: str) -> Path:
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(400, "bad name")
    path = (root / name).resolve()
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise HTTPException(404, "fixture not found")
    if root.resolve() not in path.parents and path.parent != root.resolve():
        raise HTTPException(400, "bad name")
    return path


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    import uvicorn

    if open_browser:
        webbrowser.open(f"http://{host}:{port}/")
    uvicorn.run(create_app(), host=host, port=port, log_level="info")

"""Host the pdfcopy demo server on Modal (usage covered by the monthly free credits).

Deploy:  .venv/bin/modal deploy modal_app.py
URL:     https://<workspace>--pdfcopy.modal.run
"""

import modal

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("fonts-noto-cjk", "fonts-liberation")
    .pip_install(
        "pdfminer.six>=20240706",
        "pikepdf>=9.0.0",
        "fonttools>=4.54.0",
        "fastapi>=0.115.0",
        "uvicorn[standard]>=0.32.0",
        "python-multipart>=0.0.12",
    )
    # Source tree instead of a wheel: paths.py resolves web/ and corpus/ by
    # walking up from the package directory, so /root must look like the repo.
    .add_local_dir("src/pdfcopy", "/root/pdfcopy", copy=True)
    .add_local_dir("web", "/root/web", copy=True)
    .add_local_dir("corpus", "/root/corpus", copy=True)
    .add_local_dir("docs", "/root/docs", copy=True)
    .env({"PYTHONPATH": "/root"})
)

app = modal.App("pdfcopy", image=image)


@app.function(scaledown_window=300)
@modal.asgi_app(label="pdfcopy")
def web():
    from pdfcopy.server import create_app

    return create_app()

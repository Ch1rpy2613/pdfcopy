FROM python:3.12-slim

# CJK + metric-compatible Latin fonts so the copy layer can embed glyphs
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
# web + corpus must be present at pip-install time: hatchling force-includes
# them into the wheel (pdfcopy/_web, pdfcopy/_corpus); paths.py also reads
# them from the working directory at runtime.
COPY web ./web
COPY corpus ./corpus
RUN pip install --no-cache-dir ".[demo]"

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn pdfcopy.server:create_app --factory --host 0.0.0.0 --port ${PORT}"]

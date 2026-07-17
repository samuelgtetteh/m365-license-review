# syntax=docker/dockerfile:1
FROM python:3.14-slim AS base

# No .pyc, unbuffered logs (so container stdout streams live)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first for layer caching
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install .

# Config (SKU price maps etc.) — operator can override via a mounted volume.
COPY config ./config

# Resolve config/output/data to absolute container paths (the package is
# pip-installed into site-packages, so package-relative resolution would miss these).
ENV CONFIG_DIR=/app/config \
    OUTPUT_DIR=/app/reports \
    DATA_DIR=/app/data

# Reports are written here; the SQLite profiles DB lives in /app/data.
# Mount host volumes to persist both across container restarts.
RUN mkdir -p /app/reports /app/data
VOLUME ["/app/reports", "/app/data"]

# Run as non-root
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Default entrypoint = the web app. Override CMD to use the CLI, e.g.:
#   docker run --rm -it <image> m365-review sku-check
CMD ["uvicorn", "m365_review.web.app:app", "--host", "0.0.0.0", "--port", "8000"]

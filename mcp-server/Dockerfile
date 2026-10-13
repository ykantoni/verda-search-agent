FROM python:3.12-slim

# antiword: best-effort text extraction for legacy .doc files (python-docx
# only handles .docx) — see indexer.py's _extract_doc_legacy for the
# fallback behavior when it's missing or fails on a given file.
RUN apt-get update \
    && apt-get install -y --no-install-recommends antiword \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    DOCS_DIR=/data/docs \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8001

EXPOSE 8001
CMD ["python", "-m", "local_docs_mcp.server"]

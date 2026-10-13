from __future__ import annotations

import logging
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .indexer import DocumentIndex

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DOCS_DIR = Path(os.environ.get("DOCS_DIR", "/data/docs"))
HOST = os.environ.get("MCP_HOST", "0.0.0.0")
PORT = int(os.environ.get("MCP_PORT", "8001"))

index = DocumentIndex(DOCS_DIR)
index.build()

mcp = FastMCP("local-docs", host=HOST, port=PORT)


@mcp.tool()
def search_documents(query: str, limit: int = 5) -> dict:
    """Search local PDF, DOC, DOCX and TXT files for information relevant to
    a question. Returns matching text snippets, source locations and chunk
    IDs."""
    limit = max(1, min(20, limit))
    return {"results": index.search(query, limit)}


@mcp.tool()
def get_document_chunk(chunk_id: str) -> dict:
    """Retrieve the complete text of a document chunk by ID, including
    filename and page reference. Use after search_documents to obtain
    evidence for an answer."""
    chunk = index.get_chunk(chunk_id)
    if chunk is None:
        raise ValueError(f"Unknown chunk_id: {chunk_id}")
    return chunk


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

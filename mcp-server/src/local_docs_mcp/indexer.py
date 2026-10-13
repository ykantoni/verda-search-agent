from __future__ import annotations

import hashlib
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader
from rank_bm25 import BM25Plus

logger = logging.getLogger(__name__)

CHUNK_WORD_TARGET = 400
SUPPORTED_SUFFIXES = {".txt", ".pdf", ".docx", ".doc"}


@dataclass
class Chunk:
    chunk_id: str
    file: str
    page: int | None
    text: str


class DocumentIndex:
    """BM25 keyword index over local PDF/DOC/DOCX/TXT files.

    Built once at startup from everything under `docs_dir`. No persistence
    or incremental updates in v1 — restart the pod to re-scan after adding
    documents.
    """

    def __init__(self, docs_dir: Path):
        self.docs_dir = docs_dir
        self.chunks: list[Chunk] = []
        self._by_id: dict[str, Chunk] = {}
        self._bm25: BM25Plus | None = None

    def build(self) -> None:
        self.chunks = []
        self._by_id = {}
        if self.docs_dir.is_dir():
            for path in sorted(self.docs_dir.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
                    continue
                try:
                    for chunk in self._extract(path):
                        self.chunks.append(chunk)
                        self._by_id[chunk.chunk_id] = chunk
                except Exception:
                    logger.exception("Failed to index %s, skipping", path)
        else:
            logger.warning("Docs directory %s does not exist yet", self.docs_dir)

        corpus = [chunk.text.split() for chunk in self.chunks] or [[]]
        # BM25Plus, not the classic BM25Okapi: Okapi's raw IDF formula goes
        # negative whenever a term appears in more than half the corpus,
        # which happens constantly with only a handful of indexed documents
        # (the expected case here, not an edge case) — confirmed by hand,
        # it silently turned genuine top matches into negative scores that
        # the `score <= 0` filter below then discarded as "no match" even
        # though the query matched perfectly. BM25Plus's extra delta term
        # keeps scores non-negative regardless of corpus size.
        self._bm25 = BM25Plus(corpus)
        logger.info("Indexed %d chunks from %s", len(self.chunks), self.docs_dir)

    def _extract(self, path: Path) -> list[Chunk]:
        suffix = path.suffix.lower()
        rel = str(path.relative_to(self.docs_dir))
        file_hash = hashlib.sha1(rel.encode()).hexdigest()[:8]

        if suffix == ".txt":
            text = path.read_text(errors="ignore")
            return self._chunk_text(text, rel, file_hash, page=None)

        if suffix == ".pdf":
            chunks: list[Chunk] = []
            reader = PdfReader(str(path))
            for page_num, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                chunks.extend(
                    self._chunk_text(
                        text, rel, file_hash, page=page_num, start_index=len(chunks)
                    )
                )
            return chunks

        if suffix == ".docx":
            doc = DocxDocument(str(path))
            text = "\n".join(p.text for p in doc.paragraphs)
            return self._chunk_text(text, rel, file_hash, page=None)

        if suffix == ".doc":
            # Legacy binary format: python-docx can't read it. antiword is a
            # best-effort fallback (plain text extraction only, no tables/
            # formatting) — if it's missing or fails, the file is skipped
            # with a warning rather than failing the whole index build.
            text = self._extract_doc_legacy(path)
            return self._chunk_text(text, rel, file_hash, page=None)

        return []

    @staticmethod
    def _extract_doc_legacy(path: Path) -> str:
        try:
            result = subprocess.run(
                ["antiword", str(path)],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            return result.stdout
        except Exception:
            logger.warning("antiword failed to extract %s; skipping its content", path)
            return ""

    @staticmethod
    def _chunk_text(
        text: str,
        rel: str,
        file_hash: str,
        page: int | None,
        start_index: int = 0,
    ) -> list[Chunk]:
        words = text.split()
        chunks: list[Chunk] = []
        for i in range(0, len(words), CHUNK_WORD_TARGET):
            piece = " ".join(words[i : i + CHUNK_WORD_TARGET])
            if not piece.strip():
                continue
            idx = start_index + len(chunks)
            chunks.append(
                Chunk(chunk_id=f"{file_hash}-{idx}", file=rel, page=page, text=piece)
            )
        return chunks

    def search(self, query: str, limit: int) -> list[dict]:
        if not self.chunks or self._bm25 is None:
            return []
        scores = self._bm25.get_scores(query.split())
        ranked = sorted(zip(self.chunks, scores), key=lambda cs: cs[1], reverse=True)
        results = []
        for chunk, score in ranked[:limit]:
            if score <= 0:
                continue
            results.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "file": chunk.file,
                    "page": chunk.page,
                    "snippet": chunk.text[:280],
                    "score": float(score),
                }
            )
        return results

    def get_chunk(self, chunk_id: str) -> dict | None:
        chunk = self._by_id.get(chunk_id)
        if chunk is None:
            return None
        return {
            "chunk_id": chunk.chunk_id,
            "file": chunk.file,
            "page": chunk.page,
            "text": chunk.text,
        }

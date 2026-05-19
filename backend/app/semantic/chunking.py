"""Content chunking and payload helpers for local semantic indexing."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any, Iterable, List, Optional
from uuid import UUID

from app.core.config import settings
from app.models.semantic import SemanticContentType


WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class SemanticDocument:
    tenant_id: UUID
    project_id: Optional[UUID]
    crawl_id: UUID
    page_id: UUID
    url: str
    content_type: SemanticContentType
    text: str
    content_hash: str
    chunk_index: int = 0
    heading_context: Optional[str] = None

    @property
    def text_preview(self) -> str:
        return self.text[:300]


def normalize_text(text: str) -> str:
    """Normalize text for stable hashing and embedding input."""
    return WHITESPACE_RE.sub(" ", (text or "").strip())


def content_hash(text: str) -> str:
    """Return a stable hash for normalized content."""
    normalized = normalize_text(text).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def deterministic_point_id(document: SemanticDocument, embedding_model: str) -> str:
    """Return a stable UUID-like point id for Qdrant upserts."""
    seed = "|".join(
        [
            str(document.tenant_id),
            str(document.crawl_id),
            str(document.page_id),
            embedding_model,
            document.content_type.value,
            str(document.chunk_index),
            document.content_hash,
        ]
    )
    return str(UUID(hashlib.md5(seed.encode("utf-8")).hexdigest()))


def build_vector_payload(document: SemanticDocument, embedding_model: str) -> dict[str, Any]:
    """Create the Qdrant payload required by the semantic API."""
    return {
        "tenant_id": str(document.tenant_id),
        "project_id": str(document.project_id) if document.project_id else None,
        "crawl_id": str(document.crawl_id),
        "page_id": str(document.page_id),
        "url": document.url,
        "content_type": document.content_type.value,
        "heading_context": document.heading_context,
        "chunk_index": document.chunk_index,
        "text_preview": document.text_preview,
        "content_hash": document.content_hash,
        "embedding_model": embedding_model,
    }


class SemanticContentChunker:
    """Build semantic documents from crawled page records."""

    def __init__(
        self,
        max_words: int = settings.SEMANTIC_CHUNK_MAX_WORDS,
        overlap_words: int = settings.SEMANTIC_CHUNK_OVERLAP_WORDS,
    ):
        self.max_words = max(1, int(max_words))
        self.overlap_words = max(0, min(int(overlap_words), self.max_words // 2))

    def build_page_documents(self, page: Any, crawl: Any) -> List[SemanticDocument]:
        documents: List[SemanticDocument] = []
        heading_context = self._heading_context(page)

        self._append_document(
            documents,
            page=page,
            crawl=crawl,
            content_type=SemanticContentType.full_text,
            text=getattr(page, "text_content", None),
            heading_context=heading_context,
        )
        self._append_document(
            documents,
            page=page,
            crawl=crawl,
            content_type=SemanticContentType.title,
            text=getattr(page, "title", None),
            heading_context=heading_context,
        )
        self._append_document(
            documents,
            page=page,
            crawl=crawl,
            content_type=SemanticContentType.meta_description,
            text=getattr(page, "meta_description", None),
            heading_context=heading_context,
        )

        for index, heading in enumerate(self._iter_headings(page)):
            self._append_document(
                documents,
                page=page,
                crawl=crawl,
                content_type=SemanticContentType.heading,
                text=heading,
                heading_context=heading,
                chunk_index=index,
            )

        for index, chunk in enumerate(self.chunk_text(getattr(page, "text_content", None))):
            self._append_document(
                documents,
                page=page,
                crawl=crawl,
                content_type=SemanticContentType.chunk,
                text=chunk,
                heading_context=heading_context,
                chunk_index=index,
            )

        return documents

    def chunk_text(self, text: Optional[str]) -> List[str]:
        clean = normalize_text(text or "")
        if not clean:
            return []

        words = clean.split()
        if len(words) <= self.max_words:
            return [clean]

        chunks: List[str] = []
        step = self.max_words - self.overlap_words
        start = 0
        while start < len(words):
            end = min(start + self.max_words, len(words))
            chunks.append(" ".join(words[start:end]))
            if end >= len(words):
                break
            start += step
        return chunks

    def _append_document(
        self,
        documents: List[SemanticDocument],
        page: Any,
        crawl: Any,
        content_type: SemanticContentType,
        text: Optional[str],
        heading_context: Optional[str],
        chunk_index: int = 0,
    ) -> None:
        clean = normalize_text(text or "")
        if not clean:
            return
        documents.append(
            SemanticDocument(
                tenant_id=crawl.tenant_id,
                project_id=crawl.project_id,
                crawl_id=crawl.id,
                page_id=page.id,
                url=page.url,
                content_type=content_type,
                text=clean,
                content_hash=content_hash(clean),
                chunk_index=chunk_index,
                heading_context=heading_context,
            )
        )

    def _iter_headings(self, page: Any) -> Iterable[str]:
        for field in ("h1", "h2", "h3", "h4", "h5", "h6"):
            values = getattr(page, field, None) or []
            if isinstance(values, str):
                values = [values]
            for value in values:
                clean = normalize_text(str(value))
                if clean:
                    yield clean

    def _heading_context(self, page: Any) -> Optional[str]:
        for heading in self._iter_headings(page):
            return heading[:500]
        return None

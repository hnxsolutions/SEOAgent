"""Chunking and vector payload helpers for user-provided knowledge."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.core.config import settings
from app.models.knowledge import KnowledgeSourceType
from app.semantic.chunking import content_hash, normalize_text


@dataclass(frozen=True)
class KnowledgeChunkDocument:
    tenant_id: UUID
    project_id: Optional[UUID]
    source_id: UUID
    document_id: UUID
    title: str
    source_type: KnowledgeSourceType
    text: str
    content_hash: str
    chunk_index: int
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def text_preview(self) -> str:
        return self.text[:300]


def deterministic_knowledge_point_id(document: KnowledgeChunkDocument, embedding_model: str) -> str:
    """Return a stable UUID-like point id for knowledge chunks."""
    seed = "|".join(
        [
            str(document.tenant_id),
            str(document.source_id),
            str(document.document_id),
            embedding_model,
            str(document.chunk_index),
            document.content_hash,
        ]
    )
    return str(UUID(hashlib.md5(seed.encode("utf-8")).hexdigest()))


def build_knowledge_vector_payload(
    document: KnowledgeChunkDocument,
    embedding_model: str,
    point_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create Qdrant payload for local knowledge retrieval."""
    return {
        "tenant_id": str(document.tenant_id),
        "project_id": str(document.project_id) if document.project_id else None,
        "source_id": str(document.source_id),
        "document_id": str(document.document_id),
        "title": document.title,
        "source_type": document.source_type.value if hasattr(document.source_type, "value") else str(document.source_type),
        "content_type": "knowledge_chunk",
        "chunk_index": document.chunk_index,
        "text_preview": document.text_preview,
        "chunk_text": document.text,
        "content_hash": document.content_hash,
        "embedding_model": embedding_model,
        "qdrant_point_id": point_id,
        "metadata": document.metadata or {},
    }


class KnowledgeChunker:
    """Chunk normalized knowledge documents with word-window overlap."""

    def __init__(
        self,
        max_words: int = settings.SEMANTIC_CHUNK_MAX_WORDS,
        overlap_words: int = settings.SEMANTIC_CHUNK_OVERLAP_WORDS,
    ):
        self.max_words = max(1, int(max_words))
        self.overlap_words = max(0, min(int(overlap_words), self.max_words // 2))

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

    def build_chunks(self, document: Any, source: Any) -> List[KnowledgeChunkDocument]:
        chunks = []
        for index, text in enumerate(self.chunk_text(getattr(document, "normalized_text", None))):
            metadata = dict(getattr(document, "metadata_json", None) or {})
            metadata.update({"source_title": getattr(source, "title", None), "document_title": document.title})
            chunks.append(
                KnowledgeChunkDocument(
                    tenant_id=document.tenant_id,
                    project_id=document.project_id,
                    source_id=source.id,
                    document_id=document.id,
                    title=document.title,
                    source_type=source.source_type,
                    text=text,
                    content_hash=content_hash(text),
                    chunk_index=index,
                    metadata=metadata,
                )
            )
        return chunks

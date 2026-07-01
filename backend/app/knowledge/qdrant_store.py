"""Qdrant adapter for local knowledge-base vectors."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

import structlog
from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.core.config import settings
from app.core.qdrant import get_qdrant

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class KnowledgeVectorRecord:
    point_id: str
    vector: List[float]
    payload: Dict[str, Any]


class QdrantKnowledgeStore:
    """Qdrant wrapper for tenant/project scoped knowledge retrieval."""

    def __init__(
        self,
        client: Optional[QdrantClient] = None,
        collection_name: str = settings.KNOWLEDGE_QDRANT_COLLECTION,
    ):
        self.client = client or get_qdrant()
        self.collection_name = collection_name

    def ensure_collection(self, vector_size: int) -> None:
        if not self._collection_exists():
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
            )
            logger.info("Created knowledge Qdrant collection", collection=self.collection_name, vector_size=vector_size)

        self._ensure_payload_indexes()

    def upsert_vectors(self, records: Sequence[KnowledgeVectorRecord]) -> int:
        if not records:
            return 0
        points = [
            models.PointStruct(id=record.point_id, vector=record.vector, payload=record.payload)
            for record in records
        ]
        self.client.upsert(collection_name=self.collection_name, points=points, wait=True)
        return len(points)

    def search(
        self,
        query_vector: List[float],
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        source_id: Optional[UUID] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            query_filter=self._scope_filter(tenant_id, project_id, source_id),
            limit=limit,
            with_payload=True,
        )
        return [self._hit_to_dict(hit) for hit in results]

    def _scope_filter(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        source_id: Optional[UUID] = None,
    ) -> models.Filter:
        must = [self._match("tenant_id", str(tenant_id))]
        if project_id:
            must.append(self._match("project_id", str(project_id)))
        if source_id:
            must.append(self._match("source_id", str(source_id)))
        return models.Filter(must=must)

    def _match(self, key: str, value: Any) -> models.FieldCondition:
        return models.FieldCondition(key=key, match=models.MatchValue(value=value))

    def _ensure_payload_indexes(self) -> None:
        indexes = {
            "tenant_id": models.PayloadSchemaType.KEYWORD,
            "project_id": models.PayloadSchemaType.KEYWORD,
            "source_id": models.PayloadSchemaType.KEYWORD,
            "document_id": models.PayloadSchemaType.KEYWORD,
            "source_type": models.PayloadSchemaType.KEYWORD,
            "content_type": models.PayloadSchemaType.KEYWORD,
        }
        for field_name, schema in indexes.items():
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field_name,
                    field_schema=schema,
                )
            except Exception as exc:
                logger.debug("Qdrant payload index unavailable", field=field_name, error=str(exc))

    def _collection_exists(self) -> bool:
        collections = self.client.get_collections()
        return self.collection_name in {collection.name for collection in collections.collections}

    def _collection_vector_size(self, collection: Any) -> Optional[int]:
        vectors = getattr(getattr(getattr(collection, "config", None), "params", None), "vectors", None)
        if hasattr(vectors, "size"):
            return int(vectors.size)
        if isinstance(vectors, dict) and vectors:
            first = next(iter(vectors.values()))
            if hasattr(first, "size"):
                return int(first.size)
        return None

    def _hit_to_dict(self, hit: Any) -> Dict[str, Any]:
        return {
            "point_id": str(hit.id),
            "score": float(hit.score),
            "payload": dict(hit.payload or {}),
        }

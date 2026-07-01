"""Qdrant wrapper for local semantic SEO vectors."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

import structlog
from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.core.config import settings
from app.core.qdrant import get_qdrant

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SemanticVectorRecord:
    point_id: str
    vector: List[float]
    payload: Dict[str, Any]


class QdrantSemanticStore:
    """Thin Qdrant adapter with tenant/project scoped filters."""

    def __init__(
        self,
        client: Optional[QdrantClient] = None,
        collection_name: str = settings.SEMANTIC_QDRANT_COLLECTION,
    ):
        self.client = client or get_qdrant()
        self.collection_name = collection_name

    def ensure_collection(self, vector_size: int) -> None:
        """Create the semantic collection if needed."""
        if not self._collection_exists():
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
            )
            logger.info("Created semantic Qdrant collection", collection=self.collection_name, vector_size=vector_size)

        self._ensure_payload_indexes()

    def upsert_vectors(self, records: Sequence[SemanticVectorRecord]) -> int:
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
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            query_filter=self._scope_filter(tenant_id, project_id),
            limit=limit,
            with_payload=True,
        )
        return [self._hit_to_dict(hit) for hit in results]

    def similar_to_point(
        self,
        point_id: str,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        crawl_id: Optional[UUID] = None,
        exclude_page_id: Optional[UUID] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        records = self.client.retrieve(
            collection_name=self.collection_name,
            ids=[point_id],
            with_payload=True,
            with_vectors=True,
        )
        if not records:
            return []

        vector = self._record_vector(records[0])
        if not vector:
            return []

        query_filter = self._scope_filter(
            tenant_id,
            project_id,
            crawl_id=crawl_id,
            content_type="full_text",
            exclude_page_id=exclude_page_id,
        )
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        return [self._hit_to_dict(hit) for hit in results]

    def cluster_crawl(
        self,
        tenant_id: UUID,
        crawl_id: UUID,
        project_id: Optional[UUID] = None,
        limit: int = 500,
        similarity_threshold: float = 0.78,
    ) -> List[Dict[str, Any]]:
        records = self._scroll_page_vectors(tenant_id, crawl_id, project_id, limit)
        clusters: List[Dict[str, Any]] = []
        assigned: set[str] = set()

        for record in records:
            point_id = str(record.id)
            if point_id in assigned:
                continue

            vector = self._record_vector(record)
            payload = dict(record.payload or {})
            members = [self._cluster_member(record, 1.0)]
            assigned.add(point_id)

            for candidate in records:
                candidate_id = str(candidate.id)
                if candidate_id in assigned:
                    continue
                candidate_vector = self._record_vector(candidate)
                similarity = self._cosine_similarity(vector, candidate_vector)
                if similarity >= similarity_threshold:
                    members.append(self._cluster_member(candidate, similarity))
                    assigned.add(candidate_id)

            clusters.append(
                {
                    "cluster_id": len(clusters) + 1,
                    "representative_url": payload.get("url"),
                    "representative_page_id": payload.get("page_id"),
                    "size": len(members),
                    "pages": members,
                }
            )

        return clusters

    def _scroll_page_vectors(
        self,
        tenant_id: UUID,
        crawl_id: UUID,
        project_id: Optional[UUID],
        limit: int,
    ) -> List[Any]:
        records: List[Any] = []
        offset = None
        scroll_filter = self._scope_filter(tenant_id, project_id, crawl_id=crawl_id, content_type="full_text")

        while len(records) < limit:
            batch, offset = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=scroll_filter,
                limit=min(100, limit - len(records)),
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            records.extend(batch)
            if offset is None:
                break
        return records

    def _scope_filter(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        crawl_id: Optional[UUID] = None,
        content_type: Optional[str] = None,
        exclude_page_id: Optional[UUID] = None,
    ) -> models.Filter:
        must = [self._match("tenant_id", str(tenant_id))]
        if project_id:
            must.append(self._match("project_id", str(project_id)))
        if crawl_id:
            must.append(self._match("crawl_id", str(crawl_id)))
        if content_type:
            must.append(self._match("content_type", content_type))

        must_not = [self._match("page_id", str(exclude_page_id))] if exclude_page_id else None
        return models.Filter(must=must, must_not=must_not)

    def _match(self, key: str, value: Any) -> models.FieldCondition:
        return models.FieldCondition(key=key, match=models.MatchValue(value=value))

    def _ensure_payload_indexes(self) -> None:
        indexes = {
            "tenant_id": models.PayloadSchemaType.KEYWORD,
            "project_id": models.PayloadSchemaType.KEYWORD,
            "crawl_id": models.PayloadSchemaType.KEYWORD,
            "page_id": models.PayloadSchemaType.KEYWORD,
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

    def _record_vector(self, record: Any) -> List[float]:
        vector = getattr(record, "vector", None)
        if isinstance(vector, dict):
            vector = next(iter(vector.values()), [])
        return [float(value) for value in (vector or [])]

    def _cluster_member(self, record: Any, similarity: float) -> Dict[str, Any]:
        payload = dict(record.payload or {})
        return {
            "page_id": payload.get("page_id"),
            "url": payload.get("url"),
            "score": round(float(similarity), 4),
            "text_preview": payload.get("text_preview"),
        }

    def _cosine_similarity(self, left: List[float], right: List[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if not left_norm or not right_norm:
            return 0.0
        return dot / (left_norm * right_norm)

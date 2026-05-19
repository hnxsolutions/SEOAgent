from types import SimpleNamespace
from uuid import uuid4

from app.knowledge.chunking import (
    KnowledgeChunker,
    build_knowledge_vector_payload,
    deterministic_knowledge_point_id,
)
from app.models.knowledge import KnowledgeSourceType
from app.semantic.chunking import content_hash, normalize_text


def test_knowledge_content_hash_normalizes_text():
    assert normalize_text("  Service\n\nDescription\t ") == "Service Description"
    assert content_hash("Useful   Service") == content_hash("useful service")


def test_knowledge_chunking_uses_overlap():
    chunker = KnowledgeChunker(max_words=6, overlap_words=2)
    chunks = chunker.chunk_text(" ".join(f"word{i}" for i in range(14)))

    assert len(chunks) == 3
    assert chunks[0].split()[-2:] == chunks[1].split()[:2]
    assert chunks[1].split()[-2:] == chunks[2].split()[:2]


def test_knowledge_vector_payload_and_point_id_are_deterministic():
    tenant_id = uuid4()
    project_id = uuid4()
    source_id = uuid4()
    document_id = uuid4()
    source = SimpleNamespace(id=source_id, title="Business profile", source_type=KnowledgeSourceType.business_profile)
    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        project_id=project_id,
        title="Business profile",
        normalized_text="We build local SEO landing pages and technical SEO systems.",
        metadata_json={"audience": "local businesses"},
    )
    chunk = KnowledgeChunker(max_words=50).build_chunks(document, source)[0]
    point_id = deterministic_knowledge_point_id(chunk, "BAAI/bge-small-en-v1.5")
    payload = build_knowledge_vector_payload(chunk, "BAAI/bge-small-en-v1.5", point_id=point_id)

    assert payload["tenant_id"] == str(tenant_id)
    assert payload["project_id"] == str(project_id)
    assert payload["source_id"] == str(source_id)
    assert payload["document_id"] == str(document_id)
    assert payload["source_type"] == "business_profile"
    assert payload["content_type"] == "knowledge_chunk"
    assert payload["chunk_text"].startswith("We build local SEO")
    assert point_id == deterministic_knowledge_point_id(chunk, "BAAI/bge-small-en-v1.5")

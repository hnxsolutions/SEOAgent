from types import SimpleNamespace
from uuid import uuid4

from app.models.semantic import SemanticContentType
from app.semantic.chunking import (
    SemanticContentChunker,
    build_vector_payload,
    content_hash,
    deterministic_point_id,
    normalize_text,
)


def make_crawl():
    return SimpleNamespace(id=uuid4(), tenant_id=uuid4(), project_id=uuid4())


def make_page(**overrides):
    values = {
        "id": uuid4(),
        "url": "https://example.com/page",
        "title": "Useful title",
        "meta_description": "Useful description for the page.",
        "h1": ["Main heading"],
        "h2": ["Section heading"],
        "h3": [],
        "h4": [],
        "h5": [],
        "h6": [],
        "text_content": " ".join(f"word{i}" for i in range(20)),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_content_hash_normalizes_whitespace_and_case():
    assert normalize_text("  Hello\n\nWorld\t ") == "Hello World"
    assert content_hash("Hello   World") == content_hash("hello world")


def test_chunking_uses_word_windows_with_overlap():
    chunker = SemanticContentChunker(max_words=8, overlap_words=2)
    chunks = chunker.chunk_text(" ".join(f"word{i}" for i in range(20)))

    assert len(chunks) == 3
    assert chunks[0].split()[-2:] == chunks[1].split()[:2]
    assert chunks[1].split()[-2:] == chunks[2].split()[:2]


def test_page_documents_include_required_content_types():
    crawl = make_crawl()
    page = make_page()
    documents = SemanticContentChunker(max_words=100).build_page_documents(page, crawl)
    content_types = {document.content_type for document in documents}

    assert SemanticContentType.full_text in content_types
    assert SemanticContentType.title in content_types
    assert SemanticContentType.meta_description in content_types
    assert SemanticContentType.heading in content_types
    assert SemanticContentType.chunk in content_types


def test_vector_payload_and_point_id_are_deterministic():
    crawl = make_crawl()
    page = make_page()
    document = SemanticContentChunker(max_words=100).build_page_documents(page, crawl)[0]
    payload = build_vector_payload(document, "BAAI/bge-small-en-v1.5")

    assert payload["tenant_id"] == str(crawl.tenant_id)
    assert payload["project_id"] == str(crawl.project_id)
    assert payload["crawl_id"] == str(crawl.id)
    assert payload["page_id"] == str(page.id)
    assert payload["url"] == page.url
    assert payload["content_type"] == "full_text"
    assert payload["heading_context"] == "Main heading"
    assert payload["chunk_index"] == 0
    assert payload["text_preview"]

    assert deterministic_point_id(document, "BAAI/bge-small-en-v1.5") == deterministic_point_id(
        document,
        "BAAI/bge-small-en-v1.5",
    )

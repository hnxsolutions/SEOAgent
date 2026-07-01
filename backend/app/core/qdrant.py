"""
SEO Agent SaaS - Qdrant Vector Database Configuration
"""
from qdrant_client import QdrantClient
from qdrant_client.http import models
from typing import Optional
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

# Qdrant client instance
qdrant_client: Optional[QdrantClient] = None
qdrant_error: Optional[str] = None

# Vector collection configurations for fully local embeddings
VECTOR_SIZE = settings.SEMANTIC_EMBEDDING_DIMENSION
DISTANCE = models.Distance.COSINE


async def init_qdrant():
    """Initialize Qdrant connection"""
    global qdrant_client, qdrant_error
    try:
        qdrant_client = _create_qdrant_client()
        # Test connection
        qdrant_client.get_collections()
        qdrant_error = None
        logger.info("Qdrant connection established successfully")
        
        # Initialize collections
        await _initialize_collections()
        
    except Exception as e:
        qdrant_error = str(e)
        logger.error(f"Failed to connect to Qdrant: {e}")
        raise


async def close_qdrant():
    """Close Qdrant connection"""
    global qdrant_client
    if qdrant_client:
        qdrant_client.close()
        logger.info("Qdrant connection closed")


def get_qdrant() -> QdrantClient:
    """Get Qdrant client instance"""
    if qdrant_client is None:
        # Synchronous initialization if not already done
        _init_qdrant_sync()
    return qdrant_client


def get_qdrant_status() -> dict:
    """Return a health-friendly Qdrant status."""
    mode = "embedded/local" if settings.QDRANT_LOCAL_PATH else "http"
    return {
        "available": qdrant_client is not None and qdrant_error is None,
        "mode": mode,
        "url": None if settings.QDRANT_LOCAL_PATH else settings.get_qdrant_url,
        "local_path": settings.QDRANT_LOCAL_PATH,
        "error": qdrant_error,
    }


def _init_qdrant_sync():
    """Synchronous initialization of Qdrant"""
    global qdrant_client, qdrant_error
    try:
        qdrant_client = _create_qdrant_client()
        qdrant_client.get_collections()
        qdrant_error = None
        logger.info("Qdrant connection established successfully (sync)")
    except Exception as e:
        qdrant_error = str(e)
        logger.error(f"Failed to connect to Qdrant: {e}")
        raise


async def _initialize_collections():
    """Initialize required vector collections"""
    collections_to_create = [
        {
            "name": settings.SEMANTIC_QDRANT_COLLECTION,
            "vectors_config": models.VectorParams(
                size=VECTOR_SIZE,
                distance=DISTANCE,
            ),
        },
        {
            "name": settings.KNOWLEDGE_QDRANT_COLLECTION,
            "vectors_config": models.VectorParams(
                size=VECTOR_SIZE,
                distance=DISTANCE,
            ),
        },
    ]
    
    for collection_config in collections_to_create:
        try:
            # Check if collection exists
            collections = qdrant_client.get_collections()
            collection_names = [c.name for c in collections.collections]
            
            if collection_config["name"] not in collection_names:
                # Create collection
                qdrant_client.create_collection(
                    collection_name=collection_config["name"],
                    vectors_config=collection_config["vectors_config"],
                )
                logger.info(f"Created Qdrant collection: {collection_config['name']}")
            
            # Create payload indexes for efficient filtering
            qdrant_client.create_payload_index(
                collection_name=collection_config["name"],
                field_name="tenant_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            qdrant_client.create_payload_index(
                collection_name=collection_config["name"],
                field_name="project_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            qdrant_client.create_payload_index(
                collection_name=collection_config["name"],
                field_name="crawl_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            qdrant_client.create_payload_index(
                collection_name=collection_config["name"],
                field_name="page_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            qdrant_client.create_payload_index(
                collection_name=collection_config["name"],
                field_name="content_type",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            
        except Exception as e:
            logger.warning(f"Error initializing collection {collection_config['name']}: {e}")


def _create_qdrant_client() -> QdrantClient:
    """Create a Qdrant client for server or embedded local storage."""
    if settings.QDRANT_LOCAL_PATH:
        return QdrantClient(path=settings.QDRANT_LOCAL_PATH)
    return QdrantClient(
        url=settings.get_qdrant_url,
        api_key=settings.QDRANT_API_KEY,
        prefer_grpc=True,
    )

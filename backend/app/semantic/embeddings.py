"""Embedding provider abstraction for fully local semantic indexing."""
from __future__ import annotations

from typing import List, Optional, Protocol, Sequence

from app.core.config import settings


class EmbeddingProvider(Protocol):
    model_name: str

    @property
    def dimension(self) -> int:
        ...

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        ...


class SentenceTransformerEmbeddingProvider:
    """Local sentence-transformers provider.

    This provider never calls paid AI APIs. The model is loaded lazily so tests
    can exercise the semantic stack without downloading model weights.
    """

    def __init__(self, model_name: str = settings.SEMANTIC_EMBEDDING_MODEL):
        self.model_name = model_name
        self._model = None
        self._dimension: Optional[int] = None

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._dimension = int(self._load_model().get_sentence_embedding_dimension())
        return self._dimension

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []

        model = self._load_model()
        encoded = model.encode(
            list(texts),
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        vectors = encoded.tolist() if hasattr(encoded, "tolist") else encoded
        return [[float(value) for value in vector] for vector in vectors]

    def _load_model(self):
        if self._model is not None:
            return self._model

        try:
            from sentence_transformers import SentenceTransformer
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "sentence-transformers is required for local semantic indexing. "
                "Install backend requirements before running indexing jobs."
            ) from exc

        self._model = SentenceTransformer(self.model_name)
        return self._model

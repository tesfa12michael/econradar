"""Text embeddings for the RAG corpus (feature 2.2).

Model: `sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions — the model
architecture.md decision #10 names, and exactly the width `embeddings.embedding`
was created at, so no migration is needed to store it.

**Run locally, via ONNX rather than torch** (decision #23). Decision #10 put
Mistral Embed on the cloud path with Sentence-Transformers as the offline
fallback; that ordering is inverted here, and the reason is arithmetic. The
cloud path costs a network round trip on every chat query and a rate limit
shared with narration, for a model that is 83 MB and answers in milliseconds.
Running it locally also means retrieval has no external dependency at all: the
chat page cannot be taken down by someone else's quota. `fastembed` executes the
same weights through `onnxruntime`, which keeps torch — and roughly a gigabyte
of it — off a 2 GB box.

The model is loaded on first use and then held for the process lifetime. Import
is deferred for the same reason: a box that never serves a chat query never pays
for the runtime.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from config import settings
from logging_config import get_logger
from models import EMBEDDING_DIM

logger = get_logger(__name__)


class EmbeddingUnavailable(RuntimeError):
    """The embedding model could not be loaded or produced an unusable vector."""


_model: Any = None
# Loading is not thread-safe and `embed_texts` hands work to a worker thread, so
# two concurrent first-calls could otherwise each build a model.
_lock = threading.Lock()


def _load() -> Any:
    global _model
    with _lock:
        if _model is not None:
            return _model
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # pragma: no cover - declared dependency
            raise EmbeddingUnavailable(f"fastembed is not installed: {exc}") from exc
        try:
            _model = TextEmbedding(settings.embedding_model)
        except Exception as exc:
            raise EmbeddingUnavailable(
                f"could not load {settings.embedding_model}: {type(exc).__name__}: {exc}"
            ) from exc
        logger.info("embedding model loaded: %s (%d dims)", settings.embedding_model, EMBEDDING_DIM)
        return _model


def _embed_sync(texts: list[str]) -> list[list[float]]:
    model = _load()
    vectors = [[float(v) for v in vec] for vec in model.embed(texts)]
    if len(vectors) != len(texts):
        raise EmbeddingUnavailable(
            f"embedder returned {len(vectors)} vectors for {len(texts)} texts"
        )
    for vector in vectors:
        if len(vector) != EMBEDDING_DIM:
            # A width mismatch would be accepted by Python and rejected by Postgres
            # halfway through a batch insert, so it is caught here instead.
            raise EmbeddingUnavailable(
                f"embedder returned {len(vector)} dims, but the column is vector({EMBEDDING_DIM})"
            )
    return vectors


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch off the event loop — ONNX inference is CPU-bound."""
    if not texts:
        return []
    return await asyncio.to_thread(_embed_sync, texts)


async def embed_query(text: str) -> list[float]:
    """Embed a single query. MiniLM needs no query/document prefix."""
    vectors = await embed_texts([text])
    return vectors[0]


def is_available() -> bool:
    """Whether embeddings can be produced, without raising if they cannot."""
    try:
        _load()
        return True
    except EmbeddingUnavailable as exc:
        logger.warning("embeddings unavailable: %s", exc)
        return False

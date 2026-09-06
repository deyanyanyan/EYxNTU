"""Local embeddings via sentence-transformers (no network at inference time).

The model is loaded lazily and cached per process. Weights come from HF_HOME;
set HF_HUB_OFFLINE=1 once they are present for a fully air-gapped run.
"""
from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np

from app.config import settings

log = logging.getLogger(__name__)


@lru_cache
def _model():
    from sentence_transformers import SentenceTransformer

    log.info("loading embedding model %s on %s", settings.embedding_model, settings.embedding_device)
    m = SentenceTransformer(settings.embedding_model, device=settings.embedding_device)
    dim = m.get_sentence_embedding_dimension()
    if dim != settings.embedding_dim:
        raise RuntimeError(
            f"EMBEDDING_DIM={settings.embedding_dim} but model {settings.embedding_model} produces {dim}. "
            "Fix .env and re-run the migration (vector column width must match)."
        )
    return m


def embed_texts(texts: list[str], *, is_query: bool = False) -> list[list[float]]:
    if not texts:
        return []
    vecs = _model().encode(
        texts,
        batch_size=settings.embedding_batch_size,
        normalize_embeddings=True,  # cosine == dot product downstream
        show_progress_bar=False,
    )
    return np.asarray(vecs, dtype=np.float32).tolist()


def embed_query(text: str) -> list[float]:
    return embed_texts([text], is_query=True)[0]

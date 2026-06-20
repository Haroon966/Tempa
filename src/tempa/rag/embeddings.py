from __future__ import annotations

import threading
from functools import lru_cache

from sentence_transformers import SentenceTransformer

MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
_embed_lock = threading.Lock()


class LocalEmbedder:
    def __init__(self) -> None:
        self._model = SentenceTransformer(MODEL_NAME, trust_remote_code=True)

    def embed(self, text: str) -> list[float]:
        with _embed_lock:
            vector = self._model.encode(text, normalize_embeddings=True)
        return vector.tolist()


@lru_cache
def get_embedder() -> LocalEmbedder:
    return LocalEmbedder()

from __future__ import annotations

import math
import re
import uuid
from collections import Counter
from typing import Protocol, Sequence

import numpy as np

from src.chunking import DocumentChunk


TOKEN_RE = re.compile(r"[A-Za-z0-9_\-\.]+")


def normalize_tokens(text: str) -> list[str]:
    """The same normalization is used for both BM25 corpus ingestion and queries."""
    return [t.lower() for t in TOKEN_RE.findall(text)]


class BM25Index:
    def __init__(self, chunks: Sequence[DocumentChunk]) -> None:
        self.chunks = list(chunks)
        self.tokenized = [normalize_tokens(c.content) for c in self.chunks]
        try:
            from rank_bm25 import BM25Okapi  # type: ignore
            self._engine = BM25Okapi(self.tokenized)
            self._fallback = False
        except Exception:
            self._engine = None
            self._fallback = True
            self._doc_freq = Counter()
            for tokens in self.tokenized:
                self._doc_freq.update(set(tokens))

    def _fallback_scores(self, query_tokens: list[str]) -> np.ndarray:
        n = max(len(self.tokenized), 1)
        scores = []
        for doc_tokens in self.tokenized:
            counts = Counter(doc_tokens)
            score = 0.0
            for q in query_tokens:
                df = self._doc_freq.get(q, 0)
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                score += counts.get(q, 0) * idf
            scores.append(score)
        return np.asarray(scores, dtype=float)

    def search(self, query: str, k: int = 5) -> list[tuple[DocumentChunk, float]]:
        q = normalize_tokens(query)
        if self._fallback:
            scores = self._fallback_scores(q)
        else:
            scores = np.asarray(self._engine.get_scores(q), dtype=float)
        order = np.argsort(-scores)[: min(k, len(scores))]
        return [(self.chunks[i], float(scores[i])) for i in order]


class Encoder(Protocol):
    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


class SentenceTransformerEncoder:
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        arr = self.model.encode(list(texts), convert_to_numpy=True, normalize_embeddings=True)
        return np.asarray(arr, dtype=np.float32)


class SemanticHashEncoder:
    """Offline QA/demo encoder. Production path uses SentenceTransformerEncoder.

    It expands a few domain concepts before hashing so paraphrase tests remain deterministic
    without downloading a neural model. It is intentionally labeled demo-only in the UI.
    """

    CONCEPTS = {
        "zero_downtime": {"zero", "downtime", "rolling", "upgrade", "deployment", "deploy", "traffic", "availability", "uninterrupted", "drain"},
        "socket_pool": {"econnreset", "socket", "connection", "pool", "starvation", "network", "keepalive", "reset"},
        "secret_rotation": {"secret", "credential", "rotate", "rotation", "key", "token", "restart", "reload"},
        "rate_limit": {"rate", "limit", "throttle", "quota", "429", "retry_after_ms", "backoff"},
        "observability": {"trace", "telemetry", "metric", "logging", "span", "correlation", "x-asteria-trace"},
        "cache": {"cache", "ttl", "eviction", "stale", "invalidate", "redis"},
        "auth": {"oauth", "jwt", "authentication", "authorization", "scope", "rbac"},
        "resilience": {"retry", "circuit", "breaker", "failure", "timeout", "fallback"},
        "pagination": {"cursor", "pagination", "page", "continuation", "next"},
        "idempotency": {"idempotent", "idempotency", "duplicate", "replay", "request"},
    }

    def __init__(self, dims: int = 256) -> None:
        self.dims = dims

    def _vector(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dims, dtype=np.float32)
        tokens = set(normalize_tokens(text))
        expanded = set(tokens)
        for name, group in self.CONCEPTS.items():
            if tokens & group:
                expanded.add(f"concept::{name}")
        for tok in expanded:
            idx = abs(hash(tok)) % self.dims
            vec[idx] += 1.0
        norm = np.linalg.norm(vec)
        return vec / norm if norm else vec

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        return np.vstack([self._vector(t) for t in texts])


class NumpyDenseIndex:
    def __init__(self, chunks: Sequence[DocumentChunk], encoder: Encoder) -> None:
        self.chunks = list(chunks)
        self.encoder = encoder
        self.embeddings = self._normalize(encoder.encode([c.content for c in self.chunks]))

    @staticmethod
    def _normalize(matrix: np.ndarray) -> np.ndarray:
        matrix = np.asarray(matrix, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms

    def search(self, query: str, k: int = 5) -> list[tuple[DocumentChunk, float]]:
        q = self._normalize(self.encoder.encode([query]))[0]
        similarities = self.embeddings @ q  # cosine similarity: higher is better
        order = np.argsort(-similarities)[: min(k, len(similarities))]
        return [(self.chunks[i], float(similarities[i])) for i in order]


class ChromaDenseIndex:
    """Embedded ChromaDB vector index using explicit, unit-normalized embeddings."""

    def __init__(self, chunks: Sequence[DocumentChunk], encoder: Encoder, collection_name: str | None = None) -> None:
        import chromadb  # type: ignore
        self.chunks = list(chunks)
        self.encoder = encoder
        self.client = chromadb.Client()
        self.collection = self.client.create_collection(
            name=collection_name or f"chunks_{uuid.uuid4().hex[:8]}",
            metadata={"hnsw:space": "cosine"},
        )
        embeddings = NumpyDenseIndex._normalize(encoder.encode([c.content for c in self.chunks]))
        self.collection.add(
            ids=[c.chunk_id for c in self.chunks],
            documents=[c.content for c in self.chunks],
            embeddings=embeddings.tolist(),
            metadatas=[{"parent_doc": c.parent_doc, "header_path": str(c.metadata.get("header_path", ""))} for c in self.chunks],
        )
        self._by_id = {c.chunk_id: c for c in self.chunks}

    def search(self, query: str, k: int = 5) -> list[tuple[DocumentChunk, float]]:
        q = NumpyDenseIndex._normalize(self.encoder.encode([query]))[0]
        result = self.collection.query(query_embeddings=[q.tolist()], n_results=min(k, len(self.chunks)))
        ids = result["ids"][0]
        distances = result["distances"][0]
        # Chroma cosine distance = 1 - cosine_similarity. Convert back so higher is better.
        return [(self._by_id[cid], float(1.0 - dist)) for cid, dist in zip(ids, distances)]

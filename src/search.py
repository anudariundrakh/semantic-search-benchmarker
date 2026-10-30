from __future__ import annotations

from pydantic import BaseModel

from src.chunking import DocumentChunk


class SearchResult(BaseModel):
    rank: int
    chunk_id: str
    content: str
    parent_doc: str
    header_path: str
    score: float
    strategy: str


def standardize(results: list[tuple[DocumentChunk, float]], strategy: str) -> list[SearchResult]:
    return [
        SearchResult(
            rank=i,
            chunk_id=chunk.chunk_id,
            content=chunk.content,
            parent_doc=chunk.parent_doc,
            header_path=str(chunk.metadata.get("header_path", chunk.metadata.get("section_key", ""))),
            score=float(score),
            strategy=strategy,
        )
        for i, (chunk, score) in enumerate(results, start=1)
    ]


class UnifiedSearchEngine:
    def __init__(self, bm25_index, dense_index) -> None:
        self.bm25_index = bm25_index
        self.dense_index = dense_index

    def search_bm25(self, query: str, k: int = 5) -> list[SearchResult]:
        return standardize(self.bm25_index.search(query, k), "BM25")

    def search_dense(self, query: str, k: int = 5) -> list[SearchResult]:
        return standardize(self.dense_index.search(query, k), "Dense")

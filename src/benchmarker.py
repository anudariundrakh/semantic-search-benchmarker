from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.chunking import DocumentChunk, FixedSizeChunker, StructureAwareChunker
from src.indexer import BM25Index, NumpyDenseIndex, SemanticHashEncoder, SentenceTransformerEncoder


@dataclass
class QueryEval:
    query_id: str
    query: str
    query_type: str
    target_section: str
    target_phrase: str


def load_eval_queries(path: str | Path) -> list[QueryEval]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [QueryEval(**row) for row in data]


def is_relevant(chunk: DocumentChunk, item: QueryEval) -> bool:
    section_key = str(chunk.metadata.get("section_key", ""))
    header_path = str(chunk.metadata.get("header_path", "")).lower()
    return (
        section_key == item.target_section
        or item.target_section.replace("-", " ") in header_path
        or item.target_phrase.lower() in chunk.content.lower()
    )


def hit_rate_at_k(rankings: list[list[bool]], k: int) -> float:
    if not rankings:
        return 0.0
    return sum(any(row[:k]) for row in rankings) / len(rankings)


def recall_at_k(rankings: list[list[bool]], k: int) -> float:
    if not rankings:
        return 0.0
    # Each evaluation query in this assignment has one labeled relevant section/span.
    return sum((1.0 if any(row[:k]) else 0.0) for row in rankings) / len(rankings)


def mrr_at_k(rankings: list[list[bool]], k: int) -> float:
    if not rankings:
        return 0.0
    total = 0.0
    for row in rankings:
        reciprocal = 0.0
        for rank, relevant in enumerate(row[:k], start=1):
            if relevant:
                reciprocal = 1.0 / rank
                break
        total += reciprocal  # miss contributes exactly 0.0
    return total / len(rankings)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * p)))
    return ordered[idx]


def evaluate_index(index, evals: list[QueryEval], k: int = 5) -> dict:
    rankings: list[list[bool]] = []
    latencies: list[float] = []
    details = []
    for item in evals:
        start = time.perf_counter()
        results = index.search(item.query, k)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        latencies.append(elapsed_ms)
        relevance = [is_relevant(chunk, item) for chunk, _ in results]
        rankings.append(relevance)
        details.append({
            "query_id": item.query_id,
            "query": item.query,
            "query_type": item.query_type,
            "hit": any(relevance),
            "first_relevant_rank": next((i for i, x in enumerate(relevance, 1) if x), None),
            "top_header": str(results[0][0].metadata.get("header_path", "")) if results else "",
        })
    return {
        "hit_rate": hit_rate_at_k(rankings, k),
        "recall": recall_at_k(rankings, k),
        "mrr": mrr_at_k(rankings, k),
        "latency_avg_ms": statistics.fmean(latencies) if latencies else 0.0,
        "latency_p50_ms": percentile(latencies, 0.50),
        "latency_p95_ms": percentile(latencies, 0.95),
        "details": details,
    }


def build_encoder(kind: str = "demo"):
    if kind == "minilm":
        return SentenceTransformerEncoder()
    return SemanticHashEncoder()


def run_full_benchmark(corpus_path: str | Path, eval_path: str | Path, k: int = 5, encoder_kind: str = "demo") -> dict:
    corpus_path = Path(corpus_path)
    text = corpus_path.read_text(encoding="utf-8")
    evals = load_eval_queries(eval_path)
    encoder = build_encoder(encoder_kind)

    structure = StructureAwareChunker().chunk_text(text, corpus_path.name)
    small = FixedSizeChunker(256, 32).chunk_text(text, corpus_path.name)
    large = FixedSizeChunker(1024, 128).chunk_text(text, corpus_path.name)

    configs = {
        "BM25 Baseline": BM25Index(structure),
        "Dense 256": NumpyDenseIndex(small, encoder),
        "Dense 1024": NumpyDenseIndex(large, encoder),
        "Dense Structure-Aware": NumpyDenseIndex(structure, encoder),
    }
    return {name: evaluate_index(index, evals, k) for name, index in configs.items()}

# AI Prompt Log & Code Audit

## Baseline generation prompt

> You are a Staff Information Retrieval and Search Engineer. Build a modular Python 3.11+ semantic search workbench that ingests technical Markdown, compares fixed-token and structure-aware chunking, indexes content with BM25 and dense embeddings, computes Hit Rate@K / Recall@K / MRR@K / latency, exposes a Streamlit comparator, and includes pytest coverage.

I used AI to accelerate the first draft, then audited the output as untrusted code. The findings below are the specific issues I checked and corrected.

## Audit Finding 1 — cosine distance was treated as relevance

**Risk:** Chroma returns cosine *distance*, where lower is better. The initial draft displayed that value as if higher meant more relevant, which inverted ranking semantics in the UI.

```diff
- score = distance
+ score = 1.0 - distance  # convert cosine distance back to similarity
```

**Fix:** `ChromaDenseIndex.search()` explicitly converts `1 - distance`, while the NumPy path computes normalized dot-product cosine similarity directly.

## Audit Finding 2 — ground-truth leakage across chunk sizes

**Risk:** The first draft labeled queries with array positions such as `target_chunk_id=7`. Changing from 256-token to 1024-token chunks changes chunk boundaries and IDs, making evaluation invalid.

```diff
- {"query": "...", "target_chunk_id": 7}
+ {"query": "...", "target_section": "zero-downtime-rolling-deployments",
+  "target_phrase": "zero-downtime rollout drains old workers"}
```

**Fix:** `eval_queries.json` uses stable semantic section names plus unique source spans. `is_relevant()` evaluates those labels consistently across every chunking strategy.

## Audit Finding 3 — asymmetric BM25 tokenization

**Risk:** Lowercasing and punctuation stripping the corpus while sending raw queries to BM25 makes matching inconsistent, especially for identifiers and hyphenated terms.

```diff
- corpus_tokens = normalize(document)
- query_tokens = query.split()
+ corpus_tokens = normalize_tokens(document)
+ query_tokens = normalize_tokens(query)
```

**Fix:** corpus and query paths share the same `normalize_tokens()` function.

## Audit Finding 4 — Markdown code fences could be severed

**Risk:** A naive header splitter treated `#` inside fenced code as a Markdown heading, while naive line slicing could split an opening and closing ``` fence across different chunks.

**Fix:** `StructureAwareChunker` tracks `in_fence` state. Headers are recognized only outside fences, and a fenced block remains in its parent section. Automated QA asserts both fence markers stay together.

## Audit Finding 5 — incorrect MRR miss handling

**Risk:** An early implementation searched the entire ranking and awarded reciprocal-rank credit even when the relevant result was outside K. It also used a fragile `1 / rank` expression without an explicit miss path.

```diff
- first = next(i for i, hit in enumerate(row, 1) if hit)
- rr = 1 / first
+ rr = 0.0
+ for rank, hit in enumerate(row[:k], 1):
+     if hit:
+         rr = 1.0 / rank
+         break
```

**Fix:** `mrr_at_k()` only examines the first K results and assigns exactly `0.0` when the query is missed.

## Human review summary

The final implementation separates chunking, indexing, unified search, and benchmarking; keeps retrieval score direction explicit; uses stable ground truth; bounds evaluation to K correctly; and includes deterministic offline tests so QA does not depend on external model downloads.

# 5–7 Minute Video Outline

## 0:00–1:00 — Architecture & corpus
Show the folder tree and `corpus/asteria_gateway_reference.md`. Explain exact identifiers vs conceptual queries. Open `src/chunking.py` and contrast fixed 256/1024 token windows with structure-aware header splitting that preserves fenced code blocks.

## 1:00–2:30 — AI generation & audit
Open `ai_prompt_log.md`. Explain at least two real fixes: (1) Chroma cosine distance needed conversion to `1 - distance`; (2) ground truth could not use chunk array IDs because chunk sizes change boundaries. Optionally show the BM25 normalization and MRR fixes.

## 2:30–4:00 — Live search comparator
In Streamlit, search `CUSTOM_CONFIG_FLAG_XYZ` and show why BM25 is excellent for exact identifiers. Then search `How can I deploy new versions without interrupting active traffic?` and explain why dense semantic retrieval is designed for paraphrases.

## 4:00–5:30 — Benchmark dashboard
Run the benchmark. Compare BM25, Dense 256, Dense 1024, and Dense Structure-Aware on Hit Rate@K, MRR@K, and latency. Discuss the observed trade-off instead of claiming dense search always wins.

## 5:30–6:00 — QA
Run `pytest -v` and show all tests passing. Mention overlap integrity, code-fence preservation, exact lexical retrieval, semantic retrieval, and metric math.

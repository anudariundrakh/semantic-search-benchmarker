from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st

from src.benchmarker import run_full_benchmark
from src.chunking import StructureAwareChunker
from src.indexer import BM25Index, NumpyDenseIndex, SemanticHashEncoder, SentenceTransformerEncoder
from src.search import UnifiedSearchEngine

CORPUS = PROJECT_ROOT / "corpus" / "asteria_gateway_reference.md"
EVALS = PROJECT_ROOT / "data" / "eval_queries.json"

st.set_page_config(page_title="SearchWorkbench", page_icon="🔎", layout="wide")
st.title("🔎 SearchWorkbench")
st.caption("BM25 vs dense semantic retrieval • chunking benchmarks • Hit Rate / MRR / latency")

with st.sidebar:
    st.header("Settings")
    mode = st.selectbox(
        "Dense encoder",
        ["Fast Local Demo", "MiniLM (real neural embeddings)"],
        help="MiniLM downloads sentence-transformers/all-MiniLM-L6-v2 the first time. Fast Local Demo is deterministic and offline for QA.",
    )
    k = st.slider("Top K", 1, 10, 5)
@st.cache_resource(show_spinner=False)
def make_engine(mode_name: str):
    text = CORPUS.read_text(encoding="utf-8")
    chunks = StructureAwareChunker().chunk_text(text, CORPUS.name)
    encoder = SentenceTransformerEncoder() if mode_name.startswith("MiniLM") else SemanticHashEncoder()
    return UnifiedSearchEngine(BM25Index(chunks), NumpyDenseIndex(chunks, encoder)), chunks

try:
    engine, chunks = make_engine(mode)
except Exception as exc:
    st.error(f"Could not initialize {mode}: {exc}")
    st.stop()

search_tab, benchmark_tab, corpus_tab = st.tabs(["Live Search Comparator", "Benchmark Dashboard", "Corpus & Architecture"])

with search_tab:
    st.subheader("Side-by-side retrieval")
    query = st.text_input("Technical query", value="How can I deploy new versions without interrupting active traffic?")
    quick_cols = st.columns(2)
    if quick_cols[0].button("Load exact-keyword example"):
        query = "CUSTOM_CONFIG_FLAG_XYZ"
    if quick_cols[1].button("Load conceptual example"):
        query = "How can I deploy new versions without interrupting active traffic?"

    if st.button("Search", type="primary"):
        bm = engine.search_bm25(query, k)
        dense = engine.search_dense(query, k)
        left, right = st.columns(2)
        with left:
            st.markdown("### BM25 Keyword Search")
            for r in bm:
                with st.expander(f"#{r.rank} • {r.header_path or r.chunk_id} • score {r.score:.4f}", expanded=r.rank <= 2):
                    st.write(r.content[:1400])
        with right:
            st.markdown("### Dense Vector Search")
            for r in dense:
                with st.expander(f"#{r.rank} • {r.header_path or r.chunk_id} • cosine {r.score:.4f}", expanded=r.rank <= 2):
                    st.write(r.content[:1400])

with benchmark_tab:
    st.subheader("Empirical retrieval benchmark")
    st.write("Compares BM25 against dense retrieval with 256-token, 1024-token, and structure-aware chunks over the same labeled query set.")
    if st.button("Run Benchmark", type="primary"):
        with st.spinner("Running evaluation..."):
            encoder_kind = "minilm" if mode.startswith("MiniLM") else "demo"
            results = run_full_benchmark(CORPUS, EVALS, k=k, encoder_kind=encoder_kind)
        rows = []
        for name, m in results.items():
            rows.append({
                "Configuration": name,
                f"Hit Rate@{k}": round(m["hit_rate"], 3),
                f"Recall@{k}": round(m["recall"], 3),
                f"MRR@{k}": round(m["mrr"], 3),
                "Avg latency (ms)": round(m["latency_avg_ms"], 3),
                "p95 latency (ms)": round(m["latency_p95_ms"], 3),
            })
        df = pd.DataFrame(rows).set_index("Configuration")
        st.dataframe(df, use_container_width=True)
        st.bar_chart(df[[f"Hit Rate@{k}", f"MRR@{k}"]])

        st.markdown("### Failure analysis")
        names = list(results)
        baseline = {d["query_id"]: d for d in results[names[0]]["details"]}
        dense = {d["query_id"]: d for d in results["Dense Structure-Aware"]["details"]}
        analysis = []
        for qid in baseline:
            b, d = baseline[qid], dense[qid]
            if b["hit"] != d["hit"] or b["first_relevant_rank"] != d["first_relevant_rank"]:
                winner = "BM25" if (b["first_relevant_rank"] or 999) < (d["first_relevant_rank"] or 999) else "Dense"
                reason = "Exact identifiers favor lexical matching." if b["query_type"] == "lexical" else "Paraphrases favor semantic similarity."
                analysis.append({"Query": b["query"], "Type": b["query_type"], "Winner": winner, "Why": reason})
        st.dataframe(pd.DataFrame(analysis), use_container_width=True)

with corpus_tab:
    st.subheader("Corpus overview")
    st.metric("Structure-aware sections", len(chunks))
    st.write("Original instructional corpus: Asteria Edge Gateway Reference. Ground truth is mapped to stable section names / unique text spans rather than array indices, avoiding evaluation leakage across chunk sizes.")
    st.code("Technical Docs → Fixed / Structure-aware Chunking → BM25 + Dense Indexes → Unified Search → Benchmark Evaluator")
    with st.expander("Preview corpus"):
        st.markdown(CORPUS.read_text(encoding="utf-8")[:9000])

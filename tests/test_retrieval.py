import numpy as np

from src.chunking import DocumentChunk
from src.indexer import BM25Index, NumpyDenseIndex


class TinySemanticEncoder:
    def encode(self, texts):
        vectors = []
        for text in texts:
            t = text.lower()
            if any(x in t for x in ["uninterrupted", "zero-downtime", "rolling", "active traffic", "deploy"]):
                vectors.append([1.0, 0.0, 0.0])
            elif any(x in t for x in ["fruit", "banana"]):
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return np.asarray(vectors, dtype=np.float32)


def c(cid, text):
    return DocumentChunk(chunk_id=cid, content=text, metadata={"header_path": cid}, parent_doc="x.md")


def test_exact_identifier_is_rank_one_for_bm25():
    chunks = [
        c("general", "ordinary configuration and routing options"),
        c("flag", "CUSTOM_CONFIG_FLAG_XYZ enables the experimental planner"),
        c("other", "authentication and authorization reference"),
    ]
    result = BM25Index(chunks).search("CUSTOM_CONFIG_FLAG_XYZ", k=3)
    assert result[0][0].chunk_id == "flag"


def test_paraphrase_retrieval_succeeds_for_dense_search():
    chunks = [
        c("rollout", "zero-downtime rolling upgrades drain old workers before replacement"),
        c("fruit", "banana and apple storage guide"),
        c("auth", "JWT authorization scopes"),
    ]
    index = NumpyDenseIndex(chunks, TinySemanticEncoder())
    result = index.search("deploy while keeping active traffic uninterrupted", k=2)
    assert result[0][0].chunk_id == "rollout"

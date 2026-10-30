from src.chunking import FixedSizeChunker, StructureAwareChunker


def test_chunk_overlap_integrity():
    text = " ".join(f"token{i}" for i in range(120))
    chunker = FixedSizeChunker(chunk_size=24, chunk_overlap=6)
    chunks = chunker.chunk_text(text, "sample.md")
    assert len(chunks) > 2
    for left, right in zip(chunks, chunks[1:]):
        assert left.metadata["token_ids"][-6:] == right.metadata["token_ids"][:6]


def test_structure_chunker_preserves_code_fences():
    text = """# Docs\n\n## Install\nBefore.\n```python\n# not a markdown header\nprint('ok')\n```\nAfter.\n\n## Next\nDone.\n"""
    chunks = StructureAwareChunker().chunk_text(text, "docs.md")
    code_chunks = [c for c in chunks if "print('ok')" in c.content]
    assert len(code_chunks) == 1
    assert code_chunks[0].content.count("```") == 2

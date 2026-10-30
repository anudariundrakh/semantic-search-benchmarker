from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

try:
    import tiktoken  # type: ignore
except Exception:  # pragma: no cover
    tiktoken = None


class DocumentChunk(BaseModel):
    chunk_id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    parent_doc: str


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _stable_id(parent_doc: str, strategy: str, position: int, content: str) -> str:
    digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:10]
    return f"{slugify(parent_doc)}::{strategy}::{position:04d}::{digest}"


class TokenCodec:
    """tiktoken-backed codec with a deterministic whitespace fallback for offline QA."""

    def __init__(self, encoding_name: str = "cl100k_base") -> None:
        self._encoding = tiktoken.get_encoding(encoding_name) if tiktoken else None

    def encode(self, text: str) -> list[int | str]:
        if self._encoding:
            return list(self._encoding.encode(text))
        return re.findall(r"\S+", text)

    def decode(self, tokens: list[int | str]) -> str:
        if self._encoding:
            return self._encoding.decode([int(x) for x in tokens])
        return " ".join(str(x) for x in tokens)


class FixedSizeChunker:
    def __init__(self, chunk_size: int, chunk_overlap: int = 32) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must satisfy 0 <= overlap < chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.codec = TokenCodec()

    def chunk_text(self, text: str, parent_doc: str = "document.md") -> list[DocumentChunk]:
        tokens = self.codec.encode(text)
        if not tokens:
            return []
        chunks: list[DocumentChunk] = []
        step = self.chunk_size - self.chunk_overlap
        for position, start in enumerate(range(0, len(tokens), step)):
            window = tokens[start : start + self.chunk_size]
            if not window:
                break
            content = self.codec.decode(window).strip()
            chunks.append(
                DocumentChunk(
                    chunk_id=_stable_id(parent_doc, f"fixed-{self.chunk_size}", position, content),
                    content=content,
                    parent_doc=parent_doc,
                    metadata={
                        "strategy": "fixed",
                        "chunk_size": self.chunk_size,
                        "chunk_overlap": self.chunk_overlap,
                        "token_start": start,
                        "token_end": start + len(window),
                        "token_ids": window,
                    },
                )
            )
            if start + self.chunk_size >= len(tokens):
                break
        return chunks

    def chunk_file(self, path: str | Path) -> list[DocumentChunk]:
        path = Path(path)
        return self.chunk_text(path.read_text(encoding="utf-8"), path.name)


class StructureAwareChunker:
    """Split Markdown at headers while never treating headers inside code fences as boundaries."""

    HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

    def chunk_text(self, text: str, parent_doc: str = "document.md") -> list[DocumentChunk]:
        lines = text.splitlines()
        chunks: list[DocumentChunk] = []
        hierarchy: list[str] = []
        section_lines: list[str] = []
        section_start = 1
        in_fence = False

        def flush(end_line: int) -> None:
            nonlocal section_lines, section_start
            content = "\n".join(section_lines).strip()
            if not content:
                section_lines = []
                section_start = end_line + 1
                return
            header_path = " > ".join(hierarchy) if hierarchy else "Document Preamble"
            section_key = slugify(hierarchy[-1]) if hierarchy else "document-preamble"
            position = len(chunks)
            chunks.append(
                DocumentChunk(
                    chunk_id=_stable_id(parent_doc, "structure", position, content),
                    content=content,
                    parent_doc=parent_doc,
                    metadata={
                        "strategy": "structure-aware",
                        "header_hierarchy": hierarchy.copy(),
                        "header_path": header_path,
                        "section_key": section_key,
                        "line_start": section_start,
                        "line_end": end_line,
                        "token_count": len(TokenCodec().encode(content)),
                    },
                )
            )
            section_lines = []
            section_start = end_line + 1

        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("```"):
                in_fence = not in_fence
                section_lines.append(line)
                continue
            match = self.HEADER_RE.match(line) if not in_fence else None
            if match:
                flush(idx - 1)
                level = len(match.group(1))
                title = match.group(2).strip()
                hierarchy[:] = hierarchy[: level - 1]
                hierarchy.append(title)
                section_start = idx
            section_lines.append(line)
        flush(len(lines))
        return chunks

    def chunk_file(self, path: str | Path) -> list[DocumentChunk]:
        path = Path(path)
        return self.chunk_text(path.read_text(encoding="utf-8"), path.name)

"""进程内文档库：分块 + Embedding + 混合检索。

实现 `VectorBackend` 协议，提供 `add_document` / `hybrid_search` / `count`。
需要 PostgreSQL + pgvector 时，可无缝切换到 `app.rag.pg_store.PgVectorStore`。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from app.rag.embedder import embed

_CHUNK_SIZE = 512
_CHUNK_OVERLAP = 80
RRF_K = 60          # Reciprocal Rank Fusion 常数
_VEC_WEIGHT = 1.0


def _tokenize(text: str) -> list[str]:
    """轻量分词：英文按词、中文按字（如需更优中文检索可换 jieba）。"""
    toks: list[str] = []
    for mobj in re.finditer(r"[a-zA-Z0-9_+-]+|[\u4e00-\u9fff]", text):
        toks.append(mobj.group(0).lower())
    return toks


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def split_text(text: str) -> list[str]:
    """公开的分块函数，内存 / PG 后端共用。"""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    if len(text) <= _CHUNK_SIZE:
        return [text]
    step = _CHUNK_SIZE - _CHUNK_OVERLAP
    return [text[i : i + _CHUNK_SIZE] for i in range(0, len(text), step)]


def make_vector_store(dsn: str = "", kind: str = "memory", dim: int | None = None):
    """按配置构造向量后端。

    - kind == "postgres" 且提供了 dsn：PostgreSQL + pgvector
    - 其余（含默认）：进程内内存实现
    """
    from app.rag.pg_store import PgVectorStore  # 延迟导入，避免内存模式硬依赖 pgvector

    if kind == "postgres":
        if not dsn:
            raise ValueError("vector_store=postgres 需要配置 pg_dsn")
        return PgVectorStore(dsn, dim or 128)
    return DocumentStore()


@dataclass
class StoredChunk:
    chunk_id: str
    doc_id: str
    text: str
    vector: list[float]
    metadata: dict[str, Any]


@dataclass
class ScoredChunk:
    chunk_id: str
    doc_id: str
    text: str
    metadata: dict[str, Any]
    score: float
    vector_score: float
    bm25_score: float

    @property
    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "text": self.text,
            "metadata": self.metadata,
            "score": round(self.score, 4),
            "vector_score": round(self.vector_score, 4),
            "bm25_score": round(self.bm25_score, 4),
        }


class DocumentStore:
    def __init__(self) -> None:
        self._chunks: dict[str, StoredChunk] = {}
        self._doc_seq = 0

    def add_document(self, text: str, metadata: dict[str, Any] | None = None) -> str:
        self._doc_seq += 1
        doc_id = f"doc-{self._doc_seq}"
        metadata = dict(metadata or {})
        for i, chunk in enumerate(split_text(text), start=1):
            cid = f"{doc_id}-c{i}"
            self._chunks[cid] = StoredChunk(
                chunk_id=cid, doc_id=doc_id, text=chunk,
                vector=embed(chunk), metadata={**metadata, "chunk_index": i},
            )
        return doc_id

    def _bm25(self, query_toks: set[str]) -> dict[str, float]:
        n = len(self._chunks)
        df: dict[str, int] = {}
        for c in self._chunks.values():
            for tok in set(_tokenize(c.text)):
                df[tok] = df.get(tok, 0) + 1
        scores: dict[str, float] = {}
        for cid, c in self._chunks.items():
            toks = _tokenize(c.text)
            avg_len = max(sum(len(_tokenize(x.text)) for x in self._chunks.values()) / max(n, 1), 1)
            s = 0.0
            for tok in toks:
                if tok not in query_toks:
                    continue
                tf = toks.count(tok)
                idf = math.log((n - df.get(tok, 0) + 0.5) / (df.get(tok, 0) + 0.5) + 1.0)
                s += tf * idf / (tf + 0.5 + 1.5 * (len(toks) / avg_len))
            scores[cid] = s
        return scores

    def hybrid_search(self, query: str, k: int = 5) -> list[ScoredChunk]:
        if not self._chunks:
            return []
        q_vec = embed(query)
        q_toks = set(_tokenize(query))

        vec_scores = {cid: _cosine(q_vec, c.vector) for cid, c in self._chunks.items()}
        bm_scores = self._bm25(q_toks)

        vec_rank = {cid: i + 1 for i, cid in enumerate(sorted(vec_scores, key=vec_scores.get, reverse=True))}
        bm_rank = {cid: i + 1 for i, cid in enumerate(sorted(bm_scores, key=bm_scores.get, reverse=True))}

        results: list[ScoredChunk] = []
        for cid, c in self._chunks.items():
            if vec_scores[cid] <= 0 and bm_scores[cid] <= 0:
                continue
            rrf = 1.0 / (RRF_K + vec_rank[cid]) + 1.0 / (RRF_K + bm_rank[cid])
            score = _VEC_WEIGHT * vec_scores[cid] + rrf  # 向量+RRF 融合
            results.append(ScoredChunk(
                chunk_id=cid, doc_id=c.doc_id, text=c.text, metadata=c.metadata,
                score=score, vector_score=vec_scores[cid], bm25_score=bm_scores[cid],
            ))
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:k]

    def count(self) -> int:
        return len(self._chunks)
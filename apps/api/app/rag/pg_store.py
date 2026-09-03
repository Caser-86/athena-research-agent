"""PostgreSQL + pgvector 文档后端：向量检索下沉数据库。

提供与 `DocumentStore` 相同的 `add_document` / `hybrid_search` / `count`，
通过配置 `ATHENA_VECTOR_STORE=postgres` 启用。向量列用 pgvector 的 HNSW
近似索引做余弦相似度 top-候选，BM25 + RRF 融合复用内存版逻辑（应用层完成）。
"""
from __future__ import annotations

import json
import math
import uuid
from typing import Any

from sqlalchemy import Index, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, mapped_column

from app.rag.embedder import embed, embedding_dim
from app.rag.store import RRF_K, _VEC_WEIGHT, _cosine, _tokenize, ScoredChunk, split_text

try:
    from pgvector.sqlalchemy import Vector
    _HAS_PGVECTOR = True
except Exception:  # pragma: no cover
    Vector = None
    _HAS_PGVECTOR = False

# 与 embedder 维度保持一致（演示固定 128，真实 embedding 首请求探测）
_VECTOR_DIM = 128

# 缺 pgvector 时本模块仍可被延迟导入（内存默认路径不崩），
# 但构造 PgVectorStore 时会抛清晰错误。DocChunk 类定义需 Vector，故仅在可用时定义。
if _HAS_PGVECTOR:

    class Base(DeclarativeBase):
        pass


    class DocChunk(Base):
        __tablename__ = "doc_chunks"

        chunk_id = mapped_column(Text, primary_key=True)
        doc_id = mapped_column(Text, index=True)
        text = mapped_column(Text)
        vector = mapped_column(Vector(_VECTOR_DIM), nullable=False)
        metadata_json = mapped_column(Text, default="{}")

        __table_args__ = (
            Index("ix_doc_chunks_vector", "vector", postgresql_using="hnsw",
                  postgresql_with={"m": 16, "ef_construction": 64},
                  postgresql_ops={"vector": "vector_cosine_ops"}),
        )
else:  # pragma: no cover
    Base = None
    DocChunk = None


class PgVectorStore:
    """pgvector 后端：向量检索在 PG 内完成，融合在应用层完成。"""

    def __init__(self, dsn: str, dim: int = _VECTOR_DIM) -> None:
        if not _HAS_PGVECTOR:
            raise RuntimeError("未安装 pgvector 依赖（pip install pgvector）")
        self._dim = dim
        self._engine = create_engine(dsn, echo=False)
        self._init_schema()

    def _init_schema(self) -> None:
        # 确保 vector 扩展开启（需库管理员有 CREATE 权限；可用 pgcrypto 之外的无 prep）
        with self._engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(self._engine)

    def add_document(self, text_content: str, metadata: dict[str, Any] | None = None) -> str:
        metadata = dict(metadata or {})
        doc_id = f"doc-{uuid.uuid4().hex[:8]}"
        with self._engine.begin() as conn:
            for i, chunk in enumerate(split_text(text_content), start=1):
                cid = f"{doc_id}-c{i}"
                vec = embed(chunk)
                if len(vec) != self._dim:
                    raise ValueError(f"embedding 维度 {len(vec)} 与配置 {self._dim} 不一致")
                conn.execute(
                    DocChunk.__table__.insert().values(
                        chunk_id=cid, doc_id=doc_id, text=chunk, vector=vec,
                        metadata_json=json.dumps({**metadata, "chunk_index": i}, ensure_ascii=False),
                    )
                )
        return doc_id

    def hybrid_search(self, query: str, k: int = 5) -> list[ScoredChunk]:
        q_vec = embed(query)
        if len(q_vec) != self._dim:
            raise ValueError(f"query embedding 维度 {len(q_vec)} 与配置 {self._dim} 不一致")
        # 1) pgvector：余弦距离 top 候选（扩召回收进融合）
        candidate_k = max(k * 10, 50)
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT chunk_id, doc_id, text, metadata_json, vector
                    FROM doc_chunks
                    ORDER BY vector <-> CAST(:qv AS vector)
                    LIMIT :lim
                """),
                {"qv": q_vec, "lim": candidate_k},
            ).fetchall()

        if not rows:
            return []

        # 2) 应用层 BM25 + RRF 融合（与内存版一致）
        chunks = [
            {"chunk_id": r[0], "doc_id": r[1], "text": r[2],
             "vector": _parse_vector(r[4]), "metadata": json.loads(r[3])}
            for r in rows
        ]
        return _fuse(query, q_vec, chunks, k)

    def count(self) -> int:
        with self._engine.connect() as conn:
            return int(conn.execute(text("SELECT COUNT(*) FROM doc_chunks")).scalar())


def _parse_vector(raw) -> list[float]:
    """解析 pgvector 文本表示（'[...]'）为 float 列表。"""
    s = str(raw).strip()
    if s.startswith("["):
        s = s[1:]
    if s.endswith("]"):
        s = s[:-1]
    return [float(x) for x in s.split(",") if x.strip()]


def _fuse(query: str, q_vec: list[float], chunks: list[dict], k: int) -> list[ScoredChunk]:
    """与内存版一致的 BM25 + RRF 融合（基于候选集近似全局 df）。"""
    import math

    q_toks = set(_tokenize(query))
    n = len(chunks)
    df: dict[str, int] = {}
    for c in chunks:
        for tok in set(_tokenize(c["text"])):
            df[tok] = df.get(tok, 0) + 1

    vec_scores = {c["chunk_id"]: _cosine(q_vec, c["vector"]) for c in chunks}
    bm_scores: dict[str, float] = {}
    for c in chunks:
        toks = _tokenize(c["text"])
        avg_len = max(sum(len(_tokenize(x["text"])) for x in chunks) / max(n, 1), 1)
        s = 0.0
        for tok in toks:
            if tok not in q_toks:
                continue
            tf = toks.count(tok)
            idf = math.log((n - df.get(tok, 0) + 0.5) / (df.get(tok, 0) + 0.5) + 1.0)
            s += tf * idf / (tf + 0.5 + 1.5 * (len(toks) / avg_len))
        bm_scores[c["chunk_id"]] = s

    vec_rank = {cid: i + 1 for i, cid in enumerate(sorted(vec_scores, key=vec_scores.get, reverse=True))}
    bm_rank = {cid: i + 1 for i, cid in enumerate(sorted(bm_scores, key=bm_scores.get, reverse=True))}

    results: list[ScoredChunk] = []
    for c in chunks:
        cid = c["chunk_id"]
        if vec_scores[cid] <= 0 and bm_scores.get(cid, 0) <= 0:
            continue
        rrf = 1.0 / (RRF_K + vec_rank[cid]) + 1.0 / (RRF_K + bm_rank.get(cid, k + 1))
        score = _VEC_WEIGHT * vec_scores[cid] + rrf
        results.append(ScoredChunk(
            chunk_id=cid, doc_id=c["doc_id"], text=c["text"], metadata=c["metadata"],
            score=score, vector_score=vec_scores[cid], bm25_score=bm_scores.get(cid, 0.0),
        ))
    results.sort(key=lambda x: x.score, reverse=True)
    return results[:k]
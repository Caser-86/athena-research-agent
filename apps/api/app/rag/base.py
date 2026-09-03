"""文档库抽象接口：向量检索后端协议。

`DocumentStore`（内存）与 `PgVectorStore`（PostgreSQL + pgvector）共用此接口，
通过配置 `ATHENA_VECTOR_STORE` 二选一。上层（Retriever）不感知具体实现。
"""
from __future__ import annotations

from typing import Any, Protocol


class VectorBackend(Protocol):
    def add_document(self, text: str, metadata: dict[str, Any] | None = None) -> str: ...
    def hybrid_search(self, query: str, k: int = 5) -> list[Any]: ...
    def count(self) -> int: ...
"""RAG 引擎单元测试（演示 embedding，无需外部 Key）。"""

from __future__ import annotations

from app.rag.embedder import embed
from app.rag.retriever import SEED_DOCS, Retriever


def test_demo_embedding_is_deterministic():
    v1 = embed("比亚迪销量领先")
    v2 = embed("比亚迪销量领先")
    assert v1 == v2


def test_demo_embedding_distinguishes_topics():
    a = embed("比亚迪成本优势与供应链")
    b = embed("蔚来换电服务网络")
    c = embed("比亚迪成本优势与供应链")
    # 同文本余弦约 1.0，不同主题小于同文本
    dot_same = sum(x * y for x, y in zip(a, c))
    dot_diff = sum(x * y for x, y in zip(a, b))
    assert dot_same > dot_diff
    assert dot_same > 0.9


def test_hybrid_search_returns_most_relevant():
    retriever = Retriever()
    hits = retriever.search("蔚来换电服务的竞争力", k=3)
    assert hits, "必须返回检索结果"
    assert len(hits) <= 3
    # 最相关的结果应来自包含换电/服务的文档
    top = hits[0]
    assert any(
        tag in top["metadata"].get("title", "")
        for tag in ["蔚来", "换电"]
    ) or "换电" in top["text"]


def test_hybrid_search_over_empty_store():
    from app.rag.store import DocumentStore

    ds = DocumentStore()
    assert ds.hybrid_search("anything", k=5) == []


def test_seed_corpus_includes_expected_docs():
    # 至少覆盖新能源 + 技术（RAG/Agent/MCP）两类领域，保证演示与真实检索都能命中
    assert len(SEED_DOCS) >= 4
    titles = [d[1] for d in SEED_DOCS]
    for kw in ("新能源", "RAG", "Agent"):
        assert any(kw in t for t in titles), f"种子库缺少主题：{kw}"
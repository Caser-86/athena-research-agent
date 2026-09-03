from sqlalchemy import text, create_engine
engine = create_engine("postgresql+psycopg://postgres:920220@localhost:5432/postgres")
with engine.begin() as c:
    c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
from app.rag.pg_store import PgVectorStore
s = PgVectorStore("postgresql+psycopg://postgres:920220@localhost:5432/postgres")
n0 = s.count()
doc = """
RAG（检索增强生成）与 Agent 编排是当下两种主流方案。RAG 适合知识密集、答案需可溯源的任务，
通过向量检索 + 重排序保证引用准确；Agent 编排（LangGraph 状态机）适合需要多步推理、工具调用
与决策分支的场景。在推荐系统设计中，宜先做轻量 RAG 基线，再逐步引入 Agent 编排提升复杂任务效果。
"""
doc_id = s.add_document(doc, {"title": "RAG vs Agent 选型"})
print("doc_id:", doc_id, "count after add:", s.count())
res = s.hybrid_search("RAG 与 Agent 如何选型", k=2)
print("hybrid results:", len(res))
for r in res:
    print("  -", r.metadata.get("title"), r.score, r.text[:40])
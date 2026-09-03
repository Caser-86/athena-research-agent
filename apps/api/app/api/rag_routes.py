"""RAG 检索路由：将本地混合检索能力暴露为 API（演示与前端工作台对接）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.rag.retriever import Retriever, get_retriever

router = APIRouter(prefix="/api/rag", tags=["rag"])


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    k: int = Field(default=5, ge=1, le=20)


class SearchHit(BaseModel):
    chunk_id: str
    doc_id: str
    text: str
    metadata: dict
    score: float
    vector_score: float
    bm25_score: float


def _retriever_dep() -> Retriever:
    return get_retriever()


@router.post("/search")
async def rag_search(
    body: SearchRequest,
    retriever: Annotated[Retriever, Depends(_retriever_dep)],
) -> dict:
    hits = retriever.search(body.query, k=body.k)
    return {
        "query": body.query,
        "mode": "hybrid(vector+bm25+rrf)",
        "hits": [SearchHit(**h).model_dump() for h in hits],
    }
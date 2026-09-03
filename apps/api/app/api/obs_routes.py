"""可观测性路由：暴露采集的 span 明细与聚合统计，供前端看板 / 面试演示展示成本与时延。"""

from __future__ import annotations

from fastapi import APIRouter

from app import obs

router = APIRouter(prefix="/api/obs", tags=["observability"])


@router.get("/summary")
async def obs_summary() -> dict:
    """聚合统计：调用数 / token / 总成本 / 时延 / 按 Agent 分账 / 最近任务。"""
    return obs.summary()


@router.get("/spans")
async def obs_spans() -> dict:
    """本次进程累计的所有 span（LLM 调用与任务），按时间正序。"""
    return {"spans": obs.get_spans(), "tasks": obs.get_tasks()}


@router.post("/reset")
async def obs_reset() -> dict:
    """清空观测（演示前调用，保证指标从本场会话起步）。"""
    obs.reset()
    return {"ok": True}
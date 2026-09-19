"""可观测性路由：暴露采集的 span 明细与聚合统计，供前端看板 / 面试演示展示成本与时延。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from app import obs
from app.storage import get_storage

router = APIRouter(prefix="/api/obs", tags=["observability"])


@router.get("/summary")
async def obs_summary() -> dict:
    """聚合统计：调用数 / token / 总成本 / 时延 / 按 Agent 分账 / 最近任务。"""
    # 任务总时延已随历史任务持久化；看板优先使用存储层样本，
    # 这样进程重启后 P50/P95/P99 仍有明确统计口径。
    latencies = await asyncio.to_thread(get_storage().list_task_latencies, 10_000)
    return obs.summary(task_latencies=latencies)


@router.get("/spans")
async def obs_spans() -> dict:
    """本次进程累计的所有 span（LLM 调用与任务），按时间正序。"""
    return {"spans": obs.get_spans(), "tasks": obs.get_tasks()}


@router.post("/reset")
async def obs_reset() -> dict:
    """清空观测（演示前调用，保证指标从本场会话起步）。"""
    obs.reset()
    return {"ok": True}

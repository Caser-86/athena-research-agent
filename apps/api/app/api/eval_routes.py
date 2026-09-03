"""评测看板路由：把四维指标评测结果暴露为只读 API，供前端看板展示。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.eval.harness import EvalReport, run_harness

router = APIRouter(prefix="/api/eval", tags=["eval"])

_cached: dict[float, EvalReport] = {}


async def _get_report(threshold: float) -> EvalReport:
    """按阈值缓存评测结果：同一 threshold 不重复反复跑（看板轮询用）。
    演示模式下 harness 为确定性结果，缓存安全。"""
    if threshold not in _cached:
        _cached[threshold] = await run_harness(threshold)
    return _cached[threshold]


@router.get("/summary")
async def eval_summary(
    threshold: Annotated[float, Query(ge=0.0, le=1.0)] = 0.5,
) -> dict:
    report = await _get_report(threshold)
    return {
        "threshold": report.threshold,
        "aggregate": report.aggregate,
        "kappa": report.kappa,
        "passed_threshold": report.passed_threshold,
    }


@router.get("/cases")
async def eval_cases() -> dict:
    report = await _get_report(0.5)
    return {"cases": [report._bundle_to_dict(r) for r in report.results]}
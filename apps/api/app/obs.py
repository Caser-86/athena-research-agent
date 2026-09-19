"""内置可观测性：零外部依赖的 trace / 成本 / 时延采集。

设计动机：Langfuse 等完整套件需自部署，演示与 CI 不应对环境有硬依赖。
用轻量内存采集暴露结构化 span + 聚合统计，前端看板 / 面试演示直接消费；
后续要上 Langfuse 时，只需在此模块按相同 span 契约转发。

备注：mock 模式的 token 为按字符估算（synthetic），单价来自 config，
用于演示"单任务成本"指标；真实模式消费 response.usage 真值。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from app.config import get_settings

# 单价（元/百万 token），可在 config/.env 覆盖
_SAMPLE_PRICE_IN = 2.0
_SAMPLE_PRICE_OUT = 8.0

_lock = threading.Lock()
_spans: list[dict] = []
_tasks: list[dict] = []
_current_task_id: ContextVar[str] = ContextVar("athena_obs_task_id", default="")


@dataclass
class Spec:
    spans: list[dict] = field(default_factory=list)
    tasks: list[dict] = field(default_factory=list)


def reset() -> None:
    with _lock:
        _spans.clear()
        _tasks.clear()


@contextmanager
def task_context(task_id: str) -> Iterator[None]:
    """将当前异步上下文中的 LLM/MCP span 归属到指定任务。"""
    token = _current_task_id.set(task_id)
    try:
        yield
    finally:
        _current_task_id.reset(token)


def _now() -> float:
    return time.time()


def _est_tokens(*texts: str) -> int:
    """按字符数估算 token（演示模式无 usage 时兜底，约 2 字符 ≈ 1 token）。"""
    return sum(len(t) for t in texts if t) // 2


def _llm_cost(prompt_tokens: int, completion_tokens: int) -> float:
    s = get_settings()
    p_in = float(s.llm_price_per_1m_input or _SAMPLE_PRICE_IN)
    p_out = float(s.llm_price_per_1m_output or _SAMPLE_PRICE_OUT)
    return (prompt_tokens * p_in + completion_tokens * p_out) / 1_000_000


def record_llm(
    *,
    agent: str,
    kind: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: float,
    mock: bool = False,
) -> float:
    cost = _llm_cost(prompt_tokens, completion_tokens)
    with _lock:
        _spans.append(
            {
                "ts": _now(),
                "type": "llm",
                "agent": agent,
                "kind": kind,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "cost": round(cost, 6),
                "latency_ms": round(latency_ms, 2),
                "mock": mock,
                "task_id": _current_task_id.get(),
            }
        )
    return cost


def record_tool(
    *,
    agent: str,
    kind: str,
    latency_ms: float,
    args_preview: str = "",
) -> float:
    """记录一次工具（MCP）调用。成本/ token 不适用，统一以 0 记账，仅统计时延。"""
    with _lock:
        _spans.append(
            {
                "ts": _now(),
                "type": "tool",
                "agent": agent,
                "kind": kind,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost": 0.0,
                "latency_ms": round(latency_ms, 2),
                "args_preview": args_preview[:80],
                "mock": False,
                "task_id": _current_task_id.get(),
            }
        )
    return 0.0


def record_task(*, task_id: str = "", question: str, iterations: int, latency_ms: float) -> None:
    with _lock:
        spans = [
            s
            for s in _spans
            if s["type"] == "llm" and (not task_id or s.get("task_id") == task_id)
        ]
        _tasks.append(
            {
                "ts": _now(),
                "task_id": task_id,
                "question": question[:60],
                "iterations": iterations,
                "llm_calls": len(spans),
                "total_tokens": sum(s["total_tokens"] for s in spans),
                "cost": round(sum(s["cost"] for s in spans), 6),
                "latency_ms": round(latency_ms, 1),
            }
        )


def get_spans() -> list[dict]:
    with _lock:
        return list(_spans)


def get_tasks() -> list[dict]:
    with _lock:
        return list(_tasks)


def _percentile(values: list[float], percentile: float) -> float:
    """线性插值计算百分位；空样本返回 0，避免看板出现 NaN。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 2)


def summary(*, task_latencies: list[float] | None = None) -> dict:
    with _lock:
        spans = list(_spans)
        tasks = list(_tasks)

    llm = [s for s in spans if s["type"] == "llm"]
    per_agent: dict[str, dict] = {}
    for s in llm:
        a = per_agent.setdefault(s["agent"], {"calls": 0, "tokens": 0, "cost": 0.0, "latency": 0.0})
        a["calls"] += 1
        a["tokens"] += s["total_tokens"]
        a["cost"] += s["cost"]
        a["latency"] += s["latency_ms"]

    last = tasks[-1] if tasks else None
    tools = [s for s in spans if s["type"] == "tool"]
    latency_values = (
        [float(value) for value in task_latencies if value is not None]
        if task_latencies is not None
        else [float(task["latency_ms"]) for task in tasks if task.get("latency_ms") is not None]
    )
    return {
        "llm_calls": len(llm),
        "tool_calls": len(tools),
        "tools": [
            {
                "kind": s["kind"],
                "agent": s["agent"],
                "latency_ms": s["latency_ms"],
                "args_preview": s.get("args_preview", ""),
            }
            for s in tools
        ],
        "total_tokens": sum(s["total_tokens"] for s in llm),
        "total_cost": round(sum(s["cost"] for s in llm), 6),
        "total_latency_ms": round(sum(s["latency_ms"] for s in llm), 1),
        "avg_llm_latency_ms": round(sum(s["latency_ms"] for s in llm) / len(llm), 2) if llm else 0.0,
        "task_latency_ms": {
            "count": len(latency_values),
            "p50": _percentile(latency_values, 50),
            "p95": _percentile(latency_values, 95),
            "p99": _percentile(latency_values, 99),
        },
        "per_agent": per_agent,
        "task_count": len(tasks),
        "last_task": last,
    }

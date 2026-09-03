"""HITL 人机协同节点 + 经验反思节点。

- `approval_gate`：在 Writer 产出报告**前**，对高风险动作做人工审批。
  默认 `auto_approve`（演示/CI 直接放行）；当 config 中 `human_approval=true` 时调用
  LangGraph 的 `interrupt()` 挂起，等待人工 `Command(resume=True/False)` 后恢复。
- `reflect`：研究结束后沉淀经验到长期记忆，供后续研究复用。
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, interrupt

from app.graph.events import get_bus
from app.graph.state import ResearchState
from app.memory import get_memory


def is_human_approval_enabled(config: RunnableConfig | None) -> bool:
    return bool((config.get("configurable") or {}).get("human_approval", False))


async def approval_gate(
    state: ResearchState, config: RunnableConfig | None = None
) -> dict:
    """审批准则：计划含「高风险动作」（如执行代码/SQL）时人工确认，否则自动放行。"""
    plan = state.get("plan", [])
    high_risk = any("执行" in str(t.get("title", "")) or "代码" in str(t.get("title", ""))
                    for t in plan)
    bus = get_bus(config)

    if high_risk and is_human_approval_enabled(config):
        decision = interrupt({"review": "是否批准该研究计划执行？", "question": state["question"]})
        approved = bool(decision)
        if bus is not None:
            await bus.emit("human_decision", approved=approved, question=state["question"])
        if not approved:
            # 拒绝则终止：返回一个空阻断标记（不继续 Writer）
            return {"blocked": True}
        return {"blocked": False}

    # 自动放行
    if bus is not None:
        await bus.emit("human_decision", approved=True, auto=True, question=state["question"])
    return {"blocked": False}


async def reflect(state: ResearchState, config: RunnableConfig | None = None) -> dict:
    """研究结束后写回长期经验记忆。"""
    memory = get_memory()
    memory.remember(
        task_id=state.get("task_id", ""),
        question=state["question"],
        reflection="本任务使用了 Planner→Researcher→Analyst→Critic→Writer 流水线；"
                   "Critic 质量回路在证据不足时会打回补充检索。",
        pitfalls=["单点检索源易导致证据不足", "多轮打回会累积重复证据，需按轮次去重"],
        outcome=f"iteration={state.get('iteration', 1)}; critique={state.get('critique', {}).get('score')}",
    )
    bus = get_bus(config)
    if bus is not None:
        await bus.emit("memory_saved", total=memory.count())
    return {}


def should_continue_after_approval(state: ResearchState) -> str:
    """审批后可进入 Writer；被拒绝时走 END。"""
    return "writer" if not state.get("blocked") else "rejected"
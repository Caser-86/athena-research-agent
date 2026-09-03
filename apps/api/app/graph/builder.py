"""图编排：StateGraph + Critic 质量回路 + 迭代护栏。

拓扑：
    START -> planner -> researcher -> analyst -> critic -> (条件路由)
    critic 通过 或 超过最大轮数 -> writer -> END
    critic 不通过             -> researcher（带反馈重新检索）

迭代护栏（防止循环失控）由 critique_router 实现：
- Critic 每执行一轮，state["iteration"] +1；
- 不通过且 iteration <= max_iterations 时打回；
- 超过轮数后强制放行到 Writer，并在报告中保留最后一轮评审意见。
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.graph.hitl import approval_gate, reflect, should_continue_after_approval
from app.graph.nodes import analyst, critic, planner, researcher, writer
from app.graph.state import ResearchState


def critique_router(state: ResearchState) -> str:
    """条件路由：通过（或达到迭代上限）-> 审批门；否则打回 researcher。"""
    settings = get_settings()
    critique = state.get("critique", {})
    # critic 节点返回时 iteration 已 +1，因此超过 max_iterations 即视为护栏触发
    if critique.get("passed") or state.get("iteration", 1) > settings.max_iterations:
        return "approval_gate"
    return "researcher"


def build_research_graph():
    graph = StateGraph(ResearchState)
    graph.add_node("planner", planner)
    graph.add_node("researcher", researcher)
    graph.add_node("analyst", analyst)
    graph.add_node("critic", critic)
    graph.add_node("approval_gate", approval_gate)
    graph.add_node("writer", writer)
    graph.add_node("reflect", reflect)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "researcher")
    graph.add_edge("researcher", "analyst")
    graph.add_edge("analyst", "critic")
    graph.add_conditional_edges(
        "critic",
        critique_router,
        {"researcher": "researcher", "approval_gate": "approval_gate"},
    )
    graph.add_conditional_edges(
        "approval_gate",
        should_continue_after_approval,
        {"writer": "writer", "rejected": END},
    )
    graph.add_edge("writer", "reflect")
    graph.add_edge("reflect", END)

    # MemorySaver：进程内持久化，支持同 thread_id 断点续跑
    # （第 2 周替换为 PostgreSQL checkpointer，支撑跨进程恢复）
    return graph.compile(checkpointer=MemorySaver())


@lru_cache
def get_research_graph():
    """进程级单例：图编译一次，多次复用。"""
    return build_research_graph()

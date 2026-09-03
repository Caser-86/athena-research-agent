"""ResearchState：贯穿 5 个智能体的图状态。

约定：节点返回局部更新（partial dict），由 LangGraph 合并。
findings 在多轮打回中累积（而非覆盖），保留完整证据链。
"""

from __future__ import annotations

from typing import Any, TypedDict


class ResearchState(TypedDict, total=False):
    question: str                 # 研究问题（入口写入）
    task_id: str                  # 任务标识（入口写入）
    plan: list[dict[str, Any]]    # Planner 产出：[{id, title, purpose}]
    search_results: list[dict]    # Researcher 检索原始结果：[{source_id, subtask_id, title, snippet, url}]
    findings: list[dict]           # Researcher 提取的事实：[{subtask_id, claim, source_ref, iteration}]
    analysis: str                  # Analyst 综合分析（Markdown）
    critique: dict                 # Critic 评审：{score, passed, feedback}
    report: str                     # Writer 最终报告（Markdown，带 [n] 引用）
    iteration: int                  # 当前评审轮次（Planner 初始化为 1）
    blocked: bool                   # HITL 拒绝后置位，阻止进入 Writer

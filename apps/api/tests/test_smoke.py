"""冒烟测试：无需 API Key（演示模式），验证完整编排回路。

覆盖点：
1. 端到端产出报告；
2. Critic 质量回路生效（第 1 轮打回 → 第 2 轮通过），迭代计数正确；
3. 事件总线推送了完整的 Agent 轨迹。
"""

from __future__ import annotations

import pytest

from app.graph.builder import build_research_graph
from app.graph.events import EventBus


QUESTION = "对比三个国产新能源品牌的销量与产品策略"


@pytest.mark.asyncio
async def test_graph_end_to_end_in_mock_mode():
    graph = build_research_graph()
    final = await graph.ainvoke(
        {"question": QUESTION},
        config={"configurable": {"thread_id": "smoke-1"}},
    )

    assert final.get("report"), "必须产出报告"
    assert final.get("plan"), "Planner 必须产出子任务清单"
    assert final.get("findings"), "Researcher 必须产出事实清单"
    assert final.get("analysis"), "Analyst 必须产出综合分析"


@pytest.mark.asyncio
async def test_critic_loop_and_iteration_guardrail():
    graph = build_research_graph()
    final = await graph.ainvoke(
        {"question": QUESTION},
        config={"configurable": {"thread_id": "smoke-2"}},
    )

    # 演示模式：Critic 第 1 轮打回（passed=False），第 2 轮通过
    # planner 初始化 iteration=1，每轮 Critic 后 +1，两轮评审后 iteration=3
    assert final["iteration"] == 3
    assert final["critique"]["passed"] is True
    assert final["critique"]["score"] > 0

    # 打回回路生效：第 2 轮检索的事实带 iteration=2 标记
    iterations = {f.get("iteration") for f in final["findings"]}
    assert 2 in iterations, "Critic 打回后应触发第 2 轮检索"


@pytest.mark.asyncio
async def test_event_bus_emits_full_trajectory():
    bus = EventBus()
    graph = build_research_graph()
    final = await graph.ainvoke(
        {"question": QUESTION},
        config={"configurable": {"thread_id": "smoke-3", "event_bus": bus}},
    )
    assert final.get("report")

    events = []
    while not bus.empty():
        events.append(await bus.get())

    # 至少覆盖 5 个 Agent 的 start/end 事件
    agents = {e["agent"] for e in events if e["type"] in ("agent_start", "agent_end")}
    assert {"planner", "researcher", "analyst", "critic", "writer"} <= agents

    # Critic 的打回事件必须携带评审结果（轨迹可视化的核心数据）
    critic_ends = [e for e in events if e["type"] == "agent_end" and e["agent"] == "critic"]
    assert len(critic_ends) >= 2, "演示模式下 Critic 应评审两轮"
    assert any(e["passed"] is False for e in critic_ends), "第 1 轮应打回"
    assert any(e["passed"] is True for e in critic_ends), "第 2 轮应通过"

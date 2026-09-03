"""5 个智能体节点：Planner / Researcher / Analyst / Critic / Writer。

设计要点：
- 每个节点 = 提示工程 + LLM 调用 + 事件推送（轨迹可观测）；
- Critic 负责质量回路：不通过则带反馈打回 Researcher（路由见 builder.py）；
- Researcher 的检索层可插拔：配置 TAVILY_API_KEY 走真实搜索，否则使用演示数据源
  （第 2 周将替换为 RAG 混合检索 + MCP 工具服务）。
"""

import asyncio
import time
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.config import get_settings
from app.graph.events import get_bus
from app.graph.state import ResearchState
from app.llm import chat_json, chat_text
from app.mcp.tools import call_tool as mcp_call_tool

# Researcher 并行检索的并发上限
_SEARCH_CONCURRENCY = 3


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

async def _emit(config: RunnableConfig | None, event_type: str, **payload: Any) -> None:
    bus = get_bus(config)
    if bus is not None:
        await bus.emit(event_type, **payload)


async def _search_subtask(
    question: str,
    task: dict[str, Any],
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """按子任务检索：
    - 配置 TAVILY_API_KEY 时经 MCP web_search 工具联网检索（统一走工具调用链）；
    - 否则回退到本地 RAG 混合检索（真实检索轻量种子知识库，保证无 Key demo 基于真实内容）。
    """
    settings = get_settings()
    query = f"{question} {task.get('title', '')}".strip()

    if settings.tavily_api_key:
        # 统一经 MCP 工具抽象调用，写入可观测/调用链
        start = time.monotonic()
        results = await mcp_call_tool(
            "web_search",
            {"query": query, "max_results": 3},
            agent="researcher",
        )
        latency_ms = (time.monotonic() - start) * 1000
        await _emit(
            config, "tool", agent="researcher", kind="web_search",
            query=query, latency_ms=round(latency_ms, 1), result_count=len(results),
        )
        return {
            "subtask_id": task.get("id", ""),
            "query": query,
            "results": [
                {"title": r.get("title", ""), "snippet": r.get("snippet", "")[:240], "url": r.get("url", "")}
                for r in results
            ],
        }

    # 本地 RAG 混合检索（真实检索种子知识库）
    from app.rag.retriever import get_retriever

    hits = get_retriever().search(query, k=3)
    return {
        "subtask_id": task.get("id", ""),
        "query": query,
        "results": [
            {
                "title": h["metadata"].get("title", ""),
                "snippet": h["text"][:240],
                "url": "local://" + h["doc_id"],
                "_rag_score": h["score"],
            }
            for h in hits
        ],
    }


def _format_search_results(search_results: list[dict], max_per_subtask: int = 3) -> str:
    """把检索结果编号为 S1/S2...，供 Researcher 引用与报告溯源。
    max_per_subtask 压缩上下文行数，显著降低真实模型的推理时延。"""
    lines: list[str] = []
    for i, item in enumerate(search_results, start=1):
        for r in item.get("results", [])[:max_per_subtask]:
            lines.append(f"S{i}｜{r.get('title', '')}\n{r.get('snippet', '')}\nURL: {r.get('url', '')}")
    return "\n\n".join(lines) if lines else "（无检索结果）"


# ---------------------------------------------------------------------------
# 节点 1：Planner —— 问题拆解
# ---------------------------------------------------------------------------

PLANNER_SYSTEM = """你是研究规划专家。将用户的研究问题拆解为 3-6 个可执行的子任务。
只输出 JSON，格式：{"tasks": [{"id": "t1", "title": "简短标题", "purpose": "该子任务的目的"}]}
要求：子任务之间不重叠、合起来能覆盖问题；涉及对比类问题须为每个对比对象安排独立子任务。"""


async def planner(state: ResearchState, config: RunnableConfig | None = None) -> dict:
    question = state["question"]
    start = time.monotonic()
    await _emit(config, "agent_start", agent="planner", iteration=1, input=question)

    result = await chat_json(
        "planner",
        system=PLANNER_SYSTEM,
        user=f"研究问题：{question}",
        mock_ctx={"question": question},
    )
    tasks = [t for t in result.get("tasks", []) if t.get("id") and t.get("title")]

    await _emit(
        config, "agent_end", agent="planner", iteration=1,
        latency_ms=round((time.monotonic() - start) * 1000, 1),
        tasks=tasks,
    )
    return {"plan": tasks, "iteration": 1}


# ---------------------------------------------------------------------------
# 节点 2：Researcher —— 并行检索 + 事实提取
# ---------------------------------------------------------------------------

RESEARCHER_SYSTEM = """你是研究执行专家。基于给定的子任务清单和编号检索结果（S1/S2/...），提取支撑研究问题的事实。
只输出 JSON，格式：{"findings": [{"subtask_id": "t1", "claim": "事实陈述", "source_ref": "S1"}]}
要求：每条事实必须绑定一个来源编号；不得编造检索结果中不存在的信息；覆盖所有子任务。"""


async def researcher(state: ResearchState, config: RunnableConfig | None = None) -> dict:
    question = state["question"]
    plan = state.get("plan", [])
    iteration = state.get("iteration", 1)
    critique = state.get("critique", {})
    start = time.monotonic()
    await _emit(config, "agent_start", agent="researcher", iteration=iteration)

    # 1. 并行检索（信号量限流）
    semaphore = asyncio.Semaphore(_SEARCH_CONCURRENCY)

    async def _limited(task: dict) -> dict:
        async with semaphore:
            return await _search_subtask(question, task, config)

    search_results = await asyncio.gather(*(_limited(t) for t in plan))

    # 2. 提取事实：第 2 轮起附带 Critic 反馈，定向补充
    feedback = critique.get("feedback", "") if iteration > 1 else ""
    user_prompt = (
        f"研究问题：{question}\n\n子任务清单：\n{plan}\n\n"
        f"编号检索结果：\n{_format_search_results(search_results)}\n"
    )
    if feedback:
        user_prompt += f"\n上一轮评审未通过，评审意见（请定向补充）：\n{feedback}\n"

    result = await chat_json(
        "researcher",
        system=RESEARCHER_SYSTEM,
        user=user_prompt,
        mock_ctx={"tasks": plan, "search_results": search_results},
    )
    new_findings = [
        {
            "subtask_id": f.get("subtask_id", ""),
            "claim": f.get("claim", ""),
            "source_ref": f.get("source_ref", ""),
            "iteration": iteration,
        }
        for f in result.get("findings", [])
    ]

    # 累积多轮发现，保留完整证据链
    findings = state.get("findings", []) + new_findings

    await _emit(
        config, "agent_end", agent="researcher", iteration=iteration,
        latency_ms=round((time.monotonic() - start) * 1000, 1),
        new_findings=len(new_findings), total_findings=len(findings),
    )
    return {"search_results": search_results, "findings": findings}


# ---------------------------------------------------------------------------
# 节点 3：Analyst —— 交叉验证与综合分析
# ---------------------------------------------------------------------------

ANALYST_SYSTEM = """你是研究分析专家。基于事实清单做交叉验证与综合分析：
1. 按主题归并事实，识别一致结论与矛盾之处；
2. 对矛盾信息给出解释或标注存疑；
3. 输出结构：核心结论（3-5 条，每条标注支撑来源编号）→ 矛盾与存疑 → 建议的下一步。
使用 Markdown，不要编造清单之外的数据。"""


async def analyst(state: ResearchState, config: RunnableConfig | None = None) -> dict:
    question = state["question"]
    findings = state.get("findings", [])
    iteration = state.get("iteration", 1)
    start = time.monotonic()
    await _emit(config, "agent_start", agent="analyst", iteration=iteration)

    findings_text = "\n".join(
        f"- [{f['subtask_id']}] {f['claim']}（来源：{f['source_ref']}）" for f in findings
    ) or "（无事实）"

    analysis = await chat_text(
        "analyst",
        system=ANALYST_SYSTEM,
        user=f"研究问题：{question}\n\n事实清单：\n{findings_text}",
        mock_ctx={"question": question, "findings": findings},
    )

    await _emit(
        config, "agent_end", agent="analyst", iteration=iteration,
        latency_ms=round((time.monotonic() - start) * 1000, 1),
    )
    return {"analysis": analysis}


# ---------------------------------------------------------------------------
# 节点 4：Critic —— 质量评审（回路核心）
# ---------------------------------------------------------------------------

CRITIC_SYSTEM = """你是研究质量评审专家，从三个维度评审当前成果：
1. 证据充分性：事实是否覆盖全部子任务且有定量支撑；
2. 引用对齐：结论是否都能溯源到具体来源；
3. 逻辑一致性：分析是否存在未解释的矛盾。
只输出 JSON，格式：{"score": 0-10 的数字, "passed": true/false, "feedback": "具体意见，不通过时说明缺什么"}
passed 的判定标准：score >= 阈值（见用户消息）。"""


async def critic(state: ResearchState, config: RunnableConfig | None = None) -> dict:
    settings = get_settings()
    question = state["question"]
    plan = state.get("plan", [])
    findings = state.get("findings", [])
    analysis = state.get("analysis", "")
    iteration = state.get("iteration", 1)
    start = time.monotonic()
    await _emit(config, "agent_start", agent="critic", iteration=iteration)

    findings_text = "\n".join(
        f"- [{f['subtask_id']}] {f['claim']}（来源：{f['source_ref']}，第 {f.get('iteration', 1)} 轮）"
        for f in findings
    ) or "（无事实）"

    result = await chat_json(
        "critic",
        system=CRITIC_SYSTEM,
        user=(
            f"研究问题：{question}\n当前为第 {iteration} 轮评审，通过阈值：{settings.critic_pass_score}。\n\n"
            f"子任务清单：{plan}\n\n事实清单：\n{findings_text}\n\n综合分析：\n{analysis}"
        ),
    )
    score = float(result.get("score", 0))
    passed = bool(result.get("passed", False)) and score >= settings.critic_pass_score
    critique = {
        "score": score,
        "passed": passed,
        "feedback": result.get("feedback", ""),
    }

    # 迭代护栏：无论结果如何，轮次 +1；是否继续由路由（builder.py）结合
    # max_iterations 决定，防止循环失控
    await _emit(
        config, "agent_end", agent="critic", iteration=iteration,
        latency_ms=round((time.monotonic() - start) * 1000, 1),
        score=score, passed=passed, feedback=critique["feedback"],
    )
    return {"critique": critique, "iteration": iteration + 1}


# ---------------------------------------------------------------------------
# 节点 5：Writer —— 报告撰写
# ---------------------------------------------------------------------------

WRITER_SYSTEM = """你是研究报告撰写专家。基于综合分析与事实清单撰写最终报告。
要求：
1. 结构：核心结论 → 详细分析 → 风险与局限；
2. 所有结论使用行内引用 [S1] / [S2] 标注来源，只引用事实清单中出现过的来源；
3. 不得引入清单之外的任何数据；
4. 输出 Markdown。"""


async def writer(state: ResearchState, config: RunnableConfig | None = None) -> dict:
    question = state["question"]
    findings = state.get("findings", [])
    analysis = state.get("analysis", "")
    critique = state.get("critique", {})
    iteration = state.get("iteration", 1)
    start = time.monotonic()
    await _emit(config, "agent_start", agent="writer", iteration=iteration)

    findings_text = "\n".join(
        f"- [{f['subtask_id']}] {f['claim']}（来源：{f['source_ref']}）" for f in findings
    ) or "（无事实）"

    report = await chat_text(
        "writer",
        system=WRITER_SYSTEM,
        user=(
            f"研究问题：{question}\n\n事实清单：\n{findings_text}\n\n"
            f"综合分析：\n{analysis}\n\n最终评审意见：{critique.get('feedback', '')}"
        ),
        mock_ctx={"question": question, "findings": findings},
    )

    await _emit(
        config, "agent_end", agent="writer", iteration=iteration,
        latency_ms=round((time.monotonic() - start) * 1000, 1),
    )
    return {"report": report}

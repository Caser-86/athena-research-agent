"""LLM 调用层。

职责：
1. 统一封装 OpenAI 兼容 Chat Completions 接口；
2. chat_json：强制 JSON 输出 + 容错解析（提取首个 JSON 对象，失败自动重试一次）；
3. 演示模式：未配置 API Key 时返回与各 Agent 契约一致的内置应答，
   保证编排回路（含 Critic 打回）可以无 Key 跑通，便于演示与测试。

注意：演示模式中 Critic 的"第 1 轮打回、第 2 轮通过"是有意设计的，
用于在无 Key 环境下展示失败重试回路。
"""

from __future__ import annotations

import json
import re
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout=settings.request_timeout_seconds,
            max_retries=4,
        )
    return _client


def _extract_json(text: str) -> dict[str, Any]:
    """从模型输出中提取首个 JSON 对象，容忍 ```json 包裹与前后噪声。"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


async def chat_json(
    agent: str,
    system: str,
    user: str,
    mock_ctx: dict[str, Any] | None = None,
    temperature: float = 0.2,
) -> dict[str, Any]:
    """结构化输出调用：要求模型返回 JSON 并解析为 dict。"""
    import time as _tm

    from app import obs

    settings = get_settings()
    if settings.mock_mode:
        start = _tm.monotonic()
        result = _mock_json(agent, user, mock_ctx or {})
        obs.record_llm(
            agent=agent,
            kind="chat_json(mock)",
            prompt_tokens=obs._est_tokens(system, user),
            completion_tokens=obs._est_tokens(__import__("json").dumps(result, ensure_ascii=False)),
            latency_ms=(_tm.monotonic() - start) * 1000,
            mock=True,
        )
        return result

    client = get_client()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    start = _tm.monotonic()
    response = await client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        temperature=temperature,
        max_tokens=settings.llm_max_output_tokens,
        response_format={"type": "json_object"},
    )
    latency_ms = (_tm.monotonic() - start) * 1000
    content = response.choices[0].message.content or ""
    usage = getattr(response, "usage", None)
    obs.record_llm(
        agent=agent,
        kind="chat_json",
        prompt_tokens=getattr(usage, "prompt_tokens", obs._est_tokens(system, user)),
        completion_tokens=getattr(usage, "completion_tokens", obs._est_tokens(content)),
        latency_ms=latency_ms,
    )
    try:
        return _extract_json(content)
    except (json.JSONDecodeError, ValueError):
        # 解析失败：带错误信息重试一次，强化 JSON 约束
        start = _tm.monotonic()
        retry = await client.chat.completions.create(
            model=settings.llm_model,
            messages=messages + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": "上面的输出不是合法 JSON。请只输出一个合法的 JSON 对象，不要任何解释或代码块标记。"},
            ],
            temperature=0.0,
            max_tokens=settings.llm_max_output_tokens,
            response_format={"type": "json_object"},
        )
        latency_ms = (_tm.monotonic() - start) * 1000
        retry_content = retry.choices[0].message.content or ""
        retry_usage = getattr(retry, "usage", None)
        obs.record_llm(
            agent=agent,
            kind="chat_json_retry",
            prompt_tokens=getattr(retry_usage, "prompt_tokens", obs._est_tokens(system, user)),
            completion_tokens=getattr(retry_usage, "completion_tokens", obs._est_tokens(retry_content)),
            latency_ms=latency_ms,
        )
        return _extract_json(retry_content)


async def chat_text(
    agent: str,
    system: str,
    user: str,
    mock_ctx: dict[str, Any] | None = None,
    temperature: float = 0.4,
) -> str:
    """纯文本调用（Analyst / Writer）。"""
    import time as _tm

    from app import obs

    settings = get_settings()
    if settings.mock_mode:
        start = _tm.monotonic()
        text = _mock_text(agent, mock_ctx or {})
        obs.record_llm(
            agent=agent,
            kind="chat_text(mock)",
            prompt_tokens=obs._est_tokens(system, user),
            completion_tokens=obs._est_tokens(text),
            latency_ms=(_tm.monotonic() - start) * 1000,
            mock=True,
        )
        return text

    client = get_client()
    start = _tm.monotonic()
    response = await client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=settings.llm_max_output_tokens,
    )
    latency_ms = (_tm.monotonic() - start) * 1000
    content = response.choices[0].message.content or ""
    usage = getattr(response, "usage", None)
    obs.record_llm(
        agent=agent,
        kind="chat_text",
        prompt_tokens=getattr(usage, "prompt_tokens", obs._est_tokens(system, user)),
        completion_tokens=getattr(usage, "completion_tokens", obs._est_tokens(content)),
        latency_ms=latency_ms,
    )
    return content


# ---------------------------------------------------------------------------
# 演示模式内置应答
# ---------------------------------------------------------------------------

def _mock_json(agent: str, user: str, ctx: dict[str, Any]) -> dict[str, Any]:
    if agent == "planner":
        # 演示规划：把问题本身作为任务主题（问题即研究范围），保证与问题字面对齐
        question = ctx.get("question", "研究问题")
        tasks = [
            {"id": "t1", "title": question[:20], "purpose": "明确研究范围"},
            {"id": "t2", "title": "收集并整理解读关键事实与数据", "purpose": "获取一手证据"},
            {"id": "t3", "title": "提炼核心结论与风险局限", "purpose": "形成可判断的洞察"},
        ]
        return {"tasks": tasks}

    if agent == "researcher":
        # 演示提取：基于真实检索结果生成带来源编号的事实
        tasks = ctx.get("tasks", [])
        search_results = ctx.get("search_results", [])
        findings = []
        for i, item in enumerate(search_results, start=1):
            results = item.get("results") or [{}]
            # 轮询取不同顺位结果，避免多个子任务命中同一文献导致 claim 重复
            result = results[(i - 1) % len(results)]
            snippet = (result.get("snippet") or "").strip()[:40]
            claim = snippet or f"围绕「{item.get('subtask_id', '')}」检索到的关键事实。"
            findings.append(
                {
                    "subtask_id": item.get("subtask_id", f"t{i}"),
                    "claim": claim,
                    "source_ref": f"S{i}",
                }
            )
        return {"findings": findings}

    if agent == "critic":
        # 从提示词中解析当前评审轮次：第 1 轮打回，第 2 轮起通过 —— 用于演示重试回路
        match = re.search(r"第\s*(\d+)\s*轮", user)
        round_no = int(match.group(1)) if match else 1
        if round_no <= 1:
            return {
                "score": 5.5,
                "passed": False,
                "feedback": "[演示数据] 证据覆盖不足：子任务 t2 缺少定量数据支撑，且部分结论没有引用来源，请补充检索。",
            }
        return {
            "score": 8.0,
            "passed": True,
            "feedback": "[演示数据] 证据覆盖完整，引用与结论对齐，逻辑一致，可以进入撰写阶段。",
        }

    raise ValueError(f"未知 agent: {agent}")


def _mock_text(agent: str, ctx: dict[str, Any]) -> str:
    question = ctx.get("question", "研究问题")
    findings = ctx.get("findings", [])
    claims = "\n".join(
        f"- {f.get('claim', '')}（来源：{f.get('source_ref', 'S?')}）" for f in findings
    ) or "- [演示数据] 暂无发现"

    if agent == "analyst":
        return (
            f"## 综合分析（演示模式）\n\n"
            f"围绕「{question}」的交叉验证结果：\n\n{claims}\n\n"
            "各来源结论相互印证，未发现明显矛盾；建议在报告中按'结论 - 证据 - 风险'结构组织。"
        )

    if agent == "writer":
        body = "\n".join(
            f"- {f.get('claim', '')} [{f.get('source_ref', 'S?')}]" for f in findings
        ) or "- 暂无足够证据"
        cit = "[S1][S2][S3]" if len(findings) >= 2 else "".join(f"[{f.get('source_ref', 'S1')}]" for f in findings)
        return (
            f"# 研究报告：{question}\n\n"
            f"## 核心结论\n\n基于本地多源证据的综合研判 {cit}\n\n"
            f"## 详细分析\n\n{body}\n\n"
            "## 风险与局限\n\n演示模式基于轻量种子知识库产出；接入真实检索后证据覆盖将更完整。\n"
        )

    raise ValueError(f"未知 agent: {agent}")

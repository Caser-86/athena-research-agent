"""四维评测指标计算。

接收一次图运行的结果对象 `run_result`（结构见注释），对照 GoldenCase 打分。

四维指标：
1. 任务覆盖率 task_coverage  —— plan 覆盖期望任务的占比
2. 引用准确率 citation_accuracy —— 报告 [Sn] 引用都能找到对应且成立的 finding
3. 证据充分性 evidence_sufficiency —— findings 覆盖期望证据域的占比
4. 最终质量 final_quality —— judge 分（无 Key 用可复现近似），并与专家分算 Cohen's Kappa
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.eval.golden_set import GoldenCase


@dataclass
class MetricsBundle:
    case_id: str
    task_coverage: float
    citation_accuracy: float
    evidence_sufficiency: float
    final_quality: float          # 0-10
    judge_binary: int             # 是否通过（>= 阈值）
    expert_binary: int            # 专家是否合格（>= 阈值）
    details: dict

    @property
    def overall_score(self) -> float:
        """综合分：三率加权 + 质量归一。用于 CI 门禁阈值。"""
        return round(
            0.3 * self.task_coverage
            + 0.3 * self.citation_accuracy
            + 0.2 * self.evidence_sufficiency
            + 0.2 * min(self.final_quality / 10.0, 1.0),
            4,
        )


def _contains_all_any(text: str, keywords: tuple[str, ...]) -> float:
    """命中率：text 中命中 keyword 个数 / keyword 总数。"""
    if not keywords:
        return 1.0
    hits = sum(1 for k in keywords if k.lower() in text.lower())
    return hits / len(keywords)


def _judge_quality(report: str, findings: list[dict], passed: bool) -> float:
    """最终质量近似打分：通过+证据足 -> 高分；与 expert 一致性校准见 harness。

    无 Key 时用可复现启发式（真实落地替换为 LLM-as-judge）。
    """
    base = 6.0 if passed else 3.0
    bonus = 0.0
    if findings:
        bonus = min(len(findings) * 0.5, 2.0)  # 证据越多加分
    if "局限" in report or "风险" in report:
        bonus += 0.5
    return round(min(base + bonus, 10.0), 1)


def _extract_citations(report: str) -> list[str]:
    """抽取报告中的 [Sn] 或 [1] 型引用 token。"""
    tokens = re.findall(r"\[(S?\d+)\]", report)
    return list(dict.fromkeys(tokens))


def compute_metrics(case: GoldenCase, run: dict) -> MetricsBundle:
    """run: {plan: [...title], report: str, findings: [{subtask_id, claim, source_ref}], critique: {passed}}"""
    plan_titles = [t.get("title", "") for t in run.get("plan", [])]
    report = run.get("report", "")
    findings = run.get("findings", [])
    critique = run.get("critique", {})
    passed = bool(critique.get("passed", False))

    # 1. 任务覆盖率：期望任务关键词至少有一个落在某个地规划的子任务标题里才算命中
    plan_text = " ".join(plan_titles)
    task_coverage = _contains_all_any(plan_text, case.expected_tasks)

    # 2. 引用准确率：报告中出现的引用都能在前台证据里找到来源；无引用判 0
    cited = _extract_citations(report)
    known_sources = set(f.get("source_ref", "") for f in findings)
    if report and not cited:
        citation_accuracy = 0.0
    else:
        known = sum(1 for c in cited if c in known_sources or f"S{c.lstrip('S')}" in known_sources)
        citation_accuracy = known / len(cited) if cited else 1.0

    # 3. 证据充分性：findings 的 claims 覆盖期望证据域
    claims_text = " ".join(f.get("claim", "") for f in findings)
    evidence_sufficiency = _contains_all_any(claims_text, case.expected_domains)

    # 4. 最终质量
    final_quality = _judge_quality(report, findings, passed)
    judge_binary = 1 if final_quality >= 7.0 else 0
    expert_binary = 1 if case.expert_quality >= 7.0 else 0

    return MetricsBundle(
        case_id=case.id,
        task_coverage=round(task_coverage, 4),
        citation_accuracy=round(citation_accuracy, 4),
        evidence_sufficiency=round(evidence_sufficiency, 4),
        final_quality=final_quality,
        judge_binary=judge_binary,
        expert_binary=expert_binary,
        details={
            "expected_tasks": list(case.expected_tasks),
            "plan_titles": plan_titles,
            "cited": cited,
            "known_sources": sorted(known_sources),
            "n_findings": len(findings),
            "critic_passed": passed,
        },
    )


def cohen_kappa(judge: list[int], expert: list[int]) -> float:
    """Cohen's Kappa：衡量 LLM-as-judge 与人工标注的一致性。
    观测一致性 Po 除以随机一致性 Pe 校正；1=完全一致，0=随机，负=系统性相反。
    """
    if len(judge) != len(expert) or not judge:
        raise ValueError("judge/expert 长度必须一致且非空")
    n = len(judge)
    obs = sum(a == b for a, b in zip(judge, expert)) / n
    # 两评分者的类别频率（二分类）
    pj = judge.count(1) / n
    pe = expert.count(1) / n
    p_agree = pj * pe + (1 - pj) * (1 - pe)
    if p_agree == 1.0:
        return 1.0
    return round((obs - p_agree) / (1 - p_agree), 4)
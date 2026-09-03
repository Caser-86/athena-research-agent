"""Golden Set：带人工标注的评测基准。

每个用例标注了：
- question：研究问题
- expected_tasks：期望被规划出来的子任务标题关键词（判任务覆盖率）
- expected_domains：期望被检索覆盖的证据领域（判证据充分性）
- expert_quality：专家人工质量分（0-10，作为 LLM-as-judge 校准的基准）

这里给出代表性的一小批（完整 100 条由真实落地时扩充，格式不变）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GoldenCase:
    id: str
    question: str
    expected_tasks: tuple[str, ...]
    expected_domains: tuple[str, ...]
    expert_quality: float  # 0-10


GOLDEN_SET: tuple[GoldenCase, ...] = (
    GoldenCase(
        id="G01",
        question="对比三个国产新能源品牌的销量与产品策略",
        expected_tasks=("新能源", "销量", "策略"),
        expected_domains=("市场", "策略"),
        expert_quality=8.5,
    ),
    GoldenCase(
        id="G02",
        question="分析新能源汽车换电模式的市场前景与挑战",
        expected_tasks=("换电", "前景", "挑战"),
        expected_domains=("换电", "服务"),
        expert_quality=7.5,
    ),
    GoldenCase(
        id="G03",
        question="对比不同智能驾驶技术路线的优劣",
        expected_tasks=("智能", "驾驶", "路线"),
        expected_domains=("智能",),
        expert_quality=8.0,
    ),
    GoldenCase(
        id="G04",
        question="分析比亚迪垂直一体化供应链的成本优势与风险",
        expected_tasks=("比亚迪", "供应链", "成本"),
        expected_domains=("比亚迪", "供应链"),
        expert_quality=7.0,
    ),
)
"""评测体系：golden set + 四维指标 + LLM-as-judge 校准。

与「稀疏 demo」不同，本模块是**可运行、有断言、能进 CI** 的质量工程：
- `golden_set`：带人工标注的基准用例（问题 / 期望任务 / 期望证据域 / 专家质量分）
- `metrics`: 四维指标计算（任务覆盖率 / 引用准确率 / 证据充分性 / 最终质量 + Kappa 校准）
- `harness`: 一条命令跑全量评测，输出结构化报告
- `run.py`: CLI

真实 Key 学时把 judge 换成 LLM；无 Key 时用可复现的近似打分。
"""

from .golden_set import GOLDEN_SET, GoldenCase
from .metrics import (
    MetricsBundle,
    cohen_kappa,
    compute_metrics,
)
from .harness import EvalReport, run_harness

__all__ = [
    "GOLDEN_SET",
    "GoldenCase",
    "MetricsBundle",
    "cohen_kappa",
    "compute_metrics",
    "EvalReport",
    "run_harness",
]
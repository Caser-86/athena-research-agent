"""评测流水线：一条命令跑全量 golden set，输出报告 + 门禁判定。

CI 用法（见 .github/workflows/eval.yml）：
    python -m app.eval.run --threshold 0.6
exit code !=0 表示未达到门禁，阻断合并。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from app.eval.golden_set import GOLDEN_SET
from app.eval.metrics import MetricsBundle, cohen_kappa, compute_metrics


async def _run_case(question: str) -> dict:
    """真实跑一次编排图（演示模式即可产出上下文）。"""
    from app.graph.builder import get_research_graph

    graph = get_research_graph()
    final = await graph.ainvoke(
        {"question": question},
        config={"configurable": {"thread_id": f"eval-{abs(hash(question)) % 100000}"}},
    )
    return {
        "plan": final.get("plan", []),
        "report": final.get("report", ""),
        "findings": final.get("findings", []),
        "critique": final.get("critique", {}),
    }


@dataclass
class EvalReport:
    results: list[MetricsBundle] = field(default_factory=list)
    aggregate: dict[str, float] = field(default_factory=dict)
    kappa: float = 0.0
    passed_threshold: bool = False
    threshold: float = 0.6

    def to_dict(self) -> dict[str, Any]:
        return {
            "threshold": self.threshold,
            "aggregate": self.aggregate,
            "kappa": self.kappa,
            "passed_threshold": self.passed_threshold,
            "cases": [self._bundle_to_dict(r) for r in self.results],
        }

    @staticmethod
    def _bundle_to_dict(r: MetricsBundle) -> dict:
        return {
            "case_id": r.case_id,
            "task_coverage": r.task_coverage,
            "citation_accuracy": r.citation_accuracy,
            "evidence_sufficiency": r.evidence_sufficiency,
            "final_quality": r.final_quality,
            "overall_score": r.overall_score,
            "details": r.details,
        }


async def _collect() -> list[MetricsBundle]:
    bundles: list[MetricsBundle] = []
    for case in GOLDEN_SET:
        run = await _run_case(case.question)
        bundles.append(compute_metrics(case, run))
    return bundles


def _aggregate(bundles: list[MetricsBundle]) -> dict[str, float]:
    n = len(bundles) or 1
    return {
        "avg_task_coverage": round(sum(b.task_coverage for b in bundles) / n, 4),
        "avg_citation_accuracy": round(sum(b.citation_accuracy for b in bundles) / n, 4),
        "avg_evidence_sufficiency": round(sum(b.evidence_sufficiency for b in bundles) / n, 4),
        "task_success_rate": round(
            sum(1 for b in bundles if b.task_coverage >= 0.8) / n, 4
        ),
        "citation_rate": round(
            sum(1 for b in bundles if b.citation_accuracy >= 0.8) / n, 4
        ),
    }


async def run_harness(threshold: float = 0.6) -> EvalReport:
    bundles = await _collect()
    aggregate = _aggregate(bundles)

    overall = sum(b.overall_score for b in bundles) / (len(bundles) or 1)
    aggregate["overall_score"] = round(overall, 4)

    kappa = cohen_kappa(
        [b.judge_binary for b in bundles],
        [b.expert_binary for b in bundles],
    )
    aggregate["judge_expert_kappa"] = kappa

    return EvalReport(
        results=bundles,
        aggregate=aggregate,
        kappa=kappa,
        passed_threshold=overall >= threshold,
        threshold=threshold,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Athena eval harness")
    parser.add_argument("--threshold", type=float, default=0.6, help="整体门禁阈值")
    parser.add_argument("--out", type=str, default=None, help="输出 JSON 报告路径")
    args = parser.parse_args(argv)

    report = asyncio.run(run_harness(args.threshold))
    dump = report.to_dict()
    output = json.dumps(dump, ensure_ascii=False, indent=2)
    print(output)

    if args.out:
        import pathlib

        pathlib.Path(args.out).write_text(output, encoding="utf-8")

    print(
        f"\n[HARNESS] overall={dump['aggregate']['overall_score']} "
        f"threshold={args.threshold} -> {'PASS' if report.passed_threshold else 'FAIL'} "
        f"(kappa={report.kappa})"
    )
    return 0 if report.passed_threshold else 1


if __name__ == "__main__":
    raise SystemExit(main())
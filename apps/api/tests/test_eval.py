"""评测体系单元测试。"""

from __future__ import annotations

import pytest

from app.eval.golden_set import GOLDEN_SET
from app.eval.metrics import cohen_kappa, compute_metrics


def _run(plan=None, report=None, findings=None, passed=True):
    return {
        "plan": [{"title": t} for t in (plan or [])],
        "report": report or "# 报告\n## 结论\n参考 [S1][S2]。\n## 风险与局限\n...",
        "findings": findings or [
            {"subtask_id": "t1", "claim": "比亚迪换电服务市场领先", "source_ref": "S1"},
            {"subtask_id": "t2", "claim": "蔚来供应链垂直一体化", "source_ref": "S2"},
        ],
        "critique": {"passed": passed, "score": 8.0},
    }


def test_task_coverage_positive():
    case = next(c for c in GOLDEN_SET if c.id == "G01")
    m = compute_metrics(case, _run(plan=["比亚迪销量与策略", "蔚来换电", "行业数据"]))
    assert m.task_coverage > 0.5


def test_citation_unknown_sources_penalizes():
    case = next(c for c in GOLDEN_SET if c.id == "G01")
    run = _run()
    run["report"] = "# 报告\n引用 [S99]"  # 引用来源不存在
    m = compute_metrics(case, run)
    assert m.citation_accuracy == 0.0


def test_no_citations_when_report_has_claims():
    case = next(c for c in GOLDEN_SET if c.id == "G01")
    run = _run()
    run["report"] = "# 报告\n一段没有引用的结论。"
    m = compute_metrics(case, run)
    assert m.citation_accuracy == 0.0


def test_evidence_sufficiency():
    case = next(c for c in GOLDEN_SET if c.id == "G01")
    run = _run(findings=[{"subtask_id": "t1", "claim": "市场渗透率提升", "source_ref": "S1"}])
    m = compute_metrics(case, run)
    assert 0.0 <= m.evidence_sufficiency <= 1.0


def test_cohen_kappa_perfect_and_random():
    assert cohen_kappa([1, 1, 0, 0], [1, 1, 0, 0]) == 1.0
    k = cohen_kappa([0, 0, 1, 1], [1, 1, 0, 0])
    assert k < 0, "完全相反应得负 Kappa"


def test_cohen_kappa_raises_on_mismatch():
    import pytest as _p

    with _p.raises(ValueError):
        cohen_kappa([1, 0], [1])


@pytest.mark.asyncio
async def test_harness_runs_all_golden_cases():
    from app.eval.harness import run_harness

    report = await run_harness(0.6)
    assert len(report.results) == len(GOLDEN_SET)
    assert "overall_score" in report.aggregate
    assert report.passed_threshold in (True, False)
    assert 0.0 <= report.kappa <= 1.0 or report.kappa < 0.0  # Kappa 区间合法
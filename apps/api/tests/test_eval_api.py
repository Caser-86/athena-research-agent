"""评测看板 API 测试（演示模式 / 强制 mock）。"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_eval_summary():
    r = client.get("/api/eval/summary")
    assert r.status_code == 200
    data = r.json()
    assert "aggregate" in data and "overall_score" in data["aggregate"]
    assert "kappa" in data and "passed_threshold" in data


def test_eval_cases():
    r = client.get("/api/eval/cases")
    assert r.status_code == 200
    cases = r.json()["cases"]
    assert len(cases) == 4
    assert all("case_id" in c and "overall_score" in c for c in cases)


@pytest.mark.asyncio
async def test_eval_cache_deduplicates_concurrent_runs(monkeypatch):
    from app.api import eval_routes

    eval_routes._cached.clear()
    calls = 0

    async def fake_run_harness(_threshold):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return object()

    monkeypatch.setattr(eval_routes, "run_harness", fake_run_harness)
    try:
        reports = await asyncio.gather(
            eval_routes._get_report(0.5),
            eval_routes._get_report(0.5),
        )
        assert calls == 1
        assert reports[0] is reports[1]
    finally:
        eval_routes._cached.clear()

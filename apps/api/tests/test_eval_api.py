"""评测看板 API 测试（演示模式 / 强制 mock）。"""

from __future__ import annotations

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
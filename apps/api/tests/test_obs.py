"""可观测性层测试：LLM 采集 + 任务级记录 + API 暴露（演示模式）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import obs
from app.main import app

client = TestClient(app)


def test_flow_records_llm_and_task():
    obs.reset()
    # 跑一次完整任务，触发多个 chat_json / chat_text 调用
    r = client.post(
        "/api/research/run",
        json={"question": "对比蔚来与比亚迪的产品策略"},
    )
    assert r.status_code == 200
    assert r.json()["iteration"] >= 2  # 质量回路至少打回一轮

    s = obs.summary()
    assert s["llm_calls"] >= 1
    assert s["total_tokens"] > 0
    assert s["total_cost"] > 0.0
    assert s["task_count"] == 1
    assert set(s["per_agent"].keys()) & {"planner", "researcher", "analyst", "critic", "writer"}


def test_obs_api_endpoints():
    obs.reset()
    client.post("/api/research/run", json={"question": "测试可观测性 API"})
    summ = client.get("/api/obs/summary")
    assert summ.status_code == 200
    assert "total_cost" in summ.json() and "per_agent" in summ.json()

    spans = client.get("/api/obs/spans")
    assert spans.status_code == 200
    data = spans.json()
    assert len(data["spans"]) >= 1 and len(data["tasks"]) == 1
    assert data["tasks"][0]["iterations"] >= 1
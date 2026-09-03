"""存储层测试：内存后端 + SQL 后端（SQLite 真实验证通用 schema/CRUD）+ API 集成。"""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from app.storage import Base, InMemoryStorage, SqlStorage


def _sample(task_id: str) -> dict:
    return {
        "task_id": task_id,
        "question": "测试问题",
        "iteration": 3,
        "report": "# 报告",
        "critique": {"passed": True, "score": 8.0},
        "plan": [{"id": "t1", "title": "任务一"}],
        "findings": [{"subtask_id": "t1", "claim": "事实A"}],
        "analysis": "交叉验证",
        "mock_mode": "True",
    }


def test_in_memory_crud():
    st = InMemoryStorage()
    st.save_task(_sample("a1"))
    assert st.get_task("a1")["question"] == "测试问题"
    assert st.get_task("nope") is None
    assert [t["task_id"] for t in st.list_tasks()] == ["a1"]


def test_sql_storage_crud(tmp_path):
    db = tmp_path / "athena_test.db"
    st = SqlStorage(f"sqlite:///{db}")
    st.save_task(_sample("sql-1"))
    row = st.get_task("sql-1")
    assert row is not None
    assert row["question"] == "测试问题"
    assert row["iteration"] == 3
    # JSON 列往返
    assert row["critique"]["score"] == 8.0
    assert row["plan"][0]["title"] == "任务一"
    assert row["findings"][0]["claim"] == "事实A"
    assert st.get_task("missing") is None
    assert [t["task_id"] for t in st.list_tasks()] == ["sql-1"]


def test_api_tasks_with_sql_dsn(tmp_path, monkeypatch):
    """把 ATHENA_PG_DSN 指向临时 SQLite，验证任务写入走 SQL 后端并可经 API 读回。"""
    db = tmp_path / "athena_api.db"
    monkeypatch.setenv("ATHENA_PG_DSN", f"sqlite:///{db}")
    monkeypatch.setenv("ATHENA_MOCK_FORCE", "true")
    # 重置已缓存配置与存储单例，使新 DSN 生效
    from app.config import get_settings

    get_settings.cache_clear()
    from app.storage import reset_storage

    reset_storage()

    from app.main import app

    c = TestClient(app)  # noqa: F841
    r = c.post("/api/research/run", json={"question": "入库问题"})
    assert r.status_code == 200
    task_id = r.json()["task_id"]

    # 用新连接（模拟另一个会话/进程）直接读 SQL，确认真的落库而非内存
    st = SqlStorage(f"sqlite:///{db}")
    row = st.get_task(task_id)
    assert row is not None and row["question"] == "入库问题"

    # API 读回
    got = c.get(f"/api/research/tasks/{task_id}")
    assert got.status_code == 200 and got.json()["question"] == "入库问题"
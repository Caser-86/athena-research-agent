"""可插拔存储层：历史任务持久化。

设计：定义 StorageBackend 抽象，提供两种实现——
- InMemoryStorage：默认，进程内 dict，保持轻量（旧行为，测试/演示零依赖）；
- SqlStorage：SQLAlchemy 通用关系型后端，DSN 可切 SQLite 或 PostgreSQL，
  通过 config `ATHENA_PG_DSN` 启用。全量逻辑在 SQLite 上真实可验证；
  PostgreSQL 走同套 schema，向量列/pgvector 开启后再启用 pgvector 距离检索。

语义：任务写入要连贯地落库，run / stream 结束后调用 save_task；内存的进程重启即丢，
改 DSN 后任务可跨进程恢复，且为后续 LangGraph PostgresSaver（断点续跑）留接口。
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text, func
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


# ---------------------------------------------------------------------------
# 抽象
# ---------------------------------------------------------------------------

class StorageBackend(ABC):
    @abstractmethod
    def save_task(self, task: dict) -> None: ...

    @abstractmethod
    def get_task(self, task_id: str) -> dict | None: ...

    @abstractmethod
    def list_tasks(self, limit: int = 20) -> list[dict]: ...


# ---------------------------------------------------------------------------
# 内存实现（默认）
# ---------------------------------------------------------------------------

class InMemoryStorage(StorageBackend):
    """进程内存储。并发写加锁；端口不与真实数据冲突。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[str, dict] = {}

    def save_task(self, task: dict) -> None:
        with self._lock:
            stored = dict(task)
            # 内存后端补充 created_at，与 SQL 后端对齐（ISO 字符串）
            if "created_at" not in stored:
                import datetime

                stored["created_at"] = datetime.datetime.now().isoformat()
            self._store[task["task_id"]] = stored

    def get_task(self, task_id: str) -> dict | None:
        with self._lock:
            return self._store.get(task_id)

    def list_tasks(self, limit: int = 20) -> list[dict]:
        with self._lock:
            return list(self._store.values())[-limit:]


# ---------------------------------------------------------------------------
# SQLAlchemy 关系型实现
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


class ResearchTask(Base):
    __tablename__ = "research_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(32), unique=True, nullable=False, index=True)
    question = Column(Text, nullable=False)
    iteration = Column(Integer, default=1)
    report = Column(Text, default="")
    critique = Column(JSON, nullable=True)
    plan = Column(JSON, nullable=True)
    findings = Column(JSON, nullable=True)
    analysis = Column(Text, default="")
    mock_mode = Column(String(16), default="")
    created_at = Column(DateTime, server_default=func.now())


class SqlStorage(StorageBackend):
    """通用关系型后端。DSN 形如 sqlite:///athena.db 或 postgresql://user:pw@host/db。"""

    def __init__(self, dsn: str) -> None:
        assert dsn, "SqlStorage 需要非空 DSN"
        self.engine: Engine = create_engine(dsn, future=True)
        Base.metadata.create_all(self.engine)
        self._session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def save_task(self, task: dict) -> None:
        with Session(self.engine) as s, s.begin():
            row = ResearchTask(
                task_id=task["task_id"],
                question=task.get("question", ""),
                iteration=task.get("iteration", 1),
                report=task.get("report", ""),
                critique=task.get("critique"),
                plan=task.get("plan"),
                findings=task.get("findings"),
                analysis=task.get("analysis", ""),
                mock_mode=str(task.get("mock_mode", "")),
            )
            s.add(row)

    def get_task(self, task_id: str) -> dict | None:
        with Session(self.engine) as s:
            row = s.query(ResearchTask).filter(ResearchTask.task_id == task_id).first()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_tasks(self, limit: int = 20) -> list[dict]:
        with Session(self.engine) as s:
            rows = s.query(ResearchTask).order_by(ResearchTask.id.desc()).limit(limit).all()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: ResearchTask) -> dict:
        return {
            "task_id": row.task_id,
            "question": row.question,
            "iteration": row.iteration,
            "report": row.report,
            "critique": row.critique,
            "plan": row.plan,
            "findings": row.findings,
            "analysis": row.analysis,
            "mock_mode": row.mock_mode,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------

_thread_local = threading.local()


def get_storage() -> StorageBackend:
    """进程级单例（测试中用 monkeypatch/环境变量重置）。未配置 DSN 时用内存实现。"""
    inst = getattr(_thread_local, "storage", None)
    if inst is None:
        dsn = get_settings().pg_dsn
        inst = SqlStorage(dsn) if dsn else InMemoryStorage()
        _thread_local.storage = inst
    return inst


def reset_storage() -> None:
    """清空单例（测试隔离用）。"""
    if hasattr(_thread_local, "storage"):
        del _thread_local.storage
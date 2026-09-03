"""研究任务路由：同步运行 / SSE 流式 / 任务查询。

任务存储：第 1 周使用进程内字典（演示足够），第 2 周替换为 PostgreSQL。
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.graph.builder import get_research_graph
from app.graph.events import EventBus
from app.schemas import ResearchRequest, ResearchResult
from app.storage import get_storage

router = APIRouter(prefix="/api/research", tags=["research"])

# 并发控制：全局信号量限制同时运行的编排任务数（默认 4）。
# 超出并发上限的请求会进入排队（注册表标记 waiting），避免大量慢任务挤爆进程。
_MAX_CONCURRENCY = 4
_concurrency = asyncio.Semaphore(_MAX_CONCURRENCY)
# 运行中/排队任务注册表：task_id -> {status, question, agent, iteration}
_q_registry: dict[str, dict] = {}
_q_lock = threading.Lock()


def _q_state() -> dict:
    with _q_lock:
        return {
            "running": [dict(v) for v in _q_registry.values() if v["status"] != "waiting"],
            "waiting": [dict(v) for v in _q_registry.values() if v["status"] == "waiting"],
            "max_concurrency": _MAX_CONCURRENCY,
        }


def _q_register(task_id: str, status: str, question: str, agent: str = "", iteration: int = 1) -> None:
    with _q_lock:
        _q_registry[task_id] = {
            "task_id": task_id,
            "status": status,
            "question": question[:60],
            "agent": agent,
            "iteration": iteration,
        }


def _q_update(task_id: str, **kw) -> None:
    with _q_lock:
        if task_id in _q_registry:
            _q_registry[task_id].update(kw)


def _q_deregister(task_id: str) -> None:
    """任务结束（成功/异常/取消）后移出队列注册表，避免残留 done 条目被误判为运行中。"""
    with _q_lock:
        _q_registry.pop(task_id, None)


async def _run_graph(question: str, task_id: str, bus: EventBus | None = None) -> dict:
    """执行编排图并返回最终状态。
    并发控制：基于信号量限定同时运行数；进入执行即标记 running，结束后清理注册表项。
    """
    import time

    from app import obs

    _q_register(task_id, "running", question)
    try:
        async with _concurrency:
            start = time.monotonic()
            graph = get_research_graph()
            state = {"question": question, "task_id": task_id}
            final_state = await graph.ainvoke(
                state,
                config={"configurable": {"thread_id": task_id, "event_bus": bus}},
            )
            result = {
                "task_id": task_id,
                "question": question,
                "report": final_state.get("report", ""),
                "iteration": final_state.get("iteration", 1),
                "critique": final_state.get("critique"),
                "plan": final_state.get("plan", []),
                "findings": final_state.get("findings", []),
                "analysis": final_state.get("analysis", ""),
                "mock_mode": get_settings().mock_mode,
            }
            # 可观测性：任务级记录（iteration - 1 = Critic 打回重试次数）
            obs.record_task(
                question=question,
                iterations=final_state.get("iteration", 1),
                latency_ms=(time.monotonic() - start) * 1000,
            )
            # 持久化：内存或 SQL（DSN 配置），SQL 时跨进程可查
            await asyncio.to_thread(get_storage().save_task, result)
            return result
    finally:
        # 无论成功/异常都释放队列槽位并移出注册表
        _q_deregister(task_id)


@router.post("/run", response_model=ResearchResult)
async def run_research(body: ResearchRequest) -> dict:
    """同步运行：阻塞至报告产出，返回最终状态。"""
    task_id = uuid.uuid4().hex[:12]
    return await _run_graph(body.question, task_id)


@router.post("/stream")
async def stream_research(body: ResearchRequest) -> StreamingResponse:
    """SSE 流式运行：逐 Agent 推送轨迹事件，最后推送 final。"""

    async def event_generator():
        task_id = uuid.uuid4().hex[:12]
        _q_register(task_id, "waiting", body.question)
        yield f"event: queue\ndata: {json.dumps({'type':'queue','task_id':task_id,'status':'waiting'}, ensure_ascii=False)}\n\n"
        bus = EventBus()
        task = asyncio.create_task(_run_graph(body.question, task_id, bus))
        try:
            while True:
                try:
                    event = await asyncio.wait_for(bus.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    if task.done():
                        break
                    continue
                yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            # 消费残余事件，保证轨迹完整
            while not bus.empty():
                event = await bus.get()
                yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            task.cancel()
            raise

        try:
            result = await task
            yield f"event: final\ndata: {json.dumps(result, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001 — SSE 通道需要把异常透传给客户端
            yield f"event: error\ndata: {json.dumps({'message': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/queue")
async def queue_status() -> dict:
    """查看并发队列：运行中 + 排队任务 + 并发上限。"""
    return _q_state()


@router.get("/tasks")
async def list_task_history(limit: int = 15) -> dict:
    """历史任务列表（不含整篇报告，仅摘要字段，便于前端渲染列表）。"""
    tasks = await asyncio.to_thread(get_storage().list_tasks, limit)
    summary = [
        {
            "task_id": t["task_id"],
            "question": t["question"],
            "iteration": t["iteration"],
            "mock_mode": t.get("mock_mode", ""),
            "created_at": t.get("created_at"),
            # 报告首行作为预览
            "preview": (t.get("report") or "").strip().splitlines()[:1],
        }
        for t in tasks
    ]
    return {"tasks": summary, "total": len(summary)}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str) -> dict:
    """查询历史任务（内存或 SQL 存储后端）。"""
    task = await asyncio.to_thread(get_storage().get_task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在或存储中未找到")
    return task

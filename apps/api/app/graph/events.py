"""事件总线：Agent 节点 -> SSE 推送。

节点通过 config["configurable"]["event_bus"] 获取总线实例；
未提供总线（如同步 run、测试）时为 None，节点静默跳过推送。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from langchain_core.runnables import RunnableConfig


class EventBus:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def emit(self, event_type: str, **payload: Any) -> None:
        await self._queue.put({"type": event_type, "ts": time.time(), **payload})

    async def get(self) -> dict[str, Any]:
        return await self._queue.get()

    def empty(self) -> bool:
        return self._queue.empty()


def get_bus(config: RunnableConfig | None) -> EventBus | None:
    """从 LangGraph 节点 config 中安全取出事件总线。"""
    if not config:
        return None
    return (config.get("configurable") or {}).get("event_bus")

"""MCP 工具进程内调用包装。

把 FastMCP 注册的原子工具按统一异步签名调用，并写入可观测层（span type="tool"），
使前端能展示「调用链」。LangGraph 节点只依赖本模块的 call_tool，不直接碰
FastMCP 内部结构，便于后续替换为真正独立的 MCP server（同接口）。

用法：
    from app.mcp.tools import call_tool
    result = await call_tool("web_search", {"query": "...", "max_results": 3}, agent="researcher")
"""

from __future__ import annotations

import time
from typing import Any

from app import obs
from app.mcp.server import athena_mcp


def _tool_fn(name: str) -> Any:
    """从 FastMCP 内部 ToolManager 取已注册工具的可调用函数。

    mcp 1.x 中 `athena_mcp._tool_manager._tools[name].fn` 为内部结构；
    为隔离版本演进，这里集中在单点取值，节点层不感知差异。
    """
    manager = getattr(athena_mcp, "_tool_manager", None)
    if manager is None:
        raise KeyError(f"MCP 工具管理器不可用: {name}")
    tools = getattr(manager, "_tools", {})
    tool = tools.get(name)
    if tool is None or getattr(tool, "fn", None) is None:
        raise KeyError(f"MCP 工具未注册: {name}")
    return tool.fn


async def call_tool(name: str, args: dict, *, agent: str = "tool") -> Any:
    """调用一个 MCP 工具并记录到观测层。返回工具原始结果。"""
    fn = _tool_fn(name)
    start = time.monotonic()
    result = await fn(**args)
    obs.record_tool(
        agent=agent,
        kind=name,
        latency_ms=(time.monotonic() - start) * 1000,
        args_preview=f"{name}({', '.join(f'{k}={v}' for k, v in list(args.items())[:2])})",
    )
    return result
"""MCP 工具服务测试：校验工具注册与行为（演示模式，无需外部 Key）。"""

from __future__ import annotations

import pytest

from app.mcp.server import athena_mcp


def _tool(name: str):
    return athena_mcp._tool_manager._tools[name].fn


@pytest.mark.asyncio
async def test_call_tool_wrapper_records_obs():
    """统一包装 call_tool 调用工具并把调用写入可观测层（tool span）。"""
    from app import obs
    from app.mcp.tools import call_tool

    obs.reset()
    rst = await call_tool("web_search", {"query": "新能源销量", "max_results": 2}, agent="researcher")
    assert len(rst) == 2
    tools = [s for s in obs.get_spans() if s["type"] == "tool"]
    assert len(tools) == 1
    assert tools[0]["kind"] == "web_search"
    assert tools[0]["agent"] == "researcher"
    assert tools[0]["latency_ms"] >= 0
    # 汇总里能看到工具调用计数与调用链
    summary = obs.summary()
    assert summary["tool_calls"] == 1
    assert summary["tools"][0]["kind"] == "web_search"


@pytest.mark.asyncio
async def test_call_tool_unknown_raises():
    from app.mcp.tools import call_tool

    with pytest.raises(KeyError):
        await call_tool("not_a_real_tool", {})


def test_tools_registered():
    assert set(athena_mcp._tool_manager._tools.keys()) == {
        "web_search", "sql_query", "python_sandbox", "doc_parser",
    }


@pytest.mark.asyncio
async def test_web_search_demo_mode():
    rst = await _tool("web_search")("新能源销量")
    assert len(rst) == 5


@pytest.mark.asyncio
async def test_sql_query_blocks_non_select():
    rst = await _tool("sql_query")("DROP TABLE users", "nope.db")
    assert "只读" in rst["error"]


@pytest.mark.asyncio
async def test_sql_query_readonly(tmp_path):
    import sqlite3

    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (a INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?)", [(1,), (2,), (3,)])
    conn.commit()
    conn.close()
    rst = await _tool("sql_query")("SELECT a FROM t", str(db))
    assert rst == [{"a": 1}, {"a": 2}, {"a": 3}]


@pytest.mark.asyncio
async def test_python_sandbox_blocks_danger():
    rst = await _tool("python_sandbox")("import os\nos.system('echo hi')")
    assert "拦截" in rst["error"]


@pytest.mark.asyncio
async def test_python_sandbox_runs():
    rst = await _tool("python_sandbox")("print(2+3)")
    assert "5" in rst["stdout"]


@pytest.mark.asyncio
async def test_doc_parser_local(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("# 标题\n正文内容 abc", encoding="utf-8")
    rst = await _tool("doc_parser")(str(f))
    assert "标题" in rst and "正文" in rst
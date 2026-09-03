"""Athena MCP 工具服务实现。

用 FastMCP 暴露研究 Agent 所需工具，可作为 LangGraph 节点的 function-calling 工具。
工具集演进刻意对齐企业级 Agent 的工程关切（安全 / 可观测 / 审计）：

- web_search      联网检索（未配置 Key 时返回演示结果）
- sql_query       只读 SQL 查询（鉴权 + 只读连接 + 行数限制）
- python_sandbox  受限 Python 执行（危险操作拦截 + 超时，演示实现）
- doc_parser      解析文件 / URL 的正文为文本

独立进程运行：
    python -m app.mcp.server
LangGraph 进程内调用：`from app.mcp.server import athena_mcp`（toll 已注册，可用
`athena_mcp.call_tool(name, args)` 同步调用；异步包装见 tools.py）。
"""

from __future__ import annotations

import re
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from app.config import get_settings

athena_mcp = FastMCP("athena-research")


@athena_mcp.tool()
async def web_search(query: str, max_results: int = 5) -> list[dict]:
    """联网搜索研究问题。未配置 TAVILY_API_KEY 时返回演示结果。"""
    settings = get_settings()
    if settings.tavily_api_key:
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.tavily_api_key,
                    "query": query,
                    "max_results": max_results,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")[:300]}
            for r in data.get("results", [])
        ]
    return [
        {
            "title": f"[演示] {query} 相关公开资料 {i + 1}",
            "url": "https://example.com",
            "snippet": "演示检索结果。（未配置检索 Key）",
        }
        for i in range(max_results)
    ]


@athena_mcp.tool()
async def sql_query(sql: str, db_path: str) -> list[dict]:
    """对 SQLite 执行只读查询。仅允许 SELECT/WITH；强制 LIMIT 50。
    生产环境应改用独立的只读账号与连接池，而非本演示实现。"""
    if not re.match(r"^\s*(SELECT|WITH)\b", sql, re.IGNORECASE):
        return {"error": "仅支持只读 SELECT/WITH 查询"}
    if not Path(db_path).exists():
        return {"error": f"数据库不存在: {db_path}"}
    try:
        with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(sql[:1000] + " LIMIT 50")
            return [dict(row) for row in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@athena_mcp.tool()
async def python_sandbox(code: str, timeout_seconds: int = 10) -> dict:
    """在受限 Python 中执行代码并返回 stdout。演示实现打通流程；
    生产环境应替换为 Docker 沙箱 + CPU/内存/网络三元组限制。"""
    # 简单黑名单拦截（演示防空转/注入；真正的隔离须在进程/容器边界）
    blocked_patterns = [r"^\s*import\s+(os|sys|subprocess|socket)\b", r"\bopen\s*\(", r"\beval\s*\(", r"\bexec\s*\("]
    if any(re.search(p, code) for p in blocked_patterns):
        return {"error": "危险操作被沙箱拦截（演示沙箱，生产见 Docker）"}
    with tempfile.TemporaryDirectory() as td:
        file = Path(td) / "run.py"
        file.write_text(code, encoding="utf-8")
        try:
            proc = subprocess.run(
                ["python", str(file)],
                capture_output=True, text=True, timeout=timeout_seconds, cwd=td,
            )
            return {
                "stdout": proc.stdout,
                "stderr": proc.stderr[-1000:],
                "returncode": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"error": f"执行超时（>{timeout_seconds}s）"}


@athena_mcp.tool()
async def doc_parser(source: str) -> str:
    """解析文件路径或 URL 为纯文本（截断至 5000 字符）。"""
    if source.startswith(("http://", "https://")):
        import httpx

        resp = httpx.get(source, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", "", resp.text)
        return re.sub(r"<[^>]+>", " ", text)[:5000]
    path = Path(source)
    if path.exists():
        return path.read_text(encoding="utf-8", errors="ignore")[:5000]
    return f"无法解析来源: {source}"


if __name__ == "__main__":
    athena_mcp.run()
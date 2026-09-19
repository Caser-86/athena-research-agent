"""Athena MCP 工具服务实现。

用 FastMCP 暴露研究 Agent 所需工具，可作为 LangGraph 节点的 function-calling 工具。
工具集演进刻意对齐企业级 Agent 的工程关切（安全 / 可观测 / 审计）：

- web_search      联网检索（未配置 Key 时返回演示结果）
- sql_query       只读 SQL 查询（鉴权 + 只读连接 + 行数限制）
- python_sandbox  受限 Python 执行（危险操作拦截 + 超时，演示实现）
- doc_parser      解析文件 / URL 的正文为文本

独立进程运行：
    python -m app.mcp.server
LangGraph 进程内调用：`from app.mcp.server import athena_mcp`（tool 已注册，可用
`athena_mcp.call_tool(name, args)` 同步调用；异步包装见 tools.py）。
"""

from __future__ import annotations

import ast
import asyncio
import ipaddress
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP

from app.config import get_settings

athena_mcp = FastMCP("athena-research")


@athena_mcp.tool()
async def web_search(query: str, max_results: int = 5) -> list[dict]:
    """联网搜索研究问题。未配置 ATHENA_TAVILY_API_KEY 时返回演示结果。"""
    max_results = max(0, min(max_results, 10))
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
async def sql_query(sql: str, db_path: str) -> list[dict] | dict:
    """对 SQLite 执行只读查询。仅允许 SELECT/WITH；强制 LIMIT 50。
    生产环境拒绝调用方提供任意路径；应改用受控数据服务。"""
    if get_settings().environment == "production":
        return {"error": "生产环境禁止按路径查询 SQLite，请接入受控数据服务"}
    if len(sql) > 1000:
        return {"error": "SQL 长度不能超过 1000 个字符"}
    sql = sql.strip()
    if sql.endswith(";"):
        sql = sql[:-1].rstrip()
    if ";" in sql:
        return {"error": "仅支持单条 SQL 语句"}
    if not re.match(r"^(SELECT|WITH)\b", sql, re.IGNORECASE):
        return {"error": "仅支持只读 SELECT/WITH 查询"}
    db = Path(db_path).expanduser().resolve()
    if not db.is_file():
        return {"error": f"数据库不存在: {db_path}"}
    try:
        # 包裹原查询再绑定 LIMIT，避免直接拼接破坏 ORDER BY/LIMIT 或引入多语句。
        bounded_sql = f"SELECT * FROM ({sql}) LIMIT ?"
        with closing(sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(bounded_sql, (50,))
            return [dict(row) for row in cur.fetchall()]
    except (OSError, sqlite3.Error):
        return {"error": "数据库查询失败"}


_SAFE_SANDBOX_CALLS = {"print", "len", "sum", "min", "max", "range", "sorted"}


class _UnsafeSandboxCode(ValueError):
    pass


_FORBIDDEN_SANDBOX_NODES = (
    ast.Import,
    ast.ImportFrom,
    ast.Attribute,
    ast.Lambda,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.Raise,
    ast.Yield,
    ast.YieldFrom,
)


def _validate_sandbox_code(code: str) -> None:
    """只允许演示计算子集；这不是生产级安全边界。"""
    if len(code) > 10_000:
        raise ValueError("代码长度不能超过 10000 个字符")
    tree = ast.parse(code, mode="exec")
    for node in ast.walk(tree):
        if isinstance(node, _FORBIDDEN_SANDBOX_NODES):
            raise _UnsafeSandboxCode("危险操作被沙箱拦截（演示沙箱，生产见 Docker）")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise _UnsafeSandboxCode("危险操作被沙箱拦截（演示沙箱，生产见 Docker）")
        if isinstance(node, ast.Call) and (
            not isinstance(node.func, ast.Name) or node.func.id not in _SAFE_SANDBOX_CALLS
        ):
            raise _UnsafeSandboxCode("危险操作被沙箱拦截（演示沙箱，生产见 Docker）")


@athena_mcp.tool()
async def python_sandbox(code: str, timeout_seconds: int = 10) -> dict:
    """在受限 Python 中执行代码并返回 stdout。演示实现打通流程；
    生产环境应替换为 Docker 沙箱 + CPU/内存/网络三元组限制。"""
    if get_settings().environment == "production":
        return {"error": "生产环境已禁用演示级 python_sandbox，请接入隔离执行服务"}
    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or not 1 <= timeout_seconds <= 30:
        return {"error": "timeout_seconds 必须在 1-30 秒范围内"}
    try:
        _validate_sandbox_code(code)
    except (SyntaxError, ValueError) as exc:
        return {"error": str(exc)}
    with tempfile.TemporaryDirectory() as td:
        file = Path(td) / "run.py"
        file.write_text(code, encoding="utf-8")
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-I", str(file)],
                capture_output=True, text=True, timeout=timeout_seconds, cwd=td,
                env={"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
            )
            return {
                "stdout": proc.stdout,
                "stderr": proc.stderr[-1000:],
                "returncode": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"error": f"执行超时（>{timeout_seconds}s）"}


async def _assert_public_url(source: str) -> None:
    parsed = urlparse(source)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not hostname or parsed.username or parsed.password:
        raise ValueError("仅支持不含凭据的 HTTP(S) URL")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith((".local", ".internal")):
        raise ValueError("禁止访问本机或内网地址")
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, hostname, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("URL 域名无法解析") from exc
    for info in infos:
        address = info[4][0]
        ip = ipaddress.ip_address(address)
        if any((ip.is_private, ip.is_loopback, ip.is_link_local, ip.is_reserved, ip.is_multicast, ip.is_unspecified)):
            raise ValueError("禁止访问本机或内网地址")


@athena_mcp.tool()
async def doc_parser(source: str) -> str:
    """解析文件路径或 URL 为纯文本（截断至 5000 字符）。"""
    if source.startswith(("http://", "https://")):
        import httpx

        try:
            await _assert_public_url(source)
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client, client.stream("GET", source) as resp:
                resp.raise_for_status()
                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > 1_000_000:
                        break
            raw = b"".join(chunks)[:1_000_000]
            text = raw.decode(resp.encoding or "utf-8", errors="replace")
        except (ValueError, httpx.HTTPError) as exc:
            return f"无法解析来源: {exc}"
        text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", "", text)
        return re.sub(r"<[^>]+>", " ", text)[:5000]
    settings = get_settings()
    if not settings.doc_root:
        return "无法解析来源：本地文档解析未启用，请配置 ATHENA_DOC_ROOT"
    root = Path(settings.doc_root).expanduser().resolve()
    path = Path(source).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return "无法解析来源：本地路径不在 ATHENA_DOC_ROOT 允许目录内"
    if path.is_file():
        def _read_prefix() -> str:
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                return f.read(5000)

        return await asyncio.to_thread(_read_prefix)
    return f"无法解析来源: {source}"


if __name__ == "__main__":
    athena_mcp.run()

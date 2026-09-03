"""API 鉴权依赖。

采用静态 API Key 校验：客户端在请求头携带
  `Authorization: Bearer <key>` 或 `X-API-Key: <key>`
任一匹配即通过。`ATHENA_API_KEY` 未配置时保持开放（本地演示/内网），
配置后对受保护路由统一拦截，返回 401。
"""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.config import get_settings

_SCHEMES = ("bearer",)


def _verify(token: str | None) -> None:
    settings = get_settings()
    if not settings.api_key:
        return  # 未启用鉴权：放行（仅内网/开发使用）
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 API Key：请携带 Authorization: Bearer <key> 或 X-API-Key: <key>",
        )
    if token.strip() != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key 无效",
        )


async def require_api_key(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> None:
    """FastAPI 依赖：校验请求携带的 API Key（Bearer 或 X-API-Key）。"""
    # 解析 Authorization: Bearer <key>
    token: str | None = None
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].strip().lower() in _SCHEMES:
            token = parts[1].strip()
        else:
            token = authorization.strip()
    if token is None:
        token = x_api_key
    _verify(token)
"""API 鉴权 + CORS 收敛测试。

通过 `create_app()` 工厂为每个用例构建隔离的 FastAPI 实例（不污染全局 app），
覆盖三档：
1. 未配置 ATHENA_API_KEY：开放放行，匿名可访问受保护路由。
2. 配置 Key 后：缺失 / 错误 Key 返回 401；正确 Key（Bearer 或 X-API-Key）放行。
3. CORS：配置白名单后，仅白名单 Origin 收到跨域允许头；/health 始终公开。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


def _build(monkeypatch, **env) -> TestClient:
    monkeypatch.delenv("ATHENA_API_KEY", raising=False)
    monkeypatch.delenv("ATHENA_CORS_ALLOWED_ORIGINS", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    app = create_app()
    yield TestClient(app)
    get_settings.cache_clear()


@pytest.fixture
def open_client(monkeypatch):
    yield from _build(monkeypatch)


@pytest.fixture
def protected_client(monkeypatch):
    yield from _build(
        monkeypatch,
        ATHENA_API_KEY="test-secret-key",
        ATHENA_CORS_ALLOWED_ORIGINS="http://localhost:8080",
    )


def test_open_mode_allows_anonymous(open_client):
    r = open_client.get("/api/obs/summary")
    assert r.status_code == 200


def test_open_mode_health_public(open_client):
    r = open_client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_missing_key_401(protected_client):
    assert protected_client.get("/api/obs/summary").status_code == 401


def test_wrong_key_401(protected_client):
    r = protected_client.get("/api/obs/summary", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_valid_bearer_key_200(protected_client):
    r = protected_client.get("/api/obs/summary", headers={"Authorization": "Bearer test-secret-key"})
    assert r.status_code == 200


def test_valid_x_api_key_200(protected_client):
    r = protected_client.get("/api/obs/summary", headers={"X-API-Key": "test-secret-key"})
    assert r.status_code == 200


def test_health_always_public_when_protected(protected_client):
    assert protected_client.get("/health").status_code == 200


def test_cors_whitelist_blocks_unknown_origin(protected_client):
    r = protected_client.options(
        "/api/obs/summary",
        headers={"Origin": "http://evil.example.com", "Access-Control-Request-Method": "GET"},
    )
    assert "evil" not in r.headers.get("access-control-allow-origin", "")


def test_cors_whitelist_allows_known_origin(protected_client):
    r = protected_client.options(
        "/api/obs/summary",
        headers={"Origin": "http://localhost:8080", "Access-Control-Request-Method": "GET"},
    )
    assert "localhost:8080" in r.headers.get("access-control-allow-origin", "")
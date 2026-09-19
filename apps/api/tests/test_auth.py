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


def test_api_key_uses_constant_time_comparison(monkeypatch):
    from app import auth

    monkeypatch.setenv("ATHENA_API_KEY", "test-secret-key")
    get_settings.cache_clear()
    calls = []

    def compare_digest(left, right):
        calls.append((left, right))
        return left == right

    monkeypatch.setattr(auth.secrets, "compare_digest", compare_digest)
    try:
        auth._verify("test-secret-key")
        assert calls == [("test-secret-key", "test-secret-key")]
    finally:
        get_settings.cache_clear()


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


def test_task_list_rejects_non_positive_limit(open_client):
    r = open_client.get("/api/research/tasks?limit=0")
    assert r.status_code == 422


def test_stream_does_not_expose_internal_exception(monkeypatch):
    from app.api import routes as research_routes
    from app.main import app

    async def fail_graph(*_args, **_kwargs):
        raise RuntimeError("postgres://user:secret@internal.example/db")

    monkeypatch.setattr(research_routes, "_run_graph", fail_graph)
    response = TestClient(app).post("/api/research/stream", json={"question": "测试"})

    assert response.status_code == 200
    assert "研究任务执行失败" in response.text
    assert "postgres://" not in response.text
    assert "secret" not in response.text


def test_production_disables_debug_docs_and_requires_cors(monkeypatch):
    monkeypatch.setenv("ATHENA_ENVIRONMENT", "production")
    monkeypatch.setenv("ATHENA_API_KEY", "production-key")
    monkeypatch.setenv("ATHENA_CORS_ALLOWED_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("ATHENA_ALLOWED_HOSTS", "app.example.com")
    get_settings.cache_clear()
    try:
        app = create_app()
        client = TestClient(app)
        headers = {"Host": "app.example.com"}
        assert client.get("/docs", headers=headers).status_code == 404
        assert client.get("/openapi.json", headers=headers).status_code == 404
    finally:
        get_settings.cache_clear()


def test_production_without_cors_allowlist_fails_fast(monkeypatch):
    monkeypatch.setenv("ATHENA_ENVIRONMENT", "production")
    monkeypatch.setenv("ATHENA_API_KEY", "production-key")
    monkeypatch.delenv("ATHENA_CORS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.setenv("ATHENA_ALLOWED_HOSTS", "app.example.com")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="CORS"):
            create_app()
    finally:
        get_settings.cache_clear()


def test_production_without_api_key_fails_fast(monkeypatch):
    monkeypatch.setenv("ATHENA_ENVIRONMENT", "production")
    monkeypatch.delenv("ATHENA_API_KEY", raising=False)
    monkeypatch.setenv("ATHENA_CORS_ALLOWED_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("ATHENA_ALLOWED_HOSTS", "app.example.com")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="API_KEY"):
            create_app()
    finally:
        get_settings.cache_clear()


def test_production_without_allowed_hosts_fails_fast(monkeypatch):
    monkeypatch.setenv("ATHENA_ENVIRONMENT", "production")
    monkeypatch.setenv("ATHENA_API_KEY", "production-key")
    monkeypatch.setenv("ATHENA_CORS_ALLOWED_ORIGINS", "https://app.example.com")
    monkeypatch.delenv("ATHENA_ALLOWED_HOSTS", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="ALLOWED_HOSTS"):
            create_app()
    finally:
        get_settings.cache_clear()


def test_production_rejects_untrusted_host(monkeypatch):
    monkeypatch.setenv("ATHENA_ENVIRONMENT", "production")
    monkeypatch.setenv("ATHENA_API_KEY", "production-key")
    monkeypatch.setenv("ATHENA_CORS_ALLOWED_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("ATHENA_ALLOWED_HOSTS", "app.example.com")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        assert client.get("/health", headers={"Host": "evil.example.com"}).status_code == 400
    finally:
        get_settings.cache_clear()

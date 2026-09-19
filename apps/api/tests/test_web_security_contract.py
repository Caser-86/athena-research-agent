"""前端同源鉴权契约测试，防止把 API 凭据交给浏览器。"""

import re
from pathlib import Path


ROOT = Path(__file__).parents[3]
WEB = ROOT / "apps" / "web"


def test_frontend_does_not_use_query_parameter_as_api_override():
    html = (WEB / "index.html").read_text(encoding="utf-8")

    assert "URLSearchParams" not in html
    assert "ATHENA_API_KEY" not in html
    assert "X-API-Key" not in html
    assert "style=" not in html
    assert ".style." not in html
    assert not re.search(r"\son(?:click|keydown|submit|load|input|change|keyup|focus|blur)=", html)


def test_web_proxy_injects_api_key_server_side():
    dockerfile = (WEB / "Dockerfile").read_text(encoding="utf-8")
    nginx = (WEB / "nginx.conf").read_text(encoding="utf-8")
    entrypoint = (WEB / "docker-entrypoint.sh").read_text(encoding="utf-8")

    assert "athena-entrypoint.sh" in dockerfile
    assert "${ATHENA_API_KEY}" in nginx
    assert "envsubst '${ATHENA_API_KEY}'" in entrypoint


def test_web_proxy_rate_limits_expensive_research_endpoints():
    nginx = (WEB / "nginx.conf").read_text(encoding="utf-8")

    assert "limit_req_zone $binary_remote_addr" in nginx
    assert "location ~ ^/api/research/(run|stream)$" in nginx
    assert "limit_req zone=athena_research" in nginx


def test_web_proxy_sets_browser_security_headers():
    nginx = (WEB / "nginx.conf").read_text(encoding="utf-8")

    assert "Content-Security-Policy" in nginx
    assert "'unsafe-inline'" not in nginx
    assert "sha256-UyzbubvaYZjmlReyCG+oht34+kx1NvZkC4nDnXgerzw=" in nginx
    assert "sha256-scAMKX9q39jiWbCqXPjGQo12fkHXtqSHb0L4EkvoIqY=" in nginx
    assert "object-src 'none'" in nginx
    assert "frame-ancestors 'none'" in nginx
    assert "X-Content-Type-Options" in nginx
    assert "Referrer-Policy" in nginx

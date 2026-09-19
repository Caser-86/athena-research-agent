"""配置模板与 Pydantic Settings 环境变量前缀的契约测试。"""

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[3]


def test_env_example_uses_athena_prefix_for_tavily():
    env_example = (ROOT / "apps" / "api" / ".env.example").read_text(encoding="utf-8")

    assert "ATHENA_TAVILY_API_KEY=" in env_example
    assert "\nTAVILY_API_KEY=" not in env_example


def test_compose_passes_production_gateway_settings_from_root_env():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "ATHENA_ENVIRONMENT: ${ATHENA_ENVIRONMENT:-development}" in compose
    assert "ATHENA_CORS_ALLOWED_ORIGINS: ${ATHENA_CORS_ALLOWED_ORIGINS:-}" in compose
    assert "ATHENA_ALLOWED_HOSTS: ${ATHENA_ALLOWED_HOSTS:-}" in compose


def test_observability_healthcheck_uses_configured_postgres_credentials():
    compose = (ROOT / "deploy" / "docker-compose.observability.yml").read_text(encoding="utf-8")

    assert 'pg_isready -U \\\"$${POSTGRES_USER}\\\" -d \\\"$${POSTGRES_DB}\\\"' in compose
    assert "pg_isready -U athena" not in compose


def test_production_requirements_do_not_include_test_runner():
    requirements = (ROOT / "apps" / "api" / "requirements.txt").read_text(encoding="utf-8")
    dev_requirements = (ROOT / "apps" / "api" / "requirements-dev.txt").read_text(encoding="utf-8")

    assert "pytest" not in requirements
    assert "pytest-asyncio" not in requirements
    assert "pytest>=8.0" in dev_requirements
    assert "pytest-asyncio>=0.23" in dev_requirements
    assert "ruff>=0.9" in dev_requirements


def test_production_compose_overlay_requires_non_development_credentials():
    overlay = (ROOT / "deploy" / "docker-compose.production.yml").read_text(encoding="utf-8")

    assert "ATHENA_ENVIRONMENT: production" in overlay
    assert "ATHENA_API_KEY:?" in overlay
    assert "ATHENA_CORS_ALLOWED_ORIGINS:?" in overlay
    assert "ATHENA_ALLOWED_HOSTS:?" in overlay
    assert "ATHENA_PG_DSN:?" in overlay
    assert "ATHENA_DB_PASSWORD:?" in overlay
    assert "athena_dev" not in overlay
    assert 'pg_isready -U \\\"$${POSTGRES_USER}\\\" -d \\\"$${POSTGRES_DB}\\\"' in overlay


def test_runtime_container_images_are_digest_pinned():
    api_dockerfile = (ROOT / "apps" / "api" / "Dockerfile").read_text(encoding="utf-8")
    web_dockerfile = (ROOT / "apps" / "web" / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "FROM python:3.12-slim@sha256:" in api_dockerfile
    assert "FROM nginx:1.27-alpine@sha256:" in web_dockerfile
    assert "image: pgvector/pgvector:pg16@sha256:" in compose


def test_dependency_lockfiles_are_used_by_runtime_and_ci():
    api_lock = ROOT / "apps" / "api" / "requirements.lock.txt"
    dev_lock = ROOT / "apps" / "api" / "requirements-dev.lock.txt"
    dockerfile = (ROOT / "apps" / "api" / "Dockerfile").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert api_lock.is_file() and "fastapi==" in api_lock.read_text(encoding="utf-8")
    assert dev_lock.is_file() and "pytest==" in dev_lock.read_text(encoding="utf-8")
    assert "requirements.lock.txt" in dockerfile
    assert "requirements-dev.lock.txt" in ci


def test_documentation_contract_script_passes():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_docs.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr

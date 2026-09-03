"""FastAPI 入口。"""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import require_api_key
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Athena Research Agent",
        description="企业级多智能体研究与分析平台 · LangGraph 编排 + FastAPI 网关",
        version="0.1.0",
    )

    # ---- CORS：生产收敛为白名单；未配置时本地开放（仅开发用）----
    _cors = [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors or ["*"],
        allow_credentials=bool(_cors),  # 通配 + 凭证互斥，白名单模式下才允许携带凭证
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- 鉴权：受保护路由统一校验 API Key（未配置时自动放行，便于本地演示）----
    _auth = [Depends(require_api_key)]

    # 延迟导入，避免循环依赖（路由模块 import get_settings）
    from app.api.eval_routes import router as eval_router
    from app.api.obs_routes import router as obs_router
    from app.api.rag_routes import router as rag_router
    from app.api.routes import router as research_router

    app.include_router(research_router, dependencies=_auth)
    app.include_router(rag_router, dependencies=_auth)
    app.include_router(eval_router, dependencies=_auth)
    app.include_router(obs_router, dependencies=_auth)

    @app.get("/health")
    async def health() -> dict:
        settings = get_settings()
        return {
            "status": "ok",
            "mock_mode": settings.mock_mode,
            "model": None if settings.mock_mode else settings.llm_model,
            "max_iterations": settings.max_iterations,
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)

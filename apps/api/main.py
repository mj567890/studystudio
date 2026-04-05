"""
apps/api/main.py
FastAPI 应用主入口

启动流程：
1. 初始化数据库扩展（pgvector）
2. 连接 RabbitMQ 事件总线
3. 初始化 MinIO 客户端
4. 注册所有路由
5. 启动事件消费者
"""
import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api.core.config import CONFIG
from apps.api.core.db import init_db
from apps.api.core.events import get_event_bus
from apps.api.core.storage import get_minio_client
from apps.api.modules.auth.router import router as auth_router
from apps.api.modules.knowledge.file_router import router as file_router
from apps.api.modules.routers import (
    learner_router,
    teaching_router,
    tutorial_router,
)
from apps.api.modules.admin.router import router as admin_router

logger = structlog.get_logger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="自适应学习平台 API",
        version="1.0.0",
        docs_url="/docs" if CONFIG.debug else None,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if CONFIG.debug else ["https://your-domain.com"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 全局异常处理
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled exception", path=request.url.path, error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"code": 500, "msg": "Internal server error", "trace_id": ""}
        )

    # 注册路由
    app.include_router(auth_router)
    app.include_router(file_router)
    app.include_router(learner_router)
    app.include_router(tutorial_router)
    app.include_router(teaching_router)
    app.include_router(admin_router)

    @app.on_event("startup")
    async def startup() -> None:
        logger.info("Starting up Adaptive Learning Platform API")
        await init_db()
        get_minio_client()   # 初始化 MinIO 客户端（确保 bucket 存在）
        event_bus = get_event_bus()
        await event_bus.connect()
        logger.info("Startup complete")

    @app.on_event("shutdown")
    async def shutdown() -> None:
        event_bus = get_event_bus()
        await event_bus.disconnect()
        logger.info("Shutdown complete")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "version": "1.0.0", "env": CONFIG.env}

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "apps.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=CONFIG.debug,
        workers=1 if CONFIG.debug else 4,
    )

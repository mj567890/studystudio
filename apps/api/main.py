"""
apps/api/main.py
FastAPI 应用主入口

启动流程：
1. 初始化数据库扩展（pgvector）
2. 连接 RabbitMQ 事件总线
3. 初始化 MinIO 客户端
4. 注册所有路由
5. 启动事件消费者

修复记录：
  FIX-D: startup() 中新增对 document_parsed 事件的订阅，
          触发 knowledge_tasks.run_extraction Celery 任务，
          解决"知识点审核为空"问题——之前事件发布后无人处理。
  FIX-E: startup() 中新增对 skeleton_generated 事件的订阅，
          触发 generate_annotations Celery 任务。
  FIX-F: startup() 中新增对 file_uploaded 事件的订阅，
          触发 knowledge_tasks.run_ingest Celery 任务，
          解决"文件上传后无人触发文档解析"问题。
  FIX-G: run_ingest / run_extraction 改用 apply_async(queue="knowledge")，
          确保任务进入 celery_worker 实际监听的 knowledge 队列，
          而非默认的 celery 队列（无人消费）。
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
from apps.api.modules.admin.ai_config_router import router as ai_config_router
from apps.api.modules.skill_blueprint.router import router as blueprint_router
from apps.api.modules.learner.eight_dim_endpoints import eight_dim_router

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
    app.include_router(ai_config_router)
    app.include_router(blueprint_router)
    app.include_router(eight_dim_router)

    @app.on_event("startup")
    async def startup() -> None:
        logger.info("Starting up Adaptive Learning Platform API")
        await init_db()
        get_minio_client()   # 初始化 MinIO 客户端（确保 bucket 存在）

        event_bus = get_event_bus()
        await event_bus.connect()

        # ── FIX-F：订阅 file_uploaded 事件 ──────────────────────────
        async def on_file_uploaded(envelope: dict) -> None:
            payload    = envelope.get("payload", {})
            file_id    = payload.get("file_id")
            minio_key  = payload.get("minio_key")
            space_type = payload.get("space_type", "personal")
            space_id   = payload.get("space_id")
            owner_id   = payload.get("owner_id")
            file_name  = payload.get("file_name")

            if not file_id or not minio_key:
                logger.warning("file_uploaded event missing required fields", envelope=envelope)
                return

            logger.info(
                "file_uploaded received, dispatching ingest",
                file_id=file_id,
                file_name=file_name,
            )
            # FIX-G：指定 queue="knowledge"，确保进入 worker 监听的队列
            from apps.api.tasks.knowledge_tasks import run_ingest
            run_ingest.apply_async(
                args=[file_id, minio_key, space_type, space_id, owner_id, file_name],
                queue="knowledge",
            )

        await event_bus.subscribe(
            event_name="file_uploaded",
            queue_name="knowledge.ingest.queue",
            handler=on_file_uploaded,
        )

        # ── FIX-D：订阅 document_parsed 事件 ──────────────────────────
        async def on_document_parsed(envelope: dict) -> None:
            payload = envelope.get("payload", {})
            document_id = payload.get("document_id")
            space_type  = payload.get("space_type", "personal")
            space_id    = payload.get("space_id")

            if not document_id:
                logger.warning("document_parsed event missing document_id", envelope=envelope)
                return

            logger.info(
                "document_parsed received, dispatching extraction",
                document_id=document_id,
                space_type=space_type,
            )
            # FIX-G：指定 queue="knowledge"
            from apps.api.tasks.knowledge_tasks import run_extraction
            run_extraction.apply_async(
                args=[document_id, space_type, space_id],
                queue="knowledge",
            )

        await event_bus.subscribe(
            event_name="document_parsed",
            queue_name="knowledge.extraction.queue",
            handler=on_document_parsed,
        )

        # ── FIX-E：订阅 skeleton_generated 事件 ───────────────────────
        async def on_skeleton_generated(envelope: dict) -> None:
            payload      = envelope.get("payload", {})
            tutorial_id  = payload.get("tutorial_id")
            topic_key    = payload.get("topic_key")
            user_id      = payload.get("requesting_user_id")

            if not all([tutorial_id, topic_key, user_id]):
                logger.warning("skeleton_generated event missing fields", payload=payload)
                return

            logger.info(
                "skeleton_generated received, dispatching annotations",
                tutorial_id=tutorial_id,
                topic_key=topic_key,
            )
            from apps.api.tasks.tutorial_tasks import generate_annotations
            generate_annotations.apply_async(args=[tutorial_id, topic_key, user_id], queue="tutorial")

        await event_bus.subscribe(
            event_name="skeleton_generated",
            queue_name="tutorial.annotations.queue",
            handler=on_skeleton_generated,
        )

        async def on_knowledge_extracted(envelope: dict) -> None:
            payload   = envelope.get("payload", {})
            space_id  = payload.get("space_id")
            topic_key = payload.get("topic_key")
            if not topic_key:
                return
            logger.info("knowledge_extracted → triggering blueprint synthesis", topic_key=topic_key)
            from apps.api.tasks.blueprint_tasks import synthesize_blueprint
            synthesize_blueprint.apply_async(args=[topic_key, space_id], queue="knowledge")

        await event_bus.subscribe(
            event_name="knowledge_extracted",
            queue_name="blueprint.synthesis.queue",
            handler=on_knowledge_extracted,
        )

        logger.info("Startup complete — event subscriptions active")

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

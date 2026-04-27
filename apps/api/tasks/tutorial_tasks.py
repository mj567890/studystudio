"""
apps/api/tasks/tutorial_tasks.py
Celery 任务定义

C1（V2.6）：所有任务体必须是同步函数（prefork 池不支持顶层 async def）。
           内部通过 asyncio.run() 执行异步逻辑，每个 worker 进程独立事件循环。
"""
import asyncio

import structlog
import apps.api.tasks.fork_tasks  # noqa: F401 — 确保 fork_tasks 被 worker 发现
from celery import Celery, signals as celery_signals

from apps.api.core.config import CONFIG
from apps.api.tasks.task_tracker import task_tracker, register_tracker_signals

logger = structlog.get_logger(__name__)

celery_app = Celery(
    "adaptive_learning",
    broker=CONFIG.rabbitmq.celery_broker_url,
    backend="redis://redis:6379/1",
)
# ─────────────────────────────────────────────────────────────────
# FIX-1：worker 子进程启动时重置 engine，避免 fork 继承旧连接池
# ─────────────────────────────────────────────────────────────────
@celery_signals.worker_process_init.connect
def reset_db_engine(**kwargs):
    """
    每个 worker 子进程启动时重置数据库引擎。
    dispose(close=False)：丢弃父进程连接句柄，不主动关闭 TCP，
    子进程首次使用时重新建立连接池。
    """
    from apps.api.core.db import engine
    engine.sync_engine.dispose(close=False)


celery_app.conf.update(
    task_serializer       = "json",
    result_serializer     = "json",
    accept_content        = ["json"],
    timezone              = "UTC",
    enable_utc            = True,
    task_acks_late        = True,
    result_expires        = 3600,  # 任务结果1小时后自动过期，防止回复队列积压
    worker_prefetch_multiplier = 1,
    # 明确列出所有任务模块，确保 worker 启动时全部加载
    # 不加这行时，knowledge_tasks 因从未被 import 而对 worker 不可见
    include = [
        "apps.api.tasks.tutorial_tasks",
        "apps.api.tasks.blueprint_tasks",
        "apps.api.tasks.knowledge_tasks",
        "apps.api.tasks.auto_review_tasks",
        "apps.api.tasks.embedding_tasks",
    ],
    task_routes = {
        "apps.api.tasks.tutorial_tasks.generate_skeleton":        {"queue": "tutorial"},
        "apps.api.tasks.tutorial_tasks.generate_content":         {"queue": "tutorial"},
        "apps.api.tasks.tutorial_tasks.generate_annotations":     {"queue": "tutorial"},
        "apps.api.tasks.tutorial_tasks.prebuild_placement_bank":  {"queue": "low_priority"},
        "apps.api.tasks.knowledge_tasks.run_ingest":              {"queue": "knowledge"},
        "apps.api.tasks.knowledge_tasks.run_extraction":          {"queue": "knowledge"},
        "apps.api.tasks.auto_review_tasks.auto_review_entities":  {"queue": "knowledge.review"},
        "apps.api.tasks.embedding_tasks.embed_single_entity":     {"queue": "knowledge"},
        "apps.api.tasks.embedding_tasks.backfill_entity_embeddings": {"queue": "knowledge"},
        "apps.api.tasks.tutorial_tasks.check_dlq":                   {"queue": "low_priority"},
        "apps.api.tasks.auto_review_tasks.resume_pending_review":    {"queue": "knowledge.review"},  # resume_pending_review_v1
        "apps.api.tasks.fork_tasks.fork_space_task":             {"queue": "low_priority"},
        "apps.api.tasks.blueprint_tasks.regenerate_all_chapters": {"queue": "knowledge"},
        "apps.api.tasks.blueprint_tasks.synthesize_blueprint":      {"queue": "blueprint.synthesis.queue"},
    },
    # beat_schedule 已移至下方直接赋值
)

# beat_schedule_fix_v1: conf.update() 不支持 beat_schedule，需直接赋值
celery_app.conf.beat_schedule = {
    "check-dlq-every-5min": {
        "task": "apps.api.tasks.tutorial_tasks.check_dlq",
        "schedule": 300.0,
    },
    "resume-pending-review-every-5min": {
        "task": "apps.api.tasks.auto_review_tasks.resume_pending_review",
        "schedule": 300.0,
        "options": {"queue": "knowledge.review"},
    },
}

# 注册 TaskTracker 信号（task_prerun/postrun），自动记录任务生命周期
register_tracker_signals(celery_app)


# ─────────────────────────────────────────────────────────────────
# 骨架生成任务
# ─────────────────────────────────────────────────────────────────
@celery_app.task(bind=True, max_retries=2, default_retry_delay=5,
               on_failure=task_tracker.on_failure, on_success=task_tracker.on_success)
def generate_skeleton(self, tutorial_id: str, topic_key: str, requesting_user_id: str, space_id: str | None = None):
    """
    C1：同步包装 + asyncio.run()。
    骨架是主题级通用资产，不依赖任何用户信息。
    生成完成后发布 skeleton_generated 事件。
    """
    try:
        asyncio.run(_generate_skeleton_async(tutorial_id, topic_key, requesting_user_id, space_id))
    except Exception as exc:
        logger.error("generate_skeleton failed", error=str(exc))
        raise self.retry(exc=exc)


async def _generate_skeleton_async(
    tutorial_id: str, topic_key: str, requesting_user_id: str, space_id: str | None = None
) -> None:
    from apps.api.core.db import get_independent_db, engine
    from apps.api.core.events import get_event_bus
    from apps.api.modules.tutorial.tutorial_service import TutorialGenerationService

    # FIX-3：丢弃 fork 继承的旧连接句柄，避免 "attached to a different loop"
    engine.sync_engine.dispose(close=False)

    # FIX-2：Celery worker 绕过 FastAPI lifespan，需手动连接 EventBus
    event_bus = get_event_bus()
    if event_bus._connection is None or event_bus._connection.is_closed:
        await event_bus.connect()
    try:
        async with get_independent_db() as session:
            svc = TutorialGenerationService(session)
            await svc.build_skeleton(tutorial_id, topic_key, requesting_user_id, space_id=space_id)
    finally:
        await event_bus.disconnect()


# ─────────────────────────────────────────────────────────────────
# 内容填充任务
# ─────────────────────────────────────────────────────────────────
@celery_app.task(bind=True, max_retries=2, default_retry_delay=10,
               on_failure=task_tracker.on_failure, on_success=task_tracker.on_success)
def generate_content(self, tutorial_id: str):
    """C1：同步包装。LLM 驱动，内容生成失败可独立重试，不影响骨架。"""
    logger.info("generate_content start", tutorial_id=tutorial_id)
    try:
        asyncio.run(_generate_content_async(tutorial_id))
        logger.info("generate_content done", tutorial_id=tutorial_id)
    except Exception as exc:
        logger.error("generate_content failed", tutorial_id=tutorial_id, error=str(exc))
        raise self.retry(exc=exc)


async def _generate_content_async(tutorial_id: str) -> None:
    from apps.api.core.db import get_independent_db, engine
    from apps.api.modules.tutorial.tutorial_service import TutorialGenerationService

    # FIX-3：丢弃 fork 继承的旧连接句柄，避免 "attached to a different loop"
    engine.sync_engine.dispose(close=False)

    async with get_independent_db() as session:
        svc = TutorialGenerationService(session)
        await svc.fill_content(tutorial_id)


# ─────────────────────────────────────────────────────────────────
# Annotations 生成任务（事件驱动，B3修复）
# ─────────────────────────────────────────────────────────────────
@celery_app.task(bind=True, max_retries=2, default_retry_delay=5,
               on_failure=task_tracker.on_failure, on_success=task_tracker.on_success)
def generate_annotations(self, tutorial_id: str, topic_key: str, user_id: str):
    """C1：同步包装。订阅 skeleton_generated 事件后触发，消除轮询重试竞态。"""
    try:
        asyncio.run(_generate_annotations_async(tutorial_id, topic_key, user_id))
    except Exception as exc:
        logger.error("generate_annotations failed", error=str(exc))
        raise self.retry(exc=exc)


async def _generate_annotations_async(
    tutorial_id: str, topic_key: str, user_id: str
) -> None:
    from apps.api.core.db import get_independent_db, engine
    from apps.api.core.events import get_event_bus

    # FIX-3：丢弃 fork 继承的旧连接句柄
    engine.sync_engine.dispose(close=False)

    # FIX-4：Celery worker 中 GapScanService.scan() 会发布事件，需手动连接 EventBus
    event_bus = get_event_bus()
    if event_bus._connection is None or event_bus._connection.is_closed:
        await event_bus.connect()

    try:
        async with get_independent_db() as session:
            # 获取用户漏洞报告
            from apps.api.modules.learner.learner_service import GapScanService
            gap_svc = GapScanService(session)
            gap_report = await gap_svc.scan(user_id, topic_key)

            # 获取骨架章节树
            result = await session.execute(
                __import__("sqlalchemy").text(
                    "SELECT chapter_tree FROM tutorial_skeletons WHERE tutorial_id = :tid"
                ),
                {"tid": tutorial_id}
            )
            row = result.fetchone()
            if not row:
                return

            weak_ids = {wp["entity_id"] for wp in gap_report.get("weak_points", [])}

            # 为每个薄弱点章节创建 annotation
            for chapter in (row.chapter_tree or []):
                for eid in chapter.get("target_entity_ids", []):
                    if eid in weak_ids:
                        await session.execute(
                            __import__("sqlalchemy").text("""
                                INSERT INTO tutorial_annotations
                                  (annotation_id, tutorial_id, user_id, chapter_id,
                                   gap_types, priority_boost, is_weak_point)
                                VALUES
                                  (:aid, :tid, :uid, :chid, CAST(:gaps AS jsonb), 0.5, true)
                                ON CONFLICT (tutorial_id, user_id, chapter_id)
                                DO UPDATE SET priority_boost = 0.5, is_weak_point = true
                            """),
                            {
                                "aid":  __import__("uuid").uuid4().__str__(),
                                "tid":  tutorial_id,
                                "uid":  user_id,
                                "chid": chapter.get("chapter_id", ""),
                                "gaps": __import__("json").dumps(["definition"]),
                            }
                        )
            await session.commit()
            logger.info("Annotations generated", tutorial_id=tutorial_id, user_id=user_id)
    finally:
        if event_bus._connection is not None and not event_bus._connection.is_closed:
            await event_bus.disconnect()


# ─────────────────────────────────────────────────────────────────
# 冷启动题库预生成（低优先级离线任务）
# ─────────────────────────────────────────────────────────────────
@celery_app.task(queue="low_priority", bind=True, max_retries=1,
               on_failure=task_tracker.on_failure, on_success=task_tracker.on_success)
def prebuild_placement_bank(self, topic_key: str):
    """C1：同步包装。题库预生成，用户请求时直接读缓存，P95 < 50ms。"""
    try:
        asyncio.run(_prebuild_placement_bank_async(topic_key))
    except Exception as exc:
        logger.error("prebuild_placement_bank failed", topic_key=topic_key, error=str(exc))
        raise self.retry(exc=exc)


async def _prebuild_placement_bank_async(topic_key: str) -> None:
    from apps.api.core.db import get_independent_db, engine
    from apps.api.core.llm_gateway import get_llm_gateway

    # FIX-3：丢弃 fork 继承的旧连接句柄
    engine.sync_engine.dispose(close=False)
    import uuid as _uuid
    import json as _json
    import datetime as _dt
    from sqlalchemy import text as _text

    async with get_independent_db() as session:
        result = await session.execute(
            _text("SELECT is_ready FROM placement_question_banks WHERE topic_key = :tk"),
            {"topic_key": topic_key}
        )
        row = result.fetchone()
        if row and row.is_ready:
            return  # 题库已就绪，跳过

        llm = get_llm_gateway()
        domains_result = await session.execute(
            _text("""
                SELECT DISTINCT domain_tag FROM knowledge_entities
                WHERE review_status = 'approved'
                LIMIT 6
            """)
        )
        domains = [r.domain_tag for r in domains_result.fetchall()]

        questions_by_domain: dict = {}
        for domain in domains:
            domain_questions = []
            for difficulty in ("basic", "advanced"):
                prompt = (
                    f"请为领域「{domain}」生成一道{difficulty}难度的单选题，"
                    "考查核心概念掌握情况。"
                    "以JSON格式输出：{{\"stem\": \"题目\", \"options\": [\"A.\",\"B.\",\"C.\",\"D.\"], \"answer\": \"A\"}}"
                )
                try:
                    resp = await llm.generate(prompt, model_route="quiz_generation")
                    import re
                    clean = re.sub(r"^```json\s*|\s*```$", "", resp.strip())
                    q_data = _json.loads(clean)
                    domain_questions.append({
                        "question_id": str(_uuid.uuid4()),
                        "domain":      domain,
                        "difficulty":  difficulty,
                        "stem":        q_data.get("stem", f"请选择关于{domain}的正确描述"),
                        "options":     q_data.get("options", ["A", "B", "C", "D"]),
                        "answer":      q_data.get("answer", "A"),
                    })
                except Exception as e:
                    logger.warning("Quiz gen failed", domain=domain, difficulty=difficulty, error=str(e))
                    domain_questions.append({
                        "question_id": str(_uuid.uuid4()),
                        "domain":      domain,
                        "difficulty":  difficulty,
                        "stem":        f"您对「{domain}」领域的了解程度是？",
                        "options":     ["A. 熟练", "B. 了解", "C. 不熟悉", "D. 完全不了解"],
                        "answer":      "A",
                    })
            questions_by_domain[domain] = domain_questions

        bank_id = str(_uuid.uuid4())
        await session.execute(
            _text("""
                INSERT INTO placement_question_banks
                  (bank_id, topic_key, questions_by_domain, is_ready, built_at, expires_at)
                VALUES
                  (:bid, :tk, CAST(:qbd AS jsonb), true, NOW(), NOW() + INTERVAL '7 days')
                ON CONFLICT (topic_key)
                DO UPDATE SET
                  questions_by_domain = EXCLUDED.questions_by_domain,
                  is_ready = true, built_at = NOW(),
                  expires_at = NOW() + INTERVAL '7 days'
            """),
            {"bid": bank_id, "tk": topic_key,
             "qbd": _json.dumps(questions_by_domain, ensure_ascii=False)}
        )
        await session.commit()
        logger.info("Placement bank built", topic_key=topic_key, domains=len(domains))


# ─────────────────────────────────────────────────────────────────
# 死信队列巡检任务（celery_beat 每 5 分钟触发一次）
# ─────────────────────────────────────────────────────────────────
DLQ_NAMES = [
    "knowledge.ingest.queue.dlq",
    "knowledge.extraction.queue.dlq",
    "blueprint.synthesis.queue.dlq",
    "tutorial.annotations.queue.dlq",
]

@celery_app.task(name="apps.api.tasks.tutorial_tasks.check_dlq", queue="low_priority",
               bind=True, on_failure=task_tracker.on_failure, on_success=task_tracker.on_success)
def check_dlq(self) -> dict:
    """轮询所有死信队列，有积压消息时写入 task_executions 表，供管理页面告警。"""
    import urllib.request, urllib.error, json, base64

    RABBITMQ_API = "http://rabbitmq:15672/api/queues"
    creds = base64.b64encode(b"guest:guest").decode()
    req = urllib.request.Request(RABBITMQ_API, headers={"Authorization": f"Basic {creds}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            queues = {q["name"]: q.get("messages", 0) for q in json.loads(resp.read())}
    except Exception as exc:
        logger.warning("check_dlq: RabbitMQ 不可达", error=str(exc))
        return {"status": "unreachable"}

    alerts = []
    for name in DLQ_NAMES:
        count = queues.get(name, 0)
        if count > 0:
            alerts.append({"queue": name, "messages": count})
            logger.error(
                "DLQ 有积压消息，需要排查",
                queue=name,
                messages=count,
            )

    # 有积压时写入 task_executions 表，管理页面可观察到
    if alerts:
        import asyncio as _asyncio
        import os as _os, uuid as _uuid
        _asyncio.run(_record_dlq_alert(alerts))

    if not alerts:
        logger.info("check_dlq: 所有死信队列正常，无积压消息")
        return {"status": "ok", "alerts": []}

    return {"status": "alert", "alerts": alerts}


async def _record_dlq_alert(alerts: list[dict]) -> None:
    """将 DLQ 积压告警写入 task_executions，标记为需人工关注。"""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy.pool import NullPool
    from sqlalchemy import text as _text
    import json as _json

    db_url = __import__("os").environ.get("DATABASE_URL", "postgresql+asyncpg://user:pass@postgres:5432/adaptive_learning")
    engine = create_async_engine(db_url, poolclass=NullPool, connect_args={"timeout": 5})
    SF = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with SF() as session:
        for alert in alerts:
            await session.execute(
                _text("""
                    INSERT INTO task_executions
                        (task_name, queue, status, error_message, needs_manual_review, progress_detail, created_at, updated_at)
                    VALUES
                        ('check_dlq', 'low_priority', 'failed', :err, TRUE, CAST(:detail AS jsonb), NOW(), NOW())
                """),
                {
                    "err": f"死信队列 {alert['queue']} 积压 {alert['messages']} 条消息",
                    "detail": _json.dumps({"type": "dlq_alert", **alert}),
                }
            )
        await session.commit()

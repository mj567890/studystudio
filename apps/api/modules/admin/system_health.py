"""
apps/api/modules/admin/system_health.py
系统健康监控 API —— 队列、Worker、数据库状态一目了然

用法:
  1. 复制到 apps/api/modules/admin/system_health.py
  2. 在 main.py 中注册路由:
     from apps.api.modules.admin.system_health import health_router
     app.include_router(health_router, prefix="/api/admin/health", tags=["admin-health"])
  3. 访问 GET /api/admin/health  即可获取完整健康报告
"""

import asyncio
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.core.db import get_db
from sqlalchemy import text

from apps.api.core.db import async_session_factory
# 安全审计 2026-04-27：管理端点必须要求 admin 角色
from apps.api.modules.auth.router import require_role

health_router = APIRouter()

# ── RabbitMQ 配置（从环境变量或默认值）──
RABBITMQ_API = "http://rabbitmq:15672/api"
RABBITMQ_AUTH = ("guest", "guest")

# ── 已知的工作队列及其用途 ──
KNOWN_QUEUES = {
    "knowledge":                  "知识提取任务队列",
    "tutorial":                   "教程生成任务队列",
    "low_priority":               "低优先级任务队列",
    "celery":                     "默认队列（不应有任务）",
}

EVENT_QUEUES = {
    "knowledge.ingest.queue":       "文档摄入事件队列（API 进程消费）",
    "knowledge.extraction.queue":   "知识抽取事件队列（API 进程消费）",
    "blueprint.synthesis.queue":    "蓝图合成事件队列（API 进程消费）",
    "tutorial.annotations.queue":   "教程标注事件队列（API 进程消费）",
}

DLQ_QUEUES = {
    "knowledge.ingest.queue.dlq":       "文档摄入死信队列",
    "knowledge.extraction.queue.dlq":   "知识抽取死信队列",
    "blueprint.synthesis.queue.dlq":    "蓝图合成死信队列",
    "tutorial.annotations.queue.dlq":   "教程标注死信队列",
}


def _judge_queue(name: str, messages: int, consumers: int) -> dict:
    """对单个队列做出诊断判断"""
    status = "healthy"
    explanations = []

    is_dlq = name in DLQ_QUEUES
    is_known = name in KNOWN_QUEUES
    is_celery_default = name == "celery"
    is_reply_queue = ".reply." in name or ".pidbox" in name
    is_uuid_queue = len(name) == 36 and name.count("-") == 4  # UUID 格式

    is_event = name in EVENT_QUEUES

    if is_event:
        if consumers == 0:
            status = "warning"
            explanations.append("事件队列无消费者，API 进程可能未完成启动或已重启中。"
                                "API 启动完成后会自动恢复，通常等待 10-30 秒即可。")
        elif messages > 0:
            status = "healthy"
            explanations.append(f"事件队列有 {messages} 条事件待处理，API 进程正在消费中，运行正常")
        else:
            explanations.append("事件队列空闲，API 进程正在监听，运行正常")
        return {"status": status, "explanations": explanations, "category": "event"}

    if is_dlq:
        if messages > 0:
            status = "warning"
            explanations.append(f"死信队列中有 {messages} 条失败消息，说明有任务重试多次后仍然失败，需要排查原因")
        else:
            explanations.append("无失败消息，正常")
        return {"status": status, "explanations": explanations, "category": "dlq"}

    if is_reply_queue or is_uuid_queue:
        if messages > 0 and consumers == 0:
            status = "info"
            explanations.append(f"临时回复队列，有 {messages} 条遗留消息无人消费，占用内存极小，不浪费 Token")
        else:
            explanations.append("临时队列，正常")
        return {"status": status, "explanations": explanations, "category": "temp"}

    if is_celery_default:
        if messages > 0:
            status = "warning"
            explanations.append(f"默认队列中有 {messages} 条消息但无专属消费者，这些任务不会被执行。"
                                "通常是代码中用 .delay() 而非 .apply_async(queue=...) 发送导致的。"
                                "不会浪费 Token，但任务会丢失。")
        else:
            explanations.append("默认队列为空，正常")
        return {"status": status, "explanations": explanations, "category": "work"}

    if is_known:
        if consumers == 0:
            status = "error"
            explanations.append(f"队列无消费者！对应的 Worker 可能未启动或已崩溃，新任务将堆积无法处理")
        elif messages > 0:
            # P3_queue_backlog_healthy: 有消费者时积压属于正常运行状态
            # 注意：Celery prefork 模式下，1 个 worker 实例只显示 1 个 consumer，
            # concurrency 是子进程数，不体现为 RabbitMQ consumer 数。
            # 若怀疑卡死，请查看 worker 容器日志。
            status = "healthy"
            explanations.append(f"队列中有 {messages} 条任务处理中或排队，消费者 {consumers} 个，运行正常")
        else:
            explanations.append(f"队列空闲，消费者 {consumers} 个待命，运行正常")
        return {"status": status, "explanations": explanations, "category": "work"}

    # 未知队列
    explanations.append("未识别的队列")
    return {"status": "info", "explanations": explanations, "category": "unknown"}


async def _check_rabbitmq() -> dict:
    """检查 RabbitMQ 队列状态"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{RABBITMQ_API}/queues", auth=RABBITMQ_AUTH)
            resp.raise_for_status()
            raw_queues = resp.json()
    except Exception as exc:
        return {
            "reachable": False,
            "error": str(exc),
            "summary": "RabbitMQ 连接失败，所有任务队列不可用",
            "queues": [],
        }

    queues = []
    total_messages = 0
    issues = []

    for q in raw_queues:
        name = q.get("name", "")
        messages = q.get("messages", 0)
        consumers = q.get("consumers", 0)
        total_messages += messages

        judgment = _judge_queue(name, messages, consumers)

        label = KNOWN_QUEUES.get(name) or EVENT_QUEUES.get(name) or DLQ_QUEUES.get(name) or ""

        actions = _get_actions_for_queue(name, messages, consumers, judgment['category'], judgment['status'])
        queues.append({
            "name": name,
            "label": label,
            "messages": messages,
            "consumers": consumers,
            **judgment,
            "actions": actions,
        })

        if judgment["status"] in ("error", "warning"):
            issues.append(f"[{name}] {'; '.join(judgment['explanations'])}")

    # 按 category 和 status 排序：work > dlq > temp > unknown, error > warning > healthy
    priority = {"error": 0, "warning": 1, "info": 2, "healthy": 3}
    cat_priority = {"work": 0, "event": 1, "dlq": 2, "temp": 3, "unknown": 4}
    queues.sort(key=lambda q: (cat_priority.get(q["category"], 9), priority.get(q["status"], 9)))

    if not issues:
        summary = f"RabbitMQ 运行正常，共 {len(queues)} 个队列，{total_messages} 条消息待处理"
    else:
        summary = f"RabbitMQ 发现 {len(issues)} 个问题需要关注"

    return {
        "reachable": True,
        "summary": summary,
        "total_messages": total_messages,
        "total_queues": len(queues),
        "issues": issues,
        "queues": queues,
    }


async def _check_database() -> dict:
    """检查数据库连接"""
    start = time.monotonic()
    try:
        async with async_session_factory() as session:
            result = await session.execute(text("SELECT 1"))
            _ = result.scalar()
        latency_ms = round((time.monotonic() - start) * 1000, 1)

        status = "healthy"
        summary = f"数据库连接正常，响应时间 {latency_ms}ms"
        if latency_ms > 500:
            status = "warning"
            summary = f"数据库响应较慢（{latency_ms}ms），可能存在性能问题"

        return {"reachable": True, "status": status, "latency_ms": latency_ms, "summary": summary}
    except Exception as exc:
        return {"reachable": False, "status": "error", "latency_ms": None,
                "summary": f"数据库连接失败: {str(exc)[:200]}"}


async def _check_workers() -> dict:
    """通过 RabbitMQ 检查 Celery Worker 状态"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{RABBITMQ_API}/consumers", auth=RABBITMQ_AUTH)
            resp.raise_for_status()
            consumers = resp.json()
    except Exception:
        return {"summary": "无法获取 Worker 信息", "workers": []}

    # 从 pidbox 队列推断活跃 worker
    worker_names = set()
    for c in consumers:
        queue_name = c.get("queue", {}).get("name", "")
        if ".pidbox" in queue_name:
            # celery@hostname.celery.pidbox → hostname
            parts = queue_name.split("@")
            if len(parts) > 1:
                hostname = parts[1].replace(".celery.pidbox", "")
                worker_names.add(hostname)

    # 从消费者信息推断每个 worker 监听的队列
    worker_queues = {}
    for c in consumers:
        tag = c.get("consumer_tag", "")
        queue_name = c.get("queue", {}).get("name", "")
        if ".pidbox" in queue_name or ".reply." in queue_name:
            continue
        # consumer_tag 通常包含 hostname
        for wn in worker_names:
            if wn in tag:
                worker_queues.setdefault(wn, []).append(queue_name)

    workers = []
    for wn in sorted(worker_names):
        queues = sorted(set(worker_queues.get(wn, [])))
        workers.append({
            "hostname": wn,
            "queues": queues,
            "queue_labels": [KNOWN_QUEUES.get(q, q) for q in queues],
            "status": "running",
        })

    if workers:
        summary = f"{len(workers)} 个 Worker 在线运行"
    else:
        summary = "未检测到活跃的 Worker，任务将无法处理"

    return {"summary": summary, "workers": workers}


async def _check_token_waste() -> dict:
    """检测可能浪费 Token 的情况"""
    warnings = []

    # 检查死信队列
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{RABBITMQ_API}/queues", auth=RABBITMQ_AUTH)
            resp.raise_for_status()
            for q in resp.json():
                name = q.get("name", "")
                messages = q.get("messages", 0)
                if name in DLQ_QUEUES and messages > 0:
                    warnings.append(f"{DLQ_QUEUES[name]}中有 {messages} 条失败任务——"
                                    "这些任务在失败前可能已消耗了部分 Token")
    except Exception:
        pass

    # 检查是否有任务积压在无消费者的队列
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{RABBITMQ_API}/queues", auth=RABBITMQ_AUTH)
            resp.raise_for_status()
            for q in resp.json():
                name = q.get("name", "")
                messages = q.get("messages", 0)
                consumers = q.get("consumers", 0)
                if name in KNOWN_QUEUES and messages > 0 and consumers == 0 and name != "celery":
                    warnings.append(f"[{KNOWN_QUEUES[name]}] 有 {messages} 条任务但无 Worker 处理，"
                                    "当 Worker 恢复后会集中处理，可能产生突发 Token 消耗")
    except Exception:
        pass

    if not warnings:
        return {"status": "healthy", "summary": "未发现 Token 浪费风险", "warnings": []}

    return {"status": "warning", "summary": f"发现 {len(warnings)} 个潜在 Token 风险", "warnings": warnings}


@health_router.get("")
async def get_system_health(db: AsyncSession = Depends(get_db)):
    """获取系统完整健康报告"""
    start = time.monotonic()

    rabbitmq, database, workers, token_waste, pipeline_summary = await asyncio.gather(
        _check_rabbitmq(),
        _check_database(),
        _check_workers(),
        _check_token_waste(),
        _get_pipeline_summary(db),
    )

    # 综合判断
    overall = "healthy"
    if database.get("status") == "error" or not rabbitmq.get("reachable"):
        overall = "error"
    elif rabbitmq.get("issues") or token_waste.get("status") == "warning":
        overall = "warning"

    overall_summary_parts = []
    if overall == "healthy":
        overall_summary_parts.append("系统运行正常")
    elif overall == "warning":
        overall_summary_parts.append("系统运行中，但有需要关注的问题")
    else:
        overall_summary_parts.append("系统存在严重问题，需要立即处理")

    # 聚合告警
    critical_alerts: list[dict] = []
    warning_alerts: list[dict] = []

    # 管线告警
    if pipeline_summary.get("has_issues"):
        for stuck in pipeline_summary.get("stuck_documents", []):
            alert = {
                "type": "pipeline_stuck",
                "severity": "critical",
                "message": f"文档 {stuck.get('title', stuck.get('document_id', 'unknown'))} 卡在 {stuck.get('status', 'unknown')} 状态 {stuck.get('stuck_minutes', 0):.0f} 分钟",
                "action": stuck.get("action", "retry_extraction"),
                "document_id": stuck.get("document_id"),
                "details": stuck.get("diagnosis", ""),
            }
            critical_alerts.append(alert)

    # DLQ 告警
    for queue in rabbitmq.get("queues", []):
        if queue.get("category") == "dlq" and queue.get("messages", 0) > 0:
            critical_alerts.append({
                "type": "dlq_backlog",
                "severity": "critical",
                "message": f"死信队列 {queue['name']} 积压 {queue['messages']} 条消息",
                "action": "trigger_recovery",
            })
        if queue.get("category") == "dlq" and queue.get("messages", 0) == 0:
            pass  # DLQ 正常

    # Worker 离线告警
    if workers.get("offline_queues"):
        critical_alerts.append({
            "type": "worker_offline",
            "severity": "critical",
            "message": f"以下队列无消费者: {', '.join(workers['offline_queues'])}",
            "action": "restart_workers",
        })

    # 数据库连接告警
    if database.get("status") == "error":
        critical_alerts.append({
            "type": "db_connection",
            "severity": "critical",
            "message": f"数据库连接异常: {database.get('error', 'unknown')}",
        })

    return {
        "code": 200,
        "data": {
            "overall": overall,
            "overall_summary": "；".join(overall_summary_parts),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "check_duration_ms": round((time.monotonic() - start) * 1000, 1),
            "rabbitmq": rabbitmq,
            "database": database,
            "workers": workers,
            "token_waste": token_waste,
            "pipeline_summary": pipeline_summary,
            "alerts": {
                "count": len(critical_alerts) + len(warning_alerts),
                "critical": critical_alerts,
                "warnings": warning_alerts,
            },
        }
    }


# ═══════════════════════════════════════════════════════════════
# 管理员操作接口
# ═══════════════════════════════════════════════════════════════

from pydantic import BaseModel

class QueueActionRequest(BaseModel):
    queue_name: str

class QueueActionResponse(BaseModel):
    success: bool
    message: str


def _get_actions_for_queue(name: str, messages: int, consumers: int, category: str, status: str) -> list:
    """根据队列状态生成可用操作"""
    actions = []

    if category == "work" and name == "celery" and messages > 0:
        actions.append({
            "action": "purge_queue",
            "label": "清空遗留消息",
            "description": f"清除默认队列中 {messages} 条不会被执行的消息，释放内存",
            "confirm": f"确认清空 celery 默认队列中的 {messages} 条遗留消息？这些消息本来也不会被执行。",
            "danger": False,
        })

    if category == "dlq" and messages > 0:
        actions.append({
            "action": "purge_queue",
            "label": "清空失败消息",
            "description": f"清除 {messages} 条已失败的消息",
            "confirm": f"确认清空死信队列 {name} 中的 {messages} 条失败消息？清空后无法恢复。",
            "danger": True,
        })

    if category == "temp" and messages > 0 and consumers == 0:
        actions.append({
            "action": "delete_queue",
            "label": "删除临时队列",
            "description": "删除这个无用的临时队列及其遗留消息",
            "confirm": f"确认删除临时队列 {name}？",
            "danger": False,
        })

    if category == "work" and name != "celery" and consumers == 0 and status == "error":
        # 判断是哪个 worker 服务
        service = None
        if name in ("knowledge",):
            service = "celery_worker_knowledge"
        elif name in ("tutorial",):
            service = "celery_worker"
        elif name == "low_priority":
            service = "celery_worker"

        if service:
            actions.append({
                "action": "restart_worker",
                "label": f"重启 Worker",
                "description": f"重启 {service} 服务以恢复消费能力",
                "confirm": f"确认重启 {service}？如果 Worker 正在处理其他任务，可能会中断。",
                "danger": True,
                "params": {"service": service},
            })

    return actions


# ── 管线诊断辅助函数 ─────────────────────────────────────────────

def _diagnose_stuck(status: str, hours: float) -> str:
    """根据文档卡住的状态和时长，返回人类可读的诊断信息。"""
    diagnoses = {
        "uploaded": (
            f"文档上传后 {hours:.1f} 小时仍未解析——"
            "文件解析任务（run_ingest）可能未被触发，检查 knowledge.ingest.queue 事件队列是否正常消费"
        ),
        "parsed": (
            f"文档已解析但 {hours:.1f} 小时未进行实体提取——"
            "run_extraction 任务可能未派发或 knowledge 队列阻塞，也可能是 LLM API（knowledge_extraction）调用失败"
        ),
        "extracted": (
            f"实体提取完成但 {hours:.1f} 小时未完成审核——"
            "auto_review_entities 可能未触发或 knowledge.review 队列阻塞，也可能是 LLM API 调用失败导致审核无法完成"
        ),
        "embedding": (
            f"审核通过但 {hours:.1f} 小时未完成向量化——"
            "embed_single_entity 任务可能积压，检查 knowledge 队列消费者状态和 Embedding API 连通性"
        ),
        "reviewed": (
            f"所有实体已嵌入但 {hours:.1f} 小时未生成蓝图——"
            "synthesize_blueprint 可能未触发，检查 blueprint.synthesis.queue 事件队列或 LLM API 调用是否失败"
        ),
    }
    return diagnoses.get(status, f"文档在 {status} 状态停留了 {hours:.1f} 小时，请检查相关任务队列和 LLM 服务状态")


def _suggest_action_for_stuck(status: str) -> str:
    """将文档状态映射为建议的修复操作键。"""
    mapping = {
        "uploaded":    "retry_ingest",
        "parsed":      "retry_extraction",
        "extracted":   "retry_review",
        "embedding":   "retry_backfill_embeddings",
        "reviewed":    "retry_blueprint",
    }
    return mapping.get(status, "unknown")


def _parse_last_error(raw: str) -> dict | None:
    """解析 documents.last_error JSON，返回结构化错误摘要。
    last_error 格式: [{"chunk_id": ..., "step": "recognition", "error": "..."}, ...]
    """
    import json as _json
    try:
        errors = _json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(errors, list) or not errors:
            return None
    except Exception:
        return None

    # 按错误消息分组统计
    error_counts: dict[str, dict] = {}
    steps_affected: set[str] = set()
    for err in errors:
        if not isinstance(err, dict):
            continue
        msg = err.get("error", "未知错误")
        steps_affected.add(err.get("step", "unknown"))
        if msg not in error_counts:
            error_counts[msg] = {"count": 0, "step": err.get("step", "unknown")}
        error_counts[msg]["count"] += 1

    if not error_counts:
        return None

    # 取出现次数最多的错误
    top_error = max(error_counts.items(), key=lambda x: x[1]["count"])
    top_msg = top_error[0]
    # 截断过长的错误消息（去除重复前缀）
    short_msg = top_msg.replace(
        "Error code: 500 - {'error': {'code': 500, 'message': '", ""
    ).replace(
        "', 'type': 'server_error'}}", ""
    ).strip()

    return {
        "error_count": len(errors),
        "unique_errors": len(error_counts),
        "primary_error": short_msg[:200],
        "steps_affected": sorted(steps_affected),
        # 采样前 3 条不同错误
        "sample_errors": [
            {"step": e.get("step", "?"), "index": e.get("index", "?"), "error": str(e.get("error", ""))[:150]}
            for e in errors[:3]
        ],
    }


def _format_error_hint(detail: dict | None) -> str:
    """将解析后的错误详情格式化为人类可读的诊断提示。"""
    if not detail:
        return "文档处理失败，可能因 LLM 调用异常、解析超时或资源不足导致"
    primary = detail.get("primary_error", "未知错误")
    steps = "→".join(detail.get("steps_affected", ["?"]))
    return f"{detail.get('error_count', 0)} 个 chunk 失败（阶段: {steps}），主要错误: {primary}"


async def _get_pipeline_summary(db) -> dict:
    """统计文档管线概况，含卡住文档和失败详情，直接用于主健康页面。"""
    from sqlalchemy.exc import ProgrammingError

    # Phase 1: 各状态计数
    counts: dict[str, int] = {}
    try:
        result = await db.execute(text("""
            SELECT document_status, COUNT(*) AS cnt
            FROM documents GROUP BY document_status
        """))
        counts = {row[0]: row[1] for row in result.fetchall()}
    except ProgrammingError:
        await db.rollback()

    total  = sum(counts.values())
    failed = counts.get("failed", 0)

    # Phase 2: 卡住文档
    stuck_docs: list[dict] = []
    thresholds = await _load_stuck_thresholds(db)
    for status, threshold_min in thresholds.items():
        try:
            result = await db.execute(text("""
                SELECT d.document_id::text, d.title, d.document_status,
                       EXTRACT(EPOCH FROM (NOW() - d.updated_at)) / 3600.0 AS hours_stuck,
                       COALESCE(ks.name, '未知空间') AS space_name,
                       d.last_error
                FROM documents d
                LEFT JOIN knowledge_spaces ks ON ks.space_id = d.space_id
                WHERE d.document_status = :status
                  AND d.updated_at < NOW() - INTERVAL '1 minute' * :threshold
                ORDER BY d.updated_at ASC LIMIT 10
            """), {"status": status, "threshold": threshold_min})
            for row in result.fetchall():
                hours = round(row.hours_stuck or 0, 1)
                severity = "error" if hours > (threshold_min * 2 / 60) else "warning"
                error_detail = _parse_last_error(row.last_error) if row.last_error else None
                stuck_docs.append({
                    "document_id":     row.document_id,
                    "title":           row.title,
                    "status":          row.document_status,
                    "space_name":      row.space_name,
                    "hours_stuck":     hours,
                    "severity":        severity,
                    "diagnosis":       _diagnose_stuck(row.document_status, hours),
                    "suggested_action": _suggest_action_for_stuck(row.document_status),
                    "error_detail":    error_detail,
                })
        except ProgrammingError:
            await db.rollback()

    # Phase 3: 最近失败文档
    recent_failures: list[dict] = []
    try:
        result = await db.execute(text("""
            SELECT d.document_id::text, d.title,
                   d.updated_at AS failed_at,
                   COALESCE(ks.name, '未知空间') AS space_name,
                   EXTRACT(EPOCH FROM (NOW() - d.updated_at)) / 3600.0 AS hours_since,
                   d.last_error
            FROM documents d
            LEFT JOIN knowledge_spaces ks ON ks.space_id = d.space_id
            WHERE d.document_status = 'failed'
            ORDER BY d.updated_at DESC LIMIT 10
        """))
        for row in result.fetchall():
            error_detail = _parse_last_error(row.last_error) if row.last_error else None
            error_hint = _format_error_hint(error_detail) if error_detail else \
                         "文档处理失败，可能因 LLM 调用异常、解析超时或资源不足导致"
            recent_failures.append({
                "document_id":        row.document_id,
                "title":              row.title,
                "space_name":         row.space_name,
                "failed_at":          row.failed_at.isoformat() if row.failed_at else None,
                "hours_since_failure": round(row.hours_since or 0, 1),
                "error_hint":         error_hint,
                "error_detail":       error_detail,
            })
    except ProgrammingError:
        await db.rollback()

    stuck_states = {"parsed", "extracted", "embedding", "reviewed"}

    return {
        "total_documents":    total,
        "documents_by_status": counts,
        "failed_count":       failed,
        "stuck_count":        len(stuck_docs),
        "stuck_documents":    stuck_docs,
        "recent_failures":    recent_failures,
        "has_issues": (
            failed > 0
            or len(stuck_docs) > 0
            or any(counts.get(s, 0) > 0 for s in stuck_states)
        ),
    }


# blueprint_progress_v1
@health_router.get("/blueprint-progress")
async def get_blueprint_progress(db: AsyncSession = Depends(get_db)):
    """获取各 space 的课程生成进度，供系统监控页展示。"""
    from sqlalchemy import text as _text
    from sqlalchemy.exc import ProgrammingError
    try:
        result = await db.execute(
            _text("""
                SELECT
                    ks.space_id::text,
                    ks.name,
                    ks.space_type,
                    (SELECT COUNT(*) FROM knowledge_entities ke
                     WHERE ke.space_id = ks.space_id
                       AND ke.review_status = 'approved') AS approved,
                    (SELECT COUNT(*) FROM knowledge_entities ke
                     WHERE ke.space_id = ks.space_id
                       AND ke.review_status = 'pending') AS pending,
                    sb.status AS bp_status,
                    sb.updated_at AS bp_updated_at,
                    (SELECT COUNT(*) FROM skill_chapters sc
                     JOIN skill_stages ss ON ss.stage_id = sc.stage_id
                     WHERE ss.blueprint_id = sb.blueprint_id) AS chapter_count
                FROM knowledge_spaces ks
                LEFT JOIN skill_blueprints sb ON sb.space_id = ks.space_id
                WHERE ks.space_type IN ('global', 'personal')
                ORDER BY ks.created_at DESC
                LIMIT 20
            """)
        )
        rows = []
        for r in result.fetchall():
            bp_status = r.bp_status
            if not bp_status:
                if r.pending > 0:
                    stage = "审核中"
                elif r.approved > 0:
                    stage = "待生成课程"
                else:
                    stage = "待上传资料"
            elif bp_status == "published":
                stage = "已完成"
            elif bp_status in ("generating", "review"):
                stage = "生成中"
            else:
                stage = bp_status

            rows.append({
                "space_id": r.space_id,
                "name": r.name,
                "space_type": r.space_type,
                "approved": int(r.approved or 0),
                "pending": int(r.pending or 0),
                "bp_status": bp_status,
                "stage": stage,
                "chapter_count": int(r.chapter_count or 0),
                "bp_updated_at": r.bp_updated_at.isoformat() if r.bp_updated_at else None,
            })
        return {"code": 200, "data": {"spaces": rows}}
    except ProgrammingError:
        return {"code": 200, "data": {"spaces": []}}


# ── 管线状态端点 ─────────────────────────────────────────────────

# 卡住判定默认阈值（分钟），可由 system_configs 中 pipeline.stuck_thresholds JSON 覆盖
_DEFAULT_STUCK_THRESHOLDS: dict[str, int] = {
    "uploaded":  60,   # 1 小时（应已完成解析）
    "parsed":    30,   # 30 分钟（应已完成实体提取）
    "extracted": 60,   # 1 小时（应已完成审核）
    "embedding": 120,  # 2 小时（应已完成向量化）
    "reviewed":  240,  # 4 小时（应已发布蓝图）
}


async def _load_stuck_thresholds(db: AsyncSession) -> dict[str, int]:
    """从 system_configs 加载阈值，未配置则返回默认值。"""
    import json as _json
    try:
        result = await db.execute(
            text("SELECT config_value FROM system_configs "
                 "WHERE config_key = 'pipeline.stuck_thresholds'")
        )
        row = result.fetchone()
        if row:
            custom = _json.loads(row.config_value)
            if isinstance(custom, dict):
                return {**_DEFAULT_STUCK_THRESHOLDS, **custom}
    except Exception:
        await db.rollback()
    return dict(_DEFAULT_STUCK_THRESHOLDS)


@health_router.get("/pipeline-status")
async def get_pipeline_status(db: AsyncSession = Depends(get_db)):
    """获取文档处理管线的完整状态——各阶段文档数、卡住文档、最近失败、处理速率、卡死蓝图。"""
    from sqlalchemy.exc import ProgrammingError

    STUCK_THRESHOLDS = await _load_stuck_thresholds(db)

    # Phase 1: 各状态文档计数
    documents_by_status: dict[str, int] = {}
    try:
        result = await db.execute(text("""
            SELECT document_status, COUNT(*) AS cnt
            FROM documents GROUP BY document_status
        """))
        documents_by_status = {row[0]: row[1] for row in result.fetchall()}
    except ProgrammingError:
        await db.rollback()

    # Phase 2: 卡住文档检测
    stuck_docs: list[dict] = []
    for status, threshold_min in STUCK_THRESHOLDS.items():
        try:
            result = await db.execute(text("""
                SELECT d.document_id::text,
                       d.title,
                       d.document_status,
                       EXTRACT(EPOCH FROM (NOW() - d.updated_at)) / 3600.0 AS hours_stuck,
                       COALESCE(ks.name, '未知空间') AS space_name,
                       d.last_error
                FROM documents d
                LEFT JOIN knowledge_spaces ks ON ks.space_id = d.space_id
                WHERE d.document_status = :status
                  AND d.updated_at < NOW() - INTERVAL '1 minute' * :threshold
                ORDER BY d.updated_at ASC
                LIMIT 50
            """), {"status": status, "threshold": threshold_min})
            for row in result.fetchall():
                hours = round(row.hours_stuck or 0, 1)
                severity = "error" if hours > (threshold_min * 2 / 60) else "warning"
                error_detail = _parse_last_error(row.last_error) if row.last_error else None
                stuck_docs.append({
                    "document_id":     row.document_id,
                    "title":           row.title,
                    "status":          row.document_status,
                    "space_name":      row.space_name,
                    "hours_stuck":     hours,
                    "severity":        severity,
                    "diagnosis":       _diagnose_stuck(row.document_status, hours),
                    "suggested_action": _suggest_action_for_stuck(row.document_status),
                    "error_detail":    error_detail,
                })
        except ProgrammingError:
            await db.rollback()

    # Phase 3: 处理速率（近 1 小时 / 近 24 小时推进数）
    processing_rate: dict[str, int] = {}
    for label, window_h in [("last_hour", 1), ("last_24h", 24)]:
        try:
            result = await db.execute(text("""
                SELECT COUNT(*) FROM documents
                WHERE document_status IN ('extracted', 'embedding', 'reviewed', 'published')
                  AND updated_at > NOW() - INTERVAL '1 hour' * :h
            """), {"h": window_h})
            processing_rate[label] = result.scalar() or 0
        except ProgrammingError:
            await db.rollback()
            processing_rate[label] = 0

    # Phase 4: 最近失败文档
    recent_failures: list[dict] = []
    try:
        result = await db.execute(text("""
            SELECT d.document_id::text,
                   d.title,
                   d.updated_at AS failed_at,
                   COALESCE(ks.name, '未知空间') AS space_name,
                   EXTRACT(EPOCH FROM (NOW() - d.updated_at)) / 3600.0 AS hours_since,
                   d.last_error
            FROM documents d
            LEFT JOIN knowledge_spaces ks ON ks.space_id = d.space_id
            WHERE d.document_status = 'failed'
            ORDER BY d.updated_at DESC
            LIMIT 20
        """))
        for row in result.fetchall():
            error_detail = _parse_last_error(row.last_error) if row.last_error else None
            error_hint = _format_error_hint(error_detail) if error_detail else \
                         "文档处理失败，可能因 LLM 调用异常、解析超时或资源不足导致"
            recent_failures.append({
                "document_id":        row.document_id,
                "title":              row.title,
                "space_name":         row.space_name,
                "failed_at":          row.failed_at.isoformat() if row.failed_at else None,
                "hours_since_failure": round(row.hours_since or 0, 1),
                "error_hint":         error_hint,
                "error_detail":       error_detail,
            })
    except ProgrammingError:
        await db.rollback()

    # Phase 5: 卡死蓝图（status=generating 超过 2 小时）
    stuck_blueprints: list[dict] = []
    try:
        result = await db.execute(text("""
            SELECT sb.blueprint_id::text,
                   ks.name AS space_name,
                   sb.status,
                   EXTRACT(EPOCH FROM (NOW() - sb.updated_at)) / 3600.0 AS hours_stuck
            FROM skill_blueprints sb
            JOIN knowledge_spaces ks ON ks.space_id = sb.space_id
            WHERE sb.status = 'generating'
              AND sb.updated_at < NOW() - INTERVAL '2 hours'
            ORDER BY sb.updated_at ASC
            LIMIT 20
        """))
        for row in result.fetchall():
            hours = round(row.hours_stuck or 0, 1)
            stuck_blueprints.append({
                "blueprint_id": row.blueprint_id,
                "space_name":   row.space_name,
                "status":       row.status,
                "hours_stuck":  hours,
                "diagnosis":    f"蓝图停留在 generating 状态 {hours:.1f} 小时——LLM 生成可能卡死、超时或 API 调用失败，系统将在 2 小时后自动重置为 draft",
            })
    except ProgrammingError:
        await db.rollback()

    return {
        "code": 200,
        "data": {
            "documents_by_status": documents_by_status,
            "stuck_documents": stuck_docs,
            "processing_rate": processing_rate,
            "recent_failures": recent_failures,
            "stuck_blueprints": stuck_blueprints,
        },
    }


@health_router.post("/purge-queue")
async def purge_queue(req: QueueActionRequest, _admin: dict = Depends(require_role("admin"))):
    """清空指定队列中的所有消息"""
    queue_name = req.queue_name

    # 安全检查：只允许清空特定类型的队列
    is_safe = (
        queue_name == "celery"
        or queue_name in DLQ_QUEUES
    )
    if not is_safe:
        return {"code": 403, "data": {"success": False, "message": f"不允许清空工作队列 {queue_name}，这可能导致任务丢失"}}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.delete(
                f"{RABBITMQ_API}/queues/%2F/{queue_name}/contents",
                auth=RABBITMQ_AUTH
            )
            if resp.status_code == 204:
                return {"code": 200, "data": {"success": True, "message": f"已清空队列 {queue_name}"}}
            else:
                return {"code": 500, "data": {"success": False, "message": f"清空失败: HTTP {resp.status_code}"}}
    except Exception as exc:
        return {"code": 500, "data": {"success": False, "message": f"操作失败: {str(exc)[:200]}"}}


@health_router.post("/delete-queue")
async def delete_queue(req: QueueActionRequest, _admin: dict = Depends(require_role("admin"))):
    """删除临时队列（仅允许删除 UUID 格式或回复队列）"""
    queue_name = req.queue_name

    is_uuid = len(queue_name) == 36 and queue_name.count("-") == 4
    is_reply = ".reply." in queue_name
    if not (is_uuid or is_reply):
        return {"code": 403, "data": {"success": False, "message": "只允许删除临时队列（UUID 格式或回复队列）"}}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.delete(
                f"{RABBITMQ_API}/queues/%2F/{queue_name}",
                auth=RABBITMQ_AUTH
            )
            if resp.status_code == 204:
                return {"code": 200, "data": {"success": True, "message": f"已删除队列 {queue_name}"}}
            elif resp.status_code == 404:
                return {"code": 200, "data": {"success": True, "message": f"队列 {queue_name} 已不存在"}}
            else:
                return {"code": 500, "data": {"success": False, "message": f"删除失败: HTTP {resp.status_code}"}}
    except Exception as exc:
        return {"code": 500, "data": {"success": False, "message": f"操作失败: {str(exc)[:200]}"}}


@health_router.post("/purge-all-temp")
async def purge_all_temp_queues(_admin: dict = Depends(require_role("admin"))):
    """一键清理所有无用的临时队列"""
    deleted = 0
    errors = []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{RABBITMQ_API}/queues", auth=RABBITMQ_AUTH)
            resp.raise_for_status()
            for q in resp.json():
                name = q.get("name", "")
                messages = q.get("messages", 0)
                consumers = q.get("consumers", 0)
                is_uuid = len(name) == 36 and name.count("-") == 4
                is_reply = ".reply." in name

                if (is_uuid or is_reply) and consumers == 0:
                    del_resp = await client.delete(
                        f"{RABBITMQ_API}/queues/%2F/{name}",
                        auth=RABBITMQ_AUTH
                    )
                    if del_resp.status_code in (204, 404):
                        deleted += 1
                    else:
                        errors.append(name)
    except Exception as exc:
        return {"code": 500, "data": {"success": False, "message": f"操作失败: {str(exc)[:200]}"}}

    msg = f"已清理 {deleted} 个临时队列"
    if errors:
        msg += f"，{len(errors)} 个清理失败"
    return {"code": 200, "data": {"success": True, "message": msg, "deleted": deleted}}


# ── 修复操作端点 ─────────────────────────────────────────────────

class RetryStuckRequest(BaseModel):
    document_id: str
    action: str  # retry_extraction | retry_review | retry_blueprint | retry_ingest
    space_type: str = "global"
    space_id: str | None = None

class ResetBlueprintRequest(BaseModel):
    blueprint_id: str


@health_router.post("/retry-stuck")
async def retry_stuck_document(req: RetryStuckRequest, db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_role("admin"))):
    """重新处理卡住的文档：根据 action 类型派发对应的 Celery 任务。"""
    # 验证文档存在
    result = await db.execute(
        text("SELECT document_id::text, space_type, space_id::text, file_id::text, title "
             "FROM documents WHERE document_id = CAST(:did AS uuid)"),
        {"did": req.document_id}
    )
    row = result.fetchone()
    if not row:
        return {"code": 404, "data": {"success": False, "message": "文档不存在"}}

    space_type = row.space_type or req.space_type
    space_id = str(row.space_id) if row.space_id else req.space_id

    if req.action == "retry_extraction":
        from apps.api.tasks.knowledge_tasks import run_extraction
        run_extraction.apply_async(
            args=[req.document_id, space_type, space_id],
            queue="knowledge"
        )
        return {"code": 200, "data": {
            "success": True,
            "message": f"已重新派发实体提取任务到 knowledge 队列（文档: {row.title}）"
        }}

    if req.action == "retry_review":
        from apps.api.tasks.auto_review_tasks import auto_review_entities
        auto_review_entities.apply_async(
            args=[space_id],
            queue="knowledge.review"
        )
        return {"code": 200, "data": {
            "success": True,
            "message": f"已重新触发自动审核任务（空间: {space_id}）"
        }}

    if req.action == "retry_blueprint":
        # 查询 space name 作为 topic_key
        space_row = await db.execute(
            text("SELECT name FROM knowledge_spaces WHERE space_id = CAST(:sid AS uuid)"),
            {"sid": space_id}
        )
        sr = space_row.fetchone()
        topic_key = sr.name if sr else "default"
        from apps.api.tasks.blueprint_tasks import synthesize_blueprint
        synthesize_blueprint.apply_async(
            args=[topic_key, space_id],
            queue="knowledge"
        )
        return {"code": 200, "data": {
            "success": True,
            "message": f"已重新触发蓝图生成任务（空间: {space_id}, 主题: {topic_key}）"
        }}

    if req.action == "retry_ingest":
        return {"code": 400, "data": {
            "success": False,
            "message": "重新解析需要重新上传文件，请在文件管理页面使用「重新解析」功能"
        }}

    if req.action == "retry_backfill_embeddings":
        from apps.api.tasks.embedding_tasks import backfill_entity_embeddings
        backfill_entity_embeddings.apply_async(
            args=[space_id],
            queue="knowledge"
        )
        return {"code": 200, "data": {
            "success": True,
            "message": f"已排发向量补填任务（空间: {space_id}），将补填所有缺失的 entity embeddings"
        }}

    return {"code": 400, "data": {"success": False, "message": f"不支持的操作: {req.action}"}}


@health_router.post("/retry-all-failed")
async def retry_all_failed_documents(db: AsyncSession = Depends(get_db), _admin: dict = Depends(require_role("admin"))):
    """批量重试所有失败的文档：将状态从 failed 重置为 parsed 并重新派发提取任务。"""
    result = await db.execute(text("""
        SELECT d.document_id::text, d.space_type, d.space_id::text, d.title
        FROM documents d
        WHERE d.document_status = 'failed'
    """))
    failed = [dict(r._mapping) for r in result.fetchall()]

    if not failed:
        return {"code": 200, "data": {"success": True, "message": "没有失败的文档", "count": 0}}

    retried = 0
    errors: list[str] = []
    for doc in failed:
        try:
            await db.execute(
                text("UPDATE documents SET document_status = 'parsed', updated_at = NOW() "
                     "WHERE document_id = CAST(:did AS uuid)"),
                {"did": doc["document_id"]}
            )
            from apps.api.tasks.knowledge_tasks import run_extraction
            run_extraction.apply_async(
                args=[doc["document_id"], doc["space_type"] or "global", doc["space_id"]],
                queue="knowledge"
            )
            retried += 1
        except Exception as e:
            errors.append(f"{doc.get('title', doc['document_id'])}: {str(e)[:80]}")

    await db.commit()

    msg = f"已重试 {retried} 个失败文档"
    if errors:
        msg += f"，{len(errors)} 个失败: {'; '.join(errors[:3])}"

    logger.info("Batch retry failed documents", total=len(failed), retried=retried, errors=len(errors))
    return {"code": 200, "data": {"success": True, "message": msg, "count": retried}}


@health_router.post("/trigger-recovery")
async def trigger_recovery(_admin: dict = Depends(require_role("admin"))):
    """手动触发系统恢复任务（resume_pending_review），立即执行一次卡住任务检测与恢复。"""
    try:
        from apps.api.tasks.auto_review_tasks import resume_pending_review
        result = resume_pending_review.apply_async(queue="knowledge.review")
        return {"code": 200, "data": {
            "success": True,
            "message": "恢复任务已提交到 knowledge.review 队列（task_id: {}）。"
                       "任务将：1) 检查 pending 实体并派发审核 "
                       "2) 重置卡死的 generating blueprint "
                       "3) 补派发缺失的提取任务。请 1-2 分钟后刷新管线状态查看效果。".format(result.id)
        }}
    except Exception as exc:
        return {"code": 500, "data": {
            "success": False,
            "message": f"触发恢复任务失败: {str(exc)[:200]}"
        }}


@health_router.post("/reset-stuck-blueprint")
async def reset_stuck_blueprint(req: ResetBlueprintRequest, _admin: dict = Depends(require_role("admin"))):
    """重置卡死的蓝图（status=generating 超过 2 小时 → draft），允许系统重新生成。"""
    from apps.api.core.db import async_session_factory
    async with async_session_factory() as session:
        result = await session.execute(
            text("""
                UPDATE skill_blueprints
                SET status = 'draft', updated_at = NOW()
                WHERE blueprint_id = CAST(:bid AS uuid)
                  AND status = 'generating'
                  AND updated_at < NOW() - INTERVAL '2 hours'
                RETURNING blueprint_id::text
            """),
            {"bid": req.blueprint_id}
        )
        row = result.fetchone()
        await session.commit()
        if row:
            logger.info("Stuck blueprint reset", blueprint_id=req.blueprint_id)
            return {"code": 200, "data": {
                "success": True,
                "message": f"已重置蓝图 {req.blueprint_id} 为 draft 状态，系统恢复任务将重新触发生成"
            }}
        return {"code": 200, "data": {
            "success": False,
            "message": "蓝图不存在、未卡住超过 2 小时或 not in generating 状态"
        }}


# ── LLM Provider 连通性检查 ──────────────────────────────────────

@health_router.get("/llm-status")
async def get_llm_status(_admin: dict = Depends(require_role("admin"))):
    """检查 LLM 各 provider 的连通性，用于诊断 LLM API 相关问题。"""
    import time as _time
    from apps.api.core.llm_gateway import get_llm_gateway

    gw = get_llm_gateway()
    # 确保路由表已加载
    try:
        await gw._ensure_loaded()
    except Exception:
        pass

    routes = getattr(gw, '_routes', {}) or {}
    provider_results: dict[str, dict] = {}
    seen_providers: set[str] = set()

    for capability, bindings in routes.items():
        for b in bindings:
            pid = b.provider_id
            if pid in seen_providers:
                continue
            seen_providers.add(pid)

            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    base = (b.base_url or "").rstrip("/")
                    # 尝试 /v1/models 端点（OpenAI 兼容 API）
                    resp = await client.get(
                        f"{base}/v1/models",
                        headers={"Authorization": f"Bearer {b.api_key}"}
                    )
                    provider_results[pid] = {
                        "reachable":   resp.status_code < 500,
                        "status_code": resp.status_code,
                        "model":       b.model_name,
                        "kind":        b.kind,
                        "capability":  capability,
                    }
            except Exception as e:
                provider_results[pid] = {
                    "reachable":  False,
                    "error":      str(e)[:200],
                    "model":      b.model_name,
                    "kind":       b.kind,
                    "capability": capability,
                }

    # 也检查 legacy client (CONFIG.llm)
    if not seen_providers:
        # DB 无配置，检查 legacy
        legacy_client = gw._get_legacy_client()
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                base = str(legacy_client.base_url).rstrip("/")
                resp = await client.get(
                    f"{base}/v1/models",
                    headers={"Authorization": f"Bearer {legacy_client.api_key}"}
                )
                provider_results["legacy"] = {
                    "reachable":   resp.status_code < 500,
                    "status_code": resp.status_code,
                    "model":       "CONFIG.llm (legacy)",
                    "kind":        "chat",
                    "capability":  "legacy",
                }
        except Exception as e:
            provider_results["legacy"] = {
                "reachable": False,
                "error":     str(e)[:200],
                "model":     "CONFIG.llm (legacy)",
                "kind":      "chat",
            }

    cache_age = 0.0
    if hasattr(gw, '_loaded_at') and gw._loaded_at > 0:
        cache_age = round(_time.monotonic() - gw._loaded_at, 1)

    return {
        "code": 200,
        "data": {
            "providers": provider_results,
            "cache_age_seconds": cache_age,
            "configured_capabilities": list(routes.keys()),
            "provider_count": len(provider_results),
        },
    }

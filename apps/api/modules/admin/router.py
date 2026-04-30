"""
apps/api/modules/admin/router.py
管理端 + 学习端补充接口

FE-A01: 领域查询 + 文档列表
FE-A02: 用户管理（列表+角色修改+禁用）
FE-A03: 知识点审核（通过/驳回）
FE-A04: 系统初始化（种子库+题库+系统配置）
FE-A05: 章节进度（标记完成+查询进度）
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.db import get_db
from apps.api.modules.auth.router import get_current_user, require_role

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api", tags=["admin"])


async def _safe_count(db: AsyncSession, sql: str, params: dict | None = None) -> int:
    """Best-effort COUNT helper; returns 0 instead of raising."""
    try:
        result = await db.execute(text(sql), params or {})
        row = result.fetchone()
        if not row:
            return 0
        value = getattr(row, "cnt", None)
        if value is None and len(row) > 0:
            value = row[0]
        return int(value or 0)
    except Exception as e:
        logger.warning("safe_count_failed", sql=sql, error=str(e))
        await db.rollback()
        return 0


async def _get_space_id_from_chapter(db: AsyncSession, chapter_id: str) -> str | None:
    """从 chapter_id 反查 space_id。"""
    row = await db.execute(
        text("""SELECT sb.space_id::text FROM skill_chapters sc
                JOIN skill_blueprints sb ON sb.blueprint_id = sc.blueprint_id
                WHERE sc.chapter_id = CAST(:cid AS uuid)"""),
        {"cid": chapter_id}
    )
    r = row.fetchone()
    return r[0] if r else None


async def _get_space_id_from_blueprint(db: AsyncSession, blueprint_id: str) -> str | None:
    """从 blueprint_id 反查 space_id。"""
    row = await db.execute(
        text("SELECT space_id::text FROM skill_blueprints WHERE blueprint_id = CAST(:bid AS uuid)"),
        {"bid": blueprint_id}
    )
    r = row.fetchone()
    return r[0] if r else None



# ════════════════════════════════════════════════════════════════
# FE-A01：领域查询 + 文档列表
# ════════════════════════════════════════════════════════════════
@router.get("/knowledge/domains")
async def get_domains(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """获取可见领域列表。优先从 knowledge_spaces 返回，避免实体统计异常导致 500。"""
    domains: list[dict] = []

    try:
        result = await db.execute(
            text("""
                SELECT
                    ks.space_id::text AS space_id,
                    ks.name AS domain_tag,
                    ks.space_type,
                    (SELECT COUNT(*) FROM knowledge_entities ke
                     WHERE ke.space_id = ks.space_id) AS entity_count,
                    (SELECT COUNT(*) FROM knowledge_entities ke
                     WHERE ke.space_id = ks.space_id
                       AND ke.review_status = 'approved') AS approved_count,
                    (SELECT COUNT(*) FROM knowledge_entities ke
                     WHERE ke.space_id = ks.space_id
                       AND ke.is_core = true) AS core_count  -- domains_realcount_v1
                FROM knowledge_spaces ks
                WHERE ks.name IS NOT NULL
                  AND ks.name <> ''
                  AND (
                        ks.space_type = 'global'
                     OR ks.owner_id::text = :user_id
                  )
                ORDER BY CASE WHEN ks.space_type = 'global' THEN 0 ELSE 1 END,
                         ks.name ASC
            """),
            {"user_id": current_user["user_id"]},
        )
        domains = [
            {
                "space_id": row.space_id,
                "domain_tag": row.domain_tag,
                "space_type": row.space_type,
                "entity_count": int(row.entity_count or 0),
                "approved_count": int(row.approved_count or 0),
                "core_count": int(row.core_count or 0),
            }
            for row in result.fetchall()
        ]
    except Exception as e:
        logger.warning("get_domains_space_query_failed", error=str(e))
        await db.rollback()

    if not domains:
        try:
            result = await db.execute(
                text("""
                    SELECT
                        NULL::text AS space_id,
                        ke.domain_tag,
                        ke.space_type,
                        COUNT(*) AS entity_count,
                        COALESCE(SUM(CASE WHEN ke.is_core THEN 1 ELSE 0 END), 0) AS core_count
                    FROM knowledge_entities ke
                    WHERE ke.review_status IN ('pending', 'approved')
                      AND ke.domain_tag IS NOT NULL
                      AND ke.domain_tag <> ''
                    GROUP BY ke.domain_tag, ke.space_type
                    ORDER BY CASE WHEN ke.space_type = 'global' THEN 0 ELSE 1 END,
                             ke.domain_tag ASC
                """)
            )
            domains = [
                {
                    "space_id": row.space_id,
                    "domain_tag": row.domain_tag,
                    "space_type": row.space_type,
                    "entity_count": int(row.entity_count or 0),
                "approved_count": int(row.approved_count or 0),
                    "core_count": int(row.core_count or 0),
                }
                for row in result.fetchall()
            ]
        except Exception as e:
            logger.warning("get_domains_legacy_query_failed", error=str(e))
            domains = []

    return {"code": 200, "msg": "success", "data": {"domains": domains}}


class CreateKnowledgeSpaceRequest(BaseModel):
    name: str
    space_type: str = "global"
    description: str | None = None


@router.post("/admin/knowledge/spaces")
async def create_knowledge_space(
    req: CreateKnowledgeSpaceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """创建知识空间（领域）；已存在时直接返回原 space_id。委托给 SpaceService 统一创建。"""
    from apps.api.modules.space.service import SpaceService, SpaceError
    space_name = " ".join((req.name or "").split()).strip()
    if not space_name:
        raise HTTPException(400, detail={"code": "SPACE_001", "msg": "Domain name is required"})
    try:
        service = SpaceService(db)
        data = await service.create_space(
            current_user["user_id"], space_name, req.space_type, req.description
        )
    except SpaceError as e:
        raise HTTPException(400, detail={"code": e.code, "msg": e.msg})
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "space_id":   data["space_id"],
            "domain_tag": data["name"],
            "space_type": data["space_type"],
            "created":    True,
        },
    }

def _compute_doc_progress(status: str, created_at, entity_count: int, approved_count: int) -> tuple[int, str, int | None]:
    """计算文档处理进度百分比、中文状态标签和预估剩余时间（分钟）。"""
    import datetime as _dt
    progress_map: dict[str, tuple[int, str, int | None]] = {
        "uploaded":    (10, "排队中",     None),
        "parsed":      (30, "文本已解析",   10),
        "extracting":  (50, "AI提取中",    15),
        "extracted":   (65, "AI审核中",     5),
        "embedding":   (85, "生成向量中",    3),
        "reviewed":    (95, "生成课程中",    5),
        "published":   (100, "已完成",      0),
        "failed":      (0,  "处理失败",     None),
    }
    pct, label, base_eta = progress_map.get(status, (0, status, None))
    # 如果已有知识点统计，更精确地计算进度
    if entity_count > 0 and approved_count > 0 and status in ("extracted", "embedding", "reviewed"):
        ratio = min(approved_count / max(entity_count, 1), 1.0)
        pct = 65 + int(ratio * 30)  # 65-95% 之间
    return pct, label, base_eta


def _summarize_last_error(last_error: str | None) -> str | None:
    """从 last_error JSON 中提取人类可读的错误摘要。"""
    if not last_error:
        return None
    import json as _json
    try:
        errors = _json.loads(last_error) if isinstance(last_error, str) else last_error
        if isinstance(errors, list) and errors:
            # 收集独有的错误信息
            unique_errors: dict[str, int] = {}
            for e in errors[:20]:
                msg = e.get("error", "") if isinstance(e, dict) else str(e)
                if msg:
                    unique_errors[msg] = unique_errors.get(msg, 0) + 1
            if unique_errors:
                parts = [f"{msg}（{count}次）" if count > 1 else msg
                         for msg, count in sorted(unique_errors.items(), key=lambda x: -x[1])]
                return "；".join(parts[:3])
            step = errors[0].get("step", "") if isinstance(errors[0], dict) else ""
            return f"在{step}阶段失败" if step else "处理失败"
    except Exception:
        pass
    return str(last_error)[:100]


@router.get("/files/my-documents")
async def get_my_documents(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """获取当前用户上传的文档列表及管线进度。异常时返回空列表，不让页面炸掉。"""
    try:
        result = await db.execute(
            text("""
                SELECT d.document_id, d.title, d.document_status,
                       d.chunk_count, d.is_truncated, d.original_chunk_count,
                       d.space_type, d.space_id, d.created_at, d.updated_at,
                       d.last_error,
                       ks.name AS domain_tag,
                       f.file_name, f.file_size, f.file_type,
                       (
                           SELECT COUNT(*) FROM knowledge_entities ke
                           WHERE ke.space_id = d.space_id
                             AND ke.review_status IN ('approved', 'pending')
                       ) AS entity_count,
                       (
                           SELECT COUNT(*) FROM knowledge_entities ke
                           WHERE ke.space_id = d.space_id
                             AND ke.review_status = 'approved'
                       ) AS approved_count,  -- progress_count_v1
                       EXISTS (SELECT 1 FROM document_chunks dc
                        WHERE dc.document_id = d.document_id AND dc.page_no IS NOT NULL) AS has_page_no
                FROM documents d
                LEFT JOIN files f ON d.file_id = f.file_id
                LEFT JOIN knowledge_spaces ks ON ks.space_id::text = d.space_id::text
                WHERE d.owner_id = :user_id
                ORDER BY d.created_at DESC
                LIMIT 50
            """),
            {"user_id": current_user["user_id"]},
        )
        docs = []
        for row in result.fetchall():
            status = row.document_status
            progress_pct, status_label, eta = _compute_doc_progress(
                status, row.created_at, int(row.entity_count or 0),
                int(row.approved_count or 0)
            )
            error_summary = None
            if row.last_error:
                error_summary = _summarize_last_error(row.last_error)
            docs.append({
                "document_id": str(row.document_id),
                "title": row.title,
                "status": status,
                "status_label": status_label,
                "progress_pct": progress_pct,
                "eta_minutes": eta,
                "chunk_count": row.chunk_count,
                "has_page_no": bool(row.has_page_no) if row.has_page_no is not None else False,
                "is_truncated": row.is_truncated,
                "original_chunk_count": row.original_chunk_count,
                "entity_count": int(row.entity_count or 0),
                "approved_count": int(row.approved_count or 0),
                "space_type": row.space_type,
                "space_id": str(row.space_id) if row.space_id else None,
                "domain_tag": row.domain_tag,
                "file_name": row.file_name,
                "file_size": row.file_size,
                "file_type": row.file_type,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "last_error_summary": error_summary,
            })
    except Exception as e:
        logger.warning("get_my_documents_failed", error=str(e), user_id=current_user.get("user_id"))
        docs = []

    return {"code": 200, "msg": "success", "data": {"documents": docs}}

# ════════════════════════════════════════════════════════════════
# FE-A02：用户管理
# ════════════════════════════════════════════════════════════════
@router.get("/admin/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
) -> dict:
    """获取所有用户列表（仅管理员）。"""
    result = await db.execute(
        text("""
            SELECT u.user_id, u.email, u.nickname, u.status, u.created_at,
                   COALESCE(
                       json_agg(r.role_name) FILTER (WHERE r.role_name IS NOT NULL),
                       '[]'
                   ) AS roles
            FROM users u
            LEFT JOIN user_roles ur ON u.user_id = ur.user_id
            LEFT JOIN roles r ON ur.role_id = r.role_id
            GROUP BY u.user_id, u.email, u.nickname, u.status, u.created_at
            ORDER BY u.created_at DESC
        """)
    )
    users = [
        {
            "user_id":    str(row.user_id),
            "email":      row.email,
            "nickname":   row.nickname,
            "status":     row.status,
            "roles":      row.roles if isinstance(row.roles, list) else [],
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in result.fetchall()
    ]
    return {"code": 200, "msg": "success", "data": {"users": users, "total": len(users)}}


class UpdateUserRoleRequest(BaseModel):
    user_id:   str
    role_name: str  # learner / teacher / knowledge_reviewer / admin


@router.post("/admin/users/role")
async def update_user_role(
    req: UpdateUserRoleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
) -> dict:
    """修改用户角色（仅管理员）。"""
    valid_roles = {"learner", "teacher", "knowledge_reviewer", "admin"}
    if req.role_name not in valid_roles:
        raise HTTPException(400, detail={"code": "ROLE_001", "msg": f"Invalid role: {req.role_name}"})

    # 删除原有角色，重新分配
    await db.execute(
        text("DELETE FROM user_roles WHERE user_id = :uid"),
        {"uid": req.user_id}
    )
    await db.execute(
        text("""
            INSERT INTO user_roles (user_id, role_id)
            SELECT :uid, role_id FROM roles WHERE role_name = :role
        """),
        {"uid": req.user_id, "role": req.role_name}
    )
    await db.commit()
    logger.info("User role updated", target_user=req.user_id, role=req.role_name,
                operator=current_user["user_id"])
    return {"code": 200, "msg": "success", "data": {"updated": True}}


class UpdateUserStatusRequest(BaseModel):
    user_id: str
    status:  str  # active / disabled


@router.post("/admin/users/status")
async def update_user_status(
    req: UpdateUserStatusRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
) -> dict:
    """禁用或启用用户账号（仅管理员）。"""
    if req.status not in ("active", "disabled"):
        raise HTTPException(400, detail={"code": "USER_001", "msg": "Invalid status"})
    await db.execute(
        text("UPDATE users SET status = :status, updated_at = NOW() WHERE user_id = :uid"),
        {"status": req.status, "uid": req.user_id}
    )
    await db.commit()
    return {"code": 200, "msg": "success", "data": {"updated": True}}


# ════════════════════════════════════════════════════════════════
# FE-A03：知识审核
# ════════════════════════════════════════════════════════════════
_ENTITY_TYPES = {"concept", "element", "flow", "case", "defense"}
_REVIEW_STATUSES = {"pending", "approved", "rejected"}


def _serialize_entity(row) -> dict:
    return {
        "entity_id": str(row.entity_id),
        "name": row.name,
        "entity_type": row.entity_type,
        "canonical_name": row.canonical_name,
        "domain_tag": row.domain_tag,
        "space_type": row.space_type,
        "short_definition": row.short_definition,
        "detailed_explanation": row.detailed_explanation,
        "review_status": row.review_status,
        "is_core": bool(row.is_core),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _fetch_entities(
    db: AsyncSession,
    review_status: str,
    domain_tag: str,
    limit: int,
) -> list[dict]:
    result = await db.execute(
        text("""
            SELECT entity_id, name, entity_type, canonical_name,
                   domain_tag, space_type, short_definition,
                   detailed_explanation, review_status, is_core,
                   created_at, updated_at
            FROM knowledge_entities
            WHERE (:review_status = 'all' OR review_status = :review_status)
              AND (:domain_tag = '' OR domain_tag = :domain_tag)
            ORDER BY created_at DESC
            LIMIT :limit
        """),
        {
            "review_status": review_status,
            "domain_tag": domain_tag,
            "limit": limit,
        }
    )
    return [_serialize_entity(row) for row in result.fetchall()]


@router.get("/admin/entities")
async def list_entities(
    review_status: str = Query("pending"),
    domain_tag: str = Query(""),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin", "knowledge_reviewer")),
) -> dict:
    """获取知识点列表，支持按审核状态筛选。"""
    if review_status not in (*_REVIEW_STATUSES, "all"):
        raise HTTPException(400, detail={"code": "REVIEW_002", "msg": "invalid review_status"})

    entities = await _fetch_entities(db, review_status, domain_tag, limit)
    return {"code": 200, "msg": "success", "data": {"entities": entities, "total": len(entities)}}


@router.get("/admin/entities/pending")
async def list_pending_entities(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin", "knowledge_reviewer")),
) -> dict:
    """兼容旧前端：获取待审核知识点列表。"""
    entities = await _fetch_entities(db, "pending", "", 200)
    return {"code": 200, "msg": "success", "data": {"entities": entities, "total": len(entities)}}


class ReviewEntityRequest(BaseModel):
    entity_id: str
    action: str  # approve / reject
    reason: str = ""


class BatchReviewEntitiesRequest(BaseModel):
    entity_ids: list[str]
    action: str  # approve / reject
    reason: str = ""


class UpdateEntityRequest(BaseModel):
    entity_id: str
    canonical_name: str
    entity_type: str
    domain_tag: str
    short_definition: str = ""
    detailed_explanation: str = ""
    review_status: str | None = None
    is_core: bool = False


@router.post("/admin/entities/review")
async def review_entity(
    req: ReviewEntityRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin", "knowledge_reviewer")),
) -> dict:
    """审核单个知识点：通过或驳回。"""
    if req.action not in ("approve", "reject"):
        raise HTTPException(400, detail={"code": "REVIEW_001", "msg": "action must be approve or reject"})

    status = "approved" if req.action == "approve" else "rejected"
    await db.execute(
        text("""
            UPDATE knowledge_entities
            SET review_status = :status, updated_at = NOW()
            WHERE entity_id = :eid
        """),
        {"status": status, "eid": req.entity_id}
    )
    await db.commit()
    logger.info("Entity reviewed", entity_id=req.entity_id, action=req.action,
                reviewer=current_user["user_id"])

    # Phase 1 hook：approved 后触发 embedding 生成
    if status == "approved":
        try:
            from apps.api.tasks.embedding_tasks import embed_single_entity
            embed_single_entity.apply_async(args=[req.entity_id], queue="knowledge")
        except Exception as _e:
            logger.warning("dispatch embedding failed", entity_id=req.entity_id, error=str(_e))

    return {"code": 200, "msg": "success", "data": {"entity_id": req.entity_id, "status": status}}


@router.post("/admin/entities/review/batch")
async def review_entities_batch(
    req: BatchReviewEntitiesRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin", "knowledge_reviewer")),
) -> dict:
    """批量审核知识点。"""
    if req.action not in ("approve", "reject"):
        raise HTTPException(400, detail={"code": "REVIEW_003", "msg": "action must be approve or reject"})
    if not req.entity_ids:
        raise HTTPException(400, detail={"code": "REVIEW_004", "msg": "entity_ids cannot be empty"})

    status = "approved" if req.action == "approve" else "rejected"
    for entity_id in req.entity_ids:
        await db.execute(
            text("""
                UPDATE knowledge_entities
                SET review_status = :status, updated_at = NOW()
                WHERE entity_id = :entity_id
            """),
            {"status": status, "entity_id": entity_id}
        )
    await db.commit()
    logger.info(
        "Entities batch reviewed",
        count=len(req.entity_ids),
        action=req.action,
        reviewer=current_user["user_id"],
    )

    # Phase 1 hook：批量 approved 后逐个派发 embedding 任务
    if status == "approved":
        try:
            from apps.api.tasks.embedding_tasks import embed_single_entity
            for eid in req.entity_ids:
                embed_single_entity.apply_async(args=[eid], queue="knowledge")
            logger.info("embedding tasks dispatched after batch review",
                        count=len(req.entity_ids))
        except Exception as _e:
            logger.warning("dispatch embedding (batch) failed", error=str(_e))

    return {"code": 200, "msg": "success", "data": {"count": len(req.entity_ids), "status": status}}


@router.post("/admin/entities/update")
async def update_entity(
    req: UpdateEntityRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin", "knowledge_reviewer")),
) -> dict:
    """修改知识点内容，适用于待审核和已通过知识点。"""
    if req.entity_type not in _ENTITY_TYPES:
        raise HTTPException(400, detail={"code": "REVIEW_005", "msg": "invalid entity_type"})
    if req.review_status is not None and req.review_status not in _REVIEW_STATUSES:
        raise HTTPException(400, detail={"code": "REVIEW_006", "msg": "invalid review_status"})
    if not req.canonical_name.strip():
        raise HTTPException(400, detail={"code": "REVIEW_007", "msg": "canonical_name is required"})
    if not req.domain_tag.strip():
        raise HTTPException(400, detail={"code": "REVIEW_008", "msg": "domain_tag is required"})

    sql = """
        UPDATE knowledge_entities
        SET name = :canonical_name,
            canonical_name = :canonical_name,
            entity_type = :entity_type,
            domain_tag = :domain_tag,
            short_definition = :short_definition,
            detailed_explanation = :detailed_explanation,
            is_core = :is_core,
            updated_at = NOW()
    """
    params = {
        "entity_id": req.entity_id,
        "canonical_name": req.canonical_name.strip(),
        "entity_type": req.entity_type,
        "domain_tag": req.domain_tag.strip(),
        "short_definition": req.short_definition.strip(),
        "detailed_explanation": req.detailed_explanation.strip(),
        "is_core": req.is_core,
    }
    if req.review_status is not None:
        sql += ", review_status = :review_status\n"
        params["review_status"] = req.review_status
    sql += "WHERE entity_id = :entity_id"

    await db.execute(text(sql), params)
    await db.commit()
    logger.info("Entity updated", entity_id=req.entity_id, reviewer=current_user["user_id"])
    return {"code": 200, "msg": "success", "data": {"entity_id": req.entity_id, "updated": True}}


# ════════════════════════════════════════════════════════════════
# FE-A04：系统初始化 + 系统配置
# ════════════════════════════════════════════════════════════════
@router.get("/admin/system/init-status")
async def get_init_status(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
) -> dict:
    """获取系统初始化状态。任何单表查询失败都降级为 0，避免管理首页 500。"""
    stored_init_completed = False
    try:
        result = await db.execute(
            text("SELECT config_value FROM system_configs WHERE config_key = 'init_completed'")
        )
        row = result.fetchone()
        stored_init_completed = bool(row and row.config_value == "true")
    except Exception as e:
        logger.warning("get_init_status_config_failed", error=str(e))
        await db.rollback()

    approved_entity_count = await _safe_count(
        db,
        "SELECT COUNT(*) AS cnt FROM knowledge_entities WHERE review_status = 'approved'",
    )
    total_entity_count = await _safe_count(
        db,
        "SELECT COUNT(*) AS cnt FROM knowledge_entities",
    )
    space_count = await _safe_count(
        db,
        "SELECT COUNT(*) AS cnt FROM knowledge_spaces",
    )
    document_count = await _safe_count(
        db,
        "SELECT COUNT(*) AS cnt FROM documents",
    )

    has_user_content = any([
        approved_entity_count > 0,
        total_entity_count > 0,
        space_count > 0,
        document_count > 0,
    ])

    return {
        "code": 200,
        "msg": "success",
        "data": {
            "init_completed": stored_init_completed or has_user_content,
            "entity_count": approved_entity_count,
            "needs_seed": not has_user_content,
            "space_count": space_count,
            "document_count": document_count,
            "total_entity_count": total_entity_count,
        },
    }


@router.post("/admin/system/seed-knowledge")
async def seed_knowledge(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
) -> dict:
    """一键导入种子知识库（替代命令行 seed_knowledge.py）。"""
    SEED_ENTITIES = [
        {"name": "SQL注入", "entity_type": "concept", "canonical_name": "SQL注入",
         "domain_tag": "网络安全",
         "short_definition": "攻击者通过在输入中插入恶意SQL代码，操纵数据库查询的攻击方式",
         "detailed_explanation": "SQL注入是一种代码注入技术，攻击者将恶意SQL语句插入到应用程序的输入字段中，实现未授权的数据读取、修改或删除。",
         "is_core": True},
        {"name": "XSS跨站脚本攻击", "entity_type": "concept", "canonical_name": "XSS跨站脚本攻击",
         "domain_tag": "网络安全",
         "short_definition": "攻击者向网页注入恶意客户端脚本，在用户浏览器中执行",
         "detailed_explanation": "跨站脚本攻击（XSS）是一种注入攻击，分为反射型、存储型和DOM型三种。",
         "is_core": True},
        {"name": "CSRF跨站请求伪造", "entity_type": "concept", "canonical_name": "CSRF跨站请求伪造",
         "domain_tag": "网络安全",
         "short_definition": "诱使已登录用户在不知情的情况下执行非预期操作",
         "detailed_explanation": "CSRF攻击利用网站对用户浏览器的信任，通过伪造请求让已认证用户执行恶意操作。",
         "is_core": True},
        {"name": "文件包含漏洞", "entity_type": "concept", "canonical_name": "文件包含漏洞",
         "domain_tag": "网络安全",
         "short_definition": "攻击者通过控制include路径参数，包含并执行任意文件",
         "detailed_explanation": "文件包含漏洞出现在PHP等动态语言中，分为本地文件包含（LFI）和远程文件包含（RFI）。",
         "is_core": True},
        {"name": "路径遍历攻击", "entity_type": "concept", "canonical_name": "路径遍历攻击",
         "domain_tag": "网络安全",
         "short_definition": "通过../等序列访问Web根目录以外的文件",
         "detailed_explanation": "路径遍历攻击利用../序列突破Web应用的文件访问限制，读取服务器上的敏感文件。",
         "is_core": True},
        {"name": "参数化查询", "entity_type": "defense", "canonical_name": "参数化查询",
         "domain_tag": "网络安全",
         "short_definition": "使用预编译语句分离SQL代码与数据，从根本上防止SQL注入",
         "detailed_explanation": "参数化查询是防止SQL注入最有效的方法，通过将SQL结构和数据分开传递。",
         "is_core": False},
        {"name": "输入验证", "entity_type": "defense", "canonical_name": "输入验证",
         "domain_tag": "网络安全",
         "short_definition": "对所有用户输入进行合法性校验，拒绝非预期数据",
         "detailed_explanation": "输入验证是防御注入攻击的首要措施，包括白名单验证、长度限制、类型检查。",
         "is_core": False},
        {"name": "输出编码", "entity_type": "defense", "canonical_name": "输出编码",
         "domain_tag": "网络安全",
         "short_definition": "将特殊字符转义后再输出到HTML，防止XSS攻击",
         "detailed_explanation": "输出编码将HTML特殊字符转换为HTML实体，防止浏览器将用户输入解析为可执行脚本。",
         "is_core": False},
    ]

    SEED_RELATIONS = [
        ("路径遍历攻击", "文件包含漏洞", "prerequisite_of"),
        ("参数化查询", "SQL注入", "related"),
        ("输入验证", "SQL注入", "related"),
        ("输出编码", "XSS跨站脚本攻击", "related"),
    ]

    created = 0
    for entity in SEED_ENTITIES:
        result = await db.execute(
            text("SELECT entity_id FROM knowledge_entities WHERE canonical_name = :name"),
            {"name": entity["canonical_name"]}
        )
        if result.fetchone():
            continue
        entity_id = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO knowledge_entities
                  (entity_id, name, entity_type, canonical_name, domain_tag,
                   space_type, visibility, short_definition, detailed_explanation,
                   review_status, is_core)
                VALUES
                  (:entity_id, :name, :entity_type, :canonical_name, :domain_tag,
                   'global', 'public', :short_def, :detail, 'approved', :is_core)
            """),
            {
                "entity_id":    entity_id,
                "name":         entity["name"],
                "entity_type":  entity["entity_type"],
                "canonical_name": entity["canonical_name"],
                "domain_tag":   entity["domain_tag"],
                "short_def":    entity["short_definition"],
                "detail":       entity["detailed_explanation"],
                "is_core":      entity["is_core"],
            }
        )
        created += 1

    # 导入关系
    for source_name, target_name, rtype in SEED_RELATIONS:
        src = await db.execute(
            text("SELECT entity_id FROM knowledge_entities WHERE canonical_name = :n"),
            {"n": source_name}
        )
        tgt = await db.execute(
            text("SELECT entity_id FROM knowledge_entities WHERE canonical_name = :n"),
            {"n": target_name}
        )
        src_row = src.fetchone()
        tgt_row = tgt.fetchone()
        if src_row and tgt_row:
            await db.execute(
                text("""
                    INSERT INTO knowledge_relations
                      (relation_id, source_entity_id, target_entity_id, relation_type, review_status)
                    VALUES (:rid, :src, :tgt, :rtype, 'approved')
                    ON CONFLICT DO NOTHING
                """),
                {"rid": str(uuid.uuid4()),
                 "src": str(src_row.entity_id),
                 "tgt": str(tgt_row.entity_id),
                 "rtype": rtype}
            )

    # 标记初始化完成
    await db.execute(
        text("""
            UPDATE system_configs SET config_value = 'true', updated_at = NOW()
            WHERE config_key = 'init_completed'
        """)
    )
    await db.commit()

    return {
        "code": 200, "msg": "success",
        "data": {"created": created, "message": f"种子知识库导入完成，新增 {created} 个知识点"}
    }


@router.post("/admin/system/prebuild-banks")
async def trigger_prebuild_banks(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
) -> dict:
    """触发预生成冷启动题库（替代命令行 prebuild_banks.py）。"""
    result = await db.execute(
        text("SELECT DISTINCT domain_tag FROM knowledge_entities WHERE review_status = 'approved'")
    )
    domains = [row.domain_tag for row in result.fetchall()]

    if not domains:
        raise HTTPException(400, detail={
            "code": "INIT_001",
            "msg": "知识库为空，请先导入种子知识库"
        })

    from apps.api.tasks.tutorial_tasks import prebuild_placement_bank
    for domain in domains:
        prebuild_placement_bank.apply_async(args=[domain], queue="low_priority")

    return {
        "code": 200, "msg": "success",
        "data": {
            "triggered": len(domains),
            "domains":   domains,
            "message":   f"已触发 {len(domains)} 个领域的题库生成，后台异步执行"
        }
    }


@router.get("/admin/system/configs")
async def get_system_configs(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
) -> dict:
    """获取系统配置。"""
    result = await db.execute(
        text("SELECT config_key, config_value, description FROM system_configs ORDER BY config_key")
    )
    configs = {row.config_key: {"value": row.config_value, "description": row.description}
               for row in result.fetchall()}
    return {"code": 200, "msg": "success", "data": {"configs": configs}}


class UpdateConfigRequest(BaseModel):
    config_key:   str
    config_value: str


@router.post("/admin/system/configs")
async def update_system_config(
    req: UpdateConfigRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
) -> dict:
    """更新系统配置。"""
    await db.execute(
        text("""
            INSERT INTO system_configs (config_key, config_value, updated_at)
            VALUES (:key, :val, NOW())
            ON CONFLICT (config_key)
            DO UPDATE SET config_value = EXCLUDED.config_value, updated_at = NOW()
        """),
        {"key": req.config_key, "val": req.config_value}
    )
    await db.commit()
    return {"code": 200, "msg": "success", "data": {"updated": True}}


@router.get("/admin/system/stats")
async def get_system_stats(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
) -> dict:
    """获取系统统计数据。单项失败按 0 处理，避免首页直接 500。"""
    stats = {
        "active_users": await _safe_count(
            db,
            "SELECT COUNT(*) AS cnt FROM users WHERE status = 'active'",
        ),
        "approved_entities": await _safe_count(
            db,
            "SELECT COUNT(*) AS cnt FROM knowledge_entities WHERE review_status = 'approved'",
        ),
        "pending_entities": await _safe_count(
            db,
            "SELECT COUNT(*) AS cnt FROM knowledge_entities WHERE review_status = 'pending'",
        ),
        "total_conversations": await _safe_count(
            db,
            "SELECT COUNT(*) AS cnt FROM conversations",
        ),
        "total_documents": await _safe_count(
            db,
            "SELECT COUNT(*) AS cnt FROM documents",
        ),
        "total_spaces": await _safe_count(
            db,
            "SELECT COUNT(*) AS cnt FROM knowledge_spaces",
        ),
    }
    return {"code": 200, "msg": "success", "data": stats}

# ════════════════════════════════════════════════════════════════
# FE-A05：章节进度
# ════════════════════════════════════════════════════════════════
class MarkChapterRequest(BaseModel):
    tutorial_id:      str
    chapter_id:       str
    completed:        bool = True
    duration_seconds: int  = 0


@router.post("/learners/me/chapter-progress")
async def mark_chapter_progress(
    req: MarkChapterRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """标记章节完成/未完成。"""
    await db.execute(
        text("""
            INSERT INTO chapter_progress
              (id, user_id, tutorial_id, chapter_id, completed, completed_at)
            VALUES
              (:id, :uid, :tid, :cid, :completed,
               CASE WHEN :completed THEN NOW() ELSE NULL END)
            ON CONFLICT (user_id, tutorial_id, chapter_id)
            DO UPDATE SET
              completed    = EXCLUDED.completed,
              completed_at = CASE WHEN EXCLUDED.completed THEN NOW() ELSE NULL END
        """),
        {
            "id":        str(uuid.uuid4()),
            "uid":       current_user["user_id"],
            "tid":       req.tutorial_id,
            "cid":       req.chapter_id,
            "completed": req.completed,
        }
    )
    await db.commit()
    return {"code": 200, "msg": "success", "data": {"marked": True}}


@router.get("/learners/me/chapter-progress/{tutorial_id}")
async def get_chapter_progress(
    tutorial_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """获取某教程的章节完成进度。"""
    result = await db.execute(
        text("""
            SELECT chapter_id, completed, completed_at
            FROM chapter_progress
            WHERE user_id = :uid AND tutorial_id = :tid
        """),
        {"uid": current_user["user_id"], "tid": tutorial_id}
    )
    progress = {
        row.chapter_id: {
            "completed":    row.completed,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        }
        for row in result.fetchall()
    }
    return {"code": 200, "msg": "success", "data": {"progress": progress}}


@router.post("/admin/entities/reopen/{entity_id}")
async def reopen_entity(
    entity_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin", "knowledge_reviewer")),
) -> dict:
    """将已通过或已驳回的知识点重新打回 pending，等待人工重审。"""
    await db.execute(
        text("""
            UPDATE knowledge_entities
            SET review_status = 'pending',
                ai_review_confidence = NULL,
                ai_review_reason = NULL,
                updated_at = NOW()
            WHERE entity_id = CAST(:eid AS uuid)
              AND review_status IN ('approved', 'rejected')
        """),
        {"eid": entity_id}
    )
    await db.commit()
    return {"code": 200, "msg": "success", "data": {"entity_id": entity_id, "status": "pending"}}


@router.get("/admin/auto-review/status")
async def get_auto_review_status(
    space_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin", "knowledge_reviewer")),
) -> dict:
    """查询指定 space 的知识点自动审核进度统计。"""
    if not space_id or len(space_id) < 32:
        raise HTTPException(400, detail={"code": "AR_001", "msg": "space_id 无效"})
    result = await db.execute(
        text("""
            SELECT
                COUNT(*) FILTER (WHERE review_status = 'pending')  AS pending_count,
                COUNT(*) FILTER (WHERE review_status = 'approved') AS approved_count,
                COUNT(*) FILTER (WHERE review_status = 'rejected') AS rejected_count,
                COUNT(*) FILTER (WHERE ai_review_confidence IS NOT NULL
                                   AND review_status = 'pending') AS ai_reviewed_count
            FROM knowledge_entities
            WHERE space_id = CAST(:sid AS uuid)
        """),
        {"sid": space_id}
    )
    row = result.fetchone()
    return {
        "code": 200,
        "data": {
            "pending":     row.pending_count,
            "approved":    row.approved_count,
            "rejected":    row.rejected_count,
            "ai_reviewed": row.ai_reviewed_count,
        }
    }


@router.post("/admin/auto-review/trigger")
async def trigger_auto_review(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin", "knowledge_reviewer")),
) -> dict:
    """触发对所有 global 领域的 AI 自动审核任务。"""
    result = await db.execute(
        text("""
            SELECT space_id::text, name
            FROM knowledge_spaces
            WHERE space_type IN ('global', 'personal', 'course')
            ORDER BY created_at
        """)
    )
    spaces = [dict(r._mapping) for r in result.fetchall()]
    if not spaces:
        return {"code": 200, "data": {"triggered": 0, "message": "无可用领域"}}

    triggered = 0
    from apps.api.tasks.auto_review_tasks import auto_review_entities
    for space in spaces:
        auto_review_entities.apply_async(
            args=[space["space_id"]], queue="knowledge", countdown=2
        )
        triggered += 1
        logger.info("Auto review triggered", space_id=space["space_id"],
                    name=space["name"], by=current_user.get("user_id"))

    return {
        "code": 200,
        "data": {
            "triggered": triggered,
            "spaces": [s["name"] for s in spaces],
            "message": f"已对 {triggered} 个领域触发 AI 自动审核，请稍后刷新查看结果"
        }
    }


@router.get("/admin/auto-review/spaces")
async def list_spaces_with_review_stats(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin", "knowledge_reviewer")),
) -> dict:
    """获取所有领域及其审核进度统计，供前端选择触发目标。"""
    result = await db.execute(
        text("""
            SELECT
                ks.space_id::text,
                ks.name,
                ks.space_type,
                COUNT(ke.entity_id) FILTER (WHERE ke.review_status = 'pending')  AS pending,
                COUNT(ke.entity_id) FILTER (WHERE ke.review_status = 'approved') AS approved,
                COUNT(ke.entity_id) FILTER (WHERE ke.review_status = 'rejected') AS rejected,
                0 AS ai_reviewed
            FROM knowledge_spaces ks
            LEFT JOIN knowledge_entities ke ON ke.space_id = ks.space_id
            WHERE ks.space_type = 'global'
            GROUP BY ks.space_id, ks.name, ks.space_type
            ORDER BY ks.created_at
        """)
    )
    spaces = [dict(r._mapping) for r in result.fetchall()]
    return {"code": 200, "data": {"spaces": spaces}}


# ══════════════════════════════════════════
# 课程管理（FE-A06）
# ══════════════════════════════════════════

@router.get("/admin/courses")
async def list_courses(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """获取用户有权管理的课程列表（空间所有者）。管理员可查看全部。"""
    from sqlalchemy.exc import ProgrammingError
    user_roles = set(current_user.get("roles", []))
    is_admin = bool(user_roles.intersection({"admin", "superadmin"}))
    try:
        base_sql = """
            SELECT
                ks.space_id::text,
                sb.blueprint_id::text,
                ks.name,
                ks.space_type,
                sb.status AS bp_status,
                sb.updated_at AS bp_updated_at,
                (SELECT COUNT(*) FROM skill_chapters sc
                 JOIN skill_stages ss ON ss.stage_id = sc.stage_id
                 WHERE ss.blueprint_id = sb.blueprint_id) AS chapter_count,
                (SELECT COUNT(*) FROM skill_chapters sc
                 JOIN skill_stages ss ON ss.stage_id = sc.stage_id
                 WHERE ss.blueprint_id = sb.blueprint_id
                   AND sc.content_text IS NOT NULL
                   AND sc.content_text != '') AS content_count
            FROM knowledge_spaces ks
            JOIN LATERAL (
                SELECT * FROM skill_blueprints
                WHERE space_id = ks.space_id
                ORDER BY updated_at DESC NULLS LAST
                LIMIT 1
            ) sb ON true
            WHERE ks.deleted_at IS NULL
        """
        if is_admin:
            result = await db.execute(text(base_sql + " ORDER BY ks.created_at DESC"))
        else:
            result = await db.execute(
                text(base_sql + """ AND (ks.owner_id = CAST(:uid AS uuid) OR ks.space_type = 'global')
                    ORDER BY ks.created_at DESC"""),
                {"uid": current_user["user_id"]}
            )
        courses = []
        for r in result.fetchall():
            m = dict(r._mapping)
            courses.append({
                "space_id": m["space_id"],
                "blueprint_id": m["blueprint_id"],
                "name": m["name"],
                "space_type": m["space_type"],
                "bp_status": m["bp_status"],
                "bp_updated_at": m["bp_updated_at"].isoformat() if m["bp_updated_at"] else None,
                "chapter_count": int(m["chapter_count"] or 0),
                "content_count": int(m["content_count"] or 0),
            })
        return {"code": 200, "data": {"courses": courses}}
    except ProgrammingError:
        return {"code": 200, "data": {"courses": []}}


@router.get("/admin/courses/{blueprint_id}/chapters")
async def list_course_chapters(
    blueprint_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """获取课程下所有章节，按 stage 分组。返回 topic_key 供前端跳转。需要空间所有者权限。"""
    from apps.api.modules.space.service import SpaceService, SpaceError
    space_id = await _get_space_id_from_blueprint(db, blueprint_id)
    if not space_id:
        raise HTTPException(404, detail={"msg": "课程不存在"})
    try:
        await SpaceService(db).require_space_owner(space_id, current_user["user_id"])
    except SpaceError as e:
        raise HTTPException(403, detail={"code": e.code, "msg": e.msg})
    from sqlalchemy.exc import ProgrammingError
    from apps.api.modules.skill_blueprint.repository import BlueprintRepository
    try:
        # 查询 blueprint 的 topic_key + space_id
        bp_row = await db.execute(text("""
            SELECT sb.topic_key, sb.space_id::text
            FROM skill_blueprints sb
            WHERE sb.blueprint_id = CAST(:bid AS uuid)
        """), {"bid": blueprint_id})
        bp = bp_row.fetchone()
        topic_key = bp.topic_key if bp else ""
        space_id = bp.space_id if bp else ""

        repo = BlueprintRepository(db)
        stages_raw = await repo.get_stages(blueprint_id)
    except ProgrammingError:
        return {"code": 200, "data": {"topic_key": "", "space_id": "", "stages": []}}
    stages = []
    for s in stages_raw:
        chapters_raw = await repo.get_chapters(s["stage_id"])
        chapters = [
            {
                "chapter_id": c["chapter_id"],
                "title": c["title"],
                "chapter_order": c["chapter_order"],
                "status": c["status"],
                "has_content": bool(c.get("content_text") and c["content_text"].strip()),
                "refinement_version": c.get("refinement_version") or 0,
                "refined_at": c["refined_at"].isoformat() if c.get("refined_at") else None,
            }
            for c in chapters_raw
        ]
        stages.append({
            "stage_id": s["stage_id"],
            "title": s["title"],
            "stage_type": s.get("stage_type", ""),
            "stage_order": s["stage_order"],
            "chapters": chapters,
        })
    return {"code": 200, "data": {"topic_key": topic_key, "space_id": space_id, "stages": stages}}


@router.get("/admin/courses/chapters/{chapter_id}")
async def get_chapter_detail(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """获取章节详情，供精调对话框展示当前内容和版本信息。"""
    row = (await db.execute(
        text("""SELECT sc.chapter_id::text, sc.title, sc.objective,
                       sc.content_text, sc.refinement_version, sc.refined_at,
                       sc.previous_content_text,
                       sb.space_id::text
                FROM skill_chapters sc
                JOIN skill_blueprints sb ON sb.blueprint_id = sc.blueprint_id
                WHERE sc.chapter_id = CAST(:cid AS uuid)"""),
        {"cid": chapter_id}
    )).fetchone()
    if not row:
        raise HTTPException(404, detail={"msg": "章节不存在"})

    # 提取内容摘要（取前 300 字）
    content_json = row.content_text or "{}"
    content_summary = ""
    try:
        data = json.loads(content_json) if isinstance(content_json, str) else content_json
        scene = data.get("scene_hook", "") or ""
        full = data.get("full_content", "") or ""
        content_summary = (scene + "\n" + full)[:300]
    except (json.JSONDecodeError, TypeError):
        pass

    return {
        "code": 200,
        "data": {
            "chapter_id": str(row.chapter_id),
            "title": row.title,
            "objective": row.objective,
            "refinement_version": row.refinement_version or 0,
            "refined_at": row.refined_at.isoformat() if row.refined_at else None,
            "has_previous_content": bool(row.previous_content_text),
            "content_summary": content_summary,
        }
    }


@router.post("/admin/courses/chapters/{chapter_id}/regenerate")
async def regenerate_chapter(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """单章内容重生成（同步执行，约 30-150s）。需要空间所有者权限。"""
    from apps.api.modules.space.service import SpaceService, SpaceError
    space_id = await _get_space_id_from_chapter(db, chapter_id)
    if not space_id:
        raise HTTPException(404, detail={"msg": "章节不存在或已删除"})
    try:
        await SpaceService(db).require_space_owner(space_id, current_user["user_id"])
    except SpaceError as e:
        raise HTTPException(403, detail={"code": e.code, "msg": e.msg})
    from sqlalchemy.exc import ProgrammingError
    from apps.api.modules.skill_blueprint.repository import BlueprintRepository
    from apps.api.tasks.blueprint_tasks import CHAPTER_CONTENT_PROMPT, _normalize_chapter_content
    from apps.api.core.llm_gateway import get_llm_gateway
    import apps.api.core.llm_gateway as _gw_mod

    try:
        row = (await db.execute(
            text("SELECT title, objective, task_description FROM skill_chapters WHERE chapter_id=CAST(:cid AS uuid)"),
            {"cid": chapter_id}
        )).fetchone()
    except ProgrammingError:
        raise HTTPException(400, detail={"msg": "该功能暂不可用，系统正在升级中"})
    if not row:
        return {"code": 404, "msg": "章节不存在", "data": {}}

    _gw_mod._llm_gateway = None
    llm = get_llm_gateway()
    prompt = CHAPTER_CONTENT_PROMPT.format(
        chapter_title=row.title or "",
        objective=row.objective or "",
        task_description=row.task_description or "",
    )
    content = await asyncio.wait_for(
        llm.generate(prompt, model_route="tutorial_content"),
        timeout=150
    )
    repo = BlueprintRepository(db)
    await repo.update_chapter_content(chapter_id, _normalize_chapter_content(content.strip()))
    await db.commit()
    return {"code": 200, "data": {"chapter_id": chapter_id, "regenerated": True}}


@router.post("/admin/courses/{blueprint_id}/regenerate-all")
async def regenerate_all_course_chapters(
    blueprint_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """全量章节内容重生成（派发 Celery 后台任务）。需要空间所有者权限。"""
    from apps.api.modules.space.service import SpaceService, SpaceError
    space_id = await _get_space_id_from_blueprint(db, blueprint_id)
    if not space_id:
        raise HTTPException(404, detail={"msg": "课程不存在或已删除"})
    try:
        await SpaceService(db).require_space_owner(space_id, current_user["user_id"])
    except SpaceError as e:
        raise HTTPException(403, detail={"code": e.code, "msg": e.msg})
    from apps.api.tasks.blueprint_tasks import regenerate_all_chapters
    regenerate_all_chapters.apply_async(args=[blueprint_id], queue="knowledge")
    return {"code": 200, "data": {"queued": True, "message": "已提交后台处理，请稍后刷新查看进度"}}


# ══════════════════════════════════════════
# Layer 2: 教师对话式章节精调
# ══════════════════════════════════════════

class RefineChapterRequest(BaseModel):
    instruction: str
    auto_regenerate_quiz: bool = True
    auto_regenerate_discussion: bool = False


@router.post("/admin/courses/chapters/{chapter_id}/refine")
async def refine_chapter(
    chapter_id: str,
    req: RefineChapterRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """教师通过自然语言指令精调章节内容（同步执行，约 30-150s）。需要空间所有者权限。"""
    from apps.api.modules.space.service import SpaceService, SpaceError
    space_id = await _get_space_id_from_chapter(db, chapter_id)
    if not space_id:
        raise HTTPException(404, detail={"msg": "章节不存在或已删除"})
    try:
        await SpaceService(db).require_space_owner(space_id, current_user["user_id"])
    except SpaceError as e:
        raise HTTPException(403, detail={"code": e.code, "msg": e.msg})
    from sqlalchemy.exc import ProgrammingError
    from apps.api.modules.skill_blueprint.repository import BlueprintRepository
    from apps.api.tasks.blueprint_tasks import (
        CHAPTER_REFINEMENT_PROMPT, TEACHER_INSTRUCTION_PREFIX,
        _normalize_chapter_content,
    )
    from apps.api.core.llm_gateway import get_llm_gateway
    import apps.api.core.llm_gateway as _gw_mod

    if not req.instruction.strip():
        raise HTTPException(400, detail={"msg": "精调指令不能为空"})

    # 1. 读取章节完整信息
    try:
        row = (await db.execute(
            text("""
                SELECT sc.title, sc.objective, sc.task_description,
                       sc.content_text, sc.blueprint_id::text,
                       sb.teacher_instruction
                FROM skill_chapters sc
                JOIN skill_blueprints sb ON sb.blueprint_id = sc.blueprint_id
                WHERE sc.chapter_id = CAST(:cid AS uuid)
            """),
            {"cid": chapter_id}
        )).fetchone()
    except ProgrammingError:
        raise HTTPException(400, detail={"msg": "该功能暂不可用，系统正在升级中"})
    if not row:
        return {"code": 404, "msg": "章节不存在", "data": {}}

    # 2. 提取当前内容摘要（取前 500 字，避免 prompt 过长）
    content_json = row.content_text or "{}"
    try:
        content_data = json.loads(content_json) if isinstance(content_json, str) else content_json
        current_summary = (content_data.get("full_content", "") or "")[:500]
    except (json.JSONDecodeError, TypeError):
        current_summary = str(content_json)[:500]

    # 2.5. 备份当前内容（精调前保存，支持回滚）
    await db.execute(
        text("""UPDATE skill_chapters SET previous_content_text = content_text
               WHERE chapter_id = CAST(:cid AS uuid)"""),
        {"cid": chapter_id}
    )
    await db.commit()

    # 3. 构建全局约束块
    global_block = TEACHER_INSTRUCTION_PREFIX.format(
        instruction=row.teacher_instruction or "无特殊要求"
    ) if row.teacher_instruction else ""

    # 4. 调用 LLM 精调
    _gw_mod._llm_gateway = None
    llm = get_llm_gateway()
    prompt = CHAPTER_REFINEMENT_PROMPT.format(
        chapter_title=row.title or "",
        objective=row.objective or "",
        task_description=row.task_description or "",
        current_content_summary=current_summary,
        teacher_instruction=req.instruction.strip(),
        global_instruction=global_block,
    )
    try:
        content = await asyncio.wait_for(
            llm.generate(prompt, model_route="tutorial_content"),
            timeout=150
        )
    except asyncio.TimeoutError:
        raise HTTPException(504, detail={"msg": "精调超时，请重试或缩短指令"})

    # 5. 更新章节内容
    repo = BlueprintRepository(db)
    await repo.update_chapter_content(chapter_id, _normalize_chapter_content(content.strip()))
    await db.execute(
        text("""UPDATE skill_chapters SET refined_at=now(),
               refinement_version = COALESCE(refinement_version, 0) + 1,
               updated_at=now()
               WHERE chapter_id=CAST(:cid AS uuid)"""),
        {"cid": chapter_id}
    )
    await db.commit()

    # 6. Layer 3: 测验缓存失效
    quiz_invalidated = False
    quiz_queued = False
    if req.auto_regenerate_quiz:
        try:
            await db.execute(
                text("""UPDATE chapter_quizzes SET generated_at = NULL
                       WHERE chapter_id = CAST(:cid AS uuid)"""),
                {"cid": chapter_id}
            )
            await db.commit()
            quiz_invalidated = True
            # 异步派发重新生成
            from apps.api.tasks.blueprint_tasks import regenerate_chapter_quiz
            regenerate_chapter_quiz.apply_async(args=[chapter_id], queue="knowledge", countdown=5)
            quiz_queued = True
        except Exception:
            pass  # 测验失效失败不阻断精调

    # 7. Layer 3: 讨论种子生成（可选）
    discussion_queued = False
    if req.auto_regenerate_discussion:
        try:
            # 获取章节所属 space_id 和当前用户
            bp_row = (await db.execute(
                text("SELECT sb.space_id::text FROM skill_blueprints sb "
                     "JOIN skill_chapters sc ON sc.blueprint_id = sb.blueprint_id "
                     "WHERE sc.chapter_id = CAST(:cid AS uuid)"),
                {"cid": chapter_id}
            )).fetchone()
            space_id = bp_row[0] if bp_row else None
            if space_id:
                from apps.api.tasks.blueprint_tasks import generate_discussion_seeds
                generate_discussion_seeds.apply_async(
                    args=[chapter_id, space_id, current_user.get("user_id", "")],
                    queue="knowledge", countdown=10
                )
                discussion_queued = True
        except Exception:
            pass

    return {
        "code": 200,
        "data": {
            "chapter_id": chapter_id,
            "content_regenerated": True,
            "quiz_invalidated": quiz_invalidated,
            "quiz_regeneration_queued": quiz_queued,
            "discussion_queued": discussion_queued,
        }
    }


@router.post("/admin/courses/chapters/{chapter_id}/rollback")
async def rollback_chapter(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """回滚章节到上一次精调前的版本。需要空间所有者权限。"""
    from apps.api.modules.space.service import SpaceService, SpaceError
    space_id = await _get_space_id_from_chapter(db, chapter_id)
    if not space_id:
        raise HTTPException(404, detail={"msg": "章节不存在或已删除"})
    try:
        await SpaceService(db).require_space_owner(space_id, current_user["user_id"])
    except SpaceError as e:
        raise HTTPException(403, detail={"code": e.code, "msg": e.msg})

    row = (await db.execute(
        text("""SELECT previous_content_text, content_text, title, refinement_version
               FROM skill_chapters WHERE chapter_id = CAST(:cid AS uuid)"""),
        {"cid": chapter_id}
    )).fetchone()

    if not row:
        raise HTTPException(404, detail={"msg": "章节不存在"})
    if not row.previous_content_text:
        return {"code": 400, "msg": "没有可回滚的历史版本", "data": {}}

    # 执行回滚：previous_content_text → content_text
    await db.execute(
        text("""UPDATE skill_chapters SET
               content_text = previous_content_text,
               previous_content_text = NULL,
               refinement_version = GREATEST(COALESCE(refinement_version, 0) - 1, 0),
               refined_at = NULL,
               updated_at = now()
               WHERE chapter_id = CAST(:cid AS uuid)"""),
        {"cid": chapter_id}
    )
    await db.commit()

    return {
        "code": 200,
        "data": {
            "chapter_id": chapter_id,
            "rollback_success": True,
            "title": row.title,
            "previous_version": row.refinement_version,
        }
    }


@router.post("/files/reparse/{document_id}")
async def reparse_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """管理员重新解析已上传文档：清除旧 chunks，重新提取文字并分段。"""
    import tempfile, uuid as _uuid, json
    import re as _re
    from pathlib import Path as _Path
    from sqlalchemy import text as _text

    # 1. 查文档 + 文件信息（管理员接口，不校验 owner）
    result = await db.execute(
        _text("""
            SELECT d.document_id, d.space_type, d.space_id::text,
                   f.file_name, f.storage_url
            FROM documents d
            JOIN files f ON f.file_id = d.file_id
            WHERE d.document_id = CAST(:doc_id AS uuid)
        """),
        {"doc_id": document_id},
    )
    row = result.fetchone()
    if not row:
        return {"code": 404, "msg": "文档不存在"}

    # 2. 从 MinIO 下载原文件
    from apps.api.core.storage import minio_client
    from apps.api.core.config import CONFIG
    bucket = CONFIG.minio.bucket
    storage_url = row.storage_url
    key = storage_url.split(f"/{bucket}/", 1)[-1] if f"/{bucket}/" in storage_url else storage_url

    suffix = _Path(row.file_name).suffix.lower() or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = _Path(tmp.name)

    try:
        await minio_client.download(key, tmp_path)
    except Exception as e:
        return {"code": 500, "msg": f"文件下载失败：{e}"}

    try:
        # 3. 清除旧 chunks
        await db.execute(
            _text("DELETE FROM document_chunks WHERE document_id = CAST(:d AS uuid)"),
            {"d": document_id},
        )
        await db.execute(
            _text("UPDATE documents SET document_status='uploaded', chunk_count=0, updated_at=now() WHERE document_id=CAST(:d AS uuid)"),
            {"d": document_id},
        )
        await db.commit()

        # 4. 提取文字（page-aware）
        from apps.api.modules.knowledge.ingest_service import DocumentIngestService
        svc = DocumentIngestService(db)

        # 5. 分段（参数统一使用 CONFIG.tutorial）
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=CONFIG.tutorial.chunk_size,
            chunk_overlap=CONFIG.tutorial.chunk_overlap,
            length_function=len,
        )
        pages = await svc._extract_pages(tmp_path)
        if not pages:
            return {"code": 400, "msg": "文档文字提取为空，无法解析"}

        flat: list[tuple[int, str]] = []
        for pno, ptxt in pages:
            for ct in splitter.split_text(ptxt):
                if ct.strip():
                    flat.append((pno, ct.strip()))
        flat = flat[:CONFIG.tutorial.max_chunk_count]

        # 6. 批量写入
        BATCH = CONFIG.tutorial.ingest_batch_size
        chunk_rows = [
            {
                "chunk_id":    str(_uuid.uuid4()),
                "document_id": document_id,
                "index_no":    idx,
                "title_path":  json.dumps([]),
                "content":     ct,
                "token_count": len(ct) // 4,
                "page_no":     pno,
            }
            for idx, (pno, ct) in enumerate(flat)
        ]

        for i in range(0, len(chunk_rows), BATCH):
            await db.execute(
                _text("""
                    INSERT INTO document_chunks
                      (chunk_id, document_id, index_no, title_path, content, token_count, page_no)
                    VALUES
                      (:chunk_id, CAST(:document_id AS uuid), :index_no,
                       CAST(:title_path AS jsonb), :content, :token_count, :page_no)
                """),
                chunk_rows[i:i+BATCH],
            )

        await db.execute(
            _text("""
                UPDATE documents SET
                    document_status = 'parsed',
                    chunk_count = :cnt,
                    updated_at = now()
                WHERE document_id = CAST(:d AS uuid)
            """),
            {"cnt": len(chunk_rows), "d": document_id},
        )
        await db.commit()

        # 7. 派发实体提取任务（补齐正常上传流程中的 document_parsed 事件触发）
        try:
            from apps.api.tasks.knowledge_tasks import run_extraction
            run_extraction.apply_async(
                args=[document_id, row.space_type, row.space_id],
                queue="knowledge",
            )
        except Exception as _e:
            logger.warning("reparse: run_extraction dispatch failed", error=str(_e))

        # S1：reparse 完成后触发 chunk embedding 生成
        try:
            from apps.api.tasks.embedding_tasks import embed_document_chunks
            embed_document_chunks.apply_async(
                args=[document_id],
                queue="knowledge",
            )
        except Exception as _e:
            logger.warning("reparse: embed_document_chunks dispatch failed", error=str(_e))

        return {"code": 200, "msg": "重新解析完成", "data": {"chunk_count": len(chunk_rows)}}

    except Exception as e:
        await db.rollback()
        return {"code": 500, "msg": f"解析失败：{e}"}
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post("/admin/documents/backfill-page-no")
async def backfill_page_no(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
) -> dict:
    """一键补全 document_chunks 中缺失的 page_no。

    - 非 PDF 文档：直接 UPDATE page_no = 1（单页全文）
    - PDF 文档：返回需要手动重解析的文档列表（需从原始文件提取）
    """
    # 非 PDF 文档批量补全（单页文件 page_no=1 即可）
    result = await db.execute(text("""
        UPDATE document_chunks dc
        SET page_no = 1
        WHERE dc.page_no IS NULL
          AND dc.document_id IN (
              SELECT d.document_id FROM documents d
              JOIN files f ON f.file_id = d.file_id
              WHERE f.file_type NOT ILIKE '%pdf%'
          )
    """))
    non_pdf_fixed = result.rowcount

    # 统计仍需手动处理的 PDF 文档
    pdf_rows = await db.execute(text("""
        SELECT d.document_id::text, d.file_name, f.file_type
        FROM documents d
        JOIN files f ON f.file_id = d.file_id
        WHERE f.file_type ILIKE '%pdf%'
          AND EXISTS (
              SELECT 1 FROM document_chunks dc
              WHERE dc.document_id = d.document_id AND dc.page_no IS NULL
          )
    """))
    pdf_docs = [dict(r._mapping) for r in pdf_rows.fetchall()]

    await db.commit()

    return {"code": 200, "msg": "success", "data": {
        "non_pdf_fixed": non_pdf_fixed,
        "pdf_pending":   len(pdf_docs),
        "pdf_docs":      pdf_docs,
    }}


@router.get("/files/all-documents")
async def get_all_documents(
    status:       str | None = None,
    space_type:   str | None = None,
    page:         int = 1,
    page_size:    int = 50,
    sort_by:      str = "created_at",
    sort_order:   str = "desc",
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_role("admin")),
) -> dict:
    """管理员：获取所有用户的文档列表（含管线进度、错误详情、归属）。
    安全审计 2026-04-27：权限升级 — require_role("admin") 替代 get_current_user
    """
    from sqlalchemy import text as _text

    allowed_sort_cols = {"created_at", "updated_at", "title", "document_status", "owner_name", "file_size"}
    if sort_by not in allowed_sort_cols:
        sort_by = "created_at"
    direction = "DESC" if sort_order.lower() == "desc" else "ASC"

    where_clauses = []
    params: dict = {}
    if status:
        where_clauses.append("d.document_status = :status")
        params["status"] = status
    if space_type:
        where_clauses.append("d.space_type = :space_type")
        params["space_type"] = space_type
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    offset = (max(page, 1) - 1) * max(page_size, 1)

    # 统计总数
    count_sql = f"""
        SELECT COUNT(*) FROM documents d
        LEFT JOIN files f ON f.file_id = d.file_id
        LEFT JOIN users u ON u.user_id = d.owner_id
        {where_sql}
    """
    total = (await db.execute(_text(count_sql), params)).scalar_one()

    # 主查询
    base_sql = f"""
        SELECT d.document_id::text, d.title, d.document_status, d.space_type,
               d.owner_id::text, d.created_at, d.updated_at,
               d.chunk_count, d.last_error,
               f.file_name, f.file_type, f.file_size,
               COALESCE(u.nickname, u.email) AS owner_name, u.email AS owner_email,
               COALESCE(ks.name, '—') AS space_name,
               EXTRACT(EPOCH FROM (NOW() - d.updated_at)) / 3600.0 AS hours_since_update,
               (SELECT COUNT(*) FROM knowledge_entities ke
                WHERE ke.space_id = d.space_id AND ke.review_status = 'approved') AS approved_entities,
               (SELECT COUNT(*) FROM knowledge_entities ke
                WHERE ke.space_id = d.space_id AND ke.embedding IS NOT NULL) AS embedded_entities,
               EXISTS (SELECT 1 FROM document_chunks dc
                WHERE dc.document_id = d.document_id AND dc.page_no IS NOT NULL) AS has_page_no
        FROM documents d
        LEFT JOIN files f ON f.file_id = d.file_id
        LEFT JOIN users u ON u.user_id = d.owner_id
        LEFT JOIN knowledge_spaces ks ON ks.space_id = d.space_id
        {where_sql}
        ORDER BY {sort_by} {direction}
        LIMIT :lim OFFSET :off
    """
    params.update({"lim": page_size, "off": offset})

    try:
        result = await db.execute(_text(base_sql), params)
    except Exception:
        # 排序列不存在时降级
        await db.rollback()
        fallback_sql = base_sql.replace(f"ORDER BY {sort_by}", "ORDER BY d.created_at")
        result = await db.execute(_text(fallback_sql), params)

    rows = result.fetchall()

    STATUS_ORDER = ["uploaded", "parsed", "extracted", "embedding", "reviewed", "published"]
    STAGE_LABELS = {
        "uploaded": "已上传", "parsed": "已解析", "extracted": "已提取",
        "embedding": "嵌入中", "reviewed": "已审核", "published": "已发布",
        "failed": "失败",
    }

    docs = []
    for row in rows:
        status_val = row.document_status or "uploaded"
        # 计算管线进度百分比
        try:
            stage_idx = STATUS_ORDER.index(status_val)
            progress = int((stage_idx + 1) / len(STATUS_ORDER) * 100)
        except ValueError:
            progress = 0

        # 计算停留时长
        hours_stuck = round(row.hours_since_update or 0, 1) if status_val not in ("published", "failed") else 0

        # 提取错误摘要
        error_hint = ""
        if row.last_error:
            try:
                import json
                err_data = json.loads(row.last_error) if isinstance(row.last_error, str) else row.last_error
                error_hint = err_data.get("primary_error", str(err_data))[:120] if isinstance(err_data, dict) else str(row.last_error)[:120]
            except Exception:
                error_hint = str(row.last_error)[:120]

        docs.append({
            "document_id":       str(row.document_id),
            "title":             row.title or row.file_name,
            "document_status":   status_val,
            "status_label":      STAGE_LABELS.get(status_val, status_val),
            "pipeline_progress": progress,
            "hours_stuck":       hours_stuck,
            "space_type":        row.space_type,
            "space_name":        row.space_name,
            "owner_id":          row.owner_id,
            "owner_name":        row.owner_name,
            "owner_email":       row.owner_email,
            "file_name":         row.file_name,
            "file_type":         row.file_type,
            "file_size":         row.file_size,
            "chunk_count":       row.chunk_count or 0,
            "has_page_no":       bool(row.has_page_no),
            "approved_entities": row.approved_entities or 0,
            "embedded_entities": row.embedded_entities or 0,
            "error_hint":        error_hint,
            "created_at":        row.created_at.isoformat() if row.created_at else None,
            "updated_at":        row.updated_at.isoformat() if row.updated_at else None,
        })

    return {
        "code": 200, "msg": "success",
        "data": {
            "documents": docs,
            "total":     total,
            "page":      page,
            "page_size": page_size,
            "total_pages": max(1, -(-total // page_size)),  # ceil division
        },
    }


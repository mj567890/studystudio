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
        return 0



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
                    0 AS entity_count,
                    0 AS core_count
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
                "core_count": int(row.core_count or 0),
            }
            for row in result.fetchall()
        ]
    except Exception as e:
        logger.warning("get_domains_space_query_failed", error=str(e))

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
    current_user: dict = Depends(require_role("admin", "knowledge_reviewer")),
) -> dict:
    """创建知识空间（领域）；已存在时直接返回原 space_id。"""
    space_name = " ".join((req.name or "").split()).strip()
    if not space_name:
        raise HTTPException(400, detail={"code": "SPACE_001", "msg": "Domain name is required"})
    if req.space_type not in ("global", "course", "personal"):
        raise HTTPException(400, detail={"code": "SPACE_002", "msg": "Invalid space_type"})

    if req.space_type == "global":
        existing = await db.execute(
            text("""
                SELECT space_id::text
                FROM knowledge_spaces
                WHERE space_type = :space_type
                  AND name = :name
                LIMIT 1
            """),
            {"space_type": req.space_type, "name": space_name},
        )
    else:
        existing = await db.execute(
            text("""
                SELECT space_id::text
                FROM knowledge_spaces
                WHERE space_type = :space_type
                  AND owner_id::text = :owner_id
                  AND name = :name
                LIMIT 1
            """),
            {
                "space_type": req.space_type,
                "owner_id": current_user["user_id"],
                "name": space_name,
            },
        )

    row = existing.fetchone()
    if row:
        return {
            "code": 200,
            "msg": "success",
            "data": {
                "space_id": str(row.space_id),
                "domain_tag": space_name,
                "space_type": req.space_type,
                "created": False,
            },
        }

    space_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO knowledge_spaces (space_id, space_type, owner_id, name, description)
            VALUES (:space_id, :space_type, :owner_id, :name, :description)
        """),
        {
            "space_id": space_id,
            "space_type": req.space_type,
            "owner_id": current_user["user_id"],
            "name": space_name,
            "description": req.description.strip() if req.description else None,
        },
    )
    await db.commit()
    logger.info(
        "Knowledge space created",
        space_id=space_id,
        space_type=req.space_type,
        domain_tag=space_name,
        operator=current_user["user_id"],
    )
    return {
        "code": 201,
        "msg": "success",
        "data": {
            "space_id": space_id,
            "domain_tag": space_name,
            "space_type": req.space_type,
            "created": True,
        },
    }


@router.get("/files/my-documents")
async def get_my_documents(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """获取当前用户上传的文档列表及解析状态。异常时返回空列表，不让页面炸掉。"""
    try:
        result = await db.execute(
            text("""
                SELECT d.document_id, d.title, d.document_status,
                       d.chunk_count, d.is_truncated, d.original_chunk_count,
                       d.space_type, d.space_id, d.created_at,
                       ks.name AS domain_tag,
                       f.file_name, f.file_size, f.file_type
                FROM documents d
                LEFT JOIN files f ON d.file_id = f.file_id
                LEFT JOIN knowledge_spaces ks ON ks.space_id::text = d.space_id::text
                WHERE d.owner_id = :user_id
                ORDER BY d.created_at DESC
                LIMIT 50
            """),
            {"user_id": current_user["user_id"]},
        )
        docs = [
            {
                "document_id": str(row.document_id),
                "title": row.title,
                "status": row.document_status,
                "chunk_count": row.chunk_count,
                "is_truncated": row.is_truncated,
                "space_type": row.space_type,
                "space_id": str(row.space_id) if row.space_id else None,
                "domain_tag": row.domain_tag,
                "file_name": row.file_name,
                "file_size": row.file_size,
                "file_type": row.file_type,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in result.fetchall()
        ]
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
         "domain_tag": "web-security",
         "short_definition": "攻击者通过在输入中插入恶意SQL代码，操纵数据库查询的攻击方式",
         "detailed_explanation": "SQL注入是一种代码注入技术，攻击者将恶意SQL语句插入到应用程序的输入字段中，实现未授权的数据读取、修改或删除。",
         "is_core": True},
        {"name": "XSS跨站脚本攻击", "entity_type": "concept", "canonical_name": "XSS跨站脚本攻击",
         "domain_tag": "web-security",
         "short_definition": "攻击者向网页注入恶意客户端脚本，在用户浏览器中执行",
         "detailed_explanation": "跨站脚本攻击（XSS）是一种注入攻击，分为反射型、存储型和DOM型三种。",
         "is_core": True},
        {"name": "CSRF跨站请求伪造", "entity_type": "concept", "canonical_name": "CSRF跨站请求伪造",
         "domain_tag": "web-security",
         "short_definition": "诱使已登录用户在不知情的情况下执行非预期操作",
         "detailed_explanation": "CSRF攻击利用网站对用户浏览器的信任，通过伪造请求让已认证用户执行恶意操作。",
         "is_core": True},
        {"name": "文件包含漏洞", "entity_type": "concept", "canonical_name": "文件包含漏洞",
         "domain_tag": "web-security",
         "short_definition": "攻击者通过控制include路径参数，包含并执行任意文件",
         "detailed_explanation": "文件包含漏洞出现在PHP等动态语言中，分为本地文件包含（LFI）和远程文件包含（RFI）。",
         "is_core": True},
        {"name": "路径遍历攻击", "entity_type": "concept", "canonical_name": "路径遍历攻击",
         "domain_tag": "web-security",
         "short_definition": "通过../等序列访问Web根目录以外的文件",
         "detailed_explanation": "路径遍历攻击利用../序列突破Web应用的文件访问限制，读取服务器上的敏感文件。",
         "is_core": True},
        {"name": "参数化查询", "entity_type": "defense", "canonical_name": "参数化查询",
         "domain_tag": "web-security",
         "short_definition": "使用预编译语句分离SQL代码与数据，从根本上防止SQL注入",
         "detailed_explanation": "参数化查询是防止SQL注入最有效的方法，通过将SQL结构和数据分开传递。",
         "is_core": False},
        {"name": "输入验证", "entity_type": "defense", "canonical_name": "输入验证",
         "domain_tag": "web-security",
         "short_definition": "对所有用户输入进行合法性校验，拒绝非预期数据",
         "detailed_explanation": "输入验证是防御注入攻击的首要措施，包括白名单验证、长度限制、类型检查。",
         "is_core": False},
        {"name": "输出编码", "entity_type": "defense", "canonical_name": "输出编码",
         "domain_tag": "web-security",
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
        prebuild_placement_bank.delay(domain)

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
    tutorial_id: str
    chapter_id:  str
    completed:   bool = True


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

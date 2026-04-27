"""
apps/api/modules/space/router.py
知识空间路由（Phase 1：多成员 + 邀请码）
"""
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.db import get_db
from apps.api.modules.auth.router import get_current_user
from apps.api.modules.space.service import SpaceError, SpaceService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api", tags=["space"])



class CreateSpaceRequest(BaseModel):
    name:        str = Field(min_length=1, max_length=255)
    space_type:  str = Field(default="personal", pattern="^(global|personal|course)$")
    description: Optional[str] = Field(default=None)

class UpdateSpaceRequest(BaseModel):
    name:        Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None)
    visibility:  Optional[str] = Field(default=None, pattern="^(private|shared|public)$")
    allow_fork:  Optional[bool] = Field(default=None)



class SubscribeRequest(BaseModel):
    topic_key: str = Field(min_length=1, max_length=255)

class JoinSpaceRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)


_CODE_TO_STATUS = {
    "SPACE_400": 400,
    "SPACE_403": 403,
    "SPACE_404": 404,
    "SPACE_409": 409,
    "SPACE_500": 500,
}


def _raise_http(e: SpaceError) -> None:
    status_code = _CODE_TO_STATUS.get(e.code, 400)
    raise HTTPException(status_code=status_code, detail={"code": e.code, "msg": e.msg})



@router.post("/spaces")
async def create_space(
    req: CreateSpaceRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    service = SpaceService(db)
    try:
        data = await service.create_space(
            current_user["user_id"], req.name, req.space_type, req.description
        )
    except SpaceError as e:
        _raise_http(e)
    return {"code": 201, "msg": "success", "data": data}

@router.get("/spaces")
async def list_spaces(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    service = SpaceService(db)
    data = await service.list_my_spaces(current_user["user_id"])
    return {"code": 200, "msg": "success", "data": data}


@router.post("/spaces/join")
async def join_by_invite(
    req: JoinSpaceRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    # 注意：此路由必须放在 /spaces/{space_id} 之前，避免路径参数捕获 "join"
    service = SpaceService(db)
    try:
        data = await service.join_by_invite_code(req.code, current_user["user_id"])
    except SpaceError as e:
        _raise_http(e)
    return {"code": 200, "msg": "success", "data": data}



@router.get("/spaces/public")
async def list_public_spaces(
    limit:  int = 20,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """返回所有 visibility=public 的课程，供发现页展示。
    注意：必须在 /spaces/{space_id} 之前注册，否则 public 会被当成 UUID 参数。
    """
    from sqlalchemy import text
    result = await db.execute(
        text("""
            SELECT
                ks.space_id::text,
                ks.name,
                ks.description,
                ks.created_at,
                u.nickname AS owner_nickname,
                (SELECT COUNT(*) FROM space_members sm
                 WHERE sm.space_id = ks.space_id) AS member_count,
                (SELECT COUNT(*) FROM knowledge_entities ke
                 WHERE ke.space_id = ks.space_id
                   AND ke.review_status = 'approved') AS entity_count,
                NULL AS blueprint_status,
                EXISTS(
                    SELECT 1 FROM space_members sm2
                    WHERE sm2.space_id = ks.space_id
                      AND sm2.user_id = CAST(:uid AS uuid)
                ) AS is_member
            FROM knowledge_spaces ks
            LEFT JOIN users u ON u.user_id = ks.owner_id
            WHERE ks.visibility = 'public' AND ks.deleted_at IS NULL
            ORDER BY ks.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {"uid": current_user["user_id"], "limit": limit, "offset": offset}
    )
    rows = result.fetchall()

    total_row = await db.execute(
        text("""
            SELECT COUNT(*) FROM knowledge_spaces
            WHERE visibility = 'public' AND deleted_at IS NULL
        """)
    )
    total = total_row.scalar() or 0

    spaces = [
        {
            "space_id":        r.space_id,
            "name":            r.name or "(未命名)",
            "description":     r.description or "",
            "owner_nickname":  r.owner_nickname or "匿名",
            "member_count":    int(r.member_count),
            "entity_count":    int(r.entity_count),
            "blueprint_status": r.blueprint_status,
            "is_member":       bool(r.is_member),
            "created_at":      r.created_at.isoformat() if r.created_at else "",
        }
        for r in rows
    ]
    return {"code": 200, "msg": "success", "data": {"spaces": spaces, "total": total}}


@router.get("/spaces/{space_id}")
async def get_space(
    space_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    service = SpaceService(db)
    try:
        data = await service.get_space_detail(str(space_id), current_user["user_id"])
    except SpaceError as e:
        _raise_http(e)
    return {"code": 200, "msg": "success", "data": data}


@router.patch("/spaces/{space_id}")
async def update_space(
    space_id: UUID,
    req: UpdateSpaceRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    service = SpaceService(db)
    try:
        data = await service.update_space(
            str(space_id),
            current_user["user_id"],
            req.name,
            req.description,
            req.visibility,
            req.allow_fork,
        )
    except SpaceError as e:
        _raise_http(e)
    return {"code": 200, "msg": "success", "data": data}



@router.post("/spaces/{space_id}/join-public")
async def join_public_space(
    space_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """直接加入公开课程，无需邀请码。非公开课程返回 403。"""
    from sqlalchemy import text
    sid = str(space_id)
    uid = current_user["user_id"]

    # 检查课程存在且是公开的
    row = await db.execute(
        text("SELECT name, visibility FROM knowledge_spaces WHERE space_id = CAST(:sid AS uuid) AND deleted_at IS NULL"),
        {"sid": sid}
    )
    space = row.fetchone()
    if not space:
        raise HTTPException(404, detail={"code": "SPACE_404", "msg": "课程不存在"})
    if space.visibility != "public":
        raise HTTPException(403, detail={"code": "SPACE_403", "msg": "该课程不是公开课程"})

    # 检查是否已是成员
    exists = await db.execute(
        text("""
            SELECT 1 FROM space_members
            WHERE space_id = CAST(:sid AS uuid) AND user_id = CAST(:uid AS uuid)
        """),
        {"sid": sid, "uid": uid}
    )
    if exists.fetchone():
        return {"code": 200, "msg": "success", "data": {
            "already_member": True, "space_name": space.name
        }}

    # 写入成员记录
    import uuid as _uuid
    await db.execute(
        text("""
            INSERT INTO space_members (id, space_id, user_id, role, joined_at)
            VALUES (CAST(:id AS uuid), CAST(:sid AS uuid), CAST(:uid AS uuid), 'member', NOW())
        """),
        {"id": str(_uuid.uuid4()), "sid": sid, "uid": uid}
    )
    await db.commit()
    return {"code": 200, "msg": "success", "data": {
        "already_member": False, "space_name": space.name
    }}


@router.get("/spaces/{space_id}/members")
async def list_members(
    space_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    service = SpaceService(db)
    try:
        data = await service.list_members(str(space_id), current_user["user_id"])
    except SpaceError as e:
        _raise_http(e)
    return {"code": 200, "msg": "success", "data": data}


@router.delete("/spaces/{space_id}/members/{user_id}")
async def remove_member(
    space_id: UUID,
    user_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    service = SpaceService(db)
    try:
        await service.remove_member(
            str(space_id), str(user_id), current_user["user_id"]
        )
    except SpaceError as e:
        _raise_http(e)
    return {"code": 200, "msg": "success", "data": None}


@router.post("/spaces/{space_id}/invite-code")
async def reset_invite_code(
    space_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    service = SpaceService(db)
    try:
        code = await service.reset_invite_code(str(space_id), current_user["user_id"])
    except SpaceError as e:
        _raise_http(e)
    return {"code": 200, "msg": "success", "data": {"invite_code": code}}


@router.delete("/spaces/{space_id}/invite-code")
async def revoke_invite_code(
    space_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    service = SpaceService(db)
    try:
        await service.revoke_invite_code(str(space_id), current_user["user_id"])
    except SpaceError as e:
        _raise_http(e)
    return {"code": 200, "msg": "success", "data": None}

@router.get("/subscriptions")
async def list_subscriptions(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    service = SpaceService(db)
    data = await service.list_subscriptions(current_user["user_id"])
    return {"code": 200, "msg": "success", "data": data}


@router.post("/spaces/{space_id}/subscribe")
async def subscribe(
    space_id: UUID,
    req: SubscribeRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    service = SpaceService(db)
    try:
        data = await service.subscribe_topic(
            current_user["user_id"], str(space_id), req.topic_key
        )
    except SpaceError as e:
        _raise_http(e)
    return {"code": 200, "msg": "success", "data": data}


@router.delete("/spaces/{space_id}/subscribe/{topic_key}")
async def unsubscribe(
    space_id: UUID,
    topic_key: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    service = SpaceService(db)
    try:
        await service.unsubscribe_topic(
            current_user["user_id"], str(space_id), topic_key
        )
    except SpaceError as e:
        _raise_http(e)
    return {"code": 200, "msg": "success", "data": None}


@router.get("/spaces/{space_id}/subscribe/{topic_key}/check")
async def check_update(
    space_id: UUID,
    topic_key: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    service = SpaceService(db)
    data = await service.check_update(
        current_user["user_id"], str(space_id), topic_key
    )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/spaces/{space_id}/subscribe/{topic_key}/ack")
async def ack_update(
    space_id: UUID,
    topic_key: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    service = SpaceService(db)
    try:
        data = await service.ack_update(
            current_user["user_id"], str(space_id), topic_key
        )
    except SpaceError as e:
        _raise_http(e)
    return {"code": 200, "msg": "success", "data": data}



# ═══════════════════════════════════════════════════════════════
# 知识领域导出 / 导入
# ═══════════════════════════════════════════════════════════════
import json as _json
from fastapi import UploadFile, File
from fastapi.responses import JSONResponse

@router.get("/spaces/{space_id}/export")
async def export_space(
    space_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """导出指定空间的知识点和关系（仅空间成员可用）。"""
    from sqlalchemy import text
    sid = str(space_id)

    # 鉴权
    try:
        await SpaceService(db).require_space_access(sid, current_user["user_id"])
    except SpaceError as e:
        _raise_http(e)

    # 导出知识点（不含 embedding / owner_id）
    ent_result = await db.execute(
        text("""
            SELECT entity_id, name, entity_type, canonical_name,
                   domain_tag, space_type, short_definition,
                   detailed_explanation, review_status, is_core,
                   aliases, version
            FROM knowledge_entities
            WHERE space_id = CAST(:sid AS uuid)
        """),
        {"sid": sid},
    )
    entities = [dict(row._mapping) for row in ent_result.fetchall()]

    # 收集 entity_id 集合，用于过滤跨 space 的关系
    entity_ids = {str(e["entity_id"]) for e in entities}

    # 导出关系（仅两端都在本空间内的）
    if entity_ids:
        rel_result = await db.execute(
            text("""
                SELECT relation_id, source_entity_id, target_entity_id,
                       relation_type, weight, review_status
                FROM knowledge_relations
                WHERE source_entity_id = ANY(CAST(:ids AS uuid[]))
                  AND target_entity_id = ANY(CAST(:ids AS uuid[]))
            """),
            {"ids": list(entity_ids)},
        )
        relations = [dict(row._mapping) for row in rel_result.fetchall()]
    else:
        relations = []

    # 序列化 UUID / Decimal
    def _serial(obj):
        import uuid, decimal
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        raise TypeError

    payload = {
        "export_version": "1.0",
        "space_id": sid,
        "entity_count": len(entities),
        "relation_count": len(relations),
        "entities": entities,
        "relations": relations,
    }

    return JSONResponse(
        content=_json.loads(_json.dumps(payload, default=_serial)),
        headers={"Content-Disposition": f'attachment; filename="space_{sid[:8]}_export.json"'},
    )


class ImportSpaceRequest(BaseModel):
    target_space_id: str
    data: dict  # 导出文件的完整 JSON 内容


@router.post("/spaces/import")
async def import_space(
    req: ImportSpaceRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """将导出的知识领域数据导入到目标空间（仅空间成员可用）。重复实体按 canonical_name 去重。"""
    from sqlalchemy import text
    import uuid

    # 鉴权
    try:
        await SpaceService(db).require_space_access(
            req.target_space_id, current_user["user_id"]
        )
    except SpaceError as e:
        _raise_http(e)

    data = req.data
    if data.get("export_version") != "1.0":
        raise HTTPException(400, detail={"code": "IMPORT_001", "msg": "不支持的导出版本"})

    entities = data.get("entities", [])
    relations = data.get("relations", [])

    # old_id -> new_id 映射
    id_map: dict[str, str] = {}
    inserted_entities = 0
    skipped_entities = 0

    for ent in entities:
        old_id = str(ent["entity_id"])
        canonical = ent.get("canonical_name") or ent.get("name")

        # 检查目标空间是否已有同名实体
        exists = await db.execute(
            text("""
                SELECT entity_id FROM knowledge_entities
                WHERE space_id = CAST(:sid AS uuid)
                  AND canonical_name = :cname
                LIMIT 1
            """),
            {"sid": req.target_space_id, "cname": canonical},
        )
        row = exists.fetchone()
        if row:
            id_map[old_id] = str(row.entity_id)
            skipped_entities += 1
            continue

        new_id = str(uuid.uuid4())
        id_map[old_id] = new_id
        await db.execute(
            text("""
                INSERT INTO knowledge_entities
                    (entity_id, name, entity_type, canonical_name,
                     domain_tag, space_type, space_id, owner_id,
                     short_definition, detailed_explanation,
                     review_status, is_core, aliases, version)
                VALUES
                    (CAST(:eid AS uuid), :name, :etype, :cname,
                     :dtag, :stype, CAST(:sid AS uuid), CAST(:oid AS uuid),
                     :sdef, :dexp,
                     :rstatus, :is_core, CAST(:aliases AS jsonb), :ver)
            """),
            {
                "eid":    new_id,
                "name":   ent.get("name"),
                "etype":  ent.get("entity_type", "concept"),
                "cname":  canonical,
                "dtag":   ent.get("domain_tag", ""),
                "stype":  ent.get("space_type", "personal"),
                "sid":    req.target_space_id,
                "oid":    current_user["user_id"],
                "sdef":   ent.get("short_definition") or "",
                "dexp":   ent.get("detailed_explanation") or "",
                "rstatus": "pending",
                "is_core": ent.get("is_core", False),
                "aliases": _json.dumps(ent.get("aliases") or [], ensure_ascii=False),
                "ver":    ent.get("version", 1),
            },
        )
        inserted_entities += 1

    # 导入关系（两端 id 都在映射表里才插入）
    inserted_relations = 0
    for rel in relations:
        src = id_map.get(str(rel["source_entity_id"]))
        tgt = id_map.get(str(rel["target_entity_id"]))
        if not src or not tgt:
            continue
        # 检查是否已存在相同关系
        exists = await db.execute(
            text("""
                SELECT 1 FROM knowledge_relations
                WHERE source_entity_id = CAST(:src AS uuid)
                  AND target_entity_id = CAST(:tgt AS uuid)
                  AND relation_type = :rtype
                LIMIT 1
            """),
            {"src": src, "tgt": tgt, "rtype": rel.get("relation_type", "related")},
        )
        if exists.fetchone():
            continue
        await db.execute(
            text("""
                INSERT INTO knowledge_relations
                    (relation_id, source_entity_id, target_entity_id,
                     relation_type, weight, review_status)
                VALUES
                    (uuid_generate_v4(),
                     CAST(:src AS uuid), CAST(:tgt AS uuid),
                     :rtype, :weight, 'pending')
            """),
            {
                "src":   src,
                "tgt":   tgt,
                "rtype": rel.get("relation_type", "related"),
                "weight": float(rel.get("weight", 1.0)),
            },
        )
        inserted_relations += 1

    await db.commit()

    return {
        "code": 200,
        "msg": "success",
        "data": {
            "inserted_entities":  inserted_entities,
            "skipped_entities":   skipped_entities,
            "inserted_relations": inserted_relations,
        },
    }



# -- fork routes --

class ForkSpaceRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)


@router.post("/spaces/{space_id}/fork")
async def fork_space(
    space_id: UUID,
    req: ForkSpaceRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """Fork 一个 space，异步复制所有资产到新 space。"""
    service = SpaceService(db)
    try:
        data = await service.fork_space(
            str(space_id), current_user["user_id"], req.name
        )
    except SpaceError as e:
        _raise_http(e)
    return {"code": 202, "msg": "Fork initiated", "data": data}


@router.get("/fork-tasks/{task_id}")
async def get_fork_status(
    task_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """查询 fork 任务状态：pending / running / done / failed。"""
    service = SpaceService(db)
    try:
        data = await service.get_fork_status(
            str(task_id), current_user["user_id"]
        )
    except SpaceError as e:
        _raise_http(e)
    return {"code": 200, "msg": "success", "data": data}



@router.get("/spaces/{space_id}/entities")
async def list_space_entities(
    space_id: UUID,
    limit:    int = 100,
    offset:   int = 0,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """获取空间内已审核的知识点列表（成员可用）。"""
    from sqlalchemy import text
    sid = str(space_id)
    try:
        await SpaceService(db).require_space_access(sid, current_user["user_id"])
    except SpaceError as e:
        _raise_http(e)

    result = await db.execute(
        text("""
            SELECT entity_id::text, canonical_name, entity_type,
                   domain_tag, short_definition, review_status, is_core
            FROM knowledge_entities
            WHERE space_id = CAST(:sid AS uuid)
              AND review_status = 'approved'
            ORDER BY is_core DESC, canonical_name
            LIMIT :limit OFFSET :offset
        """),
        {"sid": sid, "limit": limit, "offset": offset}
    )
    entities = [dict(r._mapping) for r in result.fetchall()]

    # 查总数
    total = (await db.execute(
        text("SELECT COUNT(*) FROM knowledge_entities WHERE space_id=CAST(:sid AS uuid) AND review_status='approved'"),
        {"sid": sid}
    )).scalar() or 0

    return {"code": 200, "msg": "success", "data": {"entities": entities, "total": total}}


@router.get("/spaces/{space_id}/blueprint")
async def get_space_blueprint(
    space_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """返回该课程最新蓝图的 topic_key 和 status。"""
    from sqlalchemy import text as _t
    from sqlalchemy.exc import ProgrammingError
    try:
        row = (await db.execute(_t("""
            SELECT topic_key, status, title
            FROM skill_blueprints
            WHERE space_id = CAST(:sid AS uuid)
            ORDER BY created_at DESC LIMIT 1
        """), {"sid": str(space_id)})).fetchone()
    except ProgrammingError:
        return {"code": 200, "msg": "success", "data": None}
    if not row:
        return {"code": 200, "msg": "success", "data": None}
    return {"code": 200, "msg": "success", "data": {
        "topic_key": row.topic_key,
        "status":    row.status,
        "title":     row.title,
    }}


@router.get("/spaces/{space_id}/chapters")
async def get_space_chapters(
    space_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """返回该课程已发布蓝图的所有已审核章节。"""
    from sqlalchemy import text as _t
    from sqlalchemy.exc import ProgrammingError
    try:
        rows = (await db.execute(_t("""
            SELECT sc.chapter_id::text, sc.title, sc.chapter_order,
                   ss.title AS stage_title
            FROM skill_chapters sc
            JOIN skill_stages ss ON ss.stage_id = sc.stage_id
            JOIN skill_blueprints sb ON sb.blueprint_id = sc.blueprint_id
            WHERE sb.space_id = CAST(:sid AS uuid)
              AND sb.status = 'published'
              AND sc.status = 'approved'
            ORDER BY sc.chapter_order
        """), {"sid": str(space_id)})).fetchall()
    except ProgrammingError:
        return {"code": 200, "msg": "success", "data": {"chapters": []}}
    chapters = [
        {
            "chapter_id":  r.chapter_id,
            "title":       r.title,
            "stage_title": r.stage_title,
        }
        for r in rows
    ]
    return {"code": 200, "msg": "success", "data": {"chapters": chapters}}


# ═══════════════════════════════════════════════════════════════
# 删除 / 回收站
# ═══════════════════════════════════════════════════════════════

@router.delete("/spaces/{space_id}")
async def delete_space(
    space_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """软删除空间——移入回收站。"""
    service = SpaceService(db)
    try:
        data = await service.soft_delete_space(str(space_id), current_user["user_id"])
    except SpaceError as e:
        _raise_http(e)
    return {"code": 200, "msg": "已移入回收站", "data": data}


@router.get("/spaces/trash")
async def list_trash(
    limit:  int = 20,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """回收站列表（仅自己拥有的空间）。"""
    service = SpaceService(db)
    data = await service.list_trash_spaces(current_user["user_id"], limit, offset)
    return {"code": 200, "msg": "success", "data": data}


@router.post("/spaces/{space_id}/restore")
async def restore_space(
    space_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """从回收站还原空间。"""
    service = SpaceService(db)
    try:
        data = await service.restore_space(str(space_id), current_user["user_id"])
    except SpaceError as e:
        _raise_http(e)
    return {"code": 200, "msg": "已还原", "data": data}


@router.delete("/spaces/{space_id}/permanent")
async def permanent_delete_space(
    space_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """彻底删除空间（不可逆）。"""
    service = SpaceService(db)
    try:
        data = await service.permanent_delete_space(
            str(space_id), current_user["user_id"]
        )
    except SpaceError as e:
        _raise_http(e)
    return {"code": 200, "msg": "已彻底删除", "data": data}


@router.delete("/spaces/trash")
async def empty_trash(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """清空回收站——彻底删除所有可删除空间。"""
    service = SpaceService(db)
    data = await service.empty_trash(current_user["user_id"])
    return {"code": 200, "msg": "回收站已清空", "data": data}


@router.get("/spaces/{space_id}/deletion-impact")
async def get_deletion_impact(
    space_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """获取删除该空间的影响范围数据（供确认弹窗使用）。"""
    service = SpaceService(db)
    try:
        data = await service.get_deletion_impact(
            str(space_id), current_user["user_id"]
        )
    except SpaceError as e:
        _raise_http(e)
    return {"code": 200, "msg": "success", "data": data}


@router.get("/spaces/{space_id}/public-info")
async def get_public_info(
    space_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """设置公开前获取影响范围信息（供确认弹窗使用）。"""
    service = SpaceService(db)
    try:
        await service._require_manager(str(space_id), current_user["user_id"])
    except SpaceError as e:
        _raise_http(e)

    stats = await service.repo.get_deletion_impact(str(space_id))
    return {
        "code": 200, "msg": "success",
        "data": {
            "document_count": stats.get("document_count", 0),
            "entity_count": stats.get("entity_count", 0),
            "warning_text": (
                "公开课程后：\n"
                "1. 您的课程章节、知识点将对所有登录用户可见\n"
                "2. 若同时开启「允许 Fork」，其他用户可复制您的课程\n"
                "3. 您的文档将为 fork 用户提供溯源依据\n"
                "4. 被 fork 后，您可能无法强制删除已共享的文档\n"
                "5. 因主动公开导致的内容扩散，系统不承担责任"
            ),
            "requires_confirmation": True,
        },
    }

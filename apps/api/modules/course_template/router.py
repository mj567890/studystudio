"""课程模板 — API 路由"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.core.db import get_db
from apps.api.modules.auth.router import get_current_user
from apps.api.modules.space.service import SpaceService
from .schema import (
    CreateTemplateRequest, UpdateTemplateRequest,
    SetSpaceDefaultTemplateRequest, TemplateOut,
)
from .service import TemplateService

router = APIRouter(prefix="/api", tags=["课程模板"])


def _out(tmpl: dict) -> dict:
    return TemplateOut(
        template_id=tmpl["template_id"],
        name=tmpl["name"],
        content=tmpl["content"],
        is_system=tmpl["is_system"],
        is_public=tmpl["is_public"],
        created_by=tmpl.get("created_by"),
        created_at=tmpl["created_at"],
        updated_at=tmpl["updated_at"],
    ).model_dump(mode="json")


# ── 列表 ──
@router.get("/course-templates")
async def list_templates(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    svc = TemplateService(db)
    templates = await svc.list_templates(current_user["user_id"])
    return {
        "code": 200, "msg": "success",
        "data": {"templates": [_out(t) for t in templates]},
    }


# ── 详情 ──
@router.get("/course-templates/{template_id}")
async def get_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    svc = TemplateService(db)
    tmpl = await svc.get_template(template_id)
    if not tmpl:
        raise HTTPException(404, detail={"code": "TPL_404", "msg": "模板不存在"})
    return {"code": 200, "msg": "success", "data": _out(tmpl)}


# ── 创建 ──
@router.post("/course-templates", status_code=201)
async def create_template(
    req: CreateTemplateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    svc = TemplateService(db)
    tmpl = await svc.create_template(
        current_user["user_id"], req.name, req.content, req.is_public,
    )
    return {"code": 201, "msg": "模板创建成功", "data": _out(tmpl)}


# ── 更新 ──
@router.put("/course-templates/{template_id}")
async def update_template(
    template_id: str,
    req: UpdateTemplateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    svc = TemplateService(db)
    try:
        tmpl = await svc.update_template(
            current_user["user_id"], template_id,
            name=req.name, content=req.content, is_public=req.is_public,
        )
    except PermissionError as e:
        raise HTTPException(403, detail={"code": "TPL_403", "msg": str(e)})
    if not tmpl:
        raise HTTPException(404, detail={"code": "TPL_404", "msg": "模板不存在"})
    return {"code": 200, "msg": "模板已更新", "data": _out(tmpl)}


# ── 删除 ──
@router.delete("/course-templates/{template_id}")
async def delete_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    svc = TemplateService(db)
    try:
        deleted = await svc.delete_template(current_user["user_id"], template_id)
    except PermissionError as e:
        raise HTTPException(403, detail={"code": "TPL_403", "msg": str(e)})
    if not deleted:
        raise HTTPException(404, detail={"code": "TPL_404", "msg": "模板不存在"})
    return {"code": 200, "msg": "模板已删除", "data": None}


# ── 设置空间默认模板 ──
@router.put("/spaces/{space_id}/default-template")
async def set_space_default_template(
    space_id: str,
    req: SetSpaceDefaultTemplateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    svc = TemplateService(db)
    space_svc = SpaceService(db)
    await space_svc.require_space_owner(space_id, current_user["user_id"])
    await svc.set_space_default_template(
        space_id, req.template_id,
        req.theory_template_id, req.task_template_id, req.project_template_id
    )
    return {"code": 200, "msg": "空间默认模板已设置", "data": None}

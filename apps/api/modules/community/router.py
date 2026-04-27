from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.core.db import get_db
from apps.api.modules.auth.router import get_current_user
from apps.api.modules.community.service import CurationService, CurationError

router = APIRouter(prefix="/api/community", tags=["community"])


def _raise_http(e: CurationError):
   raise HTTPException(400, detail={"code": e.code, "msg": e.msg})


def _check_admin(current_user: dict):
   _roles = current_user.get("roles") or []
   if isinstance(_roles, str):
       _roles = [_roles]
   _role = current_user.get("role", "")
   if _role and _role not in _roles:
       _roles = _roles + [_role]
   if not any(r in ("admin", "superadmin") for r in _roles):
       raise HTTPException(403, detail={"code": "CUR_403", "msg": "仅管理员可执行此操作"})


class SubmitCurationRequest(BaseModel):
   entity_id: str
   space_id:  str
   tags:      list[str] = []
   note:      str | None = None


class ReviewCurationRequest(BaseModel):
   status: str


@router.post("/curate")
async def submit_curation(
   req: SubmitCurationRequest,
   current_user: dict = Depends(get_current_user),
   db: AsyncSession   = Depends(get_db),
) -> dict:
   """提交策展申请（任何登录用户均可提交 global space 的已审核知识点）。"""
   svc = CurationService(db)
   try:
       data = await svc.submit(
           req.entity_id, req.space_id,
           current_user["user_id"], req.tags, req.note
       )
   except CurationError as e:
       _raise_http(e)
   return {"code": 200, "msg": "success", "data": data}


@router.get("/curations")
async def list_curations(
   space_id: str | None = None,
   tag:      str | None = None,
   limit:    int = 50,
   offset:   int = 0,
   current_user: dict = Depends(get_current_user),
   db: AsyncSession   = Depends(get_db),
) -> dict:
   """浏览已批准的策展内容（所有登录用户可见）。"""
   svc = CurationService(db)
   data = await svc.list_approved(space_id=space_id, tag=tag,
                                  limit=limit, offset=offset)
   return {"code": 200, "msg": "success", "data": data}


@router.get("/curations/pending")
async def list_pending(
   limit:  int = 50,
   offset: int = 0,
   current_user: dict = Depends(get_current_user),
   db: AsyncSession   = Depends(get_db),
) -> dict:
   """查看待审核列表（仅 admin）。"""
   _check_admin(current_user)
   svc = CurationService(db)
   data = await svc.list_pending(limit=limit, offset=offset)
   return {"code": 200, "msg": "success", "data": data}


@router.patch("/curations/{curation_id}")
async def review_curation(
   curation_id: str,
   req: ReviewCurationRequest,
   current_user: dict = Depends(get_current_user),
   db: AsyncSession   = Depends(get_db),
) -> dict:
   """审核策展申请（仅 admin）。"""
   _check_admin(current_user)
   svc = CurationService(db)
   try:
       data = await svc.review(curation_id, req.status)
   except CurationError as e:
       _raise_http(e)
   return {"code": 200, "msg": "success", "data": data}

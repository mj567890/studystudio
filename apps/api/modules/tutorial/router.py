from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.db import get_db
from apps.api.modules.tutorial.tutorial_service import TutorialService

try:
    from apps.api.modules.auth.dependencies import get_current_user
except Exception:  # pragma: no cover
    get_current_user = None  # type: ignore


router = APIRouter(prefix="/tutorials", tags=["tutorials"])


def _current_user_id(current_user: Any) -> str | None:
    if current_user is None:
        return None
    return (
        getattr(current_user, "user_id", None)
        or getattr(current_user, "id", None)
        or getattr(current_user, "sub", None)
    )


@router.get("/topics")
async def list_topics(
    space_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user) if get_current_user else None,
):
    svc = TutorialService(db)
    return await svc.list_topics(user_id=_current_user_id(current_user), space_type=space_type)


@router.get("/topic/{topic_key}")
async def get_topic_tutorial(
    topic_key: str,
    space_type: str = Query(default="personal"),
    space_id: str | None = Query(default=None),
    force: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user) if get_current_user else None,
):
    svc = TutorialService(db)
    blueprint = await svc.get_topic_tutorial(
        topic_key,
        user_id=_current_user_id(current_user),
        space_type=space_type,
        space_id=space_id,
        force=force,
    )
    return blueprint.model_dump()


@router.post("/topic/{topic_key}/regenerate")
async def regenerate_topic_tutorial(
    topic_key: str,
    payload: dict[str, Any] | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user) if get_current_user else None,
):
    svc = TutorialService(db)
    payload = payload or {}
    blueprint = await svc.regenerate_topic_tutorial(
        topic_key,
        user_id=_current_user_id(current_user),
        space_type=payload.get("space_type", "personal"),
        space_id=payload.get("space_id"),
    )
    return blueprint.model_dump()


@router.get("/chapter/{chapter_id}/content")
async def get_chapter_content(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    svc = TutorialService(db)
    try:
        return await svc.get_chapter_content(chapter_id=chapter_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/path/{topic_key}")
async def get_topic_learning_path(
    topic_key: str,
    space_type: str = Query(default="personal"),
    space_id: str | None = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user) if get_current_user else None,
):
    user_id = _current_user_id(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="not authenticated")
    svc = TutorialService(db)
    path = await svc.build_learning_path(
        user_id=user_id,
        topic_key=topic_key,
        space_type=space_type,
        space_id=space_id,
        limit=limit,
    )
    return [item.model_dump() for item in path]

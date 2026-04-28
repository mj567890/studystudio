from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from apps.api.core.db import get_db
from apps.api.modules.auth.router import get_current_user
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/discuss", tags=["discuss"])


# ── 帖子列表 ────────────────────────────────────────────────────

@router.get("/spaces/{space_id}/posts")
async def list_posts(
    space_id: str,
    chapter_id: str | None = Query(None),
    post_type:  str | None = Query(None),
    limit: int = 20,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    params: dict = {"space_id": space_id, "limit": limit, "offset": offset}
    extra = ""
    if chapter_id:
        extra += " AND p.chapter_id = CAST(:chapter_id AS uuid)"
        params["chapter_id"] = chapter_id
    if post_type:
        extra += " AND p.post_type = :post_type"
        params["post_type"] = post_type

    rows = await db.execute(text(f"""
        SELECT p.post_id::text, p.space_id::text, p.chapter_id::text,
               p.user_id::text, p.post_type, p.title, p.content,
               p.reply_count, p.created_at, p.updated_at,
               u.nickname AS username, u.avatar_url
        FROM course_posts p
        JOIN users u ON u.user_id = p.user_id
        WHERE p.space_id = CAST(:space_id AS uuid)
          {extra}
        ORDER BY p.created_at DESC
        LIMIT :limit OFFSET :offset
    """), params)

    posts = [
        {
            "post_id":       r.post_id,
            "space_id":      r.space_id,
            "chapter_id":    r.chapter_id,
            "chapter_title": None,
            "user_id":       r.user_id,
            "username":      r.username,
            "avatar_url":    r.avatar_url,
            "post_type":     r.post_type,
            "title":         r.title,
            "content":       r.content,
            "reply_count":   r.reply_count,
            "created_at":    r.created_at.isoformat(),
            "updated_at":    r.updated_at.isoformat(),
        }
        for r in rows.fetchall()
    ]
    return {"code": 200, "msg": "success", "data": {"posts": posts}}


# ── 创建帖子 ────────────────────────────────────────────────────

class CreatePostRequest(BaseModel):
    post_type:  str = "discussion"
    title:      str | None = None
    content:    str
    chapter_id: str | None = None


@router.post("/spaces/{space_id}/posts")
async def create_post(
    space_id: str,
    req: CreatePostRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if req.post_type not in ("note", "question", "discussion"):
        raise HTTPException(400, detail={"code": "POST_001", "msg": "无效的帖子类型"})
    if not req.content.strip():
        raise HTTPException(400, detail={"code": "POST_002", "msg": "内容不能为空"})

    row = await db.execute(text("""
        INSERT INTO course_posts
          (space_id, chapter_id, user_id, post_type, title, content)
        VALUES
          (CAST(:space_id AS uuid),
           CAST(:chapter_id AS uuid),
           CAST(:user_id AS uuid),
           :post_type, :title, :content)
        RETURNING post_id::text, created_at
    """), {
        "space_id":   space_id,
        "chapter_id": req.chapter_id or None,
        "user_id":    current_user["user_id"],
        "post_type":  req.post_type,
        "title":      req.title,
        "content":    req.content,
    })
    r = row.fetchone()
    await db.commit()
    return {"code": 201, "msg": "success", "data": {
        "post_id": r.post_id,
        "created_at": r.created_at.isoformat(),
    }}


# ── 删除帖子 ────────────────────────────────────────────────────

@router.delete("/posts/{post_id}")
async def delete_post(
    post_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.execute(text("""
        SELECT user_id::text FROM course_posts WHERE post_id = CAST(:pid AS uuid)
    """), {"pid": post_id})
    r = row.fetchone()
    if not r:
        raise HTTPException(404, detail={"code": "POST_404", "msg": "帖子不存在"})
    if r.user_id != current_user["user_id"]:
        raise HTTPException(403, detail={"code": "POST_403", "msg": "无权删除"})
    await db.execute(text("DELETE FROM course_posts WHERE post_id = CAST(:pid AS uuid)"), {"pid": post_id})
    await db.commit()
    return {"code": 200, "msg": "success", "data": {}}


# ── 回复列表 ────────────────────────────────────────────────────

@router.get("/posts/{post_id}/replies")
async def list_replies(
    post_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = await db.execute(text("""
        SELECT r.reply_id::text, r.post_id::text, r.user_id::text,
               r.content, r.created_at,
               u.nickname AS username, u.avatar_url
        FROM course_post_replies r
        JOIN users u ON u.user_id = r.user_id
        WHERE r.post_id = CAST(:pid AS uuid)
        ORDER BY r.created_at ASC
    """), {"pid": post_id})
    replies = [
        {
            "reply_id":   r.reply_id,
            "post_id":    r.post_id,
            "user_id":    r.user_id,
            "username":   r.username,
            "avatar_url": r.avatar_url,
            "content":    r.content,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows.fetchall()
    ]
    return {"code": 200, "msg": "success", "data": {"replies": replies}}


# ── 创建回复 ────────────────────────────────────────────────────

class CreateReplyRequest(BaseModel):
    content: str


@router.post("/posts/{post_id}/replies")
async def create_reply(
    post_id: str,
    req: CreateReplyRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not req.content.strip():
        raise HTTPException(400, detail={"code": "REPLY_001", "msg": "回复内容不能为空"})

    exists = await db.execute(text(
        "SELECT 1 FROM course_posts WHERE post_id = CAST(:pid AS uuid)"
    ), {"pid": post_id})
    if not exists.fetchone():
        raise HTTPException(404, detail={"code": "POST_404", "msg": "帖子不存在"})

    row = await db.execute(text("""
        INSERT INTO course_post_replies (post_id, user_id, content)
        VALUES (CAST(:pid AS uuid), CAST(:uid AS uuid), :content)
        RETURNING reply_id::text, created_at
    """), {
        "pid":     post_id,
        "uid":     current_user["user_id"],
        "content": req.content,
    })
    r = row.fetchone()

    # 更新帖子回复数
    await db.execute(text("""
        UPDATE course_posts SET reply_count = reply_count + 1, updated_at = now()
        WHERE post_id = CAST(:pid AS uuid)
    """), {"pid": post_id})

    await db.commit()
    return {"code": 201, "msg": "success", "data": {
        "reply_id": r.reply_id,
        "created_at": r.created_at.isoformat(),
    }}


# ── 删除回复 ────────────────────────────────────────────────────

@router.delete("/replies/{reply_id}")
async def delete_reply(
    reply_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.execute(text("""
        SELECT user_id::text, post_id::text FROM course_post_replies
        WHERE reply_id = CAST(:rid AS uuid)
    """), {"rid": reply_id})
    r = row.fetchone()
    if not r:
        raise HTTPException(404, detail={"code": "REPLY_404", "msg": "回复不存在"})
    if r.user_id != current_user["user_id"]:
        raise HTTPException(403, detail={"code": "REPLY_403", "msg": "无权删除"})

    await db.execute(text(
        "DELETE FROM course_post_replies WHERE reply_id = CAST(:rid AS uuid)"
    ), {"rid": reply_id})
    await db.execute(text("""
        UPDATE course_posts SET reply_count = GREATEST(reply_count - 1, 0), updated_at = now()
        WHERE post_id = CAST(:pid AS uuid)
    """), {"pid": r.post_id})
    await db.commit()
    return {"code": 200, "msg": "success", "data": {}}


# ── 源课程讨论引用（Fork 空间只读）──────────────────────────────

@router.get("/spaces/{space_id}/source-posts")
async def list_source_posts(
    space_id: str,
    chapter_id: str | None = Query(None),
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回 Fork 源空间对应章节的讨论帖（只读引用）。

    仅当该空间是 Fork 空间时返回数据；原创空间返回空列表。
    支持链式 Fork：沿 fork_from_space_id 追溯到最初源空间。
    """
    # 1. 查找源空间
    row = await db.execute(text("""
        WITH RECURSIVE fork_chain AS (
            SELECT space_id, fork_from_space_id, name, 1 AS depth
            FROM knowledge_spaces
            WHERE space_id = CAST(:space_id AS uuid) AND fork_from_space_id IS NOT NULL
            UNION ALL
            SELECT ks.space_id, ks.fork_from_space_id, ks.name, fc.depth + 1
            FROM knowledge_spaces ks
            JOIN fork_chain fc ON ks.space_id = fc.fork_from_space_id
        )
        SELECT space_id::text, name, depth
        FROM fork_chain
        ORDER BY depth DESC
        LIMIT 1
    """), {"space_id": space_id})
    source = row.fetchone()
    if not source:
        return {"code": 200, "msg": "success", "data": {"source_space_name": "", "posts": []}}

    # 2. 查询源空间对应章节的帖子和回复数
    params: dict = {"space_id": source.space_id, "limit": limit}
    chapter_filter = ""
    if chapter_id:
        chapter_filter = " AND p.chapter_id = CAST(:chapter_id AS uuid)"
        params["chapter_id"] = chapter_id

    rows = await db.execute(text(f"""
        SELECT p.post_id::text, p.chapter_id::text, p.user_id::text,
               p.post_type, p.title, p.content,
               p.reply_count, p.created_at, p.updated_at,
               u.nickname AS username, u.avatar_url
        FROM course_posts p
        JOIN users u ON u.user_id = p.user_id
        WHERE p.space_id = CAST(:space_id AS uuid)
          {chapter_filter}
        ORDER BY p.reply_count DESC, p.created_at DESC
        LIMIT :limit
    """), params)

    posts = [
        {
            "post_id":       r.post_id,
            "chapter_id":    r.chapter_id,
            "user_id":       r.user_id,
            "username":      r.username,
            "avatar_url":    r.avatar_url,
            "post_type":     r.post_type,
            "title":         r.title,
            "content":       r.content,
            "reply_count":   r.reply_count,
            "created_at":    r.created_at.isoformat(),
            "updated_at":    r.updated_at.isoformat(),
            "is_source":     True,
        }
        for r in rows.fetchall()
    ]
    return {"code": 200, "msg": "success", "data": {
        "source_space_name": source.name,
        "source_space_id":   source.space_id,
        "posts":             posts,
    }}


# ── 我加入的课程的最新动态（聚合 feed）──────────────────────────

@router.get("/feed")
async def get_feed(
    limit: int = 30,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = await db.execute(text("""
        SELECT p.post_id::text, p.space_id::text, p.chapter_id::text,
               p.user_id::text, p.post_type, p.title, p.content,
               p.reply_count, p.created_at,
               u.nickname AS username,
               u.avatar_url,
               ks.name AS space_name
        FROM course_posts p
        JOIN users u ON u.user_id = p.user_id
        JOIN knowledge_spaces ks ON ks.space_id = p.space_id
        WHERE p.space_id IN (
            SELECT space_id FROM space_members
            WHERE user_id = CAST(:uid AS uuid)
        )
        ORDER BY p.created_at DESC
        LIMIT :limit
    """), {"uid": current_user["user_id"], "limit": limit})

    posts = [
        {
            "post_id":       r.post_id,
            "space_id":      r.space_id,
            "space_name":    r.space_name,
            "chapter_id":    r.chapter_id,
            "chapter_title": None,
            "user_id":       r.user_id,
            "username":      r.username,
            "avatar_url":    r.avatar_url,
            "post_type":     r.post_type,
            "title":         r.title,
            "content":       r.content,
            "reply_count":   r.reply_count,
            "created_at":    r.created_at.isoformat(),
        }
        for r in rows.fetchall()
    ]
    return {"code": 200, "msg": "success", "data": {"posts": posts}}

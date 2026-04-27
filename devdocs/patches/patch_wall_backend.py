from pathlib import Path

p = Path("apps/api/modules/learner/eight_dim_endpoints.py")
s = p.read_text()

NEW = '''
# ── 学习墙 ───────────────────────────────────────────────────────────────

class WallPostRequest(BaseModel):
    chapter_id: str
    topic_key:  str = ""
    post_type:  str = "stuck"   # stuck | tip | discuss
    content:    str

class WallReplyRequest(BaseModel):
    content: str


@eight_dim_router.get("/wall/posts")
async def list_wall_posts(
    chapter_id: str = "",
    topic_key:  str = "",
    post_type:  str = "",
    status:     str = "",
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conditions = ["1=1"]
    params: dict = {}
    if chapter_id:
        conditions.append("p.chapter_id = :chapter_id")
        params["chapter_id"] = chapter_id
    if topic_key:
        conditions.append("p.topic_key = :topic_key")
        params["topic_key"] = topic_key
    if post_type:
        conditions.append("p.post_type = :post_type")
        params["post_type"] = post_type
    if status:
        conditions.append("p.status = :status")
        params["status"] = status

    where = " AND ".join(conditions)
    rows = (await db.execute(text(f"""
        SELECT p.post_id::text, p.user_id::text, p.chapter_id, p.topic_key,
               p.post_type, p.content, p.status, p.is_featured, p.likes,
               p.created_at, p.updated_at,
               u.nickname, u.avatar_url,
               COUNT(r.reply_id) AS reply_count
        FROM wall_posts p
        JOIN users u ON u.user_id = p.user_id
        LEFT JOIN wall_replies r ON r.post_id = p.post_id
        WHERE {where}
        GROUP BY p.post_id, u.nickname, u.avatar_url
        ORDER BY p.is_featured DESC, p.created_at DESC
        LIMIT 50
    """), params)).fetchall()

    posts = [
        {{
            "post_id":     r.post_id,
            "user_id":     r.user_id,
            "nickname":    r.nickname or "匿名",
            "avatar_url":  r.avatar_url,
            "chapter_id":  r.chapter_id,
            "topic_key":   r.topic_key,
            "post_type":   r.post_type,
            "content":     r.content,
            "status":      r.status,
            "is_featured": r.is_featured,
            "likes":       r.likes,
            "reply_count": r.reply_count,
            "created_at":  r.created_at.isoformat(),
            "is_mine":     r.user_id == str(current_user["user_id"]),
        }}
        for r in rows
    ]
    return {{"code": 200, "msg": "success", "data": {{"posts": posts}}}}


@eight_dim_router.post("/wall/posts")
async def create_wall_post(
    req: WallPostRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not req.content.strip():
        raise HTTPException(400, detail={{"msg": "内容不能为空"}})
    uid = current_user["user_id"]
    pid = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO wall_posts (post_id, user_id, chapter_id, topic_key, post_type, content)
        VALUES (CAST(:pid AS uuid), CAST(:uid AS uuid), :cid, :tk, :pt, :content)
    """), {{"pid": pid, "uid": uid, "cid": req.chapter_id,
            "tk": req.topic_key, "pt": req.post_type, "content": req.content}})
    await db.commit()

    # 求助型帖子 AI 自动初答
    ai_reply = None
    if req.post_type == "stuck":
        try:
            from apps.api.core.llm_gateway import LLMGateway
            gw = LLMGateway()
            prompt = f"""一位学员在学习「{req.topic_key}」时遇到了困难，发帖内容如下：

{req.content}

请给出一个简洁、有针对性的引导性回答（不要直接给出完整答案，而是帮助学员自己思考），100字以内。"""
            ai_content = await gw.generate(prompt, model_route="knowledge_extraction")
            rid = str(uuid.uuid4())
            await db.execute(text("""
                INSERT INTO wall_replies (reply_id, post_id, user_id, content, is_ai)
                VALUES (CAST(:rid AS uuid), CAST(:pid AS uuid),
                        CAST(:uid AS uuid), :content, true)
            """), {{"rid": rid, "pid": pid, "uid": uid, "content": ai_content}})
            await db.commit()
            ai_reply = ai_content
        except Exception:
            pass

    return {{"code": 200, "msg": "success", "data": {{
        "post_id": pid, "ai_reply": ai_reply
    }}}}


@eight_dim_router.get("/wall/posts/{post_id}/replies")
async def list_replies(
    post_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(text("""
        SELECT r.reply_id::text, r.user_id::text, r.content, r.is_ai,
               r.likes, r.created_at, u.nickname, u.avatar_url
        FROM wall_replies r
        JOIN users u ON u.user_id = r.user_id
        WHERE r.post_id = CAST(:pid AS uuid)
        ORDER BY r.created_at
    """), {{"pid": post_id}})).fetchall()

    replies = [
        {{
            "reply_id":   r.reply_id,
            "user_id":    r.user_id,
            "nickname":   r.nickname or "匿名",
            "avatar_url": r.avatar_url,
            "content":    r.content,
            "is_ai":      r.is_ai,
            "likes":      r.likes,
            "created_at": r.created_at.isoformat(),
            "is_mine":    r.user_id == str(current_user["user_id"]),
        }}
        for r in rows
    ]
    return {{"code": 200, "msg": "success", "data": {{"replies": replies}}}}


@eight_dim_router.post("/wall/posts/{post_id}/replies")
async def create_reply(
    post_id: str,
    req: WallReplyRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not req.content.strip():
        raise HTTPException(400, detail={{"msg": "回复内容不能为空"}})
    rid = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO wall_replies (reply_id, post_id, user_id, content)
        VALUES (CAST(:rid AS uuid), CAST(:pid AS uuid), CAST(:uid AS uuid), :content)
    """), {{"rid": rid, "pid": post_id, "uid": current_user["user_id"], "content": req.content}})
    await db.execute(text("""
        UPDATE wall_posts SET updated_at = NOW()
        WHERE post_id = CAST(:pid AS uuid)
    """), {{"pid": post_id}})
    await db.commit()
    return {{"code": 200, "msg": "success", "data": {{"reply_id": rid}}}}


@eight_dim_router.post("/wall/posts/{post_id}/resolve")
async def resolve_post(
    post_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(text("""
        UPDATE wall_posts SET status = 'resolved'
        WHERE post_id = CAST(:pid AS uuid) AND user_id = CAST(:uid AS uuid)
    """), {{"pid": post_id, "uid": current_user["user_id"]}})
    await db.commit()
    return {{"code": 200, "msg": "success", "data": {{}}}}


@eight_dim_router.post("/wall/posts/{post_id}/like")
async def like_post(
    post_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(text("""
        UPDATE wall_posts SET likes = likes + 1
        WHERE post_id = CAST(:pid AS uuid)
    """), {{"pid": post_id}})
    await db.commit()
    return {{"code": 200, "msg": "success", "data": {{}}}}

'''

ANCHOR = "# ── 阶段能力证书 PDF"
if "wall_posts" in s:
    print("✓ 学习墙接口已存在，跳过")
else:
    p.write_text(s.replace(ANCHOR, NEW + ANCHOR, 1))
    print("✓ 学习墙接口写入完成")

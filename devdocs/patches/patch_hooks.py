"""
patch_hooks.py
Phase 1 三个 hook + 注册新任务模块

修改 4 个文件：
  1. apps/api/tasks/tutorial_tasks.py     注册 embedding_tasks 模块和路由
  2. apps/api/tasks/auto_review_tasks.py  approved 后批量触发 embed_single_entity
  3. apps/api/modules/admin/router.py     review_entity + review_entities_batch 后触发

幂等：每个改动都先检查是否已存在。
"""
from pathlib import Path
import ast
import sys

CHANGES = 0

def _patch_file(path_str: str, label: str, old: str, new: str, marker: str) -> bool:
    """
    返回 True 表示这次执行做了修改。
    marker：用来检测"已经改过了"的字符串
    """
    global CHANGES
    p = Path(path_str)
    content = p.read_text(encoding="utf-8")
    if marker in content:
        print(f"[SKIP] {label}: 已是新版本")
        return False
    if old not in content:
        print(f"[ERR]  {label}: 找不到锚点", file=sys.stderr)
        sys.exit(2)
    new_content = content.replace(old, new, 1)
    try:
        ast.parse(new_content)
    except SyntaxError as e:
        print(f"[ERR]  {label}: 修改后语法错误 {e}", file=sys.stderr)
        sys.exit(3)
    p.write_text(new_content, encoding="utf-8")
    CHANGES += 1
    print(f"[OK]   {label}")
    return True


# ════════════════════════════════════════════════════════════════
# Patch 1: tutorial_tasks.py 注册新任务模块
# ════════════════════════════════════════════════════════════════
_patch_file(
    "apps/api/tasks/tutorial_tasks.py",
    "tutorial_tasks: include embedding_tasks",
    old='''    include = [
        "apps.api.tasks.tutorial_tasks",
        "apps.api.tasks.blueprint_tasks",
        "apps.api.tasks.knowledge_tasks",
        "apps.api.tasks.auto_review_tasks",
    ],''',
    new='''    include = [
        "apps.api.tasks.tutorial_tasks",
        "apps.api.tasks.blueprint_tasks",
        "apps.api.tasks.knowledge_tasks",
        "apps.api.tasks.auto_review_tasks",
        "apps.api.tasks.embedding_tasks",
    ],''',
    marker="apps.api.tasks.embedding_tasks",
)

_patch_file(
    "apps/api/tasks/tutorial_tasks.py",
    "tutorial_tasks: route embedding_tasks → knowledge",
    old='''        "apps.api.tasks.auto_review_tasks.auto_review_entities":  {"queue": "knowledge"},
    }
)''',
    new='''        "apps.api.tasks.auto_review_tasks.auto_review_entities":  {"queue": "knowledge"},
        "apps.api.tasks.embedding_tasks.embed_single_entity":     {"queue": "knowledge"},
        "apps.api.tasks.embedding_tasks.backfill_entity_embeddings": {"queue": "knowledge"},
    }
)''',
    marker="embed_single_entity\":     {\"queue\": \"knowledge\"}",
)


# ════════════════════════════════════════════════════════════════
# Patch 2: auto_review_tasks.py 在 approved 提交后 fan-out
# ════════════════════════════════════════════════════════════════
_patch_file(
    "apps/api/tasks/auto_review_tasks.py",
    "auto_review_tasks: trigger embeddings after approved commit",
    old='''            if rejected_ids:
                await session.execute(
                    text("""
                        UPDATE knowledge_entities
                        SET review_status='rejected', updated_at=now()
                        WHERE entity_id = ANY(CAST(:ids AS uuid[]))
                          AND review_status='pending'
                    """),
                    {"ids": rejected_ids}
                )

    # ── 还有更多 pending 则继续 ──────────────────────────────────''',
    new='''            if rejected_ids:
                await session.execute(
                    text("""
                        UPDATE knowledge_entities
                        SET review_status='rejected', updated_at=now()
                        WHERE entity_id = ANY(CAST(:ids AS uuid[]))
                          AND review_status='pending'
                    """),
                    {"ids": rejected_ids}
                )

    # ── Phase 1 hook: 给所有刚 approved 的实体派发 embedding 任务 ──
    if approved_ids:
        try:
            from apps.api.tasks.embedding_tasks import embed_single_entity
            for eid in approved_ids:
                embed_single_entity.apply_async(args=[eid], queue="knowledge")
            logger.info("embedding tasks dispatched after auto_review",
                        count=len(approved_ids))
        except Exception as _e:
            logger.warning("Failed to dispatch embedding tasks",
                           error=str(_e), count=len(approved_ids))

    # ── 还有更多 pending 则继续 ──────────────────────────────────''',
    marker="embedding tasks dispatched after auto_review",
)


# ════════════════════════════════════════════════════════════════
# Patch 3: admin/router.py review_entity 单条审核 hook
# ════════════════════════════════════════════════════════════════
_patch_file(
    "apps/api/modules/admin/router.py",
    "admin/router: hook review_entity",
    old='''    status = "approved" if req.action == "approve" else "rejected"
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
    return {"code": 200, "msg": "success", "data": {"entity_id": req.entity_id, "status": status}}''',
    new='''    status = "approved" if req.action == "approve" else "rejected"
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

    return {"code": 200, "msg": "success", "data": {"entity_id": req.entity_id, "status": status}}''',
    marker="Phase 1 hook：approved 后触发 embedding",
)


# ════════════════════════════════════════════════════════════════
# Patch 4: admin/router.py review_entities_batch 批量审核 hook
# ════════════════════════════════════════════════════════════════
_patch_file(
    "apps/api/modules/admin/router.py",
    "admin/router: hook review_entities_batch",
    old='''    status = "approved" if req.action == "approve" else "rejected"
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
    return {"code": 200, "msg": "success", "data": {"count": len(req.entity_ids), "status": status}}''',
    new='''    status = "approved" if req.action == "approve" else "rejected"
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

    return {"code": 200, "msg": "success", "data": {"count": len(req.entity_ids), "status": status}}''',
    marker="embedding tasks dispatched after batch review",
)


print(f"\n共完成 {CHANGES} 处修改")

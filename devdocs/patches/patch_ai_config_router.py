"""
patch_ai_config_router.py
给 ai_config_router.py 添加 POST /api/admin/ai/embeddings/backfill 接口。

幂等：已经加过就跳过。
"""
from pathlib import Path
import ast
import sys

p = Path("apps/api/modules/admin/ai_config_router.py")
content = p.read_text(encoding="utf-8")

if "embeddings/backfill" in content:
    print("[SKIP] backfill 接口已存在")
    sys.exit(0)

# ── 1. 加 BackfillRequest schema ──
schema_anchor = "class DimensionMigrateRequest(BaseModel):"
new_schema = '''class BackfillEmbeddingsRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    space_id: str | None = None     # None = 全库
    batch_size: int = Field(32, ge=1, le=200)


class DimensionMigrateRequest(BaseModel):'''

if schema_anchor not in content:
    print("[ERR] 找不到 DimensionMigrateRequest 锚点", file=sys.stderr)
    sys.exit(2)
content = content.replace(schema_anchor, new_schema, 1)
print("[OK]   BackfillEmbeddingsRequest schema 已添加")

# ── 2. 加路由 handler，放在 migrate_embedding_dimension 之前 ──
endpoint_anchor = "# ═══════════════════════════════════════════════════════════════════\n# Embedding 维度迁移（破坏性）"
new_endpoint = '''# ═══════════════════════════════════════════════════════════════════
# Embedding 批量回填（Phase 1）
# ═══════════════════════════════════════════════════════════════════
@router.post("/embeddings/backfill")
async def trigger_backfill_embeddings(
    req: BackfillEmbeddingsRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    手动触发批量 embedding 回填。
    任务异步入 knowledge 队列，立即返回 task_id。
    space_id=None 表示全库回填。
    """
    _require_admin(current_user)

    from apps.api.tasks.embedding_tasks import backfill_entity_embeddings
    async_result = backfill_entity_embeddings.apply_async(
        args=[req.space_id, req.batch_size],
        queue="knowledge",
    )
    logger.warning("Backfill embeddings dispatched",
                   task_id=async_result.id,
                   space_id=req.space_id,
                   batch_size=req.batch_size)
    return {"code": 200, "data": {
        "task_id": async_result.id,
        "space_id": req.space_id,
        "message": "回填任务已入队，请到 celery_worker_knowledge 容器日志查看进度",
    }}


# ═══════════════════════════════════════════════════════════════════
# Embedding 维度迁移（破坏性）'''

if endpoint_anchor not in content:
    print("[ERR] 找不到 Embedding 维度迁移锚点", file=sys.stderr)
    sys.exit(2)
content = content.replace(endpoint_anchor, new_endpoint, 1)
print("[OK]   /embeddings/backfill 接口已添加")

# ── 写回 + 语法检查 ──
ast.parse(content)
print("[OK]   语法 OK")
p.write_text(content, encoding="utf-8")
print("[OK]   文件已保存")

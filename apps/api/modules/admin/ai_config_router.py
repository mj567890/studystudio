"""
apps/api/modules/admin/ai_config_router.py

Admin AI 配置管理接口：
  - providers  CRUD + 测试连接
  - capability bindings CRUD（upsert by capability+priority）
  - embedding 维度探测与破坏性迁移（vector(N) → vector(M)）

权限：全部要求 admin / superadmin

Capability 注册表 KNOWN_CAPABILITIES 是本文件唯一来源，前端通过 /capabilities 接口动态拉取，
未来新增 AI 能力在这里加一行即可，不需改表结构。
"""
from __future__ import annotations

import json
import time as _time

import structlog
from fastapi import APIRouter, Depends, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.db import get_db
from apps.api.core.crypto import encrypt, decrypt, mask_secret
from apps.api.core.llm_gateway import get_llm_gateway
from apps.api.modules.auth.router import get_current_user

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/admin/ai", tags=["admin-ai-config"])


# ═══════════════════════════════════════════════════════════════════
# Capability 注册表（未来扩展在此添加一行即可）
# kind: 'chat' 或 'embedding'，决定测试时调用哪个端点
# required: true 表示核心能力，false 表示未来/可选
# ═══════════════════════════════════════════════════════════════════
KNOWN_CAPABILITIES = [
    # ── Chat（当前在用）──
    {"key": "teaching_chat_simple",  "group": "chat",   "kind": "chat",      "label": "教学对话（简单）",   "required": True},
    {"key": "teaching_chat_complex", "group": "chat",   "kind": "chat",      "label": "教学对话（复杂）",   "required": True},
    {"key": "knowledge_extraction",  "group": "chat",   "kind": "chat",      "label": "知识抽取",           "required": True},
    {"key": "quality_evaluation",    "group": "chat",   "kind": "chat",      "label": "内容质量评估",       "required": True},
    {"key": "quiz_generation",       "group": "chat",   "kind": "chat",      "label": "测验出题",           "required": True},
    {"key": "coherence_eval",        "group": "chat",   "kind": "chat",      "label": "连贯性评分",         "required": True},
    # ── Chat（新增）──
    {"key": "blueprint_synthesis",   "group": "chat",   "kind": "chat",      "label": "蓝图合成（Phase 2）", "required": False},
    # ── 向量类 ──
    {"key": "embedding",             "group": "vector", "kind": "embedding", "label": "文本向量（Phase 1 必需）", "required": True},
    {"key": "reranker",              "group": "vector", "kind": "reranker", "label": "检索重排",            "required": False},
    # ── 多模态（未来）──
    {"key": "vision_ocr",            "group": "vision", "kind": "chat",      "label": "图像 OCR",            "required": False},
    {"key": "vision_understanding",  "group": "vision", "kind": "chat",      "label": "图像理解",            "required": False},
    # ── 语音（未来）──
    {"key": "asr",                   "group": "audio",  "kind": "chat",      "label": "语音识别",            "required": False},
    {"key": "tts",                   "group": "audio",  "kind": "chat",      "label": "语音合成",            "required": False},
    # ── 生成（未来）──
    {"key": "image_generation",      "group": "image",  "kind": "chat",      "label": "图像生成",            "required": False},
    # ── 安全（未来）──
    {"key": "moderation",            "group": "safety", "kind": "chat",      "label": "内容审核",            "required": False},
]

CAPABILITY_KEYS = {c["key"] for c in KNOWN_CAPABILITIES}


# ═══════════════════════════════════════════════════════════════════
# Pydantic Schemas
# ═══════════════════════════════════════════════════════════════════
class ProviderCreate(BaseModel):
    name: str = Field(..., max_length=100)
    kind: str = Field(..., pattern="^(openai_compatible|anthropic|gemini|ollama|azure_openai)$")
    base_url: str
    api_key: str = ""         # 前端传明文，服务端加密入库
    extra_config: dict = {}
    enabled: bool = True


class ProviderUpdate(BaseModel):
    name: str | None = None
    kind: str | None = None
    base_url: str | None = None
    api_key: str | None = None    # None = 保持不变；"" = 清空
    extra_config: dict | None = None
    enabled: bool | None = None


class BindingUpsert(BaseModel):
    model_config = {"protected_namespaces": ()}
    capability: str
    provider_id: str
    model_name: str
    priority: int = 0
    params: dict = {}
    enabled: bool = True


class TestProviderRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    # 两种模式：
    # 1) 已保存的 provider → 传 provider_id（api_key 从 DB 读）
    # 2) 未保存的临时配置 → 传 base_url + api_key
    provider_id: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model_name: str
    capability_kind: str = Field(..., pattern="^(chat|embedding|reranker)$")


class BackfillEmbeddingsRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    space_id: str | None = None     # None = 全库
    batch_size: int = Field(32, ge=1, le=200)


class DimensionMigrateRequest(BaseModel):
    new_dim: int = Field(..., ge=64, le=8192)
    confirm: bool = False


# ═══════════════════════════════════════════════════════════════════
# 权限工具
# ═══════════════════════════════════════════════════════════════════
def _require_admin(current_user: dict) -> None:
    roles = current_user.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    role = current_user.get("role", "")
    if role and role not in roles:
        roles = roles + [role]
    if not any(r in ("admin", "superadmin") for r in roles):
        raise HTTPException(403, detail={"code": "ADMIN_001", "msg": "仅管理员可访问"})


# ═══════════════════════════════════════════════════════════════════
# Capabilities：前端拉取能力清单用
# ═══════════════════════════════════════════════════════════════════
@router.get("/capabilities")
async def list_capabilities(current_user: dict = Depends(get_current_user)):
    _require_admin(current_user)
    return {"code": 200, "data": {"capabilities": KNOWN_CAPABILITIES}}


# ═══════════════════════════════════════════════════════════════════
# Providers CRUD
# ═══════════════════════════════════════════════════════════════════
@router.get("/providers")
async def list_providers(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _require_admin(current_user)
    result = await db.execute(text("""
        SELECT provider_id::text AS provider_id,
               name, kind, base_url, api_key_encrypted, extra_config,
               enabled, last_tested_at, last_test_ok, last_test_error,
               created_at, updated_at
        FROM ai_providers
        ORDER BY name
    """))
    items = []
    for r in result.fetchall():
        plain = decrypt(r.api_key_encrypted or "")
        items.append({
            "provider_id":     r.provider_id,
            "name":            r.name,
            "kind":            r.kind,
            "base_url":        r.base_url,
            "api_key_masked":  mask_secret(plain),
            "has_api_key":     bool(plain),
            "extra_config":    r.extra_config,
            "enabled":         r.enabled,
            "last_tested_at":  r.last_tested_at.isoformat() if r.last_tested_at else None,
            "last_test_ok":    r.last_test_ok,
            "last_test_error": r.last_test_error,
            "created_at":      r.created_at.isoformat() if r.created_at else None,
            "updated_at":      r.updated_at.isoformat() if r.updated_at else None,
        })
    return {"code": 200, "data": {"providers": items}}


@router.post("/providers")
async def create_provider(
    req: ProviderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _require_admin(current_user)
    enc = encrypt(req.api_key) if req.api_key else ""
    try:
        result = await db.execute(text("""
            INSERT INTO ai_providers
              (name, kind, base_url, api_key_encrypted, extra_config, enabled)
            VALUES
              (:name, :kind, :base_url, :key, CAST(:extra AS jsonb), :enabled)
            RETURNING provider_id::text
        """), {
            "name": req.name, "kind": req.kind, "base_url": req.base_url,
            "key": enc,
            "extra": json.dumps(req.extra_config),
            "enabled": req.enabled,
        })
        pid = result.scalar_one()
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(400, detail={"code": "AI_P01",
                                         "msg": f"Provider 名称已存在：{req.name}"})
    await get_llm_gateway().reload()
    logger.info("Provider created", provider_id=pid, name=req.name, kind=req.kind)
    return {"code": 200, "data": {"provider_id": pid}}


@router.post("/providers/{provider_id}")
async def update_provider(
    provider_id: str,
    req: ProviderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _require_admin(current_user)
    fields = []
    params = {"pid": provider_id}
    if req.name is not None:
        fields.append("name = :name"); params["name"] = req.name
    if req.kind is not None:
        fields.append("kind = :kind"); params["kind"] = req.kind
    if req.base_url is not None:
        fields.append("base_url = :url"); params["url"] = req.base_url
    if req.api_key is not None:
        fields.append("api_key_encrypted = :key")
        params["key"] = encrypt(req.api_key) if req.api_key else ""
    if req.extra_config is not None:
        fields.append("extra_config = CAST(:extra AS jsonb)")
        params["extra"] = json.dumps(req.extra_config)
    if req.enabled is not None:
        fields.append("enabled = :enabled"); params["enabled"] = req.enabled
    if not fields:
        return {"code": 200, "data": {"message": "nothing to update"}}
    fields.append("updated_at = now()")
    try:
        await db.execute(text(
            f"UPDATE ai_providers SET {', '.join(fields)} "
            f"WHERE provider_id = CAST(:pid AS uuid)"
        ), params)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(400, detail={"code": "AI_P01", "msg": "Provider 名称冲突"})
    await get_llm_gateway().reload()
    return {"code": 200, "data": {"provider_id": provider_id}}


@router.delete("/providers/{provider_id}")
async def delete_provider(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _require_admin(current_user)
    row = await db.execute(text("""
        SELECT count(*) FROM ai_capability_bindings
        WHERE provider_id = CAST(:pid AS uuid)
    """), {"pid": provider_id})
    cnt = row.scalar_one()
    if cnt > 0:
        raise HTTPException(400, detail={
            "code": "AI_P02",
            "msg": f"该 Provider 被 {cnt} 个能力绑定使用，请先在「能力路由」页解绑",
        })
    await db.execute(text(
        "DELETE FROM ai_providers WHERE provider_id = CAST(:pid AS uuid)"
    ), {"pid": provider_id})
    await db.commit()
    await get_llm_gateway().reload()
    return {"code": 200, "data": {"deleted": True}}


# ═══════════════════════════════════════════════════════════════════
# Bindings CRUD（capability ↔ provider 路由）
# ═══════════════════════════════════════════════════════════════════
@router.get("/bindings")
async def list_bindings(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _require_admin(current_user)
    result = await db.execute(text("""
        SELECT b.binding_id::text  AS binding_id,
               b.capability,
               b.provider_id::text AS provider_id,
               b.model_name,
               b.priority,
               b.params,
               b.enabled,
               p.name AS provider_name,
               p.kind AS provider_kind,
               p.base_url AS provider_base_url
        FROM ai_capability_bindings b
        JOIN ai_providers p ON p.provider_id = b.provider_id
        ORDER BY b.capability, b.priority
    """))
    items = [dict(r._mapping) for r in result.fetchall()]
    return {"code": 200, "data": {"bindings": items}}


@router.post("/bindings")
async def upsert_binding(
    req: BindingUpsert,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _require_admin(current_user)
    if req.capability not in CAPABILITY_KEYS:
        raise HTTPException(400, detail={
            "code": "AI_B01",
            "msg": f"未知 capability: {req.capability}。请从 /capabilities 接口获取合法值。",
        })
    try:
        await db.execute(text("""
            INSERT INTO ai_capability_bindings
              (capability, provider_id, model_name, priority, params, enabled)
            VALUES
              (:cap, CAST(:pid AS uuid), :model, :prio, CAST(:params AS jsonb), :enabled)
            ON CONFLICT (capability, priority)
            DO UPDATE SET
                provider_id = EXCLUDED.provider_id,
                model_name  = EXCLUDED.model_name,
                params      = EXCLUDED.params,
                enabled     = EXCLUDED.enabled,
                updated_at  = now()
        """), {
            "cap": req.capability,
            "pid": req.provider_id,
            "model": req.model_name,
            "prio": req.priority,
            "params": json.dumps(req.params),
            "enabled": req.enabled,
        })
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(400, detail={"code": "AI_B02", "msg": str(exc.orig)[:200]})
    await get_llm_gateway().reload()
    return {"code": 200, "data": {"ok": True}}


@router.delete("/bindings/{binding_id}")
async def delete_binding(
    binding_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _require_admin(current_user)
    await db.execute(text(
        "DELETE FROM ai_capability_bindings WHERE binding_id = CAST(:bid AS uuid)"
    ), {"bid": binding_id})
    await db.commit()
    await get_llm_gateway().reload()
    return {"code": 200, "data": {"deleted": True}}


# ═══════════════════════════════════════════════════════════════════
# 连接测试（chat / embedding 两种 kind）
# ═══════════════════════════════════════════════════════════════════

async def _test_embedding_raw(base_url: str, api_key: str | None, model_name: str) -> dict:
    """
    用裸 HTTP 请求测试 embedding 端点，兼容 OpenAI 和 llama.cpp/ollama 两种响应格式。

    OpenAI 格式: {"data": [{"embedding": [...], "index": 0, "object": "embedding"}], ...}
    llama.cpp/ollama 格式: {"embedding": [...]}

    返回 {"latency_ms": int, "dimension": int, "sample": [float, ...]}
    """
    import httpx

    base = base_url.rstrip("/")
    # 尝试 /v1/embeddings 和 /embeddings 两种路径
    urls_to_try = [f"{base}/v1/embeddings", f"{base}/embeddings"]

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {"model": model_name, "input": ["测试文本 / embedding probe"]}

    last_error = None
    for url in urls_to_try:
        try:
            t0 = _time.monotonic()
            async with httpx.AsyncClient(timeout=20.0) as http_client:
                resp = await http_client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                latency_ms = int((_time.monotonic() - t0) * 1000)

                # 尝试 OpenAI 格式
                if "data" in data and isinstance(data["data"], list) and len(data["data"]) > 0:
                    item = data["data"][0]
                    vec = item.get("embedding", []) if isinstance(item, dict) else []
                    if vec and isinstance(vec, list):
                        return {"latency_ms": latency_ms, "dimension": len(vec),
                                "sample": vec[:5]}

                # 尝试 llama.cpp/ollama 格式
                if "embedding" in data and isinstance(data["embedding"], list):
                    vec = data["embedding"]
                    return {"latency_ms": latency_ms, "dimension": len(vec),
                            "sample": vec[:5]}

                # 响应格式无法识别
                raise ValueError(f"无法识别的 embedding 响应格式，前 200 字符: {json.dumps(data)[:200]}")
        except Exception as exc:
            last_error = exc
            continue

    raise last_error or RuntimeError("所有 embedding 端点均不可达")


async def _test_reranker_raw(base_url: str, api_key: str | None, model_name: str) -> dict:
    """
    用裸 HTTP 请求测试 reranker 端点，兼容 vLLM/TEI 标准格式和 Jina 格式。

    标准格式: {"results": [{"index": 0, "relevance_score": 0.95}, ...]}
    Jina 格式: {"results": [{"index": 0, "relevance_score": 0.95}], ...}  相同
    降级格式: {"scores": [0.95, 0.3, ...]}

    返回 {"latency_ms": int, "top_score": float, "doc_count": int}
    """
    import httpx

    base = base_url.rstrip("/")
    urls_to_try = [f"{base}/reranking", f"{base}/v1/reranking", f"{base}/v1/rerank", f"{base}/rerank"]

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    test_docs = [
        "SQL注入是一种通过恶意SQL语句攻击数据库的技术",
        "今天天气不错适合出去散步",
        "参数化查询是防御SQL注入最有效的方法之一",
    ]
    payload = {"query": "如何防止SQL注入", "documents": test_docs}

    url_errors: list[str] = []
    for url in urls_to_try:
        try:
            t0 = _time.monotonic()
            async with httpx.AsyncClient(timeout=20.0) as http_client:
                resp = await http_client.post(url, json=payload, headers=headers)
                if resp.status_code == 404:
                    url_errors.append(f"{url} → 404")
                    continue
                if resp.status_code != 200:
                    body = resp.text[:300]
                    url_errors.append(f"{url} → {resp.status_code}: {body}")
                    continue
                data = resp.json()
                latency_ms = int((_time.monotonic() - t0) * 1000)

                # 标准格式: {"results": [{"index": 0, "relevance_score": 0.95}, ...]}
                if "results" in data and isinstance(data["results"], list):
                    results = data["results"]
                    if results:
                        top = results[0]
                        top_score = float(top.get("relevance_score", top.get("score", 0)))
                        return {
                            "latency_ms": latency_ms,
                            "top_score": round(top_score, 4),
                            "doc_count": len(results),
                        }

                # 降级格式: {"scores": [0.95, 0.3, ...]}  或 纯数组
                if "scores" in data and isinstance(data["scores"], list):
                    scores = data["scores"]
                    return {
                        "latency_ms": latency_ms,
                        "top_score": round(float(scores[0]), 4) if scores else 0,
                        "doc_count": len(scores),
                    }

                raise ValueError(f"无法识别的 rerank 响应格式，前 200 字符: {json.dumps(data)[:200]}")
        except Exception as exc:
            url_errors.append(f"{url} → {exc}")
            continue

    detail = "; ".join(url_errors) if url_errors else "无端点可达"
    raise RuntimeError(f"所有 rerank 端点均不可达: {detail}")


@router.post("/test")
async def test_provider(
    req: TestProviderRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    测试 provider 连通性。
      - chat kind：发 POST /v1/chat/completions 一个 "ping"，返回延迟和首字符串
      - embedding kind：发 POST /v1/embeddings 一个短文本，返回延迟和探测到的维度
    对 embedding，会同时返回 current_dimension（当前 schema 配置）和 dimension_mismatch 标记，
    前端据此提示是否需要执行破坏性迁移。
    """
    _require_admin(current_user)

    # 解析 provider 信息
    base_url, api_key = req.base_url, req.api_key
    if req.provider_id:
        row = await db.execute(text("""
            SELECT base_url, api_key_encrypted FROM ai_providers
            WHERE provider_id = CAST(:pid AS uuid)
        """), {"pid": req.provider_id})
        r = row.fetchone()
        if not r:
            raise HTTPException(404, detail={"code": "AI_T01", "msg": "Provider not found"})
        base_url = r.base_url
        api_key  = decrypt(r.api_key_encrypted or "")
    if not base_url:
        raise HTTPException(400, detail={"code": "AI_T02", "msg": "base_url 不能为空"})

    client = AsyncOpenAI(
        api_key  = api_key or "not-set",
        base_url = base_url,
        timeout  = 20.0,
    )
    t0 = _time.monotonic()
    try:
        if req.capability_kind == "chat":
            resp = await client.chat.completions.create(
                model       = req.model_name,
                messages    = [{"role": "user", "content": "ping"}],
                max_tokens  = 5,
                temperature = 0.0,
            )
            latency = int((_time.monotonic() - t0) * 1000)
            content = resp.choices[0].message.content if resp.choices else ""
            result = {
                "ok": True,
                "latency_ms": latency,
                "sample": (content or "")[:200],
                "capability_kind": "chat",
            }
        elif req.capability_kind == "reranker":
            resp = await _test_reranker_raw(base_url, api_key, req.model_name)
            latency = resp["latency_ms"]
            top_score = resp["top_score"]
            result = {
                "ok": True,
                "latency_ms": latency,
                "top_score": top_score,
                "doc_count": resp["doc_count"],
                "sample": (
                    f"reranker 测试：3 篇候选文档中与查询相关性最高得分 {top_score}。"
                    f"预期：文档1,3 关于 SQL 注入应得分高，文档2 无关应得分低。"
                ),
                "capability_kind": "reranker",
            }
        else:  # embedding
            resp = await _test_embedding_raw(base_url, api_key, req.model_name)
            latency = resp["latency_ms"]
            dim = resp["dimension"]
            sample_vec = resp.get("sample", [])

            cur = await db.execute(text(
                "SELECT config_value FROM system_configs WHERE config_key='embedding.dimension'"
            ))
            cur_row = cur.fetchone()
            cur_dim = int(cur_row.config_value) if cur_row else 1536

            _mismatch = dim != cur_dim
            _suggestion = None
            if _mismatch:
                _idx_note = (
                    "注意：pgvector 的 ivfflat/hnsw 索引限制为 2000 维，"
                    f"{dim} 维将使用暴力搜索。"
                ) if dim > 2000 else ""
                _suggestion = {
                    "action": "migrate_dimension",
                    "message": (
                        f"检测到模型输出 {dim} 维向量，当前 schema 配置为 {cur_dim} 维。"
                        f"需要执行维度迁移。{_idx_note}"
                    ),
                    "payload": {"new_dim": dim, "confirm": True},
                }

            result = {
                "ok": True,
                "latency_ms": latency,
                "detected_dimension": dim,
                "current_dimension":  cur_dim,
                "dimension_mismatch": _mismatch,
                "suggested_action":   _suggestion,
                "capability_kind": "embedding",
            }

        if req.provider_id:
            await db.execute(text("""
                UPDATE ai_providers
                SET last_tested_at = now(),
                    last_test_ok = true,
                    last_test_error = NULL
                WHERE provider_id = CAST(:pid AS uuid)
            """), {"pid": req.provider_id})
            await db.commit()
        return {"code": 200, "data": result}

    except Exception as exc:
        err_msg = str(exc)[:500]
        logger.warning("Provider test failed",
                       kind=req.capability_kind, model=req.model_name, error=err_msg)
        if req.provider_id:
            try:
                await db.execute(text("""
                    UPDATE ai_providers
                    SET last_tested_at = now(),
                        last_test_ok = false,
                        last_test_error = :err
                    WHERE provider_id = CAST(:pid AS uuid)
                """), {"pid": req.provider_id, "err": err_msg})
                await db.commit()
            except Exception:
                await db.rollback()
        return {"code": 200, "data": {"ok": False, "error": err_msg}}


# ═══════════════════════════════════════════════════════════════════
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
# Embedding 维度迁移（破坏性）
# ═══════════════════════════════════════════════════════════════════
@router.post("/embedding/migrate-dimension")
async def migrate_embedding_dimension(
    req: DimensionMigrateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    ⚠️ 破坏性操作：将 knowledge_entities.embedding 和 document_chunks.embedding
    的 vector(N) 维度改为 new_dim。所有现有 embedding 会被重置为 NULL，索引重建。

    必须传 confirm=true。
    """
    _require_admin(current_user)
    if not req.confirm:
        raise HTTPException(400, detail={
            "code": "AI_M01",
            "msg": "必须设置 confirm=true 才能执行维度迁移",
        })

    new_dim = req.new_dim
    logger.warning("Starting embedding dimension migration", new_dim=new_dim)

    cur = await db.execute(text(
        "SELECT config_value FROM system_configs WHERE config_key='embedding.dimension'"
    ))
    cur_row = cur.fetchone()
    cur_dim = int(cur_row.config_value) if cur_row else 1536
    if cur_dim == new_dim:
        return {"code": 200, "data": {
            "message": f"维度未变化（{cur_dim}），无需迁移",
            "old_dim": cur_dim, "new_dim": new_dim,
        }}

    # 基础迁移语句（清空 embedding + 改列类型）
    migration_statements = [
        "UPDATE knowledge_entities SET embedding = NULL",
        "UPDATE document_chunks    SET embedding = NULL",
        "DROP INDEX IF EXISTS idx_entity_embedding",
        "DROP INDEX IF EXISTS idx_chunks_embedding",
        f"ALTER TABLE knowledge_entities ALTER COLUMN embedding TYPE vector({new_dim})",
        f"ALTER TABLE document_chunks    ALTER COLUMN embedding TYPE vector({new_dim})",
    ]
    try:
        for stmt in migration_statements:
            await db.execute(text(stmt))
        # 更新 system_configs 记录
        await db.execute(text("""
            UPDATE system_configs
            SET config_value = :dim, updated_at = now()
            WHERE config_key = 'embedding.dimension'
        """), {"dim": str(new_dim)})
        await db.execute(text("""
            INSERT INTO system_configs (config_key, config_value, description)
            SELECT 'embedding.dimension', :dim,
                   '当前 embedding 向量维度；由 admin AI 配置自动维护'
            WHERE NOT EXISTS (
                SELECT 1 FROM system_configs WHERE config_key = 'embedding.dimension'
            )
        """), {"dim": str(new_dim)})
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("Embedding dimension migration failed",
                     old_dim=cur_dim, new_dim=new_dim, error=str(exc))
        raise HTTPException(500, detail={
            "code": "AI_M02",
            "msg": f"迁移失败：{str(exc)[:300]}",
        })

    # ── 索引创建：按 ivfflat → hnsw 顺序尝试，均失败则降级为暴力搜索 ──
    index_sql = (
        "CREATE INDEX {name} ON {table} "
        "USING {method} (embedding vector_cosine_ops) WITH (lists=16)"
    )
    _warnings: list[str] = []

    for tbl, idx_name in [("knowledge_entities", "idx_entity_embedding"),
                            ("document_chunks", "idx_chunks_embedding")]:
        idx_created = False
        for method in ("ivfflat", "hnsw"):
            try:
                await db.execute(text(
                    index_sql.format(name=idx_name, table=tbl, method=method)
                ))
                await db.commit()
                idx_created = True
                break
            except Exception as _e:
                _msg = str(_e)
                # 维度超限是硬错误，换 hnsw 也没用则直接放弃
                if "cannot have more than" in _msg.lower() or "dimensions" in _msg.lower():
                    continue
                # 其他错误也尝试下一个方案
                logger.debug("Index creation attempt failed",
                             table=tbl, method=method, error=_msg)
        if not idx_created:
            _warnings.append(
                f"{tbl} 的 {new_dim} 维 embedding 索引创建失败"
                f"（ivfflat/hnsw 均不支持），将使用暴力搜索"
            )

    logger.warning("Embedding dimension migration completed",
                   old_dim=cur_dim, new_dim=new_dim)
    _msg = (f"维度已从 {cur_dim} 迁移到 {new_dim}。"
            "所有现有 embedding 已重置为 NULL，请在 Phase 1 批量任务完成后重新生成。")
    if _warnings:
        _msg += " " + "；".join(_warnings)
    return {"code": 200, "data": {
        "message": _msg,
        "old_dim": cur_dim,
        "new_dim": new_dim,
    }}

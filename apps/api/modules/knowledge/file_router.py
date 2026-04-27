"""
apps/api/modules/knowledge/file_router.py
Block A：文件上传接口

安全审计 2026-04-27：添加文件名消毒函数，移除路径穿越字符
功能：SHA-256 去重、MinIO 存储、触发 file_uploaded 事件
依赖：AsyncMinIOClient（C3）、EventBus
"""
import hashlib
import re
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlparse

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.config import CONFIG
from apps.api.core.db import get_db
from apps.api.core.events import get_event_bus
from apps.api.core.storage import get_minio_client
from apps.api.modules.auth.router import get_current_user

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api", tags=["files"])

ALLOWED_TYPES = {
    "application/pdf",
    "text/markdown",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
ALLOWED_SPACE_TYPES = {"global", "course", "personal"}
MAX_SIZE_BYTES = int(100 * 1024 * 1024)  # 100MB
# 安全审计 2026-04-27：文件名安全性约束
_MAX_FILENAME_LEN = 255


def _sanitize_filename(filename: str | None) -> str:
    """消毒文件名：移除路径穿越字符，限制长度和字符集"""
    if not filename or not filename.strip():
        return "untitled"
    # 移除路径分隔符
    sanitized = filename.replace("\\", "/")
    # 移除连续的 ../
    while "../" in sanitized:
        sanitized = sanitized.replace("../", "_")
    # 只保留文件名部分（去除任何路径前缀）
    sanitized = Path(sanitized).name
    # 移除所有不可见字符和控制字符
    sanitized = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', sanitized)
    # 移除 < > : " | ? * 等特殊字符
    sanitized = re.sub(r'[<>:"|?*]', '_', sanitized)
    # 截断长度
    if len(sanitized) > _MAX_FILENAME_LEN:
        name, ext = Path(sanitized).stem, Path(sanitized).suffix
        max_name_len = _MAX_FILENAME_LEN - len(ext) - 3
        sanitized = name[:max_name_len] + "..." + ext
    return sanitized.strip() or "untitled"


def _normalize_domain_tag(domain_tag: str | None) -> str | None:
    if domain_tag is None:
        return None
    normalized = " ".join(domain_tag.strip().split()).lower()
    return normalized or None


def _extract_minio_key(storage_url: str) -> str:
    parsed = urlparse(storage_url)
    path = parsed.path.lstrip("/")
    bucket_prefix = f"{CONFIG.minio.bucket}/"
    if path.startswith(bucket_prefix):
        return path[len(bucket_prefix):]
    if "/" in path:
        return path.split("/", 1)[1]
    return path


async def _ensure_knowledge_space(
    db: AsyncSession,
    *,
    space_type: str,
    owner_id: str,
    domain_tag: str | None,
    space_id: str | None,
) -> str | None:
    normalized_domain = _normalize_domain_tag(domain_tag)

    if space_id:
        existing_by_id = await db.execute(
            text(
                """
                    SELECT space_id::text
                    FROM knowledge_spaces
                    WHERE space_id::text = :space_id
                    LIMIT 1
                """
            ),
            {"space_id": space_id},
        )
        row = existing_by_id.fetchone()
        if row:
            return str(row.space_id)

    if not normalized_domain:
        return space_id

    if space_type == "global":
        result = await db.execute(
            text(
                """
                    SELECT space_id::text
                    FROM knowledge_spaces
                    WHERE space_type = :space_type
                      AND name = :name
                    LIMIT 1
                """
            ),
            {"space_type": space_type, "name": normalized_domain},
        )
    else:
        result = await db.execute(
            text(
                """
                    SELECT space_id::text
                    FROM knowledge_spaces
                    WHERE space_type = :space_type
                      AND owner_id::text = :owner_id
                      AND name = :name
                    LIMIT 1
                """
            ),
            {
                "space_type": space_type,
                "owner_id": owner_id,
                "name": normalized_domain,
            },
        )

    row = result.fetchone()
    if row:
        return str(row.space_id)

    from apps.api.modules.space.service import SpaceService
    service = SpaceService(db)
    data = await service.create_space(
        owner_id, normalized_domain, space_type,
        f"Auto-created from upload: {normalized_domain}"
    )
    return data["space_id"]


@router.post("/files/upload", status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    space_type: str = Form(default="personal"),
    space_id: str | None = Form(default=None),
    domain_tag: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """
    文件上传接口。
    - SHA-256 去重：相同文件复用底层 files 记录，但仍可按新空间复用/重排队
    - domain_tag：优先映射到 knowledge_spaces，供后续抽取反推领域
    - C3：通过 AsyncMinIOClient 上传，不阻塞事件循环
    - 上传成功后发布 file_uploaded 事件触发文档解析链路
    """
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail={"code": "DOC_002", "msg": f"Unsupported file type: {file.content_type}"},
        )

    if space_type not in ALLOWED_SPACE_TYPES:
        raise HTTPException(
            status_code=400,
            detail={"code": "DOC_003", "msg": f"Unsupported space_type: {space_type}"},
        )

    if space_type == "global":
        user_roles = set(current_user.get("roles", []))
        if not user_roles.intersection({"admin", "knowledge_reviewer"}):
            raise HTTPException(
                status_code=403,
                detail={"code": "AUTH_002", "msg": "Insufficient permissions for global knowledge space"},
            )

    # 安全审计 2026-04-27：消毒文件名，防止路径穿越和特殊字符注入
    safe_filename = _sanitize_filename(file.filename)

    normalized_domain_tag = _normalize_domain_tag(domain_tag)

    content = await file.read()
    if len(content) > MAX_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"code": "DOC_001", "msg": "File too large (max 100MB)"},
        )

    effective_space_id = await _ensure_knowledge_space(
        db,
        space_type=space_type,
        owner_id=current_user["user_id"],
        domain_tag=normalized_domain_tag,
        space_id=space_id,
    )

    file_hash = hashlib.sha256(content).hexdigest()
    duplicate_result = await db.execute(
        text(
            """
                SELECT file_id::text, file_name, storage_url
                FROM files
                WHERE file_hash = :hash
                LIMIT 1
            """
        ),
        {"hash": file_hash},
    )
    existing = duplicate_result.fetchone()
    if existing:
        existing_doc_result = await db.execute(
            text(
                """
                    SELECT document_id::text, document_status
                    FROM documents
                    WHERE file_id::text = :file_id
                      AND owner_id::text = :owner_id
                      AND space_type = :space_type
                      AND COALESCE(space_id::text, '') = COALESCE(:space_id, '')
                    ORDER BY created_at DESC
                    LIMIT 1
                """
            ),
            {
                "file_id": str(existing.file_id),
                "owner_id": current_user["user_id"],
                "space_type": space_type,
                "space_id": effective_space_id,
            },
        )
        existing_doc = existing_doc_result.fetchone()
        if existing_doc:
            await db.commit()
            logger.info(
                "Duplicate file reused existing document",
                file_hash=file_hash,
                file_id=str(existing.file_id),
                document_id=str(existing_doc.document_id),
                space_type=space_type,
                space_id=effective_space_id,
            )
            return {
                "code": 200,
                "msg": "success",
                "data": {
                    "file_id": str(existing.file_id),
                    "document_id": str(existing_doc.document_id),
                    "space_id": effective_space_id,
                    "domain_tag": normalized_domain_tag,
                    "is_duplicate": True,
                    "reused_document": True,
                    "requeued": False,
                },
            }

        # G-4: 跨 space 不阻止，允许在新领域重新处理同一文件
        await db.commit()

        # 同步创建 documents 记录，确保上传后立即可见
        document_id = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO documents
                  (document_id, file_id, title, source_type, document_status,
                   space_type, space_id, owner_id)
                VALUES
                  (:doc_id, :file_id, :title, 'upload', 'uploaded',
                   :space_type, :space_id, :owner_id)
            """),
            {
                "doc_id": document_id,
                "file_id": str(existing.file_id),
                "title": safe_filename or existing.file_name,
                "space_type": space_type,
                "space_id": effective_space_id,
                "owner_id": current_user["user_id"],
            },
        )
        await db.commit()

        minio_key = _extract_minio_key(existing.storage_url)
        event_bus = get_event_bus()
        await event_bus.publish(
            "file_uploaded",
            {
                "file_id": str(existing.file_id),
                "file_name": safe_filename or existing.file_name,
                "minio_key": minio_key,
                "space_type": space_type,
                "space_id": effective_space_id,
                "owner_id": current_user["user_id"],
                "document_id": document_id,
            },
        )

        logger.info(
            "Duplicate file requeued",
            file_hash=file_hash,
            file_id=str(existing.file_id),
            document_id=document_id,
            space_type=space_type,
            space_id=effective_space_id,
        )
        return {
            "code": 202,
            "msg": "success",
            "data": {
                "file_id": str(existing.file_id),
                "document_id": document_id,
                "space_id": effective_space_id,
                "domain_tag": normalized_domain_tag,
                "is_duplicate": True,
                "reused_document": False,
                "requeued": True,
            },
        }

    with tempfile.NamedTemporaryFile(
        suffix=Path(safe_filename or "upload").suffix,
        delete=False,
    ) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        file_id = str(uuid.uuid4())
        minio = get_minio_client()
        minio_key = f"files/{file_id}/{safe_filename}"
        storage_url = await minio.upload(minio_key, tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    await db.execute(
        text(
            """
                INSERT INTO files
                  (file_id, file_name, file_type, file_size, file_hash, storage_url, uploaded_by)
                VALUES
                  (:file_id, :file_name, :file_type, :file_size, :file_hash, :storage_url, :uploaded_by)
            """
        ),
        {
            "file_id": file_id,
            "file_name": safe_filename,
            "file_type": file.content_type,
            "file_size": len(content),
            "file_hash": file_hash,
            "storage_url": storage_url,
            "uploaded_by": current_user["user_id"],
        },
    )
    await db.commit()

    # 同步创建 documents 记录，确保上传后立即可见（ingest worker 异步更新状态）
    document_id = str(uuid.uuid4())
    await db.execute(
        text(
            """
                INSERT INTO documents
                  (document_id, file_id, title, source_type, document_status,
                   space_type, space_id, owner_id)
                VALUES
                  (:doc_id, :file_id, :title, 'upload', 'uploaded',
                   :space_type, :space_id, :owner_id)
            """
        ),
        {
            "doc_id": document_id,
            "file_id": file_id,
            "title": safe_filename,
            "space_type": space_type,
            "space_id": effective_space_id,
            "owner_id": current_user["user_id"],
        },
    )
    await db.commit()

    event_bus = get_event_bus()
    await event_bus.publish(
        "file_uploaded",
        {
            "file_id": file_id,
            "file_name": safe_filename,
            "minio_key": minio_key,
            "space_type": space_type,
            "space_id": effective_space_id,
            "owner_id": current_user["user_id"],
            "document_id": document_id,
        },
    )

    logger.info(
        "File uploaded",
        file_id=file_id,
        document_id=document_id,
        file_name=safe_filename,
        space_type=space_type,
        space_id=effective_space_id,
    )
    return {
        "code": 201,
        "msg": "success",
        "data": {
            "file_id": file_id,
            "document_id": document_id,
            "file_name": safe_filename,
            "file_size": len(content),
            "storage_url": storage_url,
            "space_id": effective_space_id,
            "domain_tag": normalized_domain_tag,
            "is_duplicate": False,
        },
    }


@router.delete("/files/documents/{document_id}")
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """删除文档及其所有关联数据（chunks、知识点链接、审核记录）。"""
    # 验证归属
    result = await db.execute(
        text("SELECT owner_id, document_status FROM documents WHERE document_id = CAST(:did AS uuid)"),
        {"did": document_id}
    )
    row = result.fetchone()
    if not row:
        return {"code": 404, "msg": "not found", "data": {}}
    is_admin = "admin" in current_user.get("roles", [])
    if str(row.owner_id) != current_user["user_id"] and not is_admin:
        return {"code": 403, "msg": "forbidden", "data": {}}

    # 删除关联数据
    await db.execute(
        text("DELETE FROM extract_audit WHERE chunk_id IN "
             "(SELECT chunk_id FROM document_chunks WHERE document_id = CAST(:did AS uuid))"),
        {"did": document_id}
    )
    await db.execute(
        text("DELETE FROM document_chunks WHERE document_id = CAST(:did AS uuid)"),
        {"did": document_id}
    )
    await db.execute(
        text("DELETE FROM documents WHERE document_id = CAST(:did AS uuid)"),
        {"did": document_id}
    )
    await db.commit()
    return {"code": 200, "msg": "success", "data": {}}


@router.post("/files/documents/{document_id}/retry")
async def retry_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """对失败文档重新触发解析流程。"""
    result = await db.execute(
        text("""
            SELECT d.owner_id, d.document_status, d.space_type, d.space_id,
                   f.file_name, f.storage_url,
                   d.file_id::text AS file_id
            FROM documents d
            LEFT JOIN files f ON f.file_id = d.file_id
            WHERE d.document_id = CAST(:did AS uuid)
        """),
        {"did": document_id}
    )
    row = result.fetchone()
    if not row:
        return {"code": 404, "msg": "not found", "data": {}}
    if str(row.owner_id) != current_user["user_id"] and "admin" not in current_user.get("roles", []):
        return {"code": 403, "msg": "forbidden", "data": {}}
    if row.document_status not in ("failed", "extracted"):
        return {"code": 400, "msg": "只有失败状态的文档可以重试", "data": {}}

    # 重置状态
    await db.execute(
        text("UPDATE documents SET document_status='uploaded', updated_at=NOW() "
             "WHERE document_id=CAST(:did AS uuid)"),
        {"did": document_id}
    )
    await db.commit()

    # 重新发布 file_uploaded 事件
    from apps.api.core.storage import get_minio_client
    minio_key = row.storage_url.split("/", 3)[-1] if row.storage_url else ""
    event_bus = get_event_bus()
    await event_bus.publish("file_uploaded", {
        "file_id":    row.file_id,
        "file_name":  row.file_name or "",
        "minio_key":  minio_key,
        "space_type": row.space_type,
        "space_id":   str(row.space_id) if row.space_id else None,
        "owner_id":   current_user["user_id"],
    })

    return {"code": 200, "msg": "success", "data": {}}


@router.get("/files/documents/{document_id}/view")
async def view_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """
    返回文档阅读信息：
    - PDF / Word → 预签名 URL（前端新标签打开）
    - Markdown / TXT → 纯文本内容（前端渲染）
    """
    result = await db.execute(
        text("""
            SELECT d.owner_id, f.storage_url, f.file_type, f.file_name
            FROM documents d
            LEFT JOIN files f ON f.file_id = d.file_id
            WHERE d.document_id = CAST(:did AS uuid)
        """),
        {"did": document_id}
    )
    row = result.fetchone()
    if not row:
        return {"code": 404, "msg": "not found", "data": {}}
    if str(row.owner_id) != current_user["user_id"] and "admin" not in current_user.get("roles", []):
        return {"code": 403, "msg": "forbidden", "data": {}}

    # storage_url 格式: http://minio:9000/{bucket}/{key}，去掉前三段得到 key
    raw_key = row.storage_url.split("/", 3)[-1] if row.storage_url else ""
    from apps.api.core.config import CONFIG
    bucket_prefix = CONFIG.minio.bucket + "/"
    minio_key = raw_key[len(bucket_prefix):] if raw_key.startswith(bucket_prefix) else raw_key
    file_name = row.file_name or ""
    suffix = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""

    minio = get_minio_client()

    # Markdown / TXT → 返回文本内容
    if suffix in ("md", "txt"):
        content_bytes = await minio.download_bytes(minio_key)
        import chardet
        enc = chardet.detect(content_bytes).get("encoding") or "utf-8"
        content = content_bytes.decode(enc, errors="replace")
        return {"code": 200, "msg": "success", "data": {
            "mode": "text",
            "file_name": file_name,
            "suffix": suffix,
            "content": content,
        }}

    # PDF / Word / 其他 → 预签名 URL
    presign_url = await minio.presign(minio_key, expires=3600)
    # 把 Docker 内网地址替换为外部可访问地址（通过 MINIO_PUBLIC_ENDPOINT 配置）
    import os as _os
    _public_endpoint = _os.environ.get("MINIO_PUBLIC_ENDPOINT", "http://localhost:9000")
    presign_url = presign_url.replace('http://minio:9000', _public_endpoint)
    return {"code": 200, "msg": "success", "data": {
        "mode": "url",
        "file_name": file_name,
        "suffix": suffix,
        "url": presign_url,
    }}

"""
apps/api/modules/knowledge/file_router.py
Block A：文件上传接口

功能：SHA-256 去重、MinIO 存储、触发 file_uploaded 事件
依赖：AsyncMinIOClient（C3）、EventBus
"""
import hashlib
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


def _normalize_domain_tag(domain_tag: str | None) -> str | None:
    if domain_tag is None:
        return None
    normalized = " ".join(domain_tag.strip().split())
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

    new_space_id = str(uuid.uuid4())
    await db.execute(
        text(
            """
                INSERT INTO knowledge_spaces (space_id, space_type, owner_id, name, description)
                VALUES (:space_id, :space_type, :owner_id, :name, :description)
            """
        ),
        {
            "space_id": new_space_id,
            "space_type": space_type,
            "owner_id": owner_id,
            "name": normalized_domain,
            "description": f"Auto-created from upload: {normalized_domain}",
        },
    )
    return new_space_id


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

        await db.commit()

        minio_key = _extract_minio_key(existing.storage_url)
        event_bus = get_event_bus()
        await event_bus.publish(
            "file_uploaded",
            {
                "file_id": str(existing.file_id),
                "file_name": file.filename or existing.file_name,
                "minio_key": minio_key,
                "space_type": space_type,
                "space_id": effective_space_id,
                "owner_id": current_user["user_id"],
            },
        )

        logger.info(
            "Duplicate file requeued",
            file_hash=file_hash,
            file_id=str(existing.file_id),
            space_type=space_type,
            space_id=effective_space_id,
        )
        return {
            "code": 202,
            "msg": "success",
            "data": {
                "file_id": str(existing.file_id),
                "space_id": effective_space_id,
                "domain_tag": normalized_domain_tag,
                "is_duplicate": True,
                "reused_document": False,
                "requeued": True,
            },
        }

    with tempfile.NamedTemporaryFile(
        suffix=Path(file.filename or "upload").suffix,
        delete=False,
    ) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        file_id = str(uuid.uuid4())
        minio = get_minio_client()
        minio_key = f"files/{file_id}/{file.filename}"
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
            "file_name": file.filename,
            "file_type": file.content_type,
            "file_size": len(content),
            "file_hash": file_hash,
            "storage_url": storage_url,
            "uploaded_by": current_user["user_id"],
        },
    )
    await db.commit()

    event_bus = get_event_bus()
    await event_bus.publish(
        "file_uploaded",
        {
            "file_id": file_id,
            "file_name": file.filename,
            "minio_key": minio_key,
            "space_type": space_type,
            "space_id": effective_space_id,
            "owner_id": current_user["user_id"],
        },
    )

    logger.info(
        "File uploaded",
        file_id=file_id,
        file_name=file.filename,
        space_type=space_type,
        space_id=effective_space_id,
    )
    return {
        "code": 201,
        "msg": "success",
        "data": {
            "file_id": file_id,
            "file_name": file.filename,
            "file_size": len(content),
            "storage_url": storage_url,
            "space_id": effective_space_id,
            "domain_tag": normalized_domain_tag,
            "is_duplicate": False,
        },
    }

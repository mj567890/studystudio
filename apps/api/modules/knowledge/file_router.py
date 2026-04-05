"""
apps/api/modules/knowledge/file_router.py
Block A：文件上传接口

功能：SHA-256 去重、MinIO 存储、触发 file_uploaded 事件
依赖：AsyncMinIOClient（C3）、EventBus
"""
import tempfile
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.db import get_db
from apps.api.core.events import get_event_bus
from apps.api.core.storage import get_minio_client
from apps.api.modules.auth.router import get_current_user

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api", tags=["files"])

ALLOWED_TYPES = {"application/pdf", "text/markdown", "text/plain",
                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
MAX_SIZE_BYTES = int(100 * 1024 * 1024)  # 100MB


@router.post("/files/upload", status_code=201)
async def upload_file(
    file:       UploadFile = File(...),
    space_type: str        = Form(default="personal"),
    space_id:   str | None = Form(default=None),
    db: AsyncSession       = Depends(get_db),
    current_user: dict     = Depends(get_current_user),
) -> dict:
    """
    文件上传接口。
    - SHA-256 去重：已存在相同文件则直接返回 file_id
    - C3：通过 AsyncMinIOClient 上传，不阻塞事件循环
    - 上传成功后发布 file_uploaded 事件触发文档解析链路
    """
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail={"code": "DOC_002", "msg": f"Unsupported file type: {file.content_type}"}
        )

    content = await file.read()
    if len(content) > MAX_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"code": "DOC_001", "msg": "File too large (max 100MB)"}
        )

    # 计算 SHA-256 hash
    import hashlib
    file_hash = hashlib.sha256(content).hexdigest()

    # 去重检查
    result = await db.execute(
        text("SELECT file_id FROM files WHERE file_hash = :hash"),
        {"hash": file_hash}
    )
    existing = result.fetchone()
    if existing:
        logger.info("Duplicate file detected", file_hash=file_hash)
        return {
            "code":    200,
            "msg":     "success",
            "data":    {"file_id": str(existing.file_id), "is_duplicate": True},
        }

    # 保存到临时文件后上传 MinIO
    with tempfile.NamedTemporaryFile(
        suffix=Path(file.filename or "upload").suffix, delete=False
    ) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        import uuid
        file_id  = str(uuid.uuid4())
        minio    = get_minio_client()
        minio_key = f"files/{file_id}/{file.filename}"
        storage_url = await minio.upload(minio_key, tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    # 写入数据库
    await db.execute(
        text("""
            INSERT INTO files (file_id, file_name, file_type, file_size, file_hash, storage_url, uploaded_by)
            VALUES (:file_id, :file_name, :file_type, :file_size, :file_hash, :storage_url, :uploaded_by)
        """),
        {
            "file_id":      file_id,
            "file_name":    file.filename,
            "file_type":    file.content_type,
            "file_size":    len(content),
            "file_hash":    file_hash,
            "storage_url":  storage_url,
            "uploaded_by":  current_user["user_id"],
        }
    )
    await db.commit()

    # 发布 file_uploaded 事件，触发文档解析
    event_bus = get_event_bus()
    await event_bus.publish("file_uploaded", {
        "file_id":    file_id,
        "file_name":  file.filename,
        "minio_key":  minio_key,
        "space_type": space_type,
        "space_id":   space_id,
        "owner_id":   current_user["user_id"],
    })

    logger.info("File uploaded", file_id=file_id, file_name=file.filename)
    return {
        "code": 201,
        "msg":  "success",
        "data": {
            "file_id":      file_id,
            "file_name":    file.filename,
            "file_size":    len(content),
            "storage_url":  storage_url,
            "is_duplicate": False,
        }
    }

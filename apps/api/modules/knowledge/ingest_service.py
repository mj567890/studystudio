"""
apps/api/modules/knowledge/ingest_service.py
Block B：文档接入与解析服务

功能：文档解析、文本切分、chunk 入库、发布 document_parsed 事件
V2.6 R2：截断前先记录原始分块数
V2.6 C3：通过 AsyncMinIOClient 下载文件
"""
import tempfile
import uuid
from pathlib import Path

import chardet
import structlog
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.config import CONFIG
from apps.api.core.events import get_event_bus
from apps.api.core.llm_gateway import get_llm_gateway
from apps.api.core.storage import get_minio_client

logger = structlog.get_logger(__name__)

MAX_CHUNK_COUNT  = CONFIG.tutorial.max_chunk_count    # 500
MAX_FILE_SIZE_MB = CONFIG.tutorial.max_file_size_mb   # 100.0
BATCH_SIZE       = 50


class DocumentIngestService:

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def ingest_from_file_event(
        self,
        file_id:    str,
        minio_key:  str,
        space_type: str,
        space_id:   str | None,
        owner_id:   str,
        file_name:  str,
    ) -> str:
        """从 file_uploaded 事件触发，创建 document 记录并开始解析。"""
        document_id = str(uuid.uuid4())
        await self.db.execute(
            text("""
                INSERT INTO documents
                  (document_id, file_id, title, source_type, document_status,
                   space_type, space_id, owner_id)
                VALUES
                  (:doc_id, :file_id, :title, 'upload', 'uploaded',
                   :space_type, :space_id, :owner_id)
            """),
            {
                "doc_id":     document_id,
                "file_id":    file_id,
                "title":      file_name,
                "space_type": space_type,
                "space_id":   space_id,
                "owner_id":   owner_id,
            }
        )
        # FIX-H：用 flush 代替 commit，避免关闭事务后 ingest() 无法继续操作
        # flush 会将 INSERT 发送到数据库（同事务内可见），但不关闭事务
        await self.db.flush()
        await self.ingest(document_id, minio_key, space_type, space_id)
        return document_id

    async def ingest(
        self,
        document_id: str,
        minio_key:   str,
        space_type:  str,
        space_id:    str | None,
    ) -> None:
        """
        主解析流程：
        1. 从 MinIO 下载文件（C3：AsyncMinIOClient）
        2. 按类型选择解析器
        3. 文本切分（R2：截断前记录真实分块数）
        4. 批量写入 document_chunks
        5. 发布 document_parsed 事件
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # 从 MinIO 下载（C3：通过 AsyncMinIOClient 异步下载）
            minio   = get_minio_client()
            suffix  = Path(minio_key).suffix or ".bin"
            tmp_path = Path(tmpdir) / f"{document_id}{suffix}"
            await minio.download(minio_key, tmp_path)

            # 文件大小检查
            size_mb = tmp_path.stat().st_size / 1024 / 1024
            if size_mb > MAX_FILE_SIZE_MB:
                await self._mark_failed(document_id, f"File too large: {size_mb:.1f}MB")
                return

            # 解析文本
            raw_text = await self._extract_text(tmp_path)

        if not raw_text.strip():
            await self._mark_failed(document_id, "Empty document")
            return

        # 文本切分
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1500,
            chunk_overlap=150,
            length_function=len,
        )
        all_chunks_text = splitter.split_text(raw_text)

        # R2：截断前先记录真实原始分块数
        original_count = len(all_chunks_text)
        is_truncated   = original_count > MAX_CHUNK_COUNT
        chunks_text    = all_chunks_text[:MAX_CHUNK_COUNT]

        if is_truncated:
            logger.warning(
                "Document truncated",
                document_id=document_id,
                original_count=original_count,
                kept=MAX_CHUNK_COUNT,
            )

        # 批量写入 document_chunks
        # embedding 暂不在此处生成：
        #   1. DeepSeek 不支持 OpenAI text-embedding-3-small 模型，调用会挂死
        #   2. 原 INSERT SQL 也未包含 embedding 列，计算结果从未写入数据库
        # 向量化将在知识归一化阶段按实体粒度单独处理。
        chunk_rows = []
        for idx, chunk_text in enumerate(chunks_text):
            chunk_rows.append({
                "chunk_id":    str(uuid.uuid4()),
                "document_id": document_id,
                "index_no":    idx,
                "title_path":  "[]",
                "content":     chunk_text,
                "token_count": len(chunk_text) // 4,  # 粗估
            })

        for i in range(0, len(chunk_rows), BATCH_SIZE):
            batch = chunk_rows[i:i+BATCH_SIZE]
            for row in batch:
                await self.db.execute(
                    text("""
                        INSERT INTO document_chunks
                          (chunk_id, document_id, index_no, title_path, content, token_count)
                        VALUES
                          (:chunk_id, :document_id, :index_no, CAST(:title_path AS jsonb), :content, :token_count)
                    """),
                    row
                )

        # 更新文档状态
        await self.db.execute(
            text("""
                UPDATE documents SET
                    document_status = 'parsed',
                    chunk_count = :chunk_count,
                    is_truncated = :is_truncated,
                    original_chunk_count = :original_count,
                    updated_at = NOW()
                WHERE document_id = :document_id
            """),
            {
                "document_id":    document_id,
                "chunk_count":    len(chunks_text),
                "is_truncated":   is_truncated,
                "original_count": original_count,
            }
        )
        await self.db.commit()

        # 发布 document_parsed 事件（加重连保护）
        event_bus = get_event_bus()
        _payload = {
            "document_id": document_id,
            "chunk_count": len(chunks_text),
            "space_type":  space_type,
            "space_id":    space_id,
            "is_truncated": is_truncated,
        }
        for _attempt in range(3):
            try:
                if event_bus._connection is None or event_bus._connection.is_closed:
                    await event_bus.connect()
                await event_bus.publish("document_parsed", _payload)
                break
            except Exception as _e:
                logger.warning("document_parsed publish failed, retrying",
                               attempt=_attempt + 1, error=str(_e))
                import asyncio as _asyncio
                await _asyncio.sleep(2)
        else:
            logger.error("document_parsed publish failed after 3 attempts",
                         document_id=document_id)

        logger.info(
            "Document ingested",
            document_id=document_id,
            chunks=len(chunks_text),
            truncated=is_truncated,
        )

    async def _extract_text(self, file_path: Path) -> str:
        """按文件类型选择解析器。"""
        suffix = file_path.suffix.lower()

        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(file_path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)

        elif suffix in (".docx", ".doc"):
            import docx
            doc = docx.Document(str(file_path))
            return "\n".join(para.text for para in doc.paragraphs)

        elif suffix in (".md", ".txt", ".html"):
            raw = file_path.read_bytes()
            encoding = chardet.detect(raw).get("encoding") or "utf-8"
            return raw.decode(encoding, errors="replace")

        else:
            raise ValueError(f"Unsupported file type: {suffix}")

    async def _mark_failed(self, document_id: str, reason: str) -> None:
        await self.db.execute(
            text("UPDATE documents SET document_status = 'failed', updated_at = NOW() "
                 "WHERE document_id = :doc_id"),
            {"doc_id": document_id}
        )
        await self.db.commit()
        logger.error("Document ingest failed", document_id=document_id, reason=reason)

"""
apps/api/modules/knowledge/ingest_service.py
Block B：文档接入与解析服务

功能：文档解析、文本切分、chunk 入库、发布 document_parsed 事件
V2.6 R2：截断前先记录原始分块数
V2.6 C3：通过 AsyncMinIOClient 下载文件
"""
import json as _json
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
BATCH_SIZE       = CONFIG.tutorial.ingest_batch_size   # 50


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
        document_id: str | None = None,
    ) -> str:
        """从 file_uploaded 事件触发，创建或更新 document 记录并开始解析。

        若调用方已预创建 document（如 upload endpoint），使用传入的 document_id
        并执行 UPDATE；否则创建新记录。
        """
        if document_id:
            # 预创建模式：upload endpoint 已插入 uploaded 状态记录，此处确认存在
            result = await self.db.execute(
                text("""
                    UPDATE documents
                    SET document_status = 'uploaded', updated_at = NOW()
                    WHERE document_id = CAST(:doc_id AS uuid)
                      AND document_status = 'uploaded'
                    RETURNING document_id::text
                """),
                {"doc_id": document_id},
            )
            row = result.fetchone()
            if not row:
                # 预创建的记录不存在（可能被清理），降级新建
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
        else:
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
        # 立即 commit 确保 document 记录持久化，避免 ingest() 异常时记录丢失
        await self.db.commit()
        try:
            await self.ingest(document_id, minio_key, space_type, space_id)
        except Exception:
            # ingest 失败时标记 document 为 failed，保留错误现场
            try:
                await self.db.execute(
                    text("UPDATE documents SET document_status='failed', updated_at=NOW() "
                         "WHERE document_id=:did"),
                    {"did": document_id}
                )
                await self.db.commit()
            except Exception:
                pass
            raise
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

            # 6.1: 页面级提取（替代全文压平），保留 page_no 和 title_path
            pages   = await self._extract_pages(tmp_path)
            outline = await self._extract_outline(tmp_path)

        if not pages:
            await self._mark_failed(document_id, "Empty document")
            return

        # 文本切分（每页独立切分，保留 page_no）
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=CONFIG.tutorial.chunk_size,
            chunk_overlap=CONFIG.tutorial.chunk_overlap,
            length_function=len,
        )

        chunk_rows = []
        for page_no, page_text in pages:
            page_chunks = splitter.split_text(page_text)
            title_path = self._build_title_path(page_no, outline, page_text)
            for chunk_text in page_chunks:
                chunk_rows.append({
                    "chunk_id":    str(uuid.uuid4()),
                    "document_id": document_id,
                    "title_path":  _json.dumps(title_path, ensure_ascii=False),
                    "content":     chunk_text.replace('\x00', ''),
                    "token_count": len(chunk_text) // 4,
                    "page_no":     page_no,
                })

        # R2：截断前先记录真实原始分块数
        original_count = len(chunk_rows)
        is_truncated   = original_count > MAX_CHUNK_COUNT
        if is_truncated:
            chunk_rows = chunk_rows[:MAX_CHUNK_COUNT]
            logger.warning(
                "Document truncated",
                document_id=document_id,
                original_count=original_count,
                kept=MAX_CHUNK_COUNT,
            )

        # 重新分配 index_no（截断后）
        for idx, row in enumerate(chunk_rows):
            row["index_no"] = idx

        for i in range(0, len(chunk_rows), BATCH_SIZE):
            batch = chunk_rows[i:i+BATCH_SIZE]
            for row in batch:
                await self.db.execute(
                    text("""
                        INSERT INTO document_chunks
                          (chunk_id, document_id, index_no, title_path, content, token_count, page_no)
                        VALUES
                          (:chunk_id, :document_id, :index_no, CAST(:title_path AS jsonb), :content, :token_count, :page_no)
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
                "chunk_count":    len(chunk_rows),
                "is_truncated":   is_truncated,
                "original_count": original_count,
            }
        )
        await self.db.commit()

        # 发布 document_parsed 事件（C5 fix：Celery fork 后 event loop 变更，强制重置重连）
        event_bus = get_event_bus()
        await event_bus.reset()
        _payload = {
            "document_id": document_id,
            "chunk_count": len(chunk_rows),
            "space_type":  space_type,
            "space_id":    space_id,
            "is_truncated": is_truncated,
        }
        for _attempt in range(3):
            try:
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
            chunks=len(chunk_rows),
            truncated=is_truncated,
        )

        # S1：chunks 写入完成后异步触发 chunk embedding 生成
        try:
            from apps.api.tasks.embedding_tasks import embed_document_chunks
            embed_document_chunks.apply_async(
                args=[document_id],
                queue="knowledge",
            )
            logger.info("embed_document_chunks dispatched", document_id=document_id)
        except Exception as _e:
            logger.warning("embed_document_chunks dispatch failed", error=str(_e))

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

    async def _extract_pages(self, file_path: Path) -> list[tuple[int, str]]:
        """按页提取文本，返回 [(page_no, text), ...]。PDF 按物理页，其余文件 page_no=1。"""
        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            import fitz
            results: list[tuple[int, str]] = []
            with fitz.open(str(file_path)) as doc:
                for i, page in enumerate(doc):
                    t = page.get_text()
                    if t and t.strip():
                        results.append((i + 1, t))
            if not results:
                from pypdf import PdfReader
                reader = PdfReader(str(file_path))
                for i, pg in enumerate(reader.pages):
                    t = pg.extract_text() or ""
                    if t.strip():
                        results.append((i + 1, t))
            return results
        raw = await self._extract_text(file_path)
        return [(1, raw)] if raw and raw.strip() else []

    async def _extract_outline(self, file_path: Path) -> list[dict]:
        """6.1: 提取 PDF 大纲/TOC（含层级和页码）。
        非 PDF 或提取失败时返回空列表。"""
        suffix = file_path.suffix.lower()
        if suffix != ".pdf":
            return []
        try:
            import fitz
            with fitz.open(str(file_path)) as doc:
                toc = doc.get_toc()  # [(level, title, page_number), ...]
            if not toc:
                return []
            return [{"title": t[1], "page": t[2], "level": t[0]} for t in toc]
        except Exception:
            return []

    @staticmethod
    def _build_title_path(page_no: int, outline: list[dict], page_text: str) -> list[str]:
        """6.1: 为给定页码构建层级标题路径。
        优先使用 PDF 大纲，无大纲时用正则检测标题行。"""
        if outline:
            path: list[str] = []
            for entry in outline:
                if entry["page"] <= page_no:
                    while path and len(path) >= entry["level"]:
                        path.pop()
                    path.append(entry["title"])
            return path

        # 无大纲：正则检测当前页标题
        import re
        titles: list[str] = []
        header_patterns = [
            r'^(第[一二三四五六七八九十\d]+章\s*.+)',
            r'^(Chapter\s+\d+[\s:].+)',
            r'^(\d+\.\d+\s+[A-Z\u4e00-\u9fff].+)',
            r'^(\d+\.\s+[A-Z\u4e00-\u9fff].+)',
        ]
        for line in page_text.split('\n'):
            line = line.strip()
            if not line or len(line) > 120:
                continue
            for pat in header_patterns:
                m = re.match(pat, line)
                if m:
                    titles.append(m.group(1))
                    break
        return titles

    async def _mark_failed(self, document_id: str, reason: str) -> None:
        await self.db.execute(
            text("UPDATE documents SET document_status = 'failed', updated_at = NOW() "
                 "WHERE document_id = :doc_id"),
            {"doc_id": document_id}
        )
        await self.db.commit()
        logger.error("Document ingest failed", document_id=document_id, reason=reason)

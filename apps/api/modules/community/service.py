from __future__ import annotations
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from apps.api.modules.community.repository import CurationRepository

logger = structlog.get_logger()


class CurationError(Exception):
    def __init__(self, code: str, msg: str):
        self.code = code
        self.msg = msg


class CurationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = CurationRepository(db)

    async def submit(
        self, entity_id: str, space_id: str, user_id: str,
        tags: list = [], note: str | None = None
    ) -> dict:
        row = await self.db.execute(
            text("""
                SELECT entity_id FROM knowledge_entities
                WHERE entity_id = CAST(:eid AS uuid)
                  AND space_id = CAST(:sid AS uuid)
                  AND review_status = 'approved'
            """),
            {"eid": entity_id, "sid": space_id}
        )
        if not row.fetchone():
            raise CurationError("CUR_001", "实体不存在或未通过审核")

        space_row = await self.db.execute(
            text("SELECT space_type FROM knowledge_spaces WHERE space_id = CAST(:sid AS uuid)"),
            {"sid": space_id}
        )
        sp = space_row.fetchone()
        if not sp or sp.space_type != "global":
            raise CurationError("CUR_002", "仅 global 空间的知识点可提交策展")

        result = await self.repo.create(entity_id, space_id, user_id, tags, note)
        await self.db.commit()
        logger.info("Curation submitted", entity_id=entity_id, space_id=space_id)
        return result

    async def list_approved(
        self, space_id: str | None = None, tag: str | None = None,
        limit: int = 50, offset: int = 0
    ) -> dict:
        return await self.repo.list_approved(space_id=space_id, tag=tag,
                                             limit=limit, offset=offset)

    async def list_pending(self, limit: int = 50, offset: int = 0) -> list[dict]:
        return await self.repo.list_pending(limit=limit, offset=offset)

    async def review(self, curation_id: str, status: str) -> dict:
        if status not in ("approved", "rejected"):
            raise CurationError("CUR_003", "status 只能为 approved 或 rejected")
        result = await self.repo.update_status(curation_id, status)
        if not result:
            raise CurationError("CUR_004", "策展记录不存在")
        await self.db.commit()
        logger.info("Curation reviewed", curation_id=curation_id, status=status)
        return result

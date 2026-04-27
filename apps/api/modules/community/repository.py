from __future__ import annotations
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


class CurationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self, entity_id: str, space_id: str, curated_by: str,
        tags: list, note: str | None
    ) -> dict:
        import json
        result = await self.db.execute(
            text("""
                INSERT INTO community_curations
                    (entity_id, space_id, curated_by, tags, note)
                VALUES
                    (CAST(:eid AS uuid), CAST(:sid AS uuid), CAST(:uid AS uuid),
                     CAST(:tags AS jsonb), :note)
                ON CONFLICT (entity_id, space_id) DO UPDATE
                    SET status = CASE
                            WHEN community_curations.status = 'rejected'
                            THEN 'pending'
                            ELSE community_curations.status
                        END,
                        tags = EXCLUDED.tags,
                        note = EXCLUDED.note
                RETURNING curation_id::text, entity_id::text, space_id::text,
                          curated_by::text, curated_at, status, tags, note
            """),
            {"eid": entity_id, "sid": space_id, "uid": curated_by,
             "tags": json.dumps(tags, ensure_ascii=False), "note": note}
        )
        row = result.fetchone()
        return dict(row._mapping)

    async def list_approved(
        self, space_id: str | None = None, tag: str | None = None,
        limit: int = 50, offset: int = 0
    ) -> dict:
        conditions = ["cc.status = 'approved'"]
        params: dict = {"limit": limit, "offset": offset}
        if space_id:
            conditions.append("cc.space_id = CAST(:sid AS uuid)")
            params["sid"] = space_id
        if tag:
            conditions.append("cc.tags @> CAST(:tag AS jsonb)")
            params["tag"] = f'["{tag}"]'
        where = " AND ".join(conditions)
        count_result = await self.db.execute(
            text(f"""
                SELECT COUNT(*) FROM community_curations cc
                WHERE {where}
            """),
            {k: v for k, v in params.items() if k not in ("limit", "offset")}
        )
        total = count_result.scalar() or 0
        result = await self.db.execute(
            text(f"""
                SELECT cc.curation_id::text, cc.entity_id::text, cc.space_id::text,
                       cc.curated_by::text, cc.curated_at, cc.status, cc.tags, cc.note,
                       ke.canonical_name, ke.short_definition, ke.detailed_explanation,
                       ke.domain_tag, ks.name AS space_name
                FROM community_curations cc
                JOIN knowledge_entities ke ON ke.entity_id = cc.entity_id
                JOIN knowledge_spaces ks ON ks.space_id = cc.space_id
                WHERE {where}
                ORDER BY cc.curated_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params
        )
        return {"items": [dict(r._mapping) for r in result.fetchall()], "total": total}

    async def get(self, curation_id: str) -> Optional[dict]:
        result = await self.db.execute(
            text("""
                SELECT curation_id::text, entity_id::text, space_id::text,
                       curated_by::text, curated_at, status, tags, note
                FROM community_curations
                WHERE curation_id = CAST(:cid AS uuid)
            """),
            {"cid": curation_id}
        )
        row = result.fetchone()
        return dict(row._mapping) if row else None

    async def update_status(self, curation_id: str, status: str) -> Optional[dict]:
        result = await self.db.execute(
            text("""
                UPDATE community_curations
                SET status = :status
                WHERE curation_id = CAST(:cid AS uuid)
                RETURNING curation_id::text, entity_id::text, space_id::text,
                          status, curated_at, tags, note
            """),
            {"cid": curation_id, "status": status}
        )
        row = result.fetchone()
        return dict(row._mapping) if row else None

    async def list_pending(self, limit: int = 50, offset: int = 0) -> list[dict]:
        result = await self.db.execute(
            text("""
                SELECT cc.curation_id::text, cc.entity_id::text, cc.space_id::text,
                       cc.curated_by::text, cc.curated_at, cc.status, cc.tags, cc.note,
                       ke.canonical_name, ke.short_definition, ke.domain_tag,
                       ks.name AS space_name
                FROM community_curations cc
                JOIN knowledge_entities ke ON ke.entity_id = cc.entity_id
                JOIN knowledge_spaces ks ON ks.space_id = cc.space_id
                WHERE cc.status = 'pending'
                ORDER BY cc.curated_at ASC
                LIMIT :limit OFFSET :offset
            """),
            {"limit": limit, "offset": offset}
        )
        return [dict(r._mapping) for r in result.fetchall()]

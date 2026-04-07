from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.modules.skill_blueprint.service import SkillBlueprintService


class TeachingService:
    """
    对话检索从“全局知识点词典”改为“围绕 topic / chapter 的教学上下文”。
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.blueprint_service = SkillBlueprintService(db)

    async def retrieve(
        self,
        query: str,
        user_id: str,
        topic_key: str,
        *_,
        chapter_id: str | None = None,
        limit: int = 8,
        space_type: str = "personal",
        space_id: str | None = None,
        **__,
    ) -> list[dict[str, Any]]:
        blueprint = await self.blueprint_service.get_topic_blueprint(
            topic_key,
            space_type=space_type,
            space_id=space_id,
            requested_by=user_id,
            force=False,
        )

        entity_ids: list[str] = []
        if chapter_id:
            for stage in blueprint.stages:
                for chapter in stage.chapters:
                    if chapter.chapter_id == chapter_id:
                        entity_ids = chapter.target_entity_ids or chapter.glossary_entity_ids
                        break
        if not entity_ids:
            for stage in blueprint.stages:
                for chapter in stage.chapters:
                    entity_ids.extend(chapter.target_entity_ids)
            entity_ids = list(dict.fromkeys(entity_ids))

        if not entity_ids:
            return []

        like_query = f"%{query.strip()}%"
        rows = (
            await self.db.execute(
                text(
                    """
                    SELECT
                        entity_id::text AS entity_id,
                        canonical_name,
                        COALESCE(short_definition, '') AS short_definition,
                        COALESCE(detailed_explanation, '') AS detailed_explanation,
                        COALESCE(domain_tag, '') AS domain_tag,
                        (
                            CASE WHEN canonical_name ILIKE :like_query THEN 5 ELSE 0 END +
                            CASE WHEN short_definition ILIKE :like_query THEN 3 ELSE 0 END +
                            CASE WHEN detailed_explanation ILIKE :like_query THEN 1 ELSE 0 END
                        ) AS score
                    FROM knowledge_entities
                    WHERE review_status = 'approved'
                      AND domain_tag = :topic_key
                      AND entity_id::text = ANY(:entity_ids)
                    ORDER BY score DESC, canonical_name
                    LIMIT :limit
                    """
                ),
                {
                    "like_query": like_query,
                    "topic_key": topic_key,
                    "entity_ids": entity_ids,
                    "limit": limit,
                },
            )
        ).mappings().all()

        return [dict(r) for r in rows]

    async def build_context(
        self,
        query: str,
        user_id: str,
        topic_key: str,
        *,
        chapter_id: str | None = None,
        limit: int = 8,
        space_type: str = "personal",
        space_id: str | None = None,
    ) -> str:
        items = await self.retrieve(
            query=query,
            user_id=user_id,
            topic_key=topic_key,
            chapter_id=chapter_id,
            limit=limit,
            space_type=space_type,
            space_id=space_id,
        )
        if not items:
            return "当前主题下还没有足够的已审核术语可供教学对话参考。"
        lines = []
        for item in items:
            lines.append(f"术语：{item['canonical_name']}\n定义：{item['short_definition']}\n说明：{item['detailed_explanation'][:400]}")
        return "\n\n".join(lines)

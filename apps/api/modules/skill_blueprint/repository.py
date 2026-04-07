from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .schemas import ChapterGlossaryItem, SkillBlueprint, SkillChapter, SkillStage, TopicCard


class SkillBlueprintRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def fetch_latest_blueprint_row(
        self,
        topic_key: str,
        space_type: str = "personal",
        space_id: str | None = None,
        statuses: tuple[str, ...] = ("published", "approved", "draft"),
    ) -> dict[str, Any] | None:
        params: dict[str, Any] = {
            "topic_key": topic_key,
            "space_type": space_type,
            "statuses": list(statuses),
        }
        sql = text(
            """
            SELECT *
            FROM skill_blueprints
            WHERE topic_key = :topic_key
              AND space_type = :space_type
              AND (:space_id IS NULL OR space_id = CAST(:space_id AS uuid))
              AND status = ANY(:statuses)
            ORDER BY version DESC
            LIMIT 1
            """
        )
        row = (await self.db.execute(sql, {"space_id": space_id, **params})).mappings().first()
        return dict(row) if row else None

    async def list_topic_cards(self, space_type: str | None = None) -> list[TopicCard]:
        sql = text(
            """
            WITH latest AS (
                SELECT DISTINCT ON (topic_key, space_type, COALESCE(space_id::text, ''))
                    topic_key,
                    space_type,
                    space_id,
                    version,
                    status,
                    skill_goal,
                    summary,
                    updated_at,
                    blueprint_id
                FROM skill_blueprints
                ORDER BY topic_key, space_type, COALESCE(space_id::text, ''), version DESC
            ),
            chapters AS (
                SELECT blueprint_id, COUNT(*) AS chapter_count
                FROM skill_chapters
                GROUP BY blueprint_id
            ),
            entities AS (
                SELECT domain_tag, COUNT(*) AS approved_entity_count
                FROM knowledge_entities
                WHERE review_status = 'approved'
                GROUP BY domain_tag
            )
            SELECT
                latest.topic_key,
                latest.space_type,
                latest.space_id::text AS space_id,
                latest.version,
                latest.status,
                latest.skill_goal,
                latest.summary,
                latest.updated_at::text AS updated_at,
                COALESCE(chapters.chapter_count, 0) AS chapter_count,
                COALESCE(entities.approved_entity_count, 0) AS approved_entity_count
            FROM latest
            LEFT JOIN chapters ON chapters.blueprint_id = latest.blueprint_id
            LEFT JOIN entities ON entities.domain_tag = latest.topic_key
            WHERE (:space_type IS NULL OR latest.space_type = :space_type)
            ORDER BY latest.topic_key
            """
        )
        rows = (await self.db.execute(sql, {"space_type": space_type})).mappings().all()
        return [TopicCard(**dict(r)) for r in rows]

    async def insert_blueprint(
        self,
        *,
        blueprint_id: str,
        topic_key: str,
        space_type: str,
        space_id: str | None,
        version: int,
        status: str,
        skill_goal: str,
        target_role: str,
        summary: str,
        source_fingerprint: str,
        source_entity_count: int,
        created_by: str | None,
    ) -> None:
        await self.db.execute(
            text(
                """
                INSERT INTO skill_blueprints (
                    blueprint_id, topic_key, space_type, space_id, version, status,
                    skill_goal, target_role, summary, source_fingerprint,
                    source_entity_count, created_by
                )
                VALUES (
                    CAST(:blueprint_id AS uuid),
                    :topic_key,
                    :space_type,
                    CAST(:space_id AS uuid),
                    :version,
                    :status,
                    :skill_goal,
                    :target_role,
                    :summary,
                    :source_fingerprint,
                    :source_entity_count,
                    CAST(:created_by AS uuid)
                )
                """
            ),
            {
                "blueprint_id": blueprint_id,
                "topic_key": topic_key,
                "space_type": space_type,
                "space_id": space_id,
                "version": version,
                "status": status,
                "skill_goal": skill_goal,
                "target_role": target_role,
                "summary": summary,
                "source_fingerprint": source_fingerprint,
                "source_entity_count": source_entity_count,
                "created_by": created_by,
            },
        )

    async def delete_children(self, blueprint_id: str) -> None:
        params = {"blueprint_id": blueprint_id}
        await self.db.execute(
            text(
                "DELETE FROM chapter_entity_links WHERE blueprint_id = CAST(:blueprint_id AS uuid)"
            ),
            params,
        )
        await self.db.execute(
            text(
                "DELETE FROM skill_chapter_edges WHERE blueprint_id = CAST(:blueprint_id AS uuid)"
            ),
            params,
        )
        await self.db.execute(
            text("DELETE FROM skill_chapters WHERE blueprint_id = CAST(:blueprint_id AS uuid)"),
            params,
        )
        await self.db.execute(
            text("DELETE FROM skill_stages WHERE blueprint_id = CAST(:blueprint_id AS uuid)"),
            params,
        )

    async def insert_stage(
        self,
        *,
        stage_id: str,
        blueprint_id: str,
        stage_order: int,
        title: str,
        objective: str,
        can_do_after: str,
    ) -> None:
        await self.db.execute(
            text(
                """
                INSERT INTO skill_stages (
                    stage_id, blueprint_id, stage_order, title, objective, can_do_after
                )
                VALUES (
                    CAST(:stage_id AS uuid),
                    CAST(:blueprint_id AS uuid),
                    :stage_order,
                    :title,
                    :objective,
                    :can_do_after
                )
                """
            ),
            {
                "stage_id": stage_id,
                "blueprint_id": blueprint_id,
                "stage_order": stage_order,
                "title": title,
                "objective": objective,
                "can_do_after": can_do_after,
            },
        )

    async def insert_chapter(
        self,
        *,
        chapter_id: str,
        blueprint_id: str,
        stage_id: str,
        chapter_order: int,
        title: str,
        objective: str,
        can_do_after: str,
        practice_task: str,
        pass_criteria: str,
        estimated_minutes: int,
        learning_points: list[str],
        target_entity_ids: list[str],
        glossary_entity_ids: list[str],
    ) -> None:
        await self.db.execute(
            text(
                """
                INSERT INTO skill_chapters (
                    chapter_id, blueprint_id, stage_id, chapter_order, title,
                    objective, can_do_after, practice_task, pass_criteria,
                    estimated_minutes, learning_points, target_entity_ids, glossary_entity_ids
                )
                VALUES (
                    CAST(:chapter_id AS uuid),
                    CAST(:blueprint_id AS uuid),
                    CAST(:stage_id AS uuid),
                    :chapter_order,
                    :title,
                    :objective,
                    :can_do_after,
                    :practice_task,
                    :pass_criteria,
                    :estimated_minutes,
                    CAST(:learning_points AS jsonb),
                    CAST(:target_entity_ids AS jsonb),
                    CAST(:glossary_entity_ids AS jsonb)
                )
                """
            ),
            {
                "chapter_id": chapter_id,
                "blueprint_id": blueprint_id,
                "stage_id": stage_id,
                "chapter_order": chapter_order,
                "title": title,
                "objective": objective,
                "can_do_after": can_do_after,
                "practice_task": practice_task,
                "pass_criteria": pass_criteria,
                "estimated_minutes": estimated_minutes,
                "learning_points": json.dumps(learning_points, ensure_ascii=False),
                "target_entity_ids": json.dumps(target_entity_ids, ensure_ascii=False),
                "glossary_entity_ids": json.dumps(glossary_entity_ids, ensure_ascii=False),
            },
        )

    async def insert_edge(
        self,
        *,
        blueprint_id: str,
        from_chapter_id: str,
        to_chapter_id: str,
        edge_type: str = "prerequisite",
    ) -> None:
        await self.db.execute(
            text(
                """
                INSERT INTO skill_chapter_edges (
                    blueprint_id, from_chapter_id, to_chapter_id, edge_type
                )
                VALUES (
                    CAST(:blueprint_id AS uuid),
                    CAST(:from_chapter_id AS uuid),
                    CAST(:to_chapter_id AS uuid),
                    :edge_type
                )
                ON CONFLICT (from_chapter_id, to_chapter_id, edge_type) DO NOTHING
                """
            ),
            {
                "blueprint_id": blueprint_id,
                "from_chapter_id": from_chapter_id,
                "to_chapter_id": to_chapter_id,
                "edge_type": edge_type,
            },
        )

    async def insert_entity_link(
        self,
        *,
        blueprint_id: str,
        chapter_id: str,
        entity_id: str,
        link_role: str,
        weight: float = 1.0,
    ) -> None:
        await self.db.execute(
            text(
                """
                INSERT INTO chapter_entity_links (
                    blueprint_id, chapter_id, entity_id, link_role, weight
                )
                VALUES (
                    CAST(:blueprint_id AS uuid),
                    CAST(:chapter_id AS uuid),
                    CAST(:entity_id AS uuid),
                    :link_role,
                    :weight
                )
                ON CONFLICT (chapter_id, entity_id, link_role) DO NOTHING
                """
            ),
            {
                "blueprint_id": blueprint_id,
                "chapter_id": chapter_id,
                "entity_id": entity_id,
                "link_role": link_role,
                "weight": weight,
            },
        )

    async def publish_version(self, blueprint_id: str, topic_key: str, space_type: str, space_id: str | None) -> None:
        await self.db.execute(
            text(
                """
                UPDATE skill_blueprints
                SET status = 'archived', updated_at = NOW()
                WHERE topic_key = :topic_key
                  AND space_type = :space_type
                  AND (:space_id IS NULL OR space_id = CAST(:space_id AS uuid))
                  AND blueprint_id <> CAST(:blueprint_id AS uuid)
                  AND status IN ('published', 'approved')
                """
            ),
            {
                "topic_key": topic_key,
                "space_type": space_type,
                "space_id": space_id,
                "blueprint_id": blueprint_id,
            },
        )
        await self.db.execute(
            text(
                """
                UPDATE skill_blueprints
                SET status = 'published', published_at = NOW(), updated_at = NOW()
                WHERE blueprint_id = CAST(:blueprint_id AS uuid)
                """
            ),
            {"blueprint_id": blueprint_id},
        )

    async def fetch_blueprint(self, blueprint_id: str) -> SkillBlueprint | None:
        bp_row = (
            await self.db.execute(
                text("SELECT * FROM skill_blueprints WHERE blueprint_id = CAST(:blueprint_id AS uuid)"),
                {"blueprint_id": blueprint_id},
            )
        ).mappings().first()
        if not bp_row:
            return None

        stage_rows = (
            await self.db.execute(
                text(
                    """
                    SELECT * FROM skill_stages
                    WHERE blueprint_id = CAST(:blueprint_id AS uuid)
                    ORDER BY stage_order, created_at
                    """
                ),
                {"blueprint_id": blueprint_id},
            )
        ).mappings().all()

        chapter_rows = (
            await self.db.execute(
                text(
                    """
                    SELECT * FROM skill_chapters
                    WHERE blueprint_id = CAST(:blueprint_id AS uuid)
                    ORDER BY chapter_order, created_at
                    """
                ),
                {"blueprint_id": blueprint_id},
            )
        ).mappings().all()

        glossary_rows = (
            await self.db.execute(
                text(
                    """
                    SELECT
                        cel.chapter_id::text AS chapter_id,
                        ke.entity_id::text AS entity_id,
                        ke.canonical_name,
                        COALESCE(ke.entity_type, '') AS entity_type,
                        COALESCE(ke.short_definition, '') AS short_definition,
                        COALESCE(ke.detailed_explanation, '') AS detailed_explanation,
                        cel.link_role
                    FROM chapter_entity_links cel
                    JOIN knowledge_entities ke ON ke.entity_id = cel.entity_id
                    WHERE cel.blueprint_id = CAST(:blueprint_id AS uuid)
                    ORDER BY cel.chapter_id, cel.link_role DESC, ke.canonical_name
                    """
                ),
                {"blueprint_id": blueprint_id},
            )
        ).mappings().all()

        glossary_by_chapter: dict[str, list[ChapterGlossaryItem]] = {}
        for row in glossary_rows:
            glossary_by_chapter.setdefault(row["chapter_id"], []).append(
                ChapterGlossaryItem(**dict(row))
            )

        chapters_by_stage: dict[str, list[SkillChapter]] = {}
        for row in chapter_rows:
            chapter_dict = dict(row)
            chapter = SkillChapter(
                chapter_id=str(chapter_dict["chapter_id"]),
                stage_id=str(chapter_dict["stage_id"]),
                chapter_order=chapter_dict["chapter_order"],
                title=chapter_dict["title"],
                objective=chapter_dict["objective"],
                can_do_after=chapter_dict["can_do_after"],
                practice_task=chapter_dict["practice_task"],
                pass_criteria=chapter_dict["pass_criteria"],
                estimated_minutes=chapter_dict["estimated_minutes"],
                learning_points=chapter_dict["learning_points"] or [],
                target_entity_ids=chapter_dict["target_entity_ids"] or [],
                glossary_entity_ids=chapter_dict["glossary_entity_ids"] or [],
                glossary=glossary_by_chapter.get(str(chapter_dict["chapter_id"]), []),
            )
            chapters_by_stage.setdefault(str(chapter.stage_id), []).append(chapter)

        stages: list[SkillStage] = []
        for row in stage_rows:
            stage_dict = dict(row)
            stages.append(
                SkillStage(
                    stage_id=str(stage_dict["stage_id"]),
                    stage_order=stage_dict["stage_order"],
                    title=stage_dict["title"],
                    objective=stage_dict["objective"],
                    can_do_after=stage_dict["can_do_after"],
                    chapters=chapters_by_stage.get(str(stage_dict["stage_id"]), []),
                )
            )

        bp = dict(bp_row)
        return SkillBlueprint(
            blueprint_id=str(bp["blueprint_id"]),
            topic_key=bp["topic_key"],
            space_type=bp["space_type"],
            space_id=str(bp["space_id"]) if bp["space_id"] else None,
            version=bp["version"],
            status=bp["status"],
            skill_goal=bp["skill_goal"],
            target_role=bp["target_role"],
            summary=bp["summary"],
            source_fingerprint=bp["source_fingerprint"],
            source_entity_count=bp["source_entity_count"],
            stages=stages,
        )

    async def fetch_glossary(self, entity_ids: list[str]) -> list[ChapterGlossaryItem]:
        if not entity_ids:
            return []
        rows = (
            await self.db.execute(
                text(
                    """
                    SELECT
                        entity_id::text AS entity_id,
                        canonical_name,
                        COALESCE(entity_type, '') AS entity_type,
                        COALESCE(short_definition, '') AS short_definition,
                        COALESCE(detailed_explanation, '') AS detailed_explanation,
                        'glossary' AS link_role
                    FROM knowledge_entities
                    WHERE entity_id::text = ANY(:entity_ids)
                    ORDER BY canonical_name
                    """
                ),
                {"entity_ids": entity_ids},
            )
        ).mappings().all()
        return [ChapterGlossaryItem(**dict(r)) for r in rows]

from __future__ import annotations
import uuid
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

class BlueprintRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_topic(self, topic_key: str) -> Optional[dict]:
        row = await self.db.execute(
            text("SELECT blueprint_id::text, topic_key, title, skill_goal, "
                 "status, version, space_id::text, created_at, updated_at "
                 "FROM skill_blueprints WHERE topic_key = :tk "
                 "ORDER BY version DESC LIMIT 1"),
            {"tk": topic_key}
        )
        r = row.fetchone()
        return dict(r._mapping) if r else None

    async def get_published_by_topic(self, topic_key: str) -> Optional[dict]:
        row = await self.db.execute(
            text("SELECT blueprint_id::text, topic_key, title, skill_goal, "
                 "status, version, space_id::text, created_at, updated_at "
                 "FROM skill_blueprints "
                 "WHERE topic_key = :tk AND status = 'published' "
                 "ORDER BY version DESC LIMIT 1"),
            {"tk": topic_key}
        )
        r = row.fetchone()
        return dict(r._mapping) if r else None

    async def get_stages(self, blueprint_id: str) -> List[dict]:
        rows = await self.db.execute(
            text("SELECT stage_id::text, title, description, stage_type, stage_order "
                 "FROM skill_stages WHERE blueprint_id = CAST(:bid AS uuid) "
                 "ORDER BY stage_order"),
            {"bid": blueprint_id}
        )
        return [dict(r._mapping) for r in rows.fetchall()]

    async def get_chapters(self, stage_id: str) -> List[dict]:
        rows = await self.db.execute(
            text("SELECT chapter_id::text, title, objective, task_description, "
                 "pass_criteria, common_mistakes, content_text, chapter_order, status "
                 "FROM skill_chapters WHERE stage_id = CAST(:sid AS uuid) "
                 "ORDER BY chapter_order"),
            {"sid": stage_id}
        )
        return [dict(r._mapping) for r in rows.fetchall()]

    async def get_hotwords(self, chapter_id: str) -> List[dict]:
        rows = await self.db.execute(
            text("SELECT cel.entity_id::text, ke.canonical_name, "
                 "ke.short_definition, cel.link_type "
                 "FROM chapter_entity_links cel "
                 "JOIN knowledge_entities ke ON ke.entity_id = cel.entity_id "
                 "WHERE cel.chapter_id = CAST(:cid AS uuid) "
                 "ORDER BY cel.link_type, ke.canonical_name"),
            {"cid": chapter_id}
        )
        return [dict(r._mapping) for r in rows.fetchall()]

    async def create_blueprint(self, topic_key, title, skill_goal, space_id) -> str:
        blueprint_id = str(uuid.uuid4())
        result = await self.db.execute(
            text("INSERT INTO skill_blueprints "
                 "(blueprint_id, topic_key, title, skill_goal, space_id, status) "
                 "VALUES (CAST(:bid AS uuid), :tk, :title, :goal, :sid, 'generating') "
                 "ON CONFLICT (topic_key) DO UPDATE "
                 "SET title=EXCLUDED.title, skill_goal=EXCLUDED.skill_goal, "
                 "status='generating', version=skill_blueprints.version+1, updated_at=now() "
                 "RETURNING blueprint_id::text"),
            {"bid": blueprint_id, "tk": topic_key, "title": title,
             "goal": skill_goal, "sid": space_id}
        )
        row = result.fetchone()
        return row[0] if row else blueprint_id

    async def create_stage(self, blueprint_id, title, description, stage_order, stage_type) -> str:
        stage_id = str(uuid.uuid4())
        await self.db.execute(
            text("INSERT INTO skill_stages "
                 "(stage_id, blueprint_id, title, description, stage_order, stage_type) "
                 "VALUES (CAST(:sid AS uuid), CAST(:bid AS uuid), :title, :desc, :order, :stype)"),
            {"sid": stage_id, "bid": blueprint_id, "title": title,
             "desc": description, "order": stage_order, "stype": stage_type}
        )
        return stage_id

    async def create_chapter(self, stage_id, blueprint_id, title, objective,
                              task_description, pass_criteria, common_mistakes, chapter_order) -> str:
        chapter_id = str(uuid.uuid4())
        await self.db.execute(
            text("INSERT INTO skill_chapters "
                 "(chapter_id, stage_id, blueprint_id, title, objective, "
                 "task_description, pass_criteria, common_mistakes, chapter_order) "
                 "VALUES (CAST(:cid AS uuid), CAST(:sid AS uuid), CAST(:bid AS uuid), "
                 ":title, :obj, :task, :pass_, :mistakes, :order)"),
            {"cid": chapter_id, "sid": stage_id, "bid": blueprint_id,
             "title": title, "obj": objective, "task": task_description,
             "pass_": pass_criteria, "mistakes": common_mistakes, "order": chapter_order}
        )
        return chapter_id

    async def update_chapter_content(self, chapter_id: str, content_text: str) -> None:
        await self.db.execute(
            text("UPDATE skill_chapters SET content_text=:ct, status='approved', "
                 "updated_at=now() WHERE chapter_id=CAST(:cid AS uuid)"),
            {"ct": content_text, "cid": chapter_id}
        )

    async def link_entity_to_chapter(self, chapter_id: str, entity_id: str,
                                      link_type: str = "glossary") -> None:
        await self.db.execute(
            text("INSERT INTO chapter_entity_links (chapter_id, entity_id, link_type) "
                 "VALUES (CAST(:cid AS uuid), CAST(:eid AS uuid), :lt) "
                 "ON CONFLICT (chapter_id, entity_id) DO NOTHING"),
            {"cid": chapter_id, "eid": entity_id, "lt": link_type}
        )

    async def update_blueprint_status(self, blueprint_id: str, status: str) -> None:
        await self.db.execute(
            text("UPDATE skill_blueprints SET status=:s, updated_at=now() "
                 "WHERE blueprint_id=CAST(:bid AS uuid)"),
            {"s": status, "bid": blueprint_id}
        )

    async def resolve_space_id(self, topic_key: str) -> Optional[str]:
        row = await self.db.execute(
            text("SELECT space_id::text FROM knowledge_spaces WHERE name=:name LIMIT 1"),
            {"name": topic_key}
        )
        r = row.fetchone()
        return r[0] if r else None

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .repository import SkillBlueprintRepository
from .schemas import ChapterContent, PathStep, SkillBlueprint


@dataclass
class EntityRow:
    entity_id: str
    canonical_name: str
    entity_type: str
    short_definition: str
    detailed_explanation: str
    domain_tag: str


class SkillBlueprintService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = SkillBlueprintRepository(db)

    async def list_topics(self, space_type: str | None = None):
        return await self.repo.list_topic_cards(space_type=space_type)

    async def load_approved_entities(
        self,
        topic_key: str,
        *,
        space_type: str = "personal",
        space_id: str | None = None,
    ) -> list[EntityRow]:
        sql = text(
            """
            SELECT
                entity_id::text AS entity_id,
                canonical_name,
                COALESCE(entity_type, 'concept') AS entity_type,
                COALESCE(short_definition, '') AS short_definition,
                COALESCE(detailed_explanation, '') AS detailed_explanation,
                COALESCE(domain_tag, '') AS domain_tag
            FROM knowledge_entities
            WHERE review_status = 'approved'
              AND domain_tag = :topic_key
            ORDER BY canonical_name
            """
        )
        rows = (await self.db.execute(sql, {"topic_key": topic_key})).mappings().all()
        return [EntityRow(**dict(r)) for r in rows]

    async def compute_source_fingerprint(
        self,
        topic_key: str,
        *,
        space_type: str = "personal",
        space_id: str | None = None,
    ) -> tuple[str, list[EntityRow]]:
        entities = await self.load_approved_entities(topic_key, space_type=space_type, space_id=space_id)
        payload = [
            {
                "entity_id": e.entity_id,
                "canonical_name": e.canonical_name,
                "entity_type": e.entity_type,
                "short_definition": e.short_definition,
                "detailed_explanation": e.detailed_explanation[:300],
            }
            for e in entities
        ]
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.md5(raw.encode("utf-8")).hexdigest(), entities

    def _bucketize_entities(self, entities: list[EntityRow]) -> dict[str, list[EntityRow]]:
        buckets = {"concept": [], "element": [], "flow": [], "case": [], "defense": [], "other": []}
        for item in entities:
            key = item.entity_type if item.entity_type in buckets else "other"
            buckets[key].append(item)
        return buckets

    def _chunk(self, items: list[EntityRow], size: int) -> list[list[EntityRow]]:
        return [items[i : i + size] for i in range(0, len(items), size)]

    def _chapter_title(self, topic_key: str, stage_kind: str, chunk_index: int, total_chunks: int) -> str:
        if stage_kind == "foundation":
            return f"识别 {topic_key} 的关键对象并建立判断框架"
        if stage_kind == "workflow":
            return f"把 {topic_key} 串成可执行流程"
        if stage_kind == "case":
            return f"通过案例复盘 {topic_key} 的完整链路"
        if stage_kind == "defense":
            return f"为 {topic_key} 设计防护与验证闭环"
        if total_chunks > 1:
            return f"{topic_key} 综合实战练习 {chunk_index + 1}"
        return f"完成一次 {topic_key} 的综合能力演练"

    def _stage_templates(self, topic_key: str) -> list[dict[str, str]]:
        return [
            {
                "kind": "foundation",
                "title": f"建立 {topic_key} 的问题空间",
                "objective": f"知道 {topic_key} 涉及哪些对象、边界、常见名词，以及它们在实战中的作用。",
                "can_do_after": f"看到与 {topic_key} 相关的材料时，能先判断关键对象、输入边界和目标输出。",
            },
            {
                "kind": "workflow",
                "title": f"形成 {topic_key} 的操作链路",
                "objective": f"把零散知识组织成能执行的步骤链路，而不是只记一堆名词。",
                "can_do_after": f"面对具体任务时，能写出 {topic_key} 的分析步骤和验证顺序。",
            },
            {
                "kind": "case",
                "title": f"通过案例理解 {topic_key} 的成因与后果",
                "objective": f"借助案例把原理、过程和结果串起来，知道为什么会成功或失败。",
                "can_do_after": f"能复盘一条 {topic_key} 案例链路，并指出关键转折点。",
            },
            {
                "kind": "defense",
                "title": f"完成 {topic_key} 的防护与验收",
                "objective": f"不仅能分析问题，还能提出防御、验证修复效果并形成交付标准。",
                "can_do_after": f"能为 {topic_key} 设计一套防护与验证方案。",
            },
        ]

    def synthesize_blueprint_dict(
        self,
        topic_key: str,
        *,
        entities: list[EntityRow],
        source_fingerprint: str,
        version: int,
        space_type: str = "personal",
        space_id: str | None = None,
    ) -> dict[str, Any]:
        buckets = self._bucketize_entities(entities)
        blueprint_id = str(uuid4())
        stages_payload: list[dict[str, Any]] = []
        chapter_counter = 0

        stage_inputs = self._stage_templates(topic_key)
        stage_entity_map = {
            "foundation": buckets["concept"] + buckets["element"],
            "workflow": buckets["flow"],
            "case": buckets["case"],
            "defense": buckets["defense"],
        }

        for stage_index, stage_meta in enumerate(stage_inputs, start=1):
            stage_entities = stage_entity_map.get(stage_meta["kind"], [])
            if not stage_entities:
                continue

            stage_id = str(uuid4())
            chunks = self._chunk(stage_entities, 5)
            chapters: list[dict[str, Any]] = []
            for chunk_index, chunk in enumerate(chunks):
                chapter_counter += 1
                title = self._chapter_title(topic_key, stage_meta["kind"], chunk_index, len(chunks))
                learning_points = [
                    f"围绕 {item.canonical_name} 判断它在 {topic_key} 任务里的作用。"
                    for item in chunk[:4]
                ]
                if not learning_points:
                    learning_points = [f"完成与 {topic_key} 相关的一次阶段性任务。"]

                chapter = {
                    "chapter_id": str(uuid4()),
                    "chapter_order": chapter_counter,
                    "title": title,
                    "objective": stage_meta["objective"],
                    "can_do_after": stage_meta["can_do_after"],
                    "practice_task": f"基于本章内容，完成一次与 {topic_key} 相关的小型分析或操作任务，并记录关键判断。",
                    "pass_criteria": f"能够清楚解释本章涉及对象的关系，并独立完成一次 {topic_key} 阶段任务。",
                    "estimated_minutes": 35 if stage_meta["kind"] != "case" else 45,
                    "learning_points": learning_points,
                    "target_entity_ids": [item.entity_id for item in chunk],
                    "glossary_entity_ids": [item.entity_id for item in chunk],
                }
                chapters.append(chapter)

            stages_payload.append(
                {
                    "stage_id": stage_id,
                    "stage_order": stage_index,
                    "title": stage_meta["title"],
                    "objective": stage_meta["objective"],
                    "can_do_after": stage_meta["can_do_after"],
                    "chapters": chapters,
                }
            )

        remaining = buckets["other"]
        if remaining:
            stage_id = str(uuid4())
            chapters = []
            for chunk_index, chunk in enumerate(self._chunk(remaining, 5)):
                chapter_counter += 1
                chapters.append(
                    {
                        "chapter_id": str(uuid4()),
                        "chapter_order": chapter_counter,
                        "title": self._chapter_title(topic_key, "practice", chunk_index, len(remaining)),
                        "objective": f"把与 {topic_key} 相关的零散线索重新组织成可行动的方案。",
                        "can_do_after": f"能把多个零散知识点归纳成一次 {topic_key} 综合练习的步骤。",
                        "practice_task": f"完成一次与 {topic_key} 相关的综合演练，并复盘判断依据。",
                        "pass_criteria": f"能把本章涉及的术语和流程串起来，解释为什么这样做。",
                        "estimated_minutes": 40,
                        "learning_points": [
                            f"将 {item.canonical_name} 纳入完整任务链路，而不是孤立记忆。"
                            for item in chunk[:4]
                        ],
                        "target_entity_ids": [item.entity_id for item in chunk],
                        "glossary_entity_ids": [item.entity_id for item in chunk],
                    }
                )
            stages_payload.append(
                {
                    "stage_id": stage_id,
                    "stage_order": len(stages_payload) + 1,
                    "title": f"{topic_key} 综合演练",
                    "objective": f"把前面阶段的内容合成可执行任务。",
                    "can_do_after": f"完成一次完整的 {topic_key} 小型项目或复盘任务。",
                    "chapters": chapters,
                }
            )

        if not stages_payload:
            stage_id = str(uuid4())
            chapter_id = str(uuid4())
            stages_payload = [
                {
                    "stage_id": stage_id,
                    "stage_order": 1,
                    "title": f"{topic_key} 导学与任务框架",
                    "objective": f"为 {topic_key} 建立一个基础训练框架。",
                    "can_do_after": f"知道后续应该从哪些问题入手继续补充 {topic_key} 内容。",
                    "chapters": [
                        {
                            "chapter_id": chapter_id,
                            "chapter_order": 1,
                            "title": f"{topic_key} 入门任务拆解",
                            "objective": f"先明确学习 {topic_key} 想做到什么。",
                            "can_do_after": f"知道自己要围绕哪些任务继续收集资料。",
                            "practice_task": f"列出三个与 {topic_key} 直接相关的真实任务场景。",
                            "pass_criteria": f"能用自己的话说明 {topic_key} 的任务目标。",
                            "estimated_minutes": 25,
                            "learning_points": [f"先把 {topic_key} 学成能力目标，再补充术语。"],
                            "target_entity_ids": [],
                            "glossary_entity_ids": [],
                        }
                    ],
                }
            ]

        return {
            "blueprint_id": blueprint_id,
            "topic_key": topic_key,
            "space_type": space_type,
            "space_id": space_id,
            "version": version,
            "status": "draft",
            "skill_goal": f"能够围绕 {topic_key} 完成分析、执行、复盘与验证，而不是只会解释零散名词。",
            "target_role": f"{topic_key} 学习者",
            "summary": f"这份蓝图把 {topic_key} 组织成阶段化能力训练路径，知识点只作为正文中的热词解释与术语支撑。",
            "source_fingerprint": source_fingerprint,
            "source_entity_count": len(entities),
            "stages": stages_payload,
        }

    async def create_or_refresh_blueprint(
        self,
        topic_key: str,
        *,
        space_type: str = "personal",
        space_id: str | None = None,
        requested_by: str | None = None,
        force: bool = False,
    ) -> SkillBlueprint:
        latest_row = await self.repo.fetch_latest_blueprint_row(
            topic_key=topic_key,
            space_type=space_type,
            space_id=space_id,
            statuses=("published", "approved", "draft"),
        )
        fingerprint, entities = await self.compute_source_fingerprint(
            topic_key, space_type=space_type, space_id=space_id
        )

        if latest_row and latest_row["source_fingerprint"] == fingerprint and not force:
            existing = await self.repo.fetch_blueprint(str(latest_row["blueprint_id"]))
            if existing is not None:
                return existing

        next_version = (latest_row["version"] + 1) if latest_row else 1
        blueprint = self.synthesize_blueprint_dict(
            topic_key,
            entities=entities,
            source_fingerprint=fingerprint,
            version=next_version,
            space_type=space_type,
            space_id=space_id,
        )

        await self.repo.insert_blueprint(
            blueprint_id=blueprint["blueprint_id"],
            topic_key=blueprint["topic_key"],
            space_type=blueprint["space_type"],
            space_id=blueprint["space_id"],
            version=blueprint["version"],
            status="draft",
            skill_goal=blueprint["skill_goal"],
            target_role=blueprint["target_role"],
            summary=blueprint["summary"],
            source_fingerprint=blueprint["source_fingerprint"],
            source_entity_count=blueprint["source_entity_count"],
            created_by=requested_by,
        )

        await self.repo.delete_children(blueprint["blueprint_id"])
        previous_chapter_id: str | None = None
        for stage in blueprint["stages"]:
            await self.repo.insert_stage(
                stage_id=stage["stage_id"],
                blueprint_id=blueprint["blueprint_id"],
                stage_order=stage["stage_order"],
                title=stage["title"],
                objective=stage["objective"],
                can_do_after=stage["can_do_after"],
            )
            for chapter in stage["chapters"]:
                await self.repo.insert_chapter(
                    chapter_id=chapter["chapter_id"],
                    blueprint_id=blueprint["blueprint_id"],
                    stage_id=stage["stage_id"],
                    chapter_order=chapter["chapter_order"],
                    title=chapter["title"],
                    objective=chapter["objective"],
                    can_do_after=chapter["can_do_after"],
                    practice_task=chapter["practice_task"],
                    pass_criteria=chapter["pass_criteria"],
                    estimated_minutes=chapter["estimated_minutes"],
                    learning_points=chapter["learning_points"],
                    target_entity_ids=chapter["target_entity_ids"],
                    glossary_entity_ids=chapter["glossary_entity_ids"],
                )
                for entity_id in chapter["target_entity_ids"]:
                    await self.repo.insert_entity_link(
                        blueprint_id=blueprint["blueprint_id"],
                        chapter_id=chapter["chapter_id"],
                        entity_id=entity_id,
                        link_role="core",
                        weight=1.0,
                    )
                for entity_id in chapter["glossary_entity_ids"]:
                    await self.repo.insert_entity_link(
                        blueprint_id=blueprint["blueprint_id"],
                        chapter_id=chapter["chapter_id"],
                        entity_id=entity_id,
                        link_role="glossary",
                        weight=0.8,
                    )
                if previous_chapter_id:
                    await self.repo.insert_edge(
                        blueprint_id=blueprint["blueprint_id"],
                        from_chapter_id=previous_chapter_id,
                        to_chapter_id=chapter["chapter_id"],
                    )
                previous_chapter_id = chapter["chapter_id"]

        await self.repo.publish_version(
            blueprint_id=blueprint["blueprint_id"],
            topic_key=topic_key,
            space_type=space_type,
            space_id=space_id,
        )
        await self.db.commit()

        saved = await self.repo.fetch_blueprint(blueprint["blueprint_id"])
        if saved is None:
            raise RuntimeError("blueprint created but could not be reloaded")
        return saved

    async def get_topic_blueprint(
        self,
        topic_key: str,
        *,
        space_type: str = "personal",
        space_id: str | None = None,
        requested_by: str | None = None,
        force: bool = False,
    ) -> SkillBlueprint:
        return await self.create_or_refresh_blueprint(
            topic_key,
            space_type=space_type,
            space_id=space_id,
            requested_by=requested_by,
            force=force,
        )

    async def get_chapter_content(self, chapter_id: str) -> ChapterContent:
        row = (
            await self.db.execute(
                text(
                    """
                    SELECT
                        sc.chapter_id::text AS chapter_id,
                        sc.title,
                        sc.objective,
                        sc.can_do_after,
                        sc.practice_task,
                        sc.pass_criteria,
                        sc.learning_points,
                        sb.topic_key
                    FROM skill_chapters sc
                    JOIN skill_blueprints sb ON sb.blueprint_id = sc.blueprint_id
                    WHERE sc.chapter_id = CAST(:chapter_id AS uuid)
                    """
                ),
                {"chapter_id": chapter_id},
            )
        ).mappings().first()
        if not row:
            raise ValueError("chapter not found")

        # fetch glossary from chapter entity links instead
        glossary_rows = (
            await self.db.execute(
                text(
                    """
                    SELECT ke.entity_id::text AS entity_id
                    FROM chapter_entity_links cel
                    JOIN knowledge_entities ke ON ke.entity_id = cel.entity_id
                    WHERE cel.chapter_id = CAST(:chapter_id AS uuid)
                    ORDER BY cel.link_role DESC, ke.canonical_name
                    """
                ),
                {"chapter_id": chapter_id},
            )
        ).scalars().all()
        glossary = await self.repo.fetch_glossary([str(x) for x in glossary_rows])

        topic_key = row["topic_key"]
        learning_points = row["learning_points"] or []
        sections = [
            {
                "title": "本章要解决的问题",
                "body": f"这一章围绕 {topic_key} 的一个能力单元展开，目标不是背名词，而是完成一类任务。{row['objective']}",
            },
            {
                "title": "建议学习步骤",
                "body": "\n".join(
                    [f"{idx + 1}. {item}" for idx, item in enumerate(learning_points or [f"围绕 {topic_key} 拆解任务与判断依据。"])]
                ),
            },
            {
                "title": "常见误区",
                "body": f"不要把 {topic_key} 学成术语表。先判断任务目标、输入边界、关键步骤，再回到术语解释。",
            },
            {
                "title": "练习与验收",
                "body": f"练习：{row['practice_task']}\n\n通过标准：{row['pass_criteria']}",
            },
        ]
        return ChapterContent(
            chapter_id=row["chapter_id"],
            title=row["title"],
            objective=row["objective"],
            can_do_after=row["can_do_after"],
            practice_task=row["practice_task"],
            pass_criteria=row["pass_criteria"],
            learning_points=learning_points,
            sections=sections,
            glossary=glossary,
        )

    async def build_learning_path(
        self,
        user_id: str,
        topic_key: str,
        *,
        space_type: str = "personal",
        space_id: str | None = None,
        limit: int = 12,
    ) -> list[PathStep]:
        blueprint = await self.get_topic_blueprint(
            topic_key,
            space_type=space_type,
            space_id=space_id,
            requested_by=user_id,
            force=False,
        )
        steps: list[PathStep] = []
        for stage in blueprint.stages:
            for chapter in stage.chapters:
                steps.append(
                    PathStep(
                        step_id=chapter.chapter_id,
                        type="chapter",
                        title=chapter.title,
                        objective=chapter.objective,
                        topic_key=blueprint.topic_key,
                        chapter_id=chapter.chapter_id,
                        estimated_minutes=chapter.estimated_minutes,
                        unlocked=True,
                        score=1.0,
                    )
                )
        return steps[:limit]

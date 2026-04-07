from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.modules.skill_blueprint.schemas import ChapterContent, SkillBlueprint
from apps.api.modules.skill_blueprint.service import SkillBlueprintService


class TutorialService:
    """
    Skill-first tutorial service.

    关键变化：
    1. 不再按单个 knowledge_entity 直接生成章节。
    2. 章节来自 skill_blueprints -> stages -> chapters。
    3. glossary / 热词只作为章节辅助解释材料。
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.blueprint_service = SkillBlueprintService(db)

    async def list_topics(self, *, user_id: str | None = None, space_type: str | None = None):
        return await self.blueprint_service.list_topics(space_type=space_type)

    async def get_topic_tutorial(
        self,
        topic_key: str,
        *,
        user_id: str | None = None,
        space_type: str = "personal",
        space_id: str | None = None,
        force: bool = False,
    ) -> SkillBlueprint:
        return await self.blueprint_service.get_topic_blueprint(
            topic_key,
            space_type=space_type,
            space_id=space_id,
            requested_by=user_id,
            force=force,
        )

    async def regenerate_topic_tutorial(
        self,
        topic_key: str,
        *,
        user_id: str | None = None,
        space_type: str = "personal",
        space_id: str | None = None,
    ) -> SkillBlueprint:
        return await self.blueprint_service.get_topic_blueprint(
            topic_key,
            space_type=space_type,
            space_id=space_id,
            requested_by=user_id,
            force=True,
        )

    async def get_chapter_content(self, chapter_id: str) -> ChapterContent:
        return await self.blueprint_service.get_chapter_content(chapter_id)

    async def build_learning_path(
        self,
        user_id: str,
        topic_key: str,
        *,
        space_type: str = "personal",
        space_id: str | None = None,
        limit: int = 12,
    ):
        return await self.blueprint_service.build_learning_path(
            user_id,
            topic_key,
            space_type=space_type,
            space_id=space_id,
            limit=limit,
        )

    # Compatibility wrappers for older call sites.
    async def build_skeleton(self, tutorial_id: str, topic_key: str, requesting_user_id: str):
        return await self.regenerate_topic_tutorial(topic_key, user_id=requesting_user_id)

    async def fill_content(self, chapter_id: str):
        return await self.get_chapter_content(chapter_id)

    async def mark_approved(self, tutorial_id: str) -> None:
        return None

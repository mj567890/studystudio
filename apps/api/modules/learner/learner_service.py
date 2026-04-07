from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.modules.skill_blueprint.schemas import PathStep
from apps.api.modules.skill_blueprint.service import SkillBlueprintService


class RepairPathService:
    """
    学习路径不再按 entity 返回，而是按 chapter 返回。
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.blueprint_service = SkillBlueprintService(db)

    async def compute(
        self,
        user_id: str,
        topic_key: str,
        *_,
        limit: int = 12,
        space_type: str = "personal",
        space_id: str | None = None,
        **__,
    ) -> list[PathStep]:
        return await self.blueprint_service.build_learning_path(
            user_id=user_id,
            topic_key=topic_key,
            space_type=space_type,
            space_id=space_id,
            limit=limit,
        )

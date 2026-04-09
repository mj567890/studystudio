from __future__ import annotations
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.modules.skill_blueprint.repository import BlueprintRepository
from apps.api.modules.skill_blueprint.schema import (
    BlueprintOut, BlueprintStatusOut, StageOut, ChapterOut, EntityLinkOut,
)
logger = structlog.get_logger()

class BlueprintService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = BlueprintRepository(db)

    async def get_blueprint(self, topic_key: str) -> BlueprintOut | None:
        bp = await self.repo.get_published_by_topic(topic_key)
        if not bp:
            return None
        stages_raw = await self.repo.get_stages(bp["blueprint_id"])
        stages = []
        for s in stages_raw:
            chapters_raw = await self.repo.get_chapters(s["stage_id"])
            chapters = []
            for c in chapters_raw:
                hw = await self.repo.get_hotwords(c["chapter_id"])
                chapters.append(ChapterOut(**{k: v for k, v in c.items()},
                                           hotwords=[EntityLinkOut(**h) for h in hw]))
            stages.append(StageOut(**{k: v for k, v in s.items()}, chapters=chapters))
        return BlueprintOut(blueprint_id=bp["blueprint_id"], topic_key=bp["topic_key"],
                            title=bp["title"], skill_goal=bp.get("skill_goal"),
                            status=bp["status"], version=bp["version"],
                            stages=stages, created_at=bp["created_at"],
                            updated_at=bp["updated_at"])

    async def get_status(self, topic_key: str) -> BlueprintStatusOut:
        bp = await self.repo.get_by_topic(topic_key)
        if not bp:
            return BlueprintStatusOut(topic_key=topic_key, status="not_found",
                                      message="尚未生成蓝图，请先触发 generate")
        msgs = {"draft": "草稿已创建，等待生成", "generating": "正在后台生成，请稍后刷新",
                "review": "生成完成，等待人工审核后发布", "published": "已发布，教程中心使用此蓝图",
                "archived": "已归档"}
        return BlueprintStatusOut(topic_key=topic_key, status=bp["status"],
                                  blueprint_id=bp["blueprint_id"],
                                  message=msgs.get(bp["status"], bp["status"]))

    async def publish(self, topic_key: str) -> BlueprintStatusOut:
        bp = await self.repo.get_by_topic(topic_key)
        if not bp:
            return BlueprintStatusOut(topic_key=topic_key, status="not_found", message="蓝图不存在")
        if bp["status"] not in ("review", "published"):
            return BlueprintStatusOut(topic_key=topic_key, status=bp["status"],
                                      blueprint_id=bp["blueprint_id"],
                                      message=f"当前状态 {bp['status']} 不可发布，需为 review")
        await self.repo.update_blueprint_status(bp["blueprint_id"], "published")
        await self.db.commit()
        logger.info("Blueprint published", topic_key=topic_key)
        return BlueprintStatusOut(topic_key=topic_key, status="published",
                                  blueprint_id=bp["blueprint_id"],
                                  message="蓝图已发布，教程中心将切换至新结构")

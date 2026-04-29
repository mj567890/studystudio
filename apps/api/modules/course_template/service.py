"""课程模板 — 业务逻辑层"""
from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from .repository import TemplateRepository


class TemplateService:
    def __init__(self, db: AsyncSession):
        self.repo = TemplateRepository(db)

    async def list_templates(self, user_id: str) -> list[dict]:
        return await self.repo.list_for_teacher(user_id)

    async def get_template(self, template_id: str) -> dict | None:
        return await self.repo.get_by_id(template_id)

    async def create_template(self, user_id: str, name: str, content: str,
                               is_public: bool = False) -> dict:
        return await self.repo.create(name, content, is_public, user_id)

    async def update_template(self, user_id: str, template_id: str,
                               **fields) -> dict | None:
        tmpl = await self.repo.get_by_id(template_id)
        if not tmpl:
            return None
        if tmpl["is_system"]:
            raise PermissionError("系统模板不可修改")
        if tmpl["created_by"] != user_id:
            raise PermissionError("只能修改自己的模板")
        return await self.repo.update(template_id, **fields)

    async def delete_template(self, user_id: str, template_id: str) -> bool:
        tmpl = await self.repo.get_by_id(template_id)
        if not tmpl:
            return False
        if tmpl["is_system"]:
            raise PermissionError("系统模板不可删除")
        if tmpl["created_by"] != user_id:
            raise PermissionError("只能删除自己的模板")
        return await self.repo.delete(template_id)

    async def set_space_default_template(self, space_id: str,
                                          template_id: str | None = None,
                                          theory_template_id: str | None = None,
                                          task_template_id: str | None = None,
                                          project_template_id: str | None = None) -> None:
        await self.repo.set_space_default(space_id, template_id,
                                          theory_template_id, task_template_id, project_template_id)

    async def get_space_default_instruction(self, space_id: str) -> str | None:
        return await self.repo.get_space_default_content(space_id)

"""课程模板 — 数据访问层"""
from __future__ import annotations
import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class TemplateRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_for_teacher(self, user_id: str) -> list[dict]:
        """列出用户可见模板：自己的 + 系统默认 + 他人公开"""
        result = await self.db.execute(
            text("""
                SELECT template_id::text, name, content, is_system, is_public,
                       created_by::text, created_at, updated_at
                FROM course_templates
                WHERE is_system = TRUE
                   OR is_public = TRUE
                   OR created_by::text = :uid
                ORDER BY is_system DESC, name ASC
            """),
            {"uid": user_id},
        )
        return [dict(r._mapping) for r in result.fetchall()]

    async def get_by_id(self, template_id: str) -> dict | None:
        result = await self.db.execute(
            text("""
                SELECT template_id::text, name, content, is_system, is_public,
                       created_by::text, created_at, updated_at
                FROM course_templates
                WHERE template_id = CAST(:tid AS uuid)
            """),
            {"tid": template_id},
        )
        row = result.fetchone()
        return dict(row._mapping) if row else None

    async def create(self, name: str, content: str, is_public: bool,
                     created_by: str) -> dict:
        tid = str(uuid.uuid4())
        await self.db.execute(
            text("""
                INSERT INTO course_templates (template_id, name, content, is_public, created_by)
                VALUES (CAST(:tid AS uuid), :name, :content, :is_public, CAST(:uid AS uuid))
            """),
            {"tid": tid, "name": name, "content": content,
             "is_public": is_public, "uid": created_by},
        )
        await self.db.commit()
        return await self.get_by_id(tid)

    async def update(self, template_id: str, **fields) -> dict | None:
        allowed = {"name", "content", "is_public"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return await self.get_by_id(template_id)
        set_clause = ", ".join(f"{k}=:{k}" for k in updates)
        params = {k: v for k, v in updates.items()}
        params["tid"] = template_id
        await self.db.execute(
            text(f"""
                UPDATE course_templates
                SET {set_clause}, updated_at = NOW()
                WHERE template_id = CAST(:tid AS uuid)
            """),
            params,
        )
        await self.db.commit()
        return await self.get_by_id(template_id)

    async def delete(self, template_id: str) -> bool:
        result = await self.db.execute(
            text("""
                DELETE FROM course_templates
                WHERE template_id = CAST(:tid AS uuid)
                  AND is_system = FALSE
            """),
            {"tid": template_id},
        )
        await self.db.commit()
        return result.rowcount > 0

    async def set_space_default(self, space_id: str,
                                 template_id: str | None = None,
                                 theory_template_id: str | None = None,
                                 task_template_id: str | None = None,
                                 project_template_id: str | None = None) -> None:
        # 对每列单独更新——只更新提供的字段，不覆盖未提供字段
        updates = []
        params = {"sid": space_id}
        if template_id is not None or theory_template_id is not None or \
           task_template_id is not None or project_template_id is not None:
            updates.append("updated_at = NOW()")
        if template_id is not None:
            updates.append("default_template_id = CAST(:tid AS uuid)")
            params["tid"] = template_id
        if theory_template_id is not None:
            updates.append("default_theory_template_id = CAST(:ttid AS uuid)")
            params["ttid"] = theory_template_id
        if task_template_id is not None:
            updates.append("default_task_template_id = CAST(:taid AS uuid)")
            params["taid"] = task_template_id
        if project_template_id is not None:
            updates.append("default_project_template_id = CAST(:pid AS uuid)")
            params["pid"] = project_template_id
        if updates:
            await self.db.execute(
                text(f"UPDATE knowledge_spaces SET {', '.join(updates)} "
                     "WHERE space_id = CAST(:sid AS uuid)"),
                params,
            )
            await self.db.commit()

    async def get_space_default_content(self, space_id: str) -> str | None:
        result = await self.db.execute(
            text("""
                SELECT ct.content
                FROM knowledge_spaces ks
                JOIN course_templates ct
                  ON ct.template_id = ks.default_template_id
                WHERE ks.space_id = CAST(:sid AS uuid)
            """),
            {"sid": space_id},
        )
        row = result.fetchone()
        return row[0] if row else None

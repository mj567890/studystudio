"""
apps/api/modules/space/repository.py
知识空间数据访问层（Phase 1：多成员 + 邀请码）
"""
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _uid(value: str | UUID) -> str:
    return str(UUID(str(value)))


class SpaceRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # -- 查询 ----------------------------------------------------------------

    async def list_accessible_spaces(self, user_id: str | UUID) -> list[dict]:
        """返回用户可访问的所有 space:成员身份所在的 space + 所有 global 空间。"""
        uid = _uid(user_id)
        result = await self.db.execute(
            text("""
                SELECT
                    ks.space_id::text   AS space_id,
                    ks.space_type       AS space_type,
                    ks.owner_id::text   AS owner_id,
                    ks.name             AS name,
                    ks.description      AS description,
                    ks.visibility       AS visibility,
                    ks.invite_code      AS invite_code,
                    ks.created_at       AS created_at,
                    ks.updated_at       AS updated_at,
                    ks.fork_from_space_id::text AS fork_from_space_id,
                    sm.role             AS my_role,
                    (SELECT count(*) FROM space_members sm2
                     WHERE sm2.space_id = ks.space_id) AS member_count
                FROM   knowledge_spaces ks
                LEFT JOIN space_members sm
                       ON sm.space_id = ks.space_id
                      AND sm.user_id  = CAST(:uid AS uuid)
                WHERE  sm.user_id IS NOT NULL
                   OR  ks.space_type = 'global'
                ORDER BY
                    CASE ks.space_type WHEN 'global' THEN 0 ELSE 1 END,
                    ks.created_at DESC
            """),
            {"uid": uid},
        )
        return [self._row_to_space(r) for r in result.fetchall()]

    async def get_space_with_role(
        self, space_id: str | UUID, user_id: str | UUID
    ) -> dict | None:
        sid = _uid(space_id)
        uid = _uid(user_id)
        result = await self.db.execute(
            text("""
                SELECT
                    ks.space_id::text   AS space_id,
                    ks.space_type       AS space_type,
                    ks.owner_id::text   AS owner_id,
                    ks.name             AS name,
                    ks.description      AS description,
                    ks.visibility       AS visibility,
                    ks.invite_code      AS invite_code,
                    ks.created_at       AS created_at,
                    ks.updated_at       AS updated_at,
                    ks.fork_from_space_id::text AS fork_from_space_id,
                    sm.role             AS my_role,
                    (SELECT count(*) FROM space_members sm2
                     WHERE sm2.space_id = ks.space_id) AS member_count
                FROM   knowledge_spaces ks
                LEFT JOIN space_members sm
                       ON sm.space_id = ks.space_id
                      AND sm.user_id  = CAST(:uid AS uuid)
                WHERE  ks.space_id = CAST(:sid AS uuid)
            """),
            {"sid": sid, "uid": uid},
        )
        row = result.fetchone()
        return self._row_to_space(row) if row else None

    async def get_member_role(
        self, space_id: str | UUID, user_id: str | UUID
    ) -> str | None:
        sid = _uid(space_id)
        uid = _uid(user_id)
        result = await self.db.execute(
            text("""
                SELECT role FROM space_members
                WHERE  space_id = CAST(:sid AS uuid)
                  AND  user_id  = CAST(:uid AS uuid)
            """),
            {"sid": sid, "uid": uid},
        )
        row = result.fetchone()
        return row.role if row else None

    async def list_members(self, space_id: str | UUID) -> list[dict]:
        sid = _uid(space_id)
        result = await self.db.execute(
            text("""
                SELECT
                    sm.user_id::text AS user_id,
                    u.nickname       AS nickname,
                    u.email          AS email,
                    u.avatar_url     AS avatar_url,
                    sm.role          AS role,
                    sm.joined_at     AS joined_at
                FROM   space_members sm
                JOIN   users u ON u.user_id = sm.user_id
                WHERE  sm.space_id = CAST(:sid AS uuid)
                ORDER BY
                    CASE sm.role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END,
                    sm.joined_at ASC
            """),
            {"sid": sid},
        )
        return [
            {
                "user_id":    r.user_id,
                "nickname":   r.nickname,
                "email":      r.email,
                "avatar_url": r.avatar_url,
                "role":       r.role,
                "joined_at":  r.joined_at.isoformat() if r.joined_at else None,
            }
            for r in result.fetchall()
        ]

    async def find_space_by_invite_code(self, code: str) -> dict | None:
        result = await self.db.execute(
            text("""
                SELECT space_id::text AS space_id, name, visibility
                FROM   knowledge_spaces
                WHERE  invite_code = :code
            """),
            {"code": code},
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "space_id":   row.space_id,
            "name":       row.name,
            "visibility": row.visibility,
        }

    async def count_owners(self, space_id: str | UUID) -> int:
        sid = _uid(space_id)
        result = await self.db.execute(
            text("""
                SELECT count(*) AS cnt FROM space_members
                WHERE  space_id = CAST(:sid AS uuid) AND role = 'owner'
            """),
            {"sid": sid},
        )
        row = result.fetchone()
        return int(row.cnt) if row else 0

    async def is_invite_code_taken(self, code: str) -> bool:
        result = await self.db.execute(
            text("SELECT 1 FROM knowledge_spaces WHERE invite_code = :code"),
            {"code": code},
        )
        return result.fetchone() is not None


    async def create_space(
        self,
        space_id: str,
        space_type: str,
        owner_id: str,
        name: str,
        description: str | None,
    ) -> None:
        await self.db.execute(
            text("""
                INSERT INTO knowledge_spaces
                    (space_id, space_type, owner_id, name, description)
                VALUES (
                    CAST(:sid AS uuid), :space_type,
                    CAST(:owner_id AS uuid), :name, :description
                )
                ON CONFLICT (space_id) DO NOTHING
            """),
            {"sid": space_id, "space_type": space_type,
             "owner_id": owner_id, "name": name, "description": description},
        )

    # -- 变更 ----------------------------------------------------------------

    async def update_space(
        self,
        space_id: str | UUID,
        name: str | None,
        description: str | None,
        visibility: str | None,
    ) -> None:
        sid = _uid(space_id)
        sets: list[str] = []
        params: dict[str, Any] = {"sid": sid}
        if name is not None:
            sets.append("name = :name")
            params["name"] = name
        if description is not None:
            sets.append("description = :description")
            params["description"] = description
        if visibility is not None:
            sets.append("visibility = :visibility")
            params["visibility"] = visibility
        if not sets:
            return
        sets.append("updated_at = now()")
        sql = (
            "UPDATE knowledge_spaces SET "
            + ", ".join(sets)
            + " WHERE space_id = CAST(:sid AS uuid)"
        )
        await self.db.execute(text(sql), params)

    async def set_invite_code(self, space_id: str | UUID, code: str | None) -> None:
        sid = _uid(space_id)
        await self.db.execute(
            text("""
                UPDATE knowledge_spaces
                SET    invite_code = :code, updated_at = now()
                WHERE  space_id = CAST(:sid AS uuid)
            """),
            {"sid": sid, "code": code},
        )

    async def add_member(
        self, space_id: str | UUID, user_id: str | UUID, role: str = "member"
    ) -> bool:
        """新增成员。True=新插入，False=已是成员。"""
        sid = _uid(space_id)
        uid = _uid(user_id)
        result = await self.db.execute(
            text("""
                INSERT INTO space_members (space_id, user_id, role)
                VALUES (CAST(:sid AS uuid), CAST(:uid AS uuid), :role)
                ON CONFLICT (space_id, user_id) DO NOTHING
                RETURNING user_id
            """),
            {"sid": sid, "uid": uid, "role": role},
        )
        return result.fetchone() is not None

    async def remove_member(
        self, space_id: str | UUID, user_id: str | UUID
    ) -> bool:
        sid = _uid(space_id)
        uid = _uid(user_id)
        result = await self.db.execute(
            text("""
                DELETE FROM space_members
                WHERE  space_id = CAST(:sid AS uuid)
                  AND  user_id  = CAST(:uid AS uuid)
                RETURNING user_id
            """),
            {"sid": sid, "uid": uid},
        )
        return result.fetchone() is not None


    # -- 订阅 ----------------------------------------------------------------

    async def subscribe(
        self, subscriber_id: str, space_id: str, topic_key: str, version: int
    ) -> bool:
        """订阅。True=新建，False=已存在（更新版本号）。"""
        result = await self.db.execute(
            text("""
                INSERT INTO space_subscriptions
                    (subscriber_id, space_id, topic_key, subscribed_version)
                VALUES (
                    CAST(:uid AS uuid), CAST(:sid AS uuid), :tk, :ver
                )
                ON CONFLICT (subscriber_id, space_id, topic_key)
                DO UPDATE SET subscribed_version = :ver, updated_at = now()
                RETURNING (xmax = 0) AS inserted
            """),
            {"uid": subscriber_id, "sid": space_id, "tk": topic_key, "ver": version},
        )
        row = result.fetchone()
        return bool(row.inserted) if row else False

    async def unsubscribe(
        self, subscriber_id: str, space_id: str, topic_key: str
    ) -> bool:
        result = await self.db.execute(
            text("""
                DELETE FROM space_subscriptions
                WHERE subscriber_id = CAST(:uid AS uuid)
                  AND space_id      = CAST(:sid AS uuid)
                  AND topic_key     = :tk
                RETURNING subscription_id
            """),
            {"uid": subscriber_id, "sid": space_id, "tk": topic_key},
        )
        return result.fetchone() is not None

    async def get_subscription(
        self, subscriber_id: str, space_id: str, topic_key: str
    ) -> dict | None:
        result = await self.db.execute(
            text("""
                SELECT subscription_id::text, subscriber_id::text, space_id::text,
                       topic_key, subscribed_version, created_at, updated_at
                FROM space_subscriptions
                WHERE subscriber_id = CAST(:uid AS uuid)
                  AND space_id      = CAST(:sid AS uuid)
                  AND topic_key     = :tk
            """),
            {"uid": subscriber_id, "sid": space_id, "tk": topic_key},
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "subscription_id":    row.subscription_id,
            "space_id":           row.space_id,
            "topic_key":          row.topic_key,
            "subscribed_version": row.subscribed_version,
            "created_at":         row.created_at.isoformat() if row.created_at else None,
        }

    async def list_subscriptions(self, subscriber_id: str) -> list[dict]:
        result = await self.db.execute(
            text("""
                SELECT ss.subscription_id::text, ss.space_id::text,
                       ss.topic_key, ss.subscribed_version,
                       ks.name AS space_name,
                       sb.version AS current_version,
                       sb.title   AS blueprint_title
                FROM space_subscriptions ss
                JOIN knowledge_spaces ks ON ks.space_id = ss.space_id
                LEFT JOIN skill_blueprints sb
                       ON sb.topic_key = ss.topic_key
                      AND sb.status    = 'published'
                WHERE ss.subscriber_id = CAST(:uid AS uuid)
                ORDER BY ss.created_at DESC
            """),
            {"uid": subscriber_id},
        )
        rows = result.fetchall()
        return [
            {
                "subscription_id":    r.subscription_id,
                "space_id":           r.space_id,
                "space_name":         r.space_name,
                "topic_key":          r.topic_key,
                "subscribed_version": r.subscribed_version,
                "current_version":    r.current_version,
                "blueprint_title":    r.blueprint_title,
                "has_update":         (r.current_version or 0) > r.subscribed_version,
            }
            for r in rows
        ]

    # -- 内部 ----------------------------------------------------------------

    @staticmethod
    def _row_to_space(row: Any) -> dict:
        return {
            "space_id":    row.space_id,
            "space_type":  row.space_type,
            "owner_id":    row.owner_id,
            "name":        row.name,
            "description": row.description,
            "visibility":  row.visibility,
            "invite_code": row.invite_code,
            "created_at":  row.created_at.isoformat() if row.created_at else None,
            "updated_at":  row.updated_at.isoformat() if row.updated_at else None,
            "my_role":     getattr(row, "my_role", None),
            "member_count": int(getattr(row, "member_count", 0) or 0),
            "fork_from_space_id": getattr(row, "fork_from_space_id", None),
        }

    # -- fork --

    async def create_fork_task(
        self,
        task_id: str,
        source_space_id: str,
        target_space_id: str,
        requested_by: str,
    ) -> None:
        await self.db.execute(
            text("""
                INSERT INTO fork_tasks
                    (task_id, source_space_id, target_space_id,
                     requested_by, status)
                VALUES (
                    CAST(:tid AS uuid), CAST(:src AS uuid),
                    CAST(:tgt AS uuid), CAST(:uid AS uuid),
                    'pending'
                )
            """),
            {
                "tid": task_id,
                "src": source_space_id,
                "tgt": target_space_id,
                "uid": requested_by,
            },
        )

    async def get_fork_task(self, task_id: str) -> dict | None:
        result = await self.db.execute(
            text("""
                SELECT task_id::text, source_space_id::text,
                       target_space_id::text, requested_by::text,
                       status, error_msg, created_at, updated_at
                FROM fork_tasks
                WHERE task_id = CAST(:tid AS uuid)
            """),
            {"tid": task_id},
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "task_id":         row.task_id,
            "source_space_id": row.source_space_id,
            "target_space_id": row.target_space_id,
            "requested_by":    row.requested_by,
            "status":          row.status,
            "error_msg":       row.error_msg,
            "created_at":      row.created_at.isoformat() if row.created_at else None,
            "updated_at":      row.updated_at.isoformat() if row.updated_at else None,
        }

    async def set_fork_space_id(
        self, task_id: str, target_space_id: str
    ) -> None:
        await self.db.execute(
            text("""
                UPDATE fork_tasks
                SET target_space_id = CAST(:tgt AS uuid), updated_at = now()
                WHERE task_id = CAST(:tid AS uuid)
            """),
            {"tgt": target_space_id, "tid": task_id},
        )


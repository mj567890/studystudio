"""
apps/api/modules/space/service.py
知识空间业务层（Phase 1）
"""
import secrets
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.modules.space.repository import SpaceRepository

logger = structlog.get_logger(__name__)

# 邀请码字符集：排除易混字符 0/O/1/l/I
_INVITE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_INVITE_CODE_LENGTH = 8
_VALID_VISIBILITIES = {"private", "shared", "public"}


class SpaceError(ValueError):
    """space 业务错误，携带 code 便于路由层映射 HTTP 状态。"""
    def __init__(self, code: str, msg: str) -> None:
        super().__init__(msg)
        self.code = code
        self.msg = msg


def _generate_invite_code() -> str:
    return "".join(
        secrets.choice(_INVITE_CODE_ALPHABET) for _ in range(_INVITE_CODE_LENGTH)
    )


class SpaceService:
    MANAGER_ROLES = {"owner", "admin"}

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = SpaceRepository(db)

    # -- 查询 ----------------------------------------------------------------

    async def list_my_spaces(self, user_id: str | UUID) -> list[dict]:
        spaces = await self.repo.list_accessible_spaces(user_id)
        for s in spaces:
            if s.get("my_role") not in self.MANAGER_ROLES:
                s["invite_code"] = None
        return spaces

    async def get_space_detail(
        self, space_id: str | UUID, user_id: str | UUID
    ) -> dict:
        space = await self.repo.get_space_with_role(space_id, user_id)
        if not space:
            raise SpaceError("SPACE_404", "Space not found")
        if not space.get("my_role"):
            raise SpaceError("SPACE_403", "You are not a member of this space")
        if space["my_role"] not in self.MANAGER_ROLES:
            space["invite_code"] = None
        return space

    async def list_members(
        self, space_id: str | UUID, user_id: str | UUID
    ) -> list[dict]:
        role = await self.repo.get_member_role(space_id, user_id)
        if not role:
            raise SpaceError("SPACE_403", "You are not a member of this space")
        return await self.repo.list_members(space_id)


    async def create_space(
        self,
        user_id: str,
        name: str,
        space_type: str = "personal",
        description: str | None = None,
    ) -> dict:
        import uuid as _uuid
        name = " ".join((name or "").split()).strip()
        if not name:
            raise SpaceError("SPACE_400", "Space name is required")
        if space_type not in ("global", "personal", "course"):
            raise SpaceError("SPACE_400", "Invalid space_type")

        # 重名检查
        from sqlalchemy import text as _t
        if space_type == "global":
            dup = await self.db.execute(
                _t("SELECT space_id::text FROM knowledge_spaces "
                   "WHERE space_type='global' AND name=:name LIMIT 1"),
                {"name": name},
            )
        else:
            dup = await self.db.execute(
                _t("SELECT space_id::text FROM knowledge_spaces "
                   "WHERE space_type=:st AND owner_id=CAST(:uid AS uuid) AND name=:name LIMIT 1"),
                {"st": space_type, "uid": user_id, "name": name},
            )
        row = dup.fetchone()
        if row:
            # 已存在则补插 owner 记录（幂等），保证 space_members 一致
            await self.repo.add_member(row.space_id, user_id, role="owner")
            await self.db.commit()
            return await self.repo.get_space_with_role(row.space_id, user_id)

        space_id = str(_uuid.uuid4())
        await self.repo.create_space(space_id, space_type, user_id, name, description)
        await self.repo.add_member(space_id, user_id, role="owner")
        await self.db.commit()
        logger.info("Space created", space_id=space_id, space_type=space_type, name=name)
        return await self.repo.get_space_with_role(space_id, user_id)

    # -- 变更 ----------------------------------------------------------------

    async def update_space(
        self,
        space_id: str | UUID,
        user_id: str | UUID,
        name: str | None,
        description: str | None,
        visibility: str | None,
    ) -> dict:
        await self._require_manager(space_id, user_id)
        if visibility is not None and visibility not in _VALID_VISIBILITIES:
            raise SpaceError("SPACE_400", f"Invalid visibility: {visibility}")
        await self.repo.update_space(space_id, name, description, visibility)
        await self.db.commit()
        return await self.get_space_detail(space_id, user_id)

    async def reset_invite_code(
        self, space_id: str | UUID, user_id: str | UUID
    ) -> str:
        await self._require_manager(space_id, user_id)
        for _ in range(5):
            code = _generate_invite_code()
            if not await self.repo.is_invite_code_taken(code):
                await self.repo.set_invite_code(space_id, code)
                await self.db.commit()
                logger.info("Invite code reset", space_id=str(space_id))
                return code
        raise SpaceError("SPACE_500", "Failed to generate unique invite code")

    async def revoke_invite_code(
        self, space_id: str | UUID, user_id: str | UUID
    ) -> None:
        await self._require_manager(space_id, user_id)
        await self.repo.set_invite_code(space_id, None)
        await self.db.commit()
        logger.info("Invite code revoked", space_id=str(space_id))

    async def join_by_invite_code(
        self, code: str, user_id: str | UUID
    ) -> dict:
        code = (code or "").strip().upper()
        if not code:
            raise SpaceError("SPACE_400", "Invite code is required")
        space = await self.repo.find_space_by_invite_code(code)
        if not space:
            raise SpaceError("SPACE_404", "Invalid or expired invite code")
        inserted = await self.repo.add_member(
            space["space_id"], user_id, role="member"
        )
        await self.db.commit()
        logger.info(
            "User joined space via invite",
            space_id=space["space_id"],
            user_id=str(user_id),
            new=inserted,
        )
        return {
            "space_id":       space["space_id"],
            "space_name":     space["name"],
            "already_member": not inserted,
        }

    async def remove_member(
        self,
        space_id: str | UUID,
        target_user_id: str | UUID,
        current_user_id: str | UUID,
    ) -> None:
        current_role = await self.repo.get_member_role(space_id, current_user_id)
        if not current_role:
            raise SpaceError("SPACE_403", "You are not a member of this space")

        target_role = await self.repo.get_member_role(space_id, target_user_id)
        if not target_role:
            raise SpaceError("SPACE_404", "Target user is not a member")

        is_self = str(target_user_id) == str(current_user_id)

        if is_self:
            # 退出空间
            if target_role == "owner":
                owners = await self.repo.count_owners(space_id)
                if owners <= 1:
                    raise SpaceError(
                        "SPACE_409",
                        "Last owner cannot leave the space. "
                        "Transfer ownership or delete the space first.",
                    )
        else:
            # 踢人：只有 owner/admin 能踢；owner 不可被踢
            if current_role not in self.MANAGER_ROLES:
                raise SpaceError(
                    "SPACE_403", "Only owner or admin can remove members"
                )
            if target_role == "owner":
                raise SpaceError("SPACE_403", "Cannot remove an owner")

        await self.repo.remove_member(space_id, target_user_id)
        await self.db.commit()
        logger.info(
            "Member removed",
            space_id=str(space_id),
            target_user=str(target_user_id),
            by=str(current_user_id),
            self_leave=is_self,
        )


    async def subscribe_topic(
        self, user_id: str, space_id: str, topic_key: str
    ) -> dict:
        """订阅某 space 下的 topic，记录当前 blueprint 版本号。"""
        from sqlalchemy import text as _t
        # 检查 space 存在且用户是成员
        space = await self.repo.get_space_with_role(space_id, user_id)
        if not space:
            raise SpaceError("SPACE_404", "Space not found")
        if not space.get("my_role"):
            raise SpaceError("SPACE_403", "You are not a member of this space")

        # 取当前 published blueprint 版本（skill_blueprints 表已废弃，默认版本为 1）
        from sqlalchemy.exc import ProgrammingError
        version = 1
        try:
            r = await self.db.execute(
                _t("SELECT version FROM skill_blueprints "
                   "WHERE topic_key=:tk AND space_id=CAST(:sid AS uuid) AND status='published' "
                   "ORDER BY version DESC LIMIT 1"),
                {"tk": topic_key, "sid": space_id}
            )
            row = r.fetchone()
            version = row.version if row else 1
        except ProgrammingError:
            pass

        await self.repo.subscribe(user_id, space_id, topic_key, version)
        await self.db.commit()
        logger.info("Subscribed", user_id=user_id, topic_key=topic_key, version=version)
        return await self.repo.get_subscription(user_id, space_id, topic_key)

    async def unsubscribe_topic(
        self, user_id: str, space_id: str, topic_key: str
    ) -> None:
        deleted = await self.repo.unsubscribe(user_id, space_id, topic_key)
        if not deleted:
            raise SpaceError("SPACE_404", "Subscription not found")
        await self.db.commit()
        logger.info("Unsubscribed", user_id=user_id, topic_key=topic_key)

    async def check_update(
        self, user_id: str, space_id: str, topic_key: str
    ) -> dict:
        """检查订阅的 blueprint 是否有新版本。"""
        sub = await self.repo.get_subscription(user_id, space_id, topic_key)
        if not sub:
            return {"subscribed": False}
        from sqlalchemy import text as _t
        from sqlalchemy.exc import ProgrammingError
        current = sub["subscribed_version"]
        blueprint_title = None
        try:
            r = await self.db.execute(
                _t("SELECT version, title FROM skill_blueprints "
                   "WHERE topic_key=:tk AND space_id=CAST(:sid AS uuid) AND status='published' "
                   "ORDER BY version DESC LIMIT 1"),
                {"tk": topic_key, "sid": space_id}
            )
            row = r.fetchone()
            if row:
                current = row.version
                blueprint_title = row.title
        except ProgrammingError:
            pass
        return {
            "subscribed":         True,
            "subscribed_version": sub["subscribed_version"],
            "current_version":    current,
            "has_update":         current > sub["subscribed_version"],
            "blueprint_title":    blueprint_title,
        }

    async def ack_update(
        self, user_id: str, space_id: str, topic_key: str
    ) -> dict:
        """用户确认查看更新后，把 subscribed_version 推进到最新。"""
        from sqlalchemy import text as _t
        from sqlalchemy.exc import ProgrammingError
        version = None
        try:
            r = await self.db.execute(
                _t("SELECT version FROM skill_blueprints "
                   "WHERE topic_key=:tk AND space_id=CAST(:sid AS uuid) AND status='published' "
                   "ORDER BY version DESC LIMIT 1"),
                {"tk": topic_key, "sid": space_id}
            )
            row = r.fetchone()
            if row:
                version = row.version
        except ProgrammingError:
            pass
        if not version:
            version = 1
        await self.repo.subscribe(user_id, space_id, topic_key, version)
        await self.db.commit()
        return {"subscribed_version": row.version}

    async def list_subscriptions(self, user_id: str) -> list[dict]:
        return await self.repo.list_subscriptions(user_id)


    async def require_space_access(
        self, space_id: str, user_id: str
    ) -> None:
        """校验用户是否有权访问该 space。global space 对所有登录用户开放。"""
        from sqlalchemy import text as _t
        row = await self.db.execute(
            _t("SELECT space_type FROM knowledge_spaces WHERE space_id=CAST(:sid AS uuid)"),
            {"sid": space_id}
        )
        r = row.fetchone()
        if not r:
            raise SpaceError("SPACE_404", "Space not found")
        if r.space_type == "global":
            return  # global space 公开
        role = await self.repo.get_member_role(space_id, user_id)
        if not role:
            raise SpaceError("SPACE_403", "You are not a member of this space")

    # -- 内部 ----------------------------------------------------------------

    async def _require_manager(
        self, space_id: str | UUID, user_id: str | UUID
    ) -> str:
        role = await self.repo.get_member_role(space_id, user_id)
        if not role:
            raise SpaceError("SPACE_403", "You are not a member of this space")
        if role not in self.MANAGER_ROLES:
            raise SpaceError(
                "SPACE_403", "Only owner or admin can perform this action"
            )
        return role

    # -- fork_space --

    async def fork_space(
        self,
        source_space_id: str,
        user_id: str,
        new_name: str | None = None,
    ) -> dict:
        """
        Fork 一个 space：
        1. 校验用户有权访问源 space
        2. 创建新 space（fork_from_space_id 指向源）
        3. 写 fork_tasks 记录
        4. 投递 Celery 异步任务
        5. 返回 { task_id, target_space_id }
        """
        import uuid as _uuid
        from sqlalchemy import text as _t

        # 校验源 space 存在且用户有访问权
        row = await self.db.execute(
            _t("SELECT space_type, name FROM knowledge_spaces "
               "WHERE space_id = CAST(:sid AS uuid)"),
            {"sid": source_space_id},
        )
        src = row.fetchone()
        if not src:
            raise SpaceError("SPACE_404", "Source space not found")

        if src.space_type != "global":
            role = await self.repo.get_member_role(source_space_id, user_id)
            if not role:
                raise SpaceError("SPACE_403",
                                 "You do not have access to this space")

        # 新 space 名称
        fork_name = new_name or f"[Fork] {src.name}"

        # 创建目标 space
        target_space_id = str(_uuid.uuid4())
        await self.db.execute(
            _t("""
                INSERT INTO knowledge_spaces
                    (space_id, space_type, owner_id, name,
                     description, visibility, fork_from_space_id)
                VALUES (
                    CAST(:sid AS uuid), 'personal',
                    CAST(:uid AS uuid), :name,
                    :desc, 'private',
                    CAST(:fsid AS uuid)
                )
            """),
            {
                "sid":  target_space_id,
                "uid":  user_id,
                "name": fork_name,
                "desc": f"Forked from space {source_space_id}",
                "fsid": source_space_id,
            },
        )
        await self.repo.add_member(target_space_id, user_id, role="owner")

        # 写 fork_task 记录
        task_id = str(_uuid.uuid4())
        await self.repo.create_fork_task(
            task_id, source_space_id, target_space_id, user_id
        )

        await self.db.commit()

        # 投递 Celery 任务
        from apps.api.tasks.fork_tasks import fork_space_task
        fork_space_task.apply_async(
            args=[task_id, source_space_id, target_space_id, user_id],
            queue="low_priority",
        )

        logger.info("Fork initiated",
                    task_id=task_id,
                    source=source_space_id,
                    target=target_space_id,
                    user=user_id)

        return {
            "task_id":          task_id,
            "target_space_id":  target_space_id,
            "target_space_name": fork_name,
        }

    async def get_fork_status(self, task_id: str, user_id: str) -> dict:
        """查询 fork 任务状态。"""
        task = await self.repo.get_fork_task(task_id)
        if not task:
            raise SpaceError("SPACE_404", "Fork task not found")
        if task["requested_by"] != user_id:
            raise SpaceError("SPACE_403", "Access denied")
        return task


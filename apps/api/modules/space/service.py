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
        visibility: str | None = None,
        allow_fork: bool | None = None,
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
        await self.repo.create_space(space_id, space_type, user_id, name, description, visibility, allow_fork)
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
        allow_fork: bool | None = None,
    ) -> dict:
        await self._require_manager(space_id, user_id)
        if visibility is not None and visibility not in _VALID_VISIBILITIES:
            raise SpaceError("SPACE_400", f"Invalid visibility: {visibility}")
        await self.repo.update_space(space_id, name, description, visibility, allow_fork)
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
            _t("SELECT space_type FROM knowledge_spaces "
               "WHERE space_id=CAST(:sid AS uuid) AND deleted_at IS NULL"),
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

    # -- 删除 / 回收站 --------------------------------------------------------

    async def soft_delete_space(
        self, space_id: str | UUID, user_id: str | UUID
    ) -> dict:
        """软删除：将空间移入回收站。"""
        sid = str(space_id)
        uid = str(user_id)
        await self._require_manager(sid, uid)

        fork_count = await self.repo.count_direct_forks(sid)

        await self.repo.soft_delete_space(sid, uid)
        await self.db.commit()

        logger.info("Space soft-deleted", space_id=sid, user_id=uid,
                     fork_count=fork_count)

        return {
            "space_id":             sid,
            "fork_count":           fork_count,
            "can_permanent_delete": fork_count == 0,
        }

    async def restore_space(
        self, space_id: str | UUID, user_id: str | UUID
    ) -> dict:
        """从回收站还原空间。"""
        sid = str(space_id)
        uid = str(user_id)

        trash = await self.repo.get_trash_space(sid, uid)
        if not trash:
            raise SpaceError("SPACE_404", "空间不在回收站中或无权操作")

        await self.repo.restore_space(sid)
        await self.db.commit()

        logger.info("Space restored", space_id=sid, user_id=uid)
        return await self.get_space_detail(sid, uid)

    async def permanent_delete_space(
        self, space_id: str | UUID, user_id: str | UUID
    ) -> dict:
        """彻底删除空间（级联清理所有数据）。"""
        sid = str(space_id)
        uid = str(user_id)
        await self._require_manager(sid, uid)

        # 检查 fork 引用
        fork_count = await self.repo.count_direct_forks(sid)
        if fork_count > 0:
            raise SpaceError(
                "SPACE_409",
                f"此资料库被 {fork_count} 人 fork，无法彻底删除。"
                "文档仍被引用，已改为软删除。"
            )

        # 收集 MinIO 文件列表（事务外清理）
        file_urls = await self.repo.get_space_documents(sid)

        # 事务内级联清理
        from sqlalchemy import text as _t

        # 按依赖顺序：先删子表引用，再删主表
        delete_queries = [
            # 通知
            _t("DELETE FROM user_notifications WHERE target_type='space' AND target_id=CAST(:sid AS uuid)"),
            # 对话轮次（需先于 conversations 删除）
            _t("DELETE FROM conversation_turns WHERE conversation_id IN "
               "(SELECT conversation_id FROM conversations WHERE space_id = CAST(:sid AS uuid))"),
            # 对话
            _t("DELETE FROM conversations WHERE space_id = CAST(:sid AS uuid)"),
            # 讨论回复
            _t("DELETE FROM course_post_replies WHERE post_id IN "
               "(SELECT post_id FROM course_posts WHERE space_id = CAST(:sid AS uuid))"),
            # 讨论帖
            _t("DELETE FROM course_posts WHERE space_id = CAST(:sid AS uuid)"),
            # 学习墙回复
            _t("DELETE FROM wall_replies WHERE post_id IN "
               "(SELECT post_id FROM wall_posts WHERE space_id = CAST(:sid AS uuid))"),
            # 学习墙
            _t("DELETE FROM wall_posts WHERE space_id = CAST(:sid AS uuid)"),
            # 社区策展
            _t("DELETE FROM community_curations WHERE space_id = CAST(:sid AS uuid)"),
            # 笔记实体链接（通过 entity -> space 关联）
            _t("DELETE FROM note_entity_links WHERE entity_id IN "
               "(SELECT entity_id FROM knowledge_entities WHERE space_id = CAST(:sid AS uuid))"),
            # 个人实体引用
            _t("DELETE FROM personal_entity_references WHERE ref_entity_id IN "
               "(SELECT entity_id FROM knowledge_entities WHERE space_id = CAST(:sid AS uuid))"),
            # 知识点掌握状态
            _t("DELETE FROM learner_knowledge_states WHERE entity_id IN "
               "(SELECT entity_id FROM knowledge_entities WHERE space_id = CAST(:sid AS uuid))"),
            # 测验（通过 chapter -> blueprint -> space 关联）
            _t("DELETE FROM chapter_quiz_attempts WHERE chapter_id IN "
               "(SELECT chapter_id::text FROM skill_chapters sc "
               "JOIN skill_blueprints sb ON sb.blueprint_id = sc.blueprint_id "
               "WHERE sb.space_id = CAST(:sid AS uuid))"),
            # 学习进度
            _t("DELETE FROM chapter_progress WHERE chapter_id IN "
               "(SELECT chapter_id::text FROM skill_chapters sc "
               "JOIN skill_blueprints sb ON sb.blueprint_id = sc.blueprint_id "
               "WHERE sb.space_id = CAST(:sid AS uuid))"),
            # 章末反思
            _t("DELETE FROM chapter_reflections WHERE chapter_id IN "
               "(SELECT chapter_id::text FROM skill_chapters sc "
               "JOIN skill_blueprints sb ON sb.blueprint_id = sc.blueprint_id "
               "WHERE sb.space_id = CAST(:sid AS uuid))"),
            # 章节实体链接
            _t("DELETE FROM chapter_entity_links WHERE chapter_id IN "
               "(SELECT chapter_id FROM skill_chapters sc "
               "JOIN skill_blueprints sb ON sb.blueprint_id = sc.blueprint_id "
               "WHERE sb.space_id = CAST(:sid AS uuid))"),
            # 各层结构
            _t("DELETE FROM skill_chapters WHERE blueprint_id IN "
               "(SELECT blueprint_id FROM skill_blueprints WHERE space_id = CAST(:sid AS uuid))"),
            _t("DELETE FROM skill_stages WHERE blueprint_id IN "
               "(SELECT blueprint_id FROM skill_blueprints WHERE space_id = CAST(:sid AS uuid))"),
            _t("DELETE FROM skill_blueprints WHERE space_id = CAST(:sid AS uuid)"),
            # tutorial_contents（需先于 tutorial_skeletons 删除）
            _t("DELETE FROM tutorial_contents WHERE tutorial_id IN "
               "(SELECT tutorial_id FROM tutorial_skeletons WHERE space_id = CAST(:sid AS uuid))"),
            _t("DELETE FROM tutorial_skeletons WHERE space_id = CAST(:sid AS uuid)"),
            # 知识点关系（含临时表）
            _t("DELETE FROM knowledge_relations WHERE source_entity_id IN "
               "(SELECT entity_id FROM knowledge_entities WHERE space_id = CAST(:sid AS uuid))"),
            _t("DELETE FROM knowledge_relations_temp WHERE source_entity_id IN "
               "(SELECT entity_id FROM knowledge_entities WHERE space_id = CAST(:sid AS uuid))"),
            # 知识点
            _t("DELETE FROM knowledge_entities WHERE space_id = CAST(:sid AS uuid)"),
            # 临时表（提取过程中的中间数据）
            _t("DELETE FROM knowledge_entities_temp WHERE space_id = CAST(:sid AS uuid)"),
            # 文档分块
            _t("DELETE FROM document_chunks WHERE document_id IN "
               "(SELECT document_id FROM documents WHERE space_id = CAST(:sid AS uuid))"),
            # 文档
            _t("DELETE FROM documents WHERE space_id = CAST(:sid AS uuid)"),
            # 文档共享引用（源空间删除时清理）
            _t("DELETE FROM space_document_access WHERE source_space_id = CAST(:sid AS uuid)"),
            # fork 任务
            _t("DELETE FROM fork_tasks WHERE source_space_id = CAST(:sid AS uuid)"),
            # 订阅
            _t("DELETE FROM space_subscriptions WHERE space_id = CAST(:sid AS uuid)"),
            # 成员
            _t("DELETE FROM space_members WHERE space_id = CAST(:sid AS uuid)"),
            # 取消运行中任务
            _t("UPDATE task_executions SET status='cancelled' WHERE space_id = CAST(:sid AS uuid) "
               "AND status IN ('pending','running')"),
        ]

        for q in delete_queries:
            try:
                async with self.db.begin_nested():
                    await self.db.execute(q, {"sid": sid})
            except Exception:
                pass  # 表可能不存在，savepoint 自动回滚，继续下一个

        # 删除空间本身
        await self.db.execute(
            _t("DELETE FROM knowledge_spaces WHERE space_id = CAST(:sid AS uuid)"),
            {"sid": sid}
        )
        await self.db.commit()

        # 事务外：清理 MinIO 文件（写入 Redis 兜底列表）
        if file_urls:
            try:
                import json as _json
                from apps.api.core.redis import get_redis
                redis = await get_redis()
                await redis.setex(
                    f"cleanup:minio:{sid}",
                    86400 * 3,  # 3 天 TTL
                    _json.dumps(file_urls)
                )
            except Exception:
                logger.warning("Failed to write MinIO cleanup list to Redis",
                               space_id=sid)

        logger.info("Space permanently deleted", space_id=sid, user_id=uid,
                     file_count=len(file_urls))

        return {"space_id": sid, "status": "permanently_deleted",
                "pending_minio_files": len(file_urls)}

    async def list_trash_spaces(
        self, user_id: str | UUID, limit: int = 20, offset: int = 0
    ) -> dict:
        """获取回收站列表。"""
        uid = str(user_id)
        spaces = await self.repo.list_trash_spaces(uid, limit, offset)
        total = await self.repo.count_trash_spaces(uid)
        return {"spaces": spaces, "total": total}

    async def empty_trash(self, user_id: str | UUID) -> dict:
        """清空回收站：彻底删除用户回收站中所有可删除的空间。"""
        uid = str(user_id)
        spaces = await self.repo.list_trash_spaces(uid, limit=1000, offset=0)

        deleted = []
        skipped = []
        for s in spaces:
            if s["can_permanent_delete"]:
                try:
                    await self.permanent_delete_space(s["space_id"], uid)
                    deleted.append(s["space_id"])
                except SpaceError:
                    skipped.append(s["space_id"])
            else:
                skipped.append(s["space_id"])

        logger.info("Trash emptied", user_id=uid,
                     deleted=len(deleted), skipped=len(skipped))
        return {"deleted": deleted, "skipped": skipped}

    async def get_deletion_impact(
        self, space_id: str | UUID, user_id: str | UUID
    ) -> dict:
        """获取删除空间的影响范围数据。"""
        sid = str(space_id)
        await self._require_manager(sid, str(user_id))

        stats = await self.repo.get_deletion_impact(sid)
        fork_count = stats.get("fork_count", 0)

        return {
            **stats,
            "can_permanent_delete": fork_count == 0,
            "warning": (
                "彻底删除后，所有学员的学习进度、掌握度、讨论帖、测验成绩"
                "将被永久清除，此操作不可逆。"
            ) if fork_count == 0 else (
                f"此资料库被 {fork_count} 人 fork，文档仍被引用，无法彻底删除。"
                "您可以选择软删除（仅对您不可见），文档将继续保留给 fork 用户。"
            ),
        }


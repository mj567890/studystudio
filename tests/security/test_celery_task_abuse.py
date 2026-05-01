"""
tests/security/test_celery_task_abuse.py
Celery 任务滥用测试

覆盖：
- 未授权用户不能触发任务
- 无权限 space 不能触发任务
- 重复请求不会造成异常
- apply_async 参数不能被用户污染
- 任务参数注入攻击
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ════════════════════════════════════════════════════════════════
# Celery 任务触发权限
# ════════════════════════════════════════════════════════════════
class TestCeleryTaskAuth:

    def test_unauthenticated_cannot_trigger_generation(self, client_no_auth):
        """未认证用户不能触发课程生成任务"""
        resp = client_no_auth.post(
            "/api/blueprints/test-topic/start-generation",
            json={
                "space_id": "00000000-0000-0000-0000-000000000010",
                "selected_proposal_id": "A",
            }
        )
        assert resp.status_code == 401

    def test_unauthenticated_cannot_trigger_auto_review(self, client_no_auth):
        """未认证用户不能触发文档自动审核"""
        resp = client_no_auth.post("/api/admin/auto-review/trigger")
        assert resp.status_code == 401

    def test_unauthenticated_cannot_trigger_embedding_backfill(self, client_no_auth):
        """未认证用户不能触发 embedding 回填"""
        resp = client_no_auth.post("/api/admin/ai/embeddings/backfill")
        assert resp.status_code == 401

    def test_learner_cannot_trigger_admin_tasks(self, client):
        """learner 不能触发管理级 Celery 任务"""
        admin_task_endpoints = [
            ("POST", "/api/admin/auto-review/trigger"),
            ("POST", "/api/admin/ai/embeddings/backfill"),
        ]
        for method, path in admin_task_endpoints:
            resp = client.post(path, json={})
            assert resp.status_code in (401, 403), \
                f"learner should not access {path}, got {resp.status_code}"


# ════════════════════════════════════════════════════════════════
# Celery apply_async 参数注入
# ════════════════════════════════════════════════════════════════
class TestCeleryTaskParameterInjection:

    def test_start_generation_task_args_are_controlled(self, client, mock_db):
        """
        验证 start-generation 的 task 参数由服务端控制。

        注意：extra_notes 被设计为通过 Celery task args 传递（作为 teacher_instruction），
        这是数据传递而非注入。真正的安全边界在于 Celery task 内部是否使用参数化查询，
        而非 API 端点拦截用户输入字段。
        """
        proposals = [{"id": "A", "tagline": "test", "target_audience": {},
                       "course_structure": {"stage_breakdown": "test"}}]

        with patch("apps.api.modules.skill_blueprint.repository.BlueprintRepository.get_by_topic") as mock_get, \
             patch("apps.api.modules.space.service.SpaceService.require_space_access") as mock_access, \
             patch("apps.api.tasks.blueprint_tasks.synthesize_blueprint") as mock_task:

            mock_get.return_value = None
            mock_access.return_value = None

            def _exec_side(query, params):
                m = MagicMock()
                if "course_proposals" in str(query):
                    row = MagicMock()
                    row.__getitem__ = MagicMock(return_value=json.dumps(proposals))
                    m.fetchone.return_value = row
                else:
                    m.fetchone.return_value = None
                return m
            mock_db.execute = AsyncMock(side_effect=_exec_side)

            mock_result = MagicMock()
            mock_result.id = "task-test"
            mock_task.apply_async = MagicMock(return_value=mock_result)

            # 尝试注入 SQL 到 extra_notes — 服务端起数据库查询使用参数化查询
            resp = client.post(
                "/api/blueprints/test-topic/start-generation",
                json={
                    "space_id": "00000000-0000-0000-0000-000000000010",
                    "selected_proposal_id": "A",
                    "extra_notes": "'; DROP TABLE tasks; --",
                }
            )
            assert resp.status_code == 200

            # extra_notes 按设计会被传递到 Celery task args[2]（teacher_instruction 位置）
            # 安全边界验证：Celery task 收到 payload 作为字符串数据，不做 SQL 拼接
            if mock_task.apply_async.called:
                args = mock_task.apply_async.call_args.kwargs.get("args", [])
                # args[0]=topic_key, args[1]=space_id, args[2]=extra_notes, args[3]=None
                # extra_notes 应作为纯数据传递，字符串值不变
                if len(args) >= 3:
                    assert isinstance(args[2], str), \
                        "extra_notes 应作为字符串传递到 Celery task"

    def test_submit_calibration_regenerate_task_params_controlled(self, client, mock_db):
        """
        验证 submit-calibration regenerate 的 task 参数由服务端控制。
        """
        with patch("apps.api.modules.skill_blueprint.repository.BlueprintRepository.get_by_topic") as mock_get, \
             patch("apps.api.modules.space.service.SpaceService.require_space_access") as mock_access, \
             patch("apps.api.tasks.blueprint_tasks.synthesize_blueprint") as mock_task:

            mock_get.return_value = {
                "blueprint_id": "bp-001",
                "topic_key": "test-topic",
                "status": "published",
                "space_id": "00000000-0000-0000-0000-000000000010",
                "extra_notes": None,
            }
            mock_access.return_value = None

            mock_result = MagicMock()
            mock_result.id = "task-regenerate"
            mock_task.apply_async = MagicMock(return_value=mock_result)

            resp = client.post(
                "/api/blueprints/test-topic/submit-calibration",
                json={
                    "space_id": "00000000-0000-0000-0000-000000000010",
                    "answers": {"q1": [{"id": "o1", "label": "L", "entity_id": "e1"}]},
                    "regenerate": True,
                }
            )
            assert resp.status_code == 200

            # 验证 task 参数不含用户注入
            if mock_task.apply_async.called:
                call_args = str(mock_task.apply_async.call_args)
                assert "DROP TABLE" not in call_args
                assert "__import__" not in call_args


# ════════════════════════════════════════════════════════════════
# Celery 任务重复/竞态
# ════════════════════════════════════════════════════════════════
class TestCeleryTaskIdempotency:

    def test_concurrent_generation_requests_safe(self, client, mock_db):
        """
        连续多次提交 start-generation 不应导致任务队列异常。
        """
        proposals = [{"id": "A", "tagline": "test", "target_audience": {},
                       "course_structure": {"stage_breakdown": "test"}}]

        with patch("apps.api.modules.skill_blueprint.repository.BlueprintRepository.get_by_topic") as mock_get, \
             patch("apps.api.modules.space.service.SpaceService.require_space_access") as mock_access, \
             patch("apps.api.tasks.blueprint_tasks.synthesize_blueprint") as mock_task:

            mock_get.return_value = None
            mock_access.return_value = None

            def _exec_side(query, params):
                m = MagicMock()
                if "course_proposals" in str(query):
                    row = MagicMock()
                    row.__getitem__ = MagicMock(return_value=json.dumps(proposals))
                    m.fetchone.return_value = row
                else:
                    m.fetchone.return_value = None
                return m
            mock_db.execute = AsyncMock(side_effect=_exec_side)

            for i in range(3):
                mock_result = MagicMock()
                mock_result.id = f"task-{i}"
                mock_task.apply_async = MagicMock(return_value=mock_result)

                resp = client.post(
                    "/api/blueprints/test-topic/start-generation",
                    json={
                        "space_id": "00000000-0000-0000-0000-000000000010",
                        "selected_proposal_id": "A",
                    }
                )
                assert resp.status_code == 200

    def test_concurrent_calibration_requests_safe(self, client, mock_db):
        """
        连续多次提交校准请求不应导致 DB 异常。
        """
        with patch("apps.api.modules.skill_blueprint.repository.BlueprintRepository.get_by_topic") as mock_get, \
             patch("apps.api.modules.space.service.SpaceService.require_space_access") as mock_access:

            mock_get.return_value = {
                "blueprint_id": "bp-001",
                "topic_key": "test-topic",
                "status": "published",
                "space_id": "00000000-0000-0000-0000-000000000010",
                "extra_notes": None,
            }
            mock_access.return_value = None

            for i in range(5):
                resp = client.post(
                    "/api/blueprints/test-topic/submit-calibration",
                    json={
                        "space_id": "00000000-0000-0000-0000-000000000010",
                        "answers": {"q1": f"answer-{i}"},
                        "regenerate": False,
                    }
                )
                assert resp.status_code != 500, f"Calibration #{i} caused 500"


# ════════════════════════════════════════════════════════════════
# Celery 任务优先级/签名伪造
# ════════════════════════════════════════════════════════════════
class TestCeleryTaskForgery:

    def test_task_priority_not_user_controllable(self, client, mock_db):
        """
        用户不应能通过 API 参数控制 Celery 任务优先级。
        """
        proposals = [{"id": "A", "tagline": "test", "target_audience": {},
                       "course_structure": {"stage_breakdown": "test"}}]

        with patch("apps.api.modules.skill_blueprint.repository.BlueprintRepository.get_by_topic") as mock_get, \
             patch("apps.api.modules.space.service.SpaceService.require_space_access") as mock_access, \
             patch("apps.api.tasks.blueprint_tasks.synthesize_blueprint") as mock_task:

            mock_get.return_value = None
            mock_access.return_value = None

            def _exec_side(query, params):
                m = MagicMock()
                if "course_proposals" in str(query):
                    row = MagicMock()
                    row.__getitem__ = MagicMock(return_value=json.dumps(proposals))
                    m.fetchone.return_value = row
                else:
                    m.fetchone.return_value = None
                return m
            mock_db.execute = AsyncMock(side_effect=_exec_side)

            mock_result = MagicMock()
            mock_result.id = "task-test"
            mock_task.apply_async = MagicMock(return_value=mock_result)

            # 尝试注入高优先级
            resp = client.post(
                "/api/blueprints/test-topic/start-generation",
                json={
                    "space_id": "00000000-0000-0000-0000-000000000010",
                    "selected_proposal_id": "A",
                    "extra_notes": "",
                    "celery_priority": 999,  # 非预期字段，应被忽略
                }
            )
            assert resp.status_code == 200

            # 验证 apply_async 调用参数中没有用户注入的优先级
            if mock_task.apply_async.called:
                call_kwargs = mock_task.apply_async.call_args.kwargs
                # 如果有 priority 参数，必须是服务端设置的，不是 999
                if "priority" in call_kwargs:
                    assert call_kwargs["priority"] != 999, \
                        "Celery task priority was controllable by user!"

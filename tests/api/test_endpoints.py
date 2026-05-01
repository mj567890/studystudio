"""
tests/api/test_endpoints.py
端点行为测试套件

Mock 策略：patch 源模块（非 router 模块），因为 router 内使用 local import
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ════════════════════════════════════════════════════════════════
# submit-calibration
# ════════════════════════════════════════════════════════════════
class TestSubmitCalibration:

    def test_submit_calibration_success(self, client, mock_db):
        """正常补答校准 → 200 + confidence_score"""
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

            resp = client.post(
                "/api/blueprints/test-topic/submit-calibration",
                json={
                    "space_id": "00000000-0000-0000-0000-000000000010",
                    "answers": {
                        "q1_pain_points": [
                            {"id": "opt_1", "label": "安全检查", "entity_id": "ent_001"}
                        ],
                        "q2_cases": {"id": "case_1", "label": "真实案例"},
                        "q3_misconceptions": [{"id": "m1", "label": "误解1", "entity_id": "e2"}],
                        "q4_priority": ["ent_001", "ent_002"],
                        "q5_red_lines": [
                            {"id": "rl_1", "label": "绝对不能做", "entity_id": "ent_003"}
                        ],
                    },
                    "regenerate": False,
                }
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["code"] == 200
            assert "confidence_score" in data["data"]
            assert data["data"]["confidence_score"] >= 0.8  # 5/5 answered

    def test_submit_calibration_blueprint_not_found(self, client, mock_db):
        """blueprint 不存在 → 404"""
        with patch("apps.api.modules.skill_blueprint.repository.BlueprintRepository.get_by_topic") as mock_get:
            mock_get.return_value = None

            resp = client.post(
                "/api/blueprints/nonexistent/submit-calibration",
                json={
                    "space_id": "00000000-0000-0000-0000-000000000010",
                    "answers": {},
                    "regenerate": False,
                }
            )
            assert resp.status_code == 404

    def test_submit_calibration_empty_answers_zero_confidence(self, client, mock_db):
        """全部 skip → confidence_score = 0"""
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

            resp = client.post(
                "/api/blueprints/test-topic/submit-calibration",
                json={
                    "space_id": "00000000-0000-0000-0000-000000000010",
                    "answers": {"q1": "skip", "q2": "不清楚", "q3": [], "q4": [], "q5": "skip"},
                    "regenerate": False,
                }
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["data"]["confidence_score"] == 0.0

    def test_submit_calibration_with_regenerate_triggers_task(self, client, mock_db):
        """regenerate=True 触发重建任务"""
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
            mock_result.id = "task-12345"
            mock_task.apply_async = MagicMock(return_value=mock_result)

            resp = client.post(
                "/api/blueprints/test-topic/submit-calibration",
                json={
                    "space_id": "00000000-0000-0000-0000-000000000010",
                    "answers": {"q1_pain_points": [{"id": "o1", "label": "L", "entity_id": "e1"}]},
                    "regenerate": True,
                }
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["data"]["regenerate_triggered"] is True
            assert data["data"]["task_id"] == "task-12345"

    def test_submit_calibration_missing_space_id_returns_422(self, client, mock_db):
        """缺少 space_id → 422"""
        resp = client.post(
            "/api/blueprints/test-topic/submit-calibration",
            json={"answers": {}},
        )
        assert resp.status_code == 422


# ════════════════════════════════════════════════════════════════
# start-generation
# ════════════════════════════════════════════════════════════════
class TestStartGeneration:

    def test_start_generation_no_proposals_returns_400(self, client, mock_db):
        """方案不存在 → 400"""
        # mock_db.execute 需要返回有效的 MagicMock（非 AsyncMock），
        # 否则 fetchone() 返回 coroutine 导致崩溃
        def _exec_side(query, params):
            m = MagicMock()
            m.fetchone.return_value = None  # proposals 不存在
            return m
        mock_db.execute = AsyncMock(side_effect=_exec_side)

        with patch("apps.api.modules.space.service.SpaceService.require_space_access") as mock_access:
            mock_access.return_value = None

            resp = client.post(
                "/api/blueprints/test-topic/start-generation",
                json={
                    "space_id": "00000000-0000-0000-0000-000000000010",
                    "selected_proposal_id": "A",
                }
            )
        assert resp.status_code == 400

    def test_start_generation_invalid_proposal_id_returns_400(self, client, mock_db):
        """无效方案 ID → 400"""
        proposals = [{"id": "A", "tagline": "test", "target_audience": {},
                       "course_structure": {"stage_breakdown": "test"}}]

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

        with patch("apps.api.modules.space.service.SpaceService.require_space_access") as mock_access:
            mock_access.return_value = None

            resp = client.post(
                "/api/blueprints/test-topic/start-generation",
                json={
                    "space_id": "00000000-0000-0000-0000-000000000010",
                    "selected_proposal_id": "Z",
                }
            )
        assert resp.status_code == 400

    def test_start_generation_success_triggers_task(self, client, mock_db):
        """正常启动生成 → 200 + task_id"""
        proposals = [{"id": "A", "tagline": "test", "target_audience": {"label": "新人"},
                       "course_structure": {"stage_breakdown": "test"}}]

        with patch("apps.api.modules.skill_blueprint.repository.BlueprintRepository.get_by_topic") as mock_get, \
             patch("apps.api.modules.space.service.SpaceService.require_space_access") as mock_access, \
             patch("apps.api.tasks.blueprint_tasks.synthesize_blueprint") as mock_task:

            mock_access.return_value = None

            mock_get.return_value = None  # 没有已有 blueprint

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
            mock_result.id = "task-67890"
            mock_task.apply_async = MagicMock(return_value=mock_result)

            resp = client.post(
                "/api/blueprints/test-topic/start-generation",
                json={
                    "space_id": "00000000-0000-0000-0000-000000000010",
                    "selected_proposal_id": "A",
                    "adjustments": {"total_hours": 16},
                    "calibration_answers": {"q1_pain_points": [{"id": "o1", "label": "L", "entity_id": "e1"}]},
                }
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["data"]["topic_key"] == "test-topic"
            assert data["data"]["task_id"] == "task-67890"

    def test_start_generation_missing_space_id_returns_422(self, client, mock_db):
        """缺少必填字段 → 422"""
        resp = client.post(
            "/api/blueprints/test-topic/start-generation",
            json={"selected_proposal_id": "A"},
        )
        assert resp.status_code == 422


# ════════════════════════════════════════════════════════════════
# get_blueprint
# ════════════════════════════════════════════════════════════════
class TestGetBlueprint:

    def test_get_blueprint_not_found(self, client, mock_db):
        """blueprint 不存在 → 404"""
        with patch("apps.api.modules.skill_blueprint.service.BlueprintService.get_blueprint") as mock_get:
            mock_get.return_value = None

            resp = client.get("/api/blueprints/nonexistent-topic")
            assert resp.status_code == 404

    def test_get_blueprint_success(self, client, mock_db):
        """正常获取 → 200"""
        with patch("apps.api.modules.skill_blueprint.service.BlueprintService.get_blueprint") as mock_get, \
             patch("apps.api.modules.space.service.SpaceService.require_space_access") as mock_access:

            bp_mock = MagicMock()
            bp_mock.blueprint_id = "bp-001"
            bp_mock.space_id = "00000000-0000-0000-0000-000000000010"
            bp_mock.model_dump = MagicMock(return_value={
                "blueprint_id": "bp-001",
                "topic_key": "test-topic",
                "title": "Test",
                "status": "published",
                "version": 1,
                "space_id": "00000000-0000-0000-0000-000000000010",
                "stages": [],
            })
            mock_get.return_value = bp_mock
            mock_access.return_value = None

            resp = client.get("/api/blueprints/test-topic")
            assert resp.status_code == 200
            assert resp.json()["data"]["blueprint_id"] == "bp-001"

    def test_get_blueprint_with_space_id_param(self, client, mock_db):
        """带 space_id 查询参数 → 正确传递"""
        with patch("apps.api.modules.skill_blueprint.service.BlueprintService.get_blueprint") as mock_get, \
             patch("apps.api.modules.space.service.SpaceService.require_space_access") as mock_access:

            bp_mock = MagicMock()
            bp_mock.blueprint_id = "bp-002"
            bp_mock.space_id = "sid-020"
            bp_mock.model_dump = MagicMock(return_value={
                "blueprint_id": "bp-002", "space_id": "sid-020",
                "topic_key": "test-topic", "title": "Test",
                "status": "published", "version": 1, "stages": [],
            })
            mock_get.return_value = bp_mock
            mock_access.return_value = None

            resp = client.get(
                "/api/blueprints/test-topic",
                params={"space_id": "sid-020"}
            )
            assert resp.status_code == 200
            mock_get.assert_called_once()
            assert mock_get.call_args.kwargs["space_id"] == "sid-020"

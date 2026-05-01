"""
tests/api/test_permissions.py
权限测试套件

Mock 策略：patch 源模块方法
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ════════════════════════════════════════════════════════════════
# 未认证拦截
# ════════════════════════════════════════════════════════════════
class TestUnauthenticatedAccess:

    def test_get_blueprint_without_auth_returns_401(self, client_no_auth):
        """未认证用户 → 401"""
        resp = client_no_auth.get("/api/blueprints/some-topic")
        assert resp.status_code == 401

    def test_get_status_without_auth_returns_401(self, client_no_auth):
        """未认证用户 → 401"""
        resp = client_no_auth.get("/api/blueprints/some-topic/status")
        assert resp.status_code == 401

    def test_submit_calibration_without_auth_returns_401(self, client_no_auth):
        """未认证用户 → 401"""
        resp = client_no_auth.post(
            "/api/blueprints/some-topic/submit-calibration",
            json={"space_id": "00000000-0000-0000-0000-000000000001", "answers": {}}
        )
        assert resp.status_code == 401

    def test_start_generation_without_auth_returns_401(self, client_no_auth):
        """未认证用户 → 401"""
        resp = client_no_auth.post(
            "/api/blueprints/some-topic/start-generation",
            json={"space_id": "00000000-0000-0000-0000-000000000001",
                  "selected_proposal_id": "A"}
        )
        assert resp.status_code == 401


# ════════════════════════════════════════════════════════════════
# 空间权限控制
# ════════════════════════════════════════════════════════════════
class TestSpaceAccessControl:

    def test_get_blueprint_success(self, client, mock_db):
        """正常访问 → 200"""
        with patch("apps.api.modules.skill_blueprint.service.BlueprintService.get_blueprint") as mock_get, \
             patch("apps.api.modules.space.service.SpaceService.require_space_access") as mock_access:

            bp_mock = MagicMock()
            bp_mock.blueprint_id = "bp-001"
            bp_mock.space_id = "sp-001"
            bp_mock.model_dump = MagicMock(return_value={
                "blueprint_id": "bp-001", "status": "published"
            })
            mock_get.return_value = bp_mock
            mock_access.return_value = None

            resp = client.get("/api/blueprints/test-topic")
            assert resp.status_code == 200

    def test_get_blueprint_not_found(self, client, mock_db):
        """不存在 → 404"""
        with patch("apps.api.modules.skill_blueprint.service.BlueprintService.get_blueprint") as mock_get:
            mock_get.return_value = None
            resp = client.get("/api/blueprints/nonexistent")
            assert resp.status_code == 404


# ════════════════════════════════════════════════════════════════
# publish 权限控制（仅管理员）
# ════════════════════════════════════════════════════════════════
class TestPublishPermissions:

    def test_learner_cannot_publish(self, client, mock_db):
        """普通用户（learner）→ 403"""
        with patch("apps.api.modules.skill_blueprint.repository.BlueprintRepository.get_by_topic") as mock_get:
            mock_get.return_value = {
                "blueprint_id": "bp-001",
                "topic_key": "test",
                "status": "review",
                "space_id": "sp-001",
            }
            resp = client.post("/api/blueprints/test-topic/publish")
            assert resp.status_code == 403

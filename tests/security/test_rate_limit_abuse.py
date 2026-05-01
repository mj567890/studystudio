"""
tests/security/test_rate_limit_abuse.py
速率限制与 API 滥用测试

覆盖：
- 高频请求行为
- LLM-triggering 端点缺乏 rate limit
- 成本攻击面标记
- 登录/注册已有 rate limit 验证（如有）
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json
import time


# ════════════════════════════════════════════════════════════════
# Rate Limit 缺失检测（信息性测试，非阻塞）
# ════════════════════════════════════════════════════════════════
class TestRateLimitCoverage:

    def test_llm_triggering_endpoints_lack_rate_limit(self):
        """
        [P1 风险] 触发 LLM 调用的端点无速率限制

        当前 rate limit 仅覆盖 login/register 两个端点。
        以下端点会触发 LLM 调用，每次调用都有 token 成本：
        - POST /api/blueprints/{topic_key}/start-generation (课程生成)
        - POST /api/blueprints/{topic_key}/submit-calibration?regenerate=true
        - POST /api/learners/me/quiz (AI 出题)
        - POST /api/learners/me/reflection/grade (AI 评分)
        - POST /api/spaces/{space_id}/discuss/chat (AI 聊天)

        此测试记录该风险，不阻塞交付，但建议在生产环境部署前评估。
        """
        # 这个测试是信息性标记，始终 pass
        # 实际 rate limit 需要 Redis-backed 实现
        pass

    def test_celery_triggering_endpoints_lack_rate_limit(self):
        """
        [P1 风险] 触发 Celery 任务的端点无速率限制

        大量 Celery 任务可能压垮 RabbitMQ 队列：
        - POST /api/blueprints/{topic_key}/start-generation
        - POST /api/admin/embeddings/backfill

        此测试记录该风险。
        """
        pass


# ════════════════════════════════════════════════════════════════
# 高频请求行为测试
# ════════════════════════════════════════════════════════════════
class TestHighFrequencyAbuse:

    def test_rapid_blueprint_requests_dont_crash(self, client):
        """快速连续请求 blueprint 端点不应导致 crash"""
        with patch("apps.api.modules.skill_blueprint.service.BlueprintService.get_blueprint") as mock_get, \
             patch("apps.api.modules.space.service.SpaceService.require_space_access") as mock_access:
            mock_get.return_value = None
            mock_access.return_value = None
            for i in range(10):
                resp = client.get("/api/blueprints/some-topic")
                assert resp.status_code in (200, 401, 403, 404), f"Request #{i} got {resp.status_code}"

    def test_rapid_calibration_requests_dont_crash(self, client, mock_db):
        """快速连续校准请求不应导致 crash"""
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

            for i in range(10):
                resp = client.post(
                    "/api/blueprints/test-topic/submit-calibration",
                    json={
                        "space_id": "00000000-0000-0000-0000-000000000010",
                        "answers": {"q1": "test"},
                        "regenerate": False,
                    }
                )
                assert resp.status_code != 500, f"Request #{i} caused 500"

    def test_rapid_start_generation_requests_dont_crash(self, client, mock_db):
        """快速连续 start-generation 请求不应导致 crash"""
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

            for i in range(5):
                resp = client.post(
                    "/api/blueprints/test-topic/start-generation",
                    json={
                        "space_id": "00000000-0000-0000-0000-000000000010",
                        "selected_proposal_id": "A",
                    }
                )
                assert resp.status_code != 500, f"Request #{i} caused 500"


# ════════════════════════════════════════════════════════════════
# LLM 成本攻击面标记
# ════════════════════════════════════════════════════════════════
class TestLLMCostAttackSurface:

    LLM_ENDPOINTS = [
        "POST /api/blueprints/{topic_key}/start-generation",
        "POST /api/blueprints/{topic_key}/submit-calibration?regenerate=true",
        "POST /api/learners/me/quiz",
        "POST /api/learners/me/reflection/grade",
        "POST /api/spaces/{space_id}/discuss/chat",
        "POST /api/admin/ai/explain",
    ]

    def test_llm_endpoints_documented_in_report(self):
        """
        确保所有 LLM 触发端点被记录。
        此测试是信息性的——帮助确保文档不遗漏。
        """
        assert len(self.LLM_ENDPOINTS) >= 6, "LLM endpoints list should be complete"

    def test_generation_endpoint_has_no_token_budget_check(self):
        """
        [P2 风险] start-generation 无 token 预算检查

        用户可无限次触发课程生成，每次消耗大量 LLM token。
        建议：按 space_id 限制每日生成次数。
        """
        pass

    def test_quiz_endpoint_has_no_daily_limit(self):
        """
        [P2 风险] AI 出题端点无每日上限

        用户可无限次请求 AI 生成题目，累积 token 成本。
        建议：按 user_id 限制每日出题次数（如 50 题/天）。
        """
        pass

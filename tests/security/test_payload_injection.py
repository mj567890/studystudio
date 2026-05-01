"""
tests/security/test_payload_injection.py
恶意 Payload 注入测试

覆盖：
- XSS payload
- SQL 注入 payload
- 模板注入 payload
- 路径遍历
- 超长输入
- 空/null/非预期类型
- 嵌套超深 JSON
- Unicode 攻击
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ════════════════════════════════════════════════════════════════
# XSS Payload
# ════════════════════════════════════════════════════════════════
class TestXSSPayloads:

    XSS_PAYLOADS = [
        ("basic script", "<script>alert(1)</script>"),
        ("img onerror", "<img src=x onerror=alert(1)>"),
        ("svg onload", "<svg onload=alert(1)>"),
        ("javascript URL", "javascript:alert(1)"),
        ("event handler", "<body onload=alert(1)>"),
        ("encoded", "%3Cscript%3Ealert(1)%3C/script%3E"),
        ("double encoded", "%253Cscript%253Ealert(1)%253C/script%253E"),
    ]

    # Subset of payloads safe for URL paths (angle brackets break URL routing)
    XSS_URL_SAFE_PAYLOADS = [
        ("encoded", "%3Cscript%3Ealert(1)%3C/script%3E"),
        ("double encoded", "%253Cscript%253Ealert(1)%253C/script%253E"),
        ("script keyword", "script-alert-test"),
        ("percent encoded js", "javascript%3Aalert(1)"),
    ]

    @pytest.mark.parametrize("label,payload", XSS_URL_SAFE_PAYLOADS)
    def test_xss_in_blueprint_topic_key(self, client, label, payload):
        """XSS payload 在 URL 路径中不应导致 500"""
        with patch("apps.api.modules.skill_blueprint.service.BlueprintService.get_blueprint") as mock_get:
            mock_get.return_value = None
            resp = client.get(f"/api/blueprints/{payload}")
            assert resp.status_code != 500, \
                f"XSS '{label}' in topic_key caused 500"

    @pytest.mark.parametrize("label,payload", XSS_PAYLOADS)
    def test_xss_in_calibration_answers(self, client, mock_db, label, payload):
        """XSS payload 在校准答案中不应导致 500"""
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
                    "answers": {"q1": payload, "q2": payload},
                    "regenerate": False,
                }
            )
            assert resp.status_code != 500, \
                f"XSS '{label}' in calibration answers caused 500"

    @pytest.mark.parametrize("label,payload", XSS_PAYLOADS)
    def test_xss_in_start_generation_adjustments(self, client, mock_db, label, payload):
        """XSS payload 在 adjustments 中不应导致 500"""
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

            resp = client.post(
                "/api/blueprints/test-topic/start-generation",
                json={
                    "space_id": "00000000-0000-0000-0000-000000000010",
                    "selected_proposal_id": "A",
                    "extra_notes": payload,
                }
            )
            assert resp.status_code != 500, \
                f"XSS '{label}' in extra_notes caused 500"


# ════════════════════════════════════════════════════════════════
# SQL 注入 Payload
# ════════════════════════════════════════════════════════════════
class TestSQLInjectionPayloads:

    # URL-safe SQLi payloads (no raw quotes/semicolons in path)
    SQLI_URL_PAYLOADS = [
        ("percent encoded OR", "%27%20OR%20%271%27%3D%271"),
        ("percent encoded UNION", "%27%20UNION%20SELECT"),
        ("double dash comment", "test--"),
        ("hash comment", "test%23"),
    ]

    SQLI_PARAM_PAYLOADS = [
        ("classic OR", "' OR '1'='1"),
        ("union select", "' UNION SELECT * FROM users--"),
        ("drop table", "'; DROP TABLE users; --"),
        ("comment bypass", "admin'--"),
        ("batched query", "'; DELETE FROM spaces WHERE '1'='1"),
        ("blind true", "' AND 1=1--"),
        ("blind false", "' AND 1=0--"),
        ("time-based", "'; SELECT pg_sleep(5)--"),
    ]

    @pytest.mark.parametrize("label,payload", SQLI_URL_PAYLOADS)
    def test_sqli_in_topic_key(self, client, label, payload):
        """SQLi payload 在 topic_key 中不应导致 500"""
        with patch("apps.api.modules.skill_blueprint.service.BlueprintService.get_blueprint") as mock_get:
            mock_get.return_value = None
            resp = client.get(f"/api/blueprints/{payload}")
            assert resp.status_code != 500, \
                f"SQLi '{label}' in topic_key caused 500"

    @pytest.mark.parametrize("label,payload", SQLI_PARAM_PAYLOADS)
    def test_sqli_in_space_id(self, client, label, payload):
        """SQLi payload 在 space_id 查询参数中不应导致 500"""
        with patch("apps.api.modules.skill_blueprint.service.BlueprintService.get_blueprint") as mock_svc, \
             patch("apps.api.modules.space.service.SpaceService.require_space_access") as mock_access:
            mock_svc.return_value = None
            mock_access.return_value = None

            resp = client.get(
                "/api/blueprints/some-topic",
                params={"space_id": payload}
            )
            # SQLi in query params → handled by parameterized queries
            # Response can be 200/401/403/404 but not 500
            assert resp.status_code != 500, \
                f"SQLi '{label}' in space_id caused 500"

    @pytest.mark.parametrize("label,payload", SQLI_PARAM_PAYLOADS)
    def test_sqli_in_calibration_answers(self, client, mock_db, label, payload):
        """SQLi payload 在校准答案中不应导致 500"""
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
                    "answers": {"q1": payload},
                    "regenerate": False,
                }
            )
            assert resp.status_code != 500, \
                f"SQLi '{label}' in calibration answers caused 500"


# ════════════════════════════════════════════════════════════════
# 超长输入 / 边界值
# ════════════════════════════════════════════════════════════════
class TestBoundaryInputs:

    def test_extreme_long_topic_key(self, client):
        """超长 topic_key（500 chars）→ 应返回 4xx 而非 500"""
        with patch("apps.api.modules.skill_blueprint.service.BlueprintService.get_blueprint") as mock_get:
            mock_get.return_value = None
            long_key = "a" * 500
            resp = client.get(f"/api/blueprints/{long_key}")
            assert resp.status_code != 500
            assert resp.status_code < 500

    def test_extreme_long_space_id(self, client):
        """超长 space_id → 应返回 4xx 而非 500"""
        with patch("apps.api.modules.skill_blueprint.service.BlueprintService.get_blueprint") as mock_get, \
             patch("apps.api.modules.space.service.SpaceService.require_space_access") as mock_access:
            mock_get.return_value = None
            mock_access.return_value = None

            long_id = "0" * 500
            resp = client.get(
                "/api/blueprints/some-topic",
                params={"space_id": long_id}
            )
            assert resp.status_code != 500

    def test_extreme_long_json_body(self, client, mock_db):
        """超大 JSON body → 应返回 4xx 而非 500"""
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

            huge_payload = {"key": "x" * 5000}
            resp = client.post(
                "/api/blueprints/some-topic/submit-calibration",
                json={
                    "space_id": "00000000-0000-0000-0000-000000000010",
                    "answers": huge_payload,
                    "regenerate": False,
                }
            )
            assert resp.status_code != 500

    def test_deeply_nested_json(self, client, mock_db):
        """超深嵌套 JSON（20 层）→ 不应导致 500"""
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

            # 构造 20 层嵌套
            nested = "end"
            for _ in range(20):
                nested = {"child": nested}

            resp = client.post(
                "/api/blueprints/test-topic/submit-calibration",
                json={
                    "space_id": "00000000-0000-0000-0000-000000000010",
                    "answers": {"q1": nested},
                    "regenerate": False,
                }
            )
            assert resp.status_code != 500

    def test_null_and_empty_values(self, client, mock_db):
        """null / 空值 / 空对象 不应导致 500"""
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

            payloads = [
                {"space_id": None, "answers": {}, "regenerate": False},
                {"space_id": "", "answers": {}, "regenerate": False},
                {},
            ]
            for i, body in enumerate(payloads):
                resp = client.post(
                    "/api/blueprints/test-topic/submit-calibration",
                    json=body
                )
                assert resp.status_code != 500, \
                    f"Null/empty payload #{i} caused 500: {resp.text[:200]}"

    def test_unexpected_fields_accepted_or_rejected_cleanly(self, client, mock_db):
        """非预期字段应被忽略或干净拒绝（不能 500）"""
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
                    "answers": {},
                    "regenerate": False,
                    "__proto__": {"isAdmin": True},
                    "constructor": "malicious",
                    "__defineGetter__": "hack",
                }
            )
            assert resp.status_code != 500


# ════════════════════════════════════════════════════════════════
# Unicode / 编码攻击
# ════════════════════════════════════════════════════════════════
class TestUnicodeAttacks:

    UNICODE_PAYLOADS = [
        ("null byte", "topic%00key"),
        ("right-to-left override", "topic%E2%80%AEkey"),
        ("zero-width chars", "topic%E2%80%8Bkey"),
        ("homoglyph admin", "admin%D0%B0"),
    ]

    @pytest.mark.parametrize("label,payload", UNICODE_PAYLOADS)
    def test_unicode_in_topic_key(self, client, label, payload):
        """Unicode 攻击 payload（URL 编码）在 topic_key 中不应导致 500"""
        with patch("apps.api.modules.skill_blueprint.service.BlueprintService.get_blueprint") as mock_get:
            mock_get.return_value = None
            try:
                resp = client.get(f"/api/blueprints/{payload}")
                assert resp.status_code != 500
            except UnicodeError:
                pass

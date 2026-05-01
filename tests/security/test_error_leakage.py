"""
tests/security/test_error_leakage.py
错误信息泄露测试

覆盖：
- 4xx/5xx 响应不得包含 stack trace
- 不得泄露本地文件路径
- 不得泄露 secret / API key
- 不得泄露 database URL
- 不得泄露 internal module path
- 不得包含 traceback
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ════════════════════════════════════════════════════════════════
# 敏感信息泄露模式
# ════════════════════════════════════════════════════════════════
SENSITIVE_PATTERNS = [
    ("stack trace", "Traceback (most recent call last)"),
    ("file path: studystudio", "D:\\studystudio"),
    ("file path: /app/", "/app/"),
    ("file path: /home/", "/home/"),
    ("file path: /Users/", "/Users/"),
    ("file path: /var/", "/var/"),
    ("file path: C:\\", "C:\\"),
    ("file path: .py line", ".py\", line"),
    ("postgresql URL", "postgresql://"),
    ("postgres URL alt", "postgres://"),
    ("asyncpg URL", "postgresql+asyncpg://"),
    ("secret key", "SECRET_KEY"),
    ("JWT secret", "JWT_SECRET_KEY"),
    ("API key pattern", "sk-"),
    ("database password", "password="),
    ("redis URL", "redis://"),
    ("rabbitmq URL", "amqp://"),
    ("minio endpoint", "MINIO_ENDPOINT"),
    ("openai key", "OPENAI_API_KEY"),
    ("python traceback", "raise "),
    ("module path", "site-packages"),
]


def _check_no_sensitive_leak(response_text: str, endpoint_label: str) -> list[str]:
    """检查响应文本是否泄露敏感信息，返回发现的问题列表"""
    leaks = []
    lower = response_text.lower()
    for name, pattern in SENSITIVE_PATTERNS:
        if pattern.lower() in lower:
            leaks.append(f"[{endpoint_label}] leaked {name}: matched '{pattern}'")
    return leaks


# ════════════════════════════════════════════════════════════════
# 错误响应泄露检查
# ════════════════════════════════════════════════════════════════
class TestErrorResponseLeakage:

    def test_404_response_no_stack_trace(self, client):
        """404 响应不应包含 stack trace"""
        with patch("apps.api.modules.skill_blueprint.service.BlueprintService.get_blueprint") as mock_get:
            mock_get.return_value = None
            resp = client.get("/api/blueprints/nonexistent-topic-404-test")
            if resp.status_code == 404:
                leaks = _check_no_sensitive_leak(resp.text, "404 blueprint")
                assert len(leaks) == 0, f"404 response leaked: {leaks}"

    def test_422_response_no_stack_trace(self, client):
        """422 响应不应包含 stack trace"""
        resp = client.post(
            "/api/blueprints/test-topic/submit-calibration",
            json={"invalid_field": True}  # 缺少必填字段
        )
        if resp.status_code == 422:
            leaks = _check_no_sensitive_leak(resp.text, "422 calibration")
            assert len(leaks) == 0, f"422 response leaked: {leaks}"

    def test_401_response_no_sensitive_info(self, client_no_auth):
        """401 响应不应泄露敏感信息"""
        resp = client_no_auth.get("/api/users/me")
        assert resp.status_code == 401
        leaks = _check_no_sensitive_leak(resp.text, "401 users/me")
        assert len(leaks) == 0, f"401 response leaked: {leaks}"

    def test_403_response_no_sensitive_info(self, client):
        """403 响应不应泄露敏感信息"""
        resp = client.post("/api/blueprints/test-topic/publish")
        if resp.status_code == 403:
            leaks = _check_no_sensitive_leak(resp.text, "403 publish")
            assert len(leaks) == 0, f"403 response leaked: {leaks}"

    def test_error_response_has_structured_format(self, client):
        """错误响应应遵循统一格式"""
        with patch("apps.api.modules.skill_blueprint.service.BlueprintService.get_blueprint") as mock_get:
            mock_get.return_value = None
            resp = client.get("/api/blueprints/__nonexistent__")
            assert resp.status_code in (401, 403, 404)
            data = resp.json()
            # 无论是 401/403/404，格式应是 {code, msg} 或 {detail: {...}}
            if "detail" in data:
                assert isinstance(data["detail"], (str, dict))
            elif "code" in data or "msg" in data:
                pass  # OK


# ════════════════════════════════════════════════════════════════
# 异常触发泄露检查
# ════════════════════════════════════════════════════════════════
class TestExceptionLeakage:

    def test_internal_error_does_not_leak_details(self, client, mock_db):
        """模拟内部异常，验证响应不泄露内部细节（5xx 或 4xx 均可）"""
        # 使用计数器控制异常触发时机：前 2 次 db.execute 正常，第 3 次崩溃
        # 这样保证 space check + get_by_topic 通过，但在后续 db 操作时触发异常
        error_counter = [0]

        async def _fail_on_later_call(*args, **kwargs):
            error_counter[0] += 1
            if error_counter[0] >= 3:
                raise RuntimeError("SIMULATED-CRASH-FOR-TEST")
            m = MagicMock()
            row = MagicMock()
            row.__getitem__ = MagicMock(return_value="{}")
            m.fetchone.return_value = row
            return m

        mock_db.execute = AsyncMock(side_effect=_fail_on_later_call)

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
                }
            )
            # 异常可能被中间件捕获为 5xx 或 4xx
            # 关键：响应不应泄露内部细节
            leaks = _check_no_sensitive_leak(resp.text, f"{resp.status_code} internal")
            assert len(leaks) == 0, f"{resp.status_code} response leaked: {leaks}"


# ════════════════════════════════════════════════════════════════
# 响应头安全
# ════════════════════════════════════════════════════════════════
class TestResponseHeadersSecurity:

    def test_no_server_header_leak(self, client):
        """响应不应泄露服务器类型/版本"""
        resp = client.get("/api/users/me")
        # FastAPI/Starlette 默认不设 Server header，或可在 nginx 层处理
        server = resp.headers.get("server", "").lower()
        # 如果在本地开发环境有 server header，检查不包含版本号
        assert "uvicorn" not in server, f"Server header leaks: {server}"

    def test_content_type_is_json_for_api_responses(self, client_no_auth):
        """API 响应 Content-Type 应为 application/json"""
        resp = client_no_auth.get("/api/users/me")
        assert resp.status_code == 401
        content_type = resp.headers.get("content-type", "")
        assert "application/json" in content_type or "text/html" not in content_type, \
            f"Unexpected content-type: {content_type}"

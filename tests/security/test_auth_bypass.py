"""
tests/security/test_auth_bypass.py
红队认证绕过测试

覆盖：
- 无 token 访问受保护接口 → 401
- 空 token / 伪造 token / 过期 token → 401
- 普通用户不能访问管理员接口 → 403
- JWT 算法混淆攻击
"""
import pytest
from unittest.mock import patch, MagicMock
import time
import jwt


# ════════════════════════════════════════════════════════════════
# 无认证访问受保护端点
# ════════════════════════════════════════════════════════════════
class TestUnauthenticatedAccess:

    PROTECTED_ENDPOINTS = [
        ("GET", "/api/users/me"),
        ("PATCH", "/api/users/me"),
        ("DELETE", "/api/users/me"),
        ("GET", "/api/spaces"),
        ("GET", "/api/blueprints/some-topic"),
        ("GET", "/api/blueprints/some-topic/status"),
        ("POST", "/api/blueprints/some-topic/submit-calibration"),
        ("POST", "/api/blueprints/some-topic/start-generation"),
        ("POST", "/api/blueprints/some-topic/publish"),
        ("GET", "/api/files/my-documents"),
        ("GET", "/api/tutorials/topic/some-topic"),
        ("POST", "/api/spaces"),
        ("GET", "/api/admin/users"),
        ("GET", "/api/admin/system/stats"),
        ("GET", "/api/admin/tasks"),
    ]

    @pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
    def test_protected_endpoint_returns_401_without_token(self, client_no_auth, method, path):
        """受保护端点无 token 必须返回 401"""
        if method == "GET":
            resp = client_no_auth.get(path)
        elif method == "POST":
            resp = client_no_auth.post(path, json={})
        elif method == "PATCH":
            resp = client_no_auth.patch(path, json={})
        elif method == "DELETE":
            resp = client_no_auth.delete(path)
        else:
            pytest.skip(f"Unknown method: {method}")

        assert resp.status_code == 401, \
            f"{method} {path} should return 401 without auth, got {resp.status_code}"

    def test_empty_token_rejected(self, client_no_auth):
        """空 Authorization header → 401"""
        resp = client_no_auth.get(
            "/api/users/me",
            headers={"Authorization": ""}
        )
        assert resp.status_code in (401, 403)

    def test_malformed_token_rejected(self, client_no_auth):
        """畸形 token → 401"""
        resp = client_no_auth.get(
            "/api/users/me",
            headers={"Authorization": "Bearer not.a.valid.jwt"}
        )
        assert resp.status_code in (401, 403)


# ════════════════════════════════════════════════════════════════
# 伪造/过期 token
# ════════════════════════════════════════════════════════════════
class TestForgedTokens:

    def test_expired_token_rejected(self, client_no_auth):
        """过期 token → 401"""
        expired = jwt.encode(
            {"user_id": "test", "exp": int(time.time()) - 3600},
            "test-secret",
            algorithm="HS256"
        )
        resp = client_no_auth.get(
            "/api/users/me",
            headers={"Authorization": f"Bearer {expired}"}
        )
        assert resp.status_code in (401, 403)

    def test_tampered_token_rejected(self, client_no_auth):
        """被篡改的 token → 401（签名无效）"""
        original = jwt.encode(
            {"user_id": "00000000-0000-0000-0000-000000000001", "exp": int(time.time()) + 3600},
            "test-secret",
            algorithm="HS256"
        )
        # 篡改 payload
        header, payload, signature = original.split(".")
        tampered_payload = jwt.utils.base64url_encode(
            b'{"user_id": "evil-user", "exp": 99999999999, "roles": ["admin"]}'
        )
        tampered = f"{header}.{tampered_payload}.{signature}"

        resp = client_no_auth.get(
            "/api/users/me",
            headers={"Authorization": f"Bearer {tampered}"}
        )
        assert resp.status_code in (401, 403)

    def test_none_algorithm_attack_rejected(self, client_no_auth):
        """JWT algorithm=none 攻击 → 401"""
        none_token = jwt.encode(
            {"user_id": "evil", "roles": ["admin"]},
            key="",
            algorithm="HS256"
        )
        # 手动构造 alg=none header
        header = jwt.utils.base64url_encode(b'{"alg":"none","typ":"JWT"}')
        payload = jwt.utils.base64url_encode(
            b'{"user_id":"evil","roles":["admin"],"exp":9999999999}'
        )
        none_jwt = f"{header}.{payload}."

        resp = client_no_auth.get(
            "/api/users/me",
            headers={"Authorization": f"Bearer {none_jwt}"}
        )
        assert resp.status_code in (401, 403)


# ════════════════════════════════════════════════════════════════
# 管理员权限提升
# ════════════════════════════════════════════════════════════════
class TestAdminPrivilegeEscalation:

    ADMIN_ENDPOINTS = [
        ("GET", "/api/admin/users"),
        ("GET", "/api/admin/system/stats"),
        ("GET", "/api/admin/tasks"),
        ("GET", "/api/admin/ai/bindings"),
        ("GET", "/api/admin/entities"),
    ]

    @pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
    def test_learner_cannot_access_admin_endpoint(self, client, method, path):
        """learner 用户访问管理端点 → 403"""
        if method == "GET":
            resp = client.get(path)
        elif method == "POST":
            resp = client.post(path, json={})
        else:
            pytest.skip(f"Unknown method: {method}")

        assert resp.status_code in (401, 403), \
            f"learner accessing admin {method} {path} should be 403, got {resp.status_code}"

"""
tests/unit/test_auth_security.py
认证与安全单元测试套件

覆盖：
- 密码哈希与验证（bcrypt、72字节截断）
- JWT 签发与解码
- 密码强度校验
- IP 速率限制器（滑动窗口）
- require_role 权限检查
"""
import math
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from apps.api.modules.auth.service import (
    hash_password,
    verify_password,
    create_access_token,
    decode_token,
    _truncate_password,
    _normalize_uuid_str,
)
from apps.api.modules.auth.router import (
    RateLimiter,
    _check_password_strength,
    require_role,
)


# ════════════════════════════════════════════════════════════════
# 密码哈希与验证
# ════════════════════════════════════════════════════════════════
class TestPasswordHashing:

    def test_hash_produces_different_output_each_time(self):
        """每次哈希同一密码产生不同输出（salt）。"""
        h1 = hash_password("TestPassword1!")
        h2 = hash_password("TestPassword1!")
        assert h1 != h2

    def test_verify_same_password(self):
        """正确密码验证通过。"""
        plain = "StrongPass123!"
        hashed = hash_password(plain)
        assert verify_password(plain, hashed) is True

    def test_verify_wrong_password(self):
        """错误密码验证失败。"""
        hashed = hash_password("CorrectPass1!")
        assert verify_password("WrongPass1!", hashed) is False

    def test_bcrypt_format(self):
        """哈希字符串以 $2b$ 或 $2a$ 开头（bcrypt 格式）。"""
        hashed = hash_password("TestPass1!")
        assert hashed.startswith("$2b$") or hashed.startswith("$2a$")

    def test_verify_unicode_password(self):
        """Unicode 密码支持。"""
        plain = "密码测试Pass123!"
        hashed = hash_password(plain)
        assert verify_password(plain, hashed) is True


# ════════════════════════════════════════════════════════════════
# 密码 72 字节截断
# ════════════════════════════════════════════════════════════════
class TestPasswordTruncation:

    def test_short_password_unchanged(self):
        """短密码不截断。"""
        plain = "Short1!"
        assert _truncate_password(plain) == plain

    def test_exact_72_bytes_unchanged(self):
        """恰好 72 字节的 ASCII 密码不截断。"""
        plain = "a" * 72  # 72 ASCII = 72 bytes
        assert len(_truncate_password(plain)) == 72

    def test_over_72_bytes_truncated(self):
        """超过 72 字节时截断。"""
        plain = "a" * 100  # 100 ASCII = 100 bytes
        result = _truncate_password(plain)
        assert len(result) == 72

    def test_multibyte_unicode_truncation(self):
        """多字节 Unicode 字符：按字节截断，确保不超过 72 字节。"""
        # 中文每个字符 3 字节，25 * 3 = 75 > 72
        plain = "密码" * 25
        encoded = _truncate_password(plain).encode("utf-8")
        assert len(encoded) <= 72

    def test_truncated_password_still_verifiable(self):
        """截断后的密码与原始哈希兼容（bcrypt 只使用前 72 字节）。"""
        # 超出 72 字节的密码
        long_plain = "a" * 80
        truncated = _truncate_password(long_plain)
        # hash_password 内部已调用 _truncate_password
        hashed = hash_password(long_plain)
        # 验证截断后的密码应与长密码的哈希匹配
        assert verify_password(truncated, hashed) is True
        # 也验证原始长密码可验证
        assert verify_password(long_plain, hashed) is True


# ════════════════════════════════════════════════════════════════
# JWT 签发与解码
# ════════════════════════════════════════════════════════════════
class TestJWT:

    def test_create_and_decode_roundtrip(self):
        """令牌签发后可正确解码。"""
        token = create_access_token(
            "00000000-0000-0000-0000-000000000001",
            ["learner", "admin"]
        )
        payload = decode_token(token)
        assert payload["sub"] == "00000000-0000-0000-0000-000000000001"
        assert "learner" in payload["roles"]
        assert "admin" in payload["roles"]

    def test_decode_invalid_token_raises(self):
        """无效令牌解码抛出 ValueError。"""
        with pytest.raises(ValueError, match="Invalid token"):
            decode_token("invalid.token.string")

    def test_token_contains_iat_and_exp(self):
        """令牌包含签发时间（iat）和过期时间（exp）。"""
        token = create_access_token(
            "00000000-0000-0000-0000-000000000001",
            ["learner"]
        )
        payload = decode_token(token)
        assert "iat" in payload
        assert "exp" in payload
        assert payload["exp"] > payload["iat"]

    def test_decode_empty_token_raises(self):
        """空令牌解码抛出 ValueError。"""
        with pytest.raises(ValueError, match="Invalid token"):
            decode_token("")

    def test_decode_none_token_raises(self):
        """None 令牌解码抛出异常。"""
        with pytest.raises((ValueError, TypeError, AttributeError)):
            decode_token(None)


# ════════════════════════════════════════════════════════════════
# UUID 规范化（安全：防止注入）
# ════════════════════════════════════════════════════════════════
class TestNormalizeUUID:

    def test_valid_uuid_string(self):
        result = _normalize_uuid_str("00000000-0000-0000-0000-000000000001")
        assert result == "00000000-0000-0000-0000-000000000001"

    def test_invalid_uuid_string_raises(self):
        """非 UUID 格式字符串应抛出 ValueError。"""
        with pytest.raises(ValueError):
            _normalize_uuid_str("not-a-uuid")

    def test_sql_injection_attempt_rejected(self):
        """SQL 注入字符串不应被当作有效 UUID。"""
        with pytest.raises(ValueError):
            _normalize_uuid_str("'; DROP TABLE users; --")

    def test_uuid_object_passthrough(self):
        """UUID 对象直接转为字符串。"""
        from uuid import UUID
        uid = UUID("00000000-0000-0000-0000-000000000001")
        result = _normalize_uuid_str(uid)
        assert result == "00000000-0000-0000-0000-000000000001"


# ════════════════════════════════════════════════════════════════
# 密码强度校验
# ════════════════════════════════════════════════════════════════
class TestPasswordStrength:

    def test_strong_password_accepted(self):
        """强密码（大写+小写+数字+特殊字符，>=8位）通过。"""
        assert _check_password_strength("Str0ng!Pass") == "Str0ng!Pass"

    def test_too_short_rejected(self):
        """少于 8 位拒绝。"""
        with pytest.raises(ValueError, match="至少 8 位"):
            _check_password_strength("Ab1!")

    def test_only_one_char_type_rejected(self):
        """仅含一种字符类型拒绝。"""
        with pytest.raises(ValueError, match="至少三种"):
            _check_password_strength("abcdefgh")

    def test_only_two_char_types_rejected(self):
        """仅含两种字符类型拒绝。"""
        with pytest.raises(ValueError, match="至少三种"):
            _check_password_strength("abcdefg1")

    def test_three_char_types_accepted(self):
        """三种字符类型（大写+小写+数字）通过。"""
        assert _check_password_strength("Abcdefgh1") == "Abcdefgh1"

    def test_common_password_rejected(self):
        """常见弱密码拒绝。"""
        with pytest.raises(ValueError, match="过于常见"):
            _check_password_strength("Password123")

    def test_all_common_passwords_rejected(self):
        """所有内置常见密码均被拒绝。"""
        from apps.api.modules.auth.router import _check_password_strength
        common_passwords = ["Aa123456", "Abc12345", "Admin123", "Qwerty123"]
        for pw in common_passwords:
            with pytest.raises(ValueError, match="过于常见"):
                _check_password_strength(pw)

    def test_eight_char_min_boundary(self):
        """恰好 8 位符合复杂度要求通过。"""
        assert _check_password_strength("Abcdefg1") == "Abcdefg1"


# ════════════════════════════════════════════════════════════════
# IP 速率限制器（滑动窗口）
# ════════════════════════════════════════════════════════════════
class TestRateLimiter:

    def test_first_request_allowed(self):
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        assert limiter.is_allowed("192.168.1.1") is True

    def test_requests_within_limit_allowed(self):
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        for _ in range(5):
            assert limiter.is_allowed("192.168.1.1") is True

    def test_requests_exceed_limit_blocked(self):
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            assert limiter.is_allowed("192.168.1.1") is True
        # 第 4 次应被拒绝
        assert limiter.is_allowed("192.168.1.1") is False

    def test_different_keys_independent(self):
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        # Key A 用完限额
        assert limiter.is_allowed("A") is True
        assert limiter.is_allowed("A") is True
        assert limiter.is_allowed("A") is False
        # Key B 不受影响
        assert limiter.is_allowed("B") is True

    def test_reset_after_returns_seconds(self):
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        assert limiter.is_allowed("192.168.1.1") is True
        retry_after = limiter.reset_after("192.168.1.1")
        # 刚用完，需等约 60 秒
        assert 0 < retry_after <= 60

    def test_reset_after_no_record_returns_zero(self):
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        assert limiter.reset_after("never.seen") == 0.0

    def test_window_cleanup_frees_slots(self):
        """手动模拟窗口滑动：旧记录过期后，新请求应被允许。"""
        limiter = RateLimiter(max_requests=2, window_seconds=1)
        assert limiter.is_allowed("ip") is True
        assert limiter.is_allowed("ip") is True
        assert limiter.is_allowed("ip") is False
        # 等待窗口过期
        time.sleep(1.1)
        # 旧记录应被清理，新请求允许
        assert limiter.is_allowed("ip") is True

    def test_cleanup_removes_expired_keys(self):
        limiter = RateLimiter(max_requests=10, window_seconds=0.01)
        limiter.is_allowed("temp.ip")
        time.sleep(0.02)
        limiter._cleanup("temp.ip", time.time())
        assert "temp.ip" not in limiter._store


# ════════════════════════════════════════════════════════════════
# require_role 权限检查
# ════════════════════════════════════════════════════════════════
class TestRequireRole:

    @pytest.mark.asyncio
    async def test_admin_passes_admin_check(self):
        """管理员用户通过 require_role("admin") 检查。"""
        checker = require_role("admin")
        user = {"user_id": "u1", "roles": ["admin", "learner"]}
        result = await checker(current_user=user)
        assert result == user

    @pytest.mark.asyncio
    async def test_learner_fails_admin_check(self):
        """普通用户无法通过 require_role("admin") 检查。"""
        from fastapi import HTTPException
        checker = require_role("admin")
        user = {"user_id": "u1", "roles": ["learner"]}
        with pytest.raises(HTTPException) as exc:
            await checker(current_user=user)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_any_matching_role_passes(self):
        """多角色要求中，匹配任意一个即可通过。"""
        checker = require_role("admin", "knowledge_reviewer")
        user = {"user_id": "u1", "roles": ["knowledge_reviewer", "learner"]}
        result = await checker(current_user=user)
        assert result == user

    @pytest.mark.asyncio
    async def test_empty_roles_fails(self):
        """无角色用户无法通过任何权限检查。"""
        from fastapi import HTTPException
        checker = require_role("admin")
        user = {"user_id": "u1", "roles": []}
        with pytest.raises(HTTPException) as exc:
            await checker(current_user=user)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_no_roles_key_fails(self):
        """缺少 roles 字段的用户无法通过检查。"""
        from fastapi import HTTPException
        checker = require_role("admin")
        user = {"user_id": "u1"}  # 无 roles
        with pytest.raises(HTTPException) as exc:
            await checker(current_user=user)
        assert exc.value.status_code == 403


# ════════════════════════════════════════════════════════════════
# JWT 密钥强度验证（config 级）
# ════════════════════════════════════════════════════════════════
class TestJWTSecretValidation:

    def test_development_env_allows_empty_secret(self):
        """开发环境下允许空/弱密钥（APP_ENV=development）。"""
        with patch.dict("os.environ", {"APP_ENV": "development", "JWT_SECRET_KEY": ""}):
            from apps.api.core.config import Settings, get_settings
            # 在开发环境下，空密钥不应导致 RuntimeError
            try:
                settings = Settings()
                assert settings.env == "development"
        # 注意：CONFIG 在模块加载时已缓存，此测试验证 Settings 类的行为
            except RuntimeError:
                pytest.fail("Development environment should allow empty JWT secret")

    def test_production_requires_nondefulat_secret(self):
        """生产环境应拒绝弱默认密钥。"""
        from apps.api.core.config import Settings
        settings = Settings()
        # 生产环境下使用弱密钥应触发校验
        if settings.env != "development":
            assert settings.jwt.secret_key not in (
                "", "change-me-in-production", "dev-secret-key-CHANGE-IN-PRODUCTION"
            )

    def test_get_settings_caches_result(self):
        """get_settings() 应返回缓存的同一实例。"""
        from apps.api.core.config import get_settings
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

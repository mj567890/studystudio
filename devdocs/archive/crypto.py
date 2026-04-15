"""
apps/api/core/crypto.py
AI 配置敏感字段加密封装（Fernet = AES-128-CBC + HMAC-SHA256）

依赖：
    pip install "cryptography>=42"

密钥管理：
    环境变量 AI_CONFIG_ENCRYPTION_KEY，必须是 urlsafe base64 编码的 32 字节。
    生成方法：
        python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
    密钥丢失 = 所有已加密 api_key 作废，必须纳入运维备份流程。

加解密行为：
    encrypt("")   → ""          （空字符串不加密）
    decrypt("")   → ""
    decrypt(坏密文) → "" + 警告 （不抛异常，保持上层接口健壮）
"""
from __future__ import annotations

import os

import structlog
from cryptography.fernet import Fernet, InvalidToken

logger = structlog.get_logger(__name__)

_CIPHER: Fernet | None = None


def _get_cipher() -> Fernet:
    global _CIPHER
    if _CIPHER is not None:
        return _CIPHER

    raw = os.environ.get("AI_CONFIG_ENCRYPTION_KEY", "").strip()
    if not raw:
        raise RuntimeError(
            "AI_CONFIG_ENCRYPTION_KEY 未配置。\n"
            "请执行下面的命令生成密钥，并加入 docker-compose.yml 中 api / celery_worker / celery_worker_knowledge 三个服务的 environment：\n"
            '    python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"\n'
            "密钥丢失等于所有已加密 api_key 作废，请同时纳入运维备份。"
        )

    try:
        _CIPHER = Fernet(raw.encode("ascii") if isinstance(raw, str) else raw)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            f"AI_CONFIG_ENCRYPTION_KEY 格式错误：{exc}。"
            "必须是 urlsafe base64 编码的 32 字节密钥。"
        ) from exc
    return _CIPHER


def encrypt(plaintext: str) -> str:
    """加密字符串，返回 urlsafe base64 密文。空串返回空串。"""
    if not plaintext:
        return ""
    return _get_cipher().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    """解密密文。空串或解密失败返回空串（并记录警告），不抛异常。"""
    if not ciphertext:
        return ""
    try:
        return _get_cipher().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.warning(
            "Failed to decrypt AI config secret: invalid token or key mismatch. "
            "可能原因：AI_CONFIG_ENCRYPTION_KEY 被替换，或密文被篡改。"
        )
        return ""
    except Exception as exc:
        logger.warning("Decrypt unexpected error", error=str(exc))
        return ""


def mask_secret(secret: str, show_tail: int = 6) -> str:
    """前端回显用的脱敏格式：sk-••••••1a2b3c"""
    if not secret:
        return ""
    if len(secret) <= show_tail:
        return "••••••"
    prefix = secret[:3] if secret.startswith("sk-") else ""
    return f"{prefix}••••••{secret[-show_tail:]}"

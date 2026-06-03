"""登录验证：口令哈希（PBKDF2）+ 无状态 HMAC 令牌 + FastAPI 守卫依赖。

只用标准库，不引入额外依赖。令牌为无状态签名串，重启后端不会失效（密钥持久化在
data 目录的 .auth_secret 文件）。内部管理工具，安全级别取「够用且不明文存储口令」。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings

# ---- 口令哈希 ------------------------------------------------------------

_PBKDF2_ITERS = 100_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERS)
    return f"pbkdf2_sha256${_PBKDF2_ITERS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters_s, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters_s)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


# ---- 令牌签发 / 校验 -----------------------------------------------------

_TOKEN_TTL = 30 * 24 * 3600  # 30 天


@lru_cache(maxsize=1)
def _secret() -> bytes:
    """持久化的签名密钥：data 目录下 .auth_secret，缺失则生成。"""
    secret_path = Path(get_settings().infra.data_dir) / ".auth_secret"
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    if secret_path.exists():
        data = secret_path.read_text(encoding="utf-8").strip()
        if data:
            return bytes.fromhex(data)
    secret = secrets.token_bytes(32)
    secret_path.write_text(secret.hex(), encoding="utf-8")
    try:
        os.chmod(secret_path, 0o600)
    except OSError:
        pass
    return secret


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def create_token(username: str) -> str:
    expiry = int(time.time()) + _TOKEN_TTL
    payload = f"{username}:{expiry}"
    sig = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).digest()
    return f"{_b64e(payload.encode('utf-8'))}.{_b64e(sig)}"


def verify_token(token: str) -> str | None:
    """校验令牌，返回 username；无效或过期返回 None。"""
    try:
        payload_b64, sig_b64 = token.split(".")
        payload = _b64d(payload_b64).decode("utf-8")
        expected = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64d(sig_b64), expected):
            return None
        username, expiry_s = payload.rsplit(":", 1)
        if int(expiry_s) < int(time.time()):
            return None
        return username
    except (ValueError, TypeError):
        return None


# ---- FastAPI 守卫依赖 ----------------------------------------------------

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    username = verify_token(creds.credentials)
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效，请重新登录"
        )
    return username


# ---- 启动时播种默认管理员 ------------------------------------------------

DEFAULT_ADMIN = "admin"
DEFAULT_PASSWORD = "admin"


def seed_default_admin(factory) -> None:
    """无任何用户时创建默认管理员 admin/admin。"""
    from app.models.user import User

    db = factory()
    try:
        if db.query(User).count() > 0:
            return
        db.add(User(username=DEFAULT_ADMIN, password_hash=hash_password(DEFAULT_PASSWORD)))
        db.commit()
    finally:
        db.close()

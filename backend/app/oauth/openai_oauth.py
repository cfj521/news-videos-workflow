"""OpenAI ChatGPT 订阅 OAuth（借用 Codex 公开 client，调用未公开端点，仅个人本机使用）。"""
from __future__ import annotations

import base64
import hashlib
import httpx
import json
import secrets
import threading
from datetime import datetime, timezone
from urllib.parse import quote, urlencode

# ---- 常量 ----
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTH_BASE = "https://auth.openai.com"
AUTHORIZE_URL = f"{AUTH_BASE}/oauth/authorize"
TOKEN_URL = f"{AUTH_BASE}/oauth/token"
REDIRECT_URI = "http://localhost:1455/auth/callback"
SCOPE = "openid profile email offline_access"
ORIGINATOR = "codex_cli_rs"
CODEX_BASE = "https://chatgpt.com/backend-api/codex"
CALLBACK_PORT = 1455


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def gen_pkce() -> tuple[str, str]:
    """返回 (code_verifier, code_challenge)，S256。"""
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def build_authorize_url(code_challenge: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "originator": ORIGINATOR,
    }
    # quote_via=quote 让空格编码为 %20（OpenAI 不接受 +）
    return f"{AUTHORIZE_URL}?{urlencode(params, quote_via=quote)}"


def parse_claims(jwt_str: str) -> dict:
    """解 JWT payload（不验签，仅本地读取声明）。"""
    payload = json.loads(_b64url_decode(jwt_str.split(".")[1]))
    auth = payload.get("https://api.openai.com/auth", {}) or {}
    profile = payload.get("https://api.openai.com/profile", {}) or {}
    return {
        "exp": payload.get("exp"),
        "account_id": auth.get("chatgpt_account_id", ""),
        "plan_type": auth.get("chatgpt_plan_type", ""),
        "email": profile.get("email") or payload.get("email", ""),
    }


def exchange_code(code: str, code_verifier: str) -> dict:
    """用 authorization_code 换取 access_token / refresh_token。"""
    data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier,
    }
    with httpx.Client(timeout=30) as c:
        resp = c.post(TOKEN_URL, data=data)
        resp.raise_for_status()
        return resp.json()


def refresh_tokens(refresh_token: str) -> dict:
    """用 refresh_token 换取新 access_token。"""
    data = {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": refresh_token,
        "scope": SCOPE,
    }
    with httpx.Client(timeout=30) as c:
        resp = c.post(TOKEN_URL, data=data)
        resp.raise_for_status()
        return resp.json()


# ---- token 服务 ----

_refresh_lock = threading.Lock()
_REFRESH_MARGIN = 300  # 距过期 <5 分钟即刷新


class NotLoggedInError(Exception):
    pass


def _apply_tokens(row, tok: dict) -> None:
    """把 token dict 写入 row（解析 access_token 声明）。"""
    access = tok["access_token"]
    claims = parse_claims(access)
    row.access_token = access
    if tok.get("refresh_token"):
        row.refresh_token = tok["refresh_token"]
    if tok.get("id_token"):
        row.id_token = tok["id_token"]
    row.account_id = claims["account_id"] or row.account_id
    row.plan_type = claims["plan_type"] or row.plan_type
    row.account_email = claims["email"] or row.account_email
    if claims["exp"] is None:
        raise ValueError("access_token 缺少 exp 声明")
    row.expires_at = datetime.fromtimestamp(claims["exp"], tz=timezone.utc)
    row.last_refresh = datetime.now(timezone.utc)


def store_tokens(db, tok: dict):
    from app.models.oauth_credential import OAuthCredential
    row = db.query(OAuthCredential).filter_by(provider="openai").first()
    if row is None:
        row = OAuthCredential(provider="openai", refresh_token="", access_token="", expires_at=datetime.now(timezone.utc))
        db.add(row)
    _apply_tokens(row, tok)
    db.commit()
    db.refresh(row)
    return row


def get_valid_access_token(db) -> tuple[str, str]:
    """返回 (access_token, account_id)；临期自动刷新。未登录抛 NotLoggedInError。"""
    from app.models.oauth_credential import OAuthCredential
    row = db.query(OAuthCredential).filter_by(provider="openai").first()
    if row is None:
        raise NotLoggedInError("未登录 OpenAI（订阅模式）")
    now = datetime.now(timezone.utc)
    # 兜底：SQLite 下 expires_at 可能是 naive datetime，统一视为 UTC
    expires_at = row.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    remaining = (expires_at - now).total_seconds()
    if remaining < _REFRESH_MARGIN:
        with _refresh_lock:
            db.refresh(row)
            expires_at2 = row.expires_at
            if expires_at2 is not None and expires_at2.tzinfo is None:
                expires_at2 = expires_at2.replace(tzinfo=timezone.utc)
            if (expires_at2 - datetime.now(timezone.utc)).total_seconds() < _REFRESH_MARGIN:
                tok = refresh_tokens(row.refresh_token)
                _apply_tokens(row, tok)
                db.commit()
                db.refresh(row)
    return row.access_token, row.account_id


def get_status(db) -> dict:
    from app.models.oauth_credential import OAuthCredential
    row = db.query(OAuthCredential).filter_by(provider="openai").first()
    if row is None:
        return {"logged_in": False}
    expires_at = row.expires_at
    if expires_at is not None:
        # 兜底：SQLite 下可能是 naive datetime，统一视为 UTC，保证 isoformat 带时区后缀
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        expires_iso = expires_at.isoformat()
    else:
        expires_iso = None
    return {
        "logged_in": True,
        "email": row.account_email,
        "plan": row.plan_type,
        "expires_at": expires_iso,
    }


def logout(db) -> None:
    from app.models.oauth_credential import OAuthCredential
    db.query(OAuthCredential).filter_by(provider="openai").delete()
    db.commit()

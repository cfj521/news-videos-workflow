"""OpenAI ChatGPT 订阅 OAuth（借用 Codex 公开 client，调用未公开端点，仅个人本机使用）。"""
from __future__ import annotations

import base64
import hashlib
import httpx
import json
import secrets
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

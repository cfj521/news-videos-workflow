"""OpenAI ChatGPT 订阅 OAuth（借用 Codex 公开 client，调用未公开端点，仅个人本机使用）。"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import socket
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, quote, urlencode, urlparse

import httpx
import openai

from app.store import providers_store
from app.store.oauth_models import OAuthData

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


def _apply_tokens(data: "OAuthData", tok: dict) -> None:
    """把 token dict 写入 OAuthData（解析 access_token 声明）。"""
    access = tok["access_token"]
    claims = parse_claims(access)
    data.access_token = access
    if tok.get("refresh_token"):
        data.refresh_token = tok["refresh_token"]
    if tok.get("id_token"):
        data.id_token = tok["id_token"]
    data.account_id = claims["account_id"] or data.account_id
    data.plan_type = claims["plan_type"] or data.plan_type
    data.account_email = claims["email"] or data.account_email
    if claims["exp"] is None:
        raise ValueError("access_token 缺少 exp 声明")
    data.expires_at = datetime.fromtimestamp(claims["exp"], tz=timezone.utc).isoformat()
    data.last_refresh = datetime.now(timezone.utc).isoformat()


_PROVIDER = "openai"


def store_tokens(tok: dict) -> OAuthData:
    data = providers_store.load_oauth(_PROVIDER)
    _apply_tokens(data, tok)
    providers_store.save_oauth(_PROVIDER, data)
    return data


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def get_valid_access_token() -> tuple[str, str]:
    """返回 (access_token, account_id)；临期自动刷新。未登录抛 NotLoggedInError。"""
    data = providers_store.load_oauth(_PROVIDER)
    if not data.access_token:
        raise NotLoggedInError("未登录 OpenAI（订阅模式）")
    now = datetime.now(timezone.utc)
    expires_at = _parse_iso(data.expires_at)
    remaining = (expires_at - now).total_seconds() if expires_at else -1
    if remaining < _REFRESH_MARGIN:
        with _refresh_lock:
            data = providers_store.load_oauth(_PROVIDER)  # 锁内重读，避免重复刷新
            expires_at2 = _parse_iso(data.expires_at)
            now2 = datetime.now(timezone.utc)
            if not expires_at2 or (expires_at2 - now2).total_seconds() < _REFRESH_MARGIN:
                if not data.refresh_token:
                    raise NotLoggedInError("缺少 refresh_token，请重新登录 OpenAI（订阅模式）")
                tok = refresh_tokens(data.refresh_token)
                _apply_tokens(data, tok)
                providers_store.save_oauth(_PROVIDER, data)
    return data.access_token, data.account_id


def get_status() -> dict:
    data = providers_store.load_oauth(_PROVIDER)
    if not data.access_token:
        return {"logged_in": False}
    expires_at = _parse_iso(data.expires_at)
    return {
        "logged_in": True,
        "email": data.account_email,
        "plan": data.plan_type,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


def logout() -> None:
    providers_store.clear_oauth(_PROVIDER)


# ---- 回调监听 + subscription_creds + codex client ----

log = logging.getLogger("oauth.openai")


def _open_session():
    """自建 DB session（回调线程/provider 无 db 时用）。"""
    from app.api.dependencies import get_session_factory
    return get_session_factory()()


def handle_callback(db, query: dict) -> bool:
    """处理回调 query。db 仅用于读写 OAuthLoginSession；token 走 providers_store。"""
    from app.models.oauth_credential import OAuthLoginSession
    state = query.get("state", "")
    code = query.get("code", "")
    sess = db.query(OAuthLoginSession).filter_by(state=state, status="pending").first()
    if sess is None or not code:
        return False
    try:
        tok = exchange_code(code, sess.code_verifier)
        store_tokens(tok)
        sess.status = "success"
        db.commit()
        return True
    except Exception as e:  # noqa: BLE001
        log.exception("OAuth 回调处理失败")
        sess.status = "error"
        sess.error = str(e)
        db.commit()
        return False


class _DualStackHTTPServer(HTTPServer):
    """同时监听 IPv4/IPv6。Windows 上 localhost 常优先解析为 ::1，单绑 127.0.0.1 会被拒。

    用 AF_INET6 + IPV6_V6ONLY=0 让同一 socket 既收 ::1 也收 127.0.0.1（IPv4-mapped）。
    """
    address_family = socket.AF_INET6

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (AttributeError, OSError):
            pass
        super().server_bind()


def start_login_listener(state: str, timeout: int = 300) -> None:
    """后台线程起 1455 监听，处理一次回调后关闭。端口占用直接标记错误。"""
    import time as _time

    result_holder: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # 静音默认日志
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            if not parsed.path.startswith("/auth/callback"):
                self.send_response(404)
                self.end_headers()
                return
            q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            db = _open_session()
            try:
                ok = handle_callback(db, q)
            finally:
                db.close()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "登录成功，可关闭本页。" if ok else "登录失败，请回到设置页重试。"
            self.wfile.write(f"<html><body><h3>{msg}</h3></body></html>".encode("utf-8"))
            result_holder["done"] = True

    def serve():
        # 优先双栈（兼顾 localhost→::1 的 Windows），失败再退回 IPv4；都失败视为端口占用
        server = None
        last_err: OSError | None = None
        for factory in (
            lambda: _DualStackHTTPServer(("", CALLBACK_PORT), Handler),
            lambda: HTTPServer(("127.0.0.1", CALLBACK_PORT), Handler),
        ):
            try:
                server = factory()
                break
            except OSError as e:
                last_err = e
        if server is None:
            log.error("无法绑定 1455 端口（可能 codex 正在登录）：%s", last_err)
            db = _open_session()
            try:
                from app.models.oauth_credential import OAuthLoginSession
                s = db.query(OAuthLoginSession).filter_by(state=state).first()
                if s:
                    s.status, s.error = "error", "端口 1455 被占用"
                    db.commit()
            finally:
                db.close()
            return
        server.timeout = 5
        deadline = _time.time() + timeout
        while not result_holder.get("done") and _time.time() < deadline:
            server.handle_request()
        server.server_close()

    threading.Thread(target=serve, daemon=True).start()


def subscription_creds() -> tuple[str, str, str]:
    """供 provider 工厂用：返回 (CODEX_BASE, access_token, account_id)。"""
    token, account_id = get_valid_access_token()
    return CODEX_BASE, token, account_id


def build_codex_client(access_token: str, account_id: str):
    return openai.AsyncOpenAI(
        base_url=CODEX_BASE,
        api_key=access_token,
        default_headers={"ChatGPT-Account-ID": account_id, "originator": ORIGINATOR},
    )

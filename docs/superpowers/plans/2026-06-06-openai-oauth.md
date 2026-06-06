# OpenAI OAuth 登录（订阅模式）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 OpenAI 供应商新增「用 ChatGPT 账号 OAuth 登录吃订阅额度」的鉴权模式，与现有 API Key 模式并存，覆盖文本/生图/解析。

**Architecture:** 自写 OAuth PKCE 流程（借用 Codex 公开 client_id），临时起 `127.0.0.1:1455` 监听回调，token 存 DB（登录态也落 DB 以兼容 `--reload` 多进程）。订阅调用走 `https://chatgpt.com/backend-api/codex` 的 Responses API，每次调用前取新 token 建 client 以防中途过期。分两阶段：阶段一登录链路可独立验收，阶段二 provider 三路集成（每路先 spike 抓真实请求）。

**Tech Stack:** FastAPI / SQLAlchemy / openai Python SDK / httpx / 标准库 `http.server` `secrets` `hashlib` `base64`；前端 React + TS。

**Spec:** `docs/superpowers/specs/2026-06-06-openai-oauth-design.md`

---

## 文件结构

阶段一（登录链路）：
- Create `backend/app/models/oauth_credential.py` — DB 模型：凭证 + 登录会话临时态
- Create `backend/app/oauth/__init__.py` — 空包标识
- Create `backend/app/oauth/openai_oauth.py` — OAuth 常量 + PKCE/authorize/parse + token 端点 + 回调监听 + token 服务 + codex client 构造器
- Create `backend/app/api/openai_oauth.py` — `/api/auth/openai/*` 路由（顶部 import 新模型保证建表）
- Modify `backend/app/api/router.py` — 注册新 router
- Modify `backend/app/config.py` — `ProviderCreds.auth_mode`、`ProviderCfg.auth_mode`/`account_id`
- Modify `config.yaml.example` — openai 段补 `auth_mode`
- Modify `backend/app/models/__init__.py` — 导出新模型
- Modify `frontend/src/pages/Settings.tsx` — openai tab 模式切换 + 登录 UI
- Tests: `backend/tests/test_openai_oauth.py`、`backend/tests/test_api_openai_oauth.py`、`backend/tests/test_oauth_credential_model.py`

阶段二（provider 集成）：
- Modify `backend/app/providers/text/openai_text.py` — 订阅分支（responses）
- Modify `backend/app/providers/image/openai_image.py` — 订阅分支（image_generation 工具）
- Modify `backend/app/providers/image/__init__.py` — 工厂订阅分支
- Modify `backend/app/pipeline/runner.py` — `_build_text_provider` / `_build_summary_provider` 订阅分支
- Modify `backend/app/api/pipeline.py` — vision 构造透传 auth_mode/account_id
- Modify `backend/app/services/document_import_pdf.py` — `_vision_extract` 订阅分支
- Tests: `backend/tests/test_openai_text_subscription.py`、`backend/tests/test_image_openai_subscription.py`

> 命令一律在 `backend/` 目录、conda 环境 `env_news_videos_wf` 下执行（`pytest`、`ruff`）。

---

# 阶段一：OAuth 登录链路

## Task 1: 配置层增加 auth_mode

**Files:**
- Modify: `backend/app/config.py`（`ProviderCreds` 约 line 41；`ProviderCfg` 约 line 26）
- Modify: `config.yaml.example`（providers.openai 段，约 line 25-33）
- Test: `backend/tests/test_config_auth_mode.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_config_auth_mode.py`:
```python
from app.config import ProviderCreds, ProviderCfg


def test_provider_creds_default_auth_mode():
    assert ProviderCreds().auth_mode == "api_key"


def test_provider_creds_subscription():
    c = ProviderCreds(auth_mode="subscription")
    assert c.auth_mode == "subscription"


def test_provider_cfg_carries_account_id():
    # vision 透传载体需要带订阅信息
    cfg = ProviderCfg(provider="openai", auth_mode="subscription", account_id="acc-1")
    assert cfg.auth_mode == "subscription"
    assert cfg.account_id == "acc-1"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_config_auth_mode.py -v`
Expected: FAIL（`ProviderCreds` 无 `auth_mode`；`ProviderCfg` 无 `auth_mode`/`account_id`）

- [ ] **Step 3: 实现**

`config.py` 中 `ProviderCreds` 增加字段：
```python
class ProviderCreds(BaseModel):
    """单个供应商的连接凭证与参数。供应商参数库 providers 的一项，被各用途按需引用。"""
    base_url: str = ""
    api_key: str = ""
    auth_mode: str = "api_key"  # api_key | subscription（仅 openai 用，subscription 走 OAuth 订阅）
    max_output_tokens: int = 65535
    models: ProviderModels = ProviderModels()
```

`config.py` 中 `ProviderCfg` 增加字段（vision 透传用）：
```python
class ProviderCfg(BaseModel):
    provider: str = ""
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    auth_mode: str = "api_key"   # 透传给 vision 解析，决定走 chat.completions 还是 codex responses
    account_id: str = ""         # 订阅模式的 ChatGPT account id
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_config_auth_mode.py -v`
Expected: PASS

- [ ] **Step 5: 更新 config.yaml.example**

在 `config.yaml.example` 的 `openai:` 段（`base_url` 下一行）加：
```yaml
  openai:
    base_url: https://api.openai.com/v1
    api_key: ""
    auth_mode: api_key            # api_key（填 key 按量计费）| subscription（ChatGPT 订阅登录，在「模型配置」页登录）
    max_output_tokens: 65535
```

- [ ] **Step 6: 提交**

```bash
git add backend/app/config.py config.yaml.example backend/tests/test_config_auth_mode.py
git commit -m "feat(config): providers 增加 auth_mode；ProviderCfg 透传订阅信息"
```

---

## Task 2: DB 模型 — 凭证表 + 登录会话表

**Files:**
- Create: `backend/app/models/oauth_credential.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_oauth_credential_model.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_oauth_credential_model.py`:
```python
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.oauth_credential import OAuthCredential, OAuthLoginSession


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_credential_roundtrip():
    s = _session()
    s.add(OAuthCredential(
        provider="openai", access_token="at", refresh_token="rt",
        account_id="acc", expires_at=datetime.now(timezone.utc),
        plan_type="plus", account_email="a@b.com",
    ))
    s.commit()
    row = s.query(OAuthCredential).filter_by(provider="openai").one()
    assert row.access_token == "at"
    assert row.plan_type == "plus"


def test_login_session_roundtrip():
    s = _session()
    s.add(OAuthLoginSession(state="st", code_verifier="cv", status="pending"))
    s.commit()
    row = s.query(OAuthLoginSession).filter_by(state="st").one()
    assert row.status == "pending"
    assert row.code_verifier == "cv"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_oauth_credential_model.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现模型**

Create `backend/app/models/oauth_credential.py`:
```python
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class OAuthCredential(Base, TimestampMixin):
    """OAuth 订阅凭证（当前仅 openai/ChatGPT）。token 明文存，仅个人本机使用。"""
    __tablename__ = "oauth_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(30), unique=True, index=True)  # "openai"
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str] = mapped_column(Text)
    id_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_id: Mapped[str] = mapped_column(String(64), default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    plan_type: Mapped[str] = mapped_column(String(32), default="")
    account_email: Mapped[str] = mapped_column(String(255), default="")
    last_refresh: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OAuthLoginSession(Base, TimestampMixin):
    """一次登录流程的临时态：跨进程（--reload）共享 PKCE/state 与结果，故落 DB。"""
    __tablename__ = "oauth_login_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    state: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    code_verifier: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|success|error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 4: 注册到 models/__init__.py**

在 `backend/app/models/__init__.py` 末尾加：
```python
from .oauth_credential import OAuthCredential as OAuthCredential
from .oauth_credential import OAuthLoginSession as OAuthLoginSession
```

- [ ] **Step 5: 运行确认通过**

Run: `pytest tests/test_oauth_credential_model.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/models/oauth_credential.py backend/app/models/__init__.py backend/tests/test_oauth_credential_model.py
git commit -m "feat(models): oauth_credentials + oauth_login_sessions 表"
```

---

## Task 3: OAuth 核心纯函数（PKCE / authorize URL / parse_claims）

**Files:**
- Create: `backend/app/oauth/__init__.py`（空文件）
- Create: `backend/app/oauth/openai_oauth.py`
- Test: `backend/tests/test_openai_oauth.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_openai_oauth.py`:
```python
import base64
import json

from app.oauth import openai_oauth as oo


def test_gen_pkce_shapes():
    verifier, challenge = oo.gen_pkce()
    assert 43 <= len(verifier) <= 128
    assert "=" not in challenge and "+" not in challenge and "/" not in challenge  # base64url 无填充


def test_build_authorize_url_uses_percent20_and_params():
    url = oo.build_authorize_url("CHAL", "STATE")
    assert url.startswith("https://auth.openai.com/oauth/authorize?")
    assert "client_id=app_EMoamEEZ73f0CkXaXp7hrann" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A1455%2Fauth%2Fcallback" in url
    assert "scope=openid%20profile%20email%20offline_access" in url  # 空格必须 %20
    assert "code_challenge=CHAL" in url
    assert "code_challenge_method=S256" in url
    assert "state=STATE" in url


def _fake_jwt(payload: dict) -> str:
    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{b64({'alg': 'none'})}.{b64(payload)}.sig"


def test_parse_claims_extracts_nested_fields():
    token = _fake_jwt({
        "exp": 1781519415,
        "https://api.openai.com/auth": {"chatgpt_account_id": "acc-9", "chatgpt_plan_type": "plus"},
        "https://api.openai.com/profile": {"email": "x@y.com"},
    })
    claims = oo.parse_claims(token)
    assert claims["exp"] == 1781519415
    assert claims["account_id"] == "acc-9"
    assert claims["plan_type"] == "plus"
    assert claims["email"] == "x@y.com"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_openai_oauth.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现核心常量与纯函数**

Create `backend/app/oauth/__init__.py`（空文件）。

Create `backend/app/oauth/openai_oauth.py`:
```python
"""OpenAI ChatGPT 订阅 OAuth（借用 Codex 公开 client，调用未公开端点，仅个人本机使用）。"""
from __future__ import annotations

import base64
import hashlib
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
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_openai_oauth.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/oauth/ backend/tests/test_openai_oauth.py
git commit -m "feat(oauth): PKCE / authorize URL / JWT 声明解析"
```

---

## Task 4: token 端点调用（exchange_code / refresh_tokens）

**Files:**
- Modify: `backend/app/oauth/openai_oauth.py`
- Test: `backend/tests/test_openai_oauth.py`（追加）

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/test_openai_oauth.py` 追加：
```python
def test_exchange_code_posts_expected_body(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"access_token": "at", "refresh_token": "rt"}

    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, data=None, **k):
            captured["url"] = url
            captured["data"] = data
            return FakeResp()

    monkeypatch.setattr(oo.httpx, "Client", FakeClient)
    out = oo.exchange_code("CODE", "VERIFIER")
    assert out["access_token"] == "at"
    assert captured["url"] == oo.TOKEN_URL
    assert captured["data"]["grant_type"] == "authorization_code"
    assert captured["data"]["code"] == "CODE"
    assert captured["data"]["code_verifier"] == "VERIFIER"
    assert captured["data"]["client_id"] == oo.CLIENT_ID
    assert captured["data"]["redirect_uri"] == oo.REDIRECT_URI


def test_refresh_tokens_posts_refresh_grant(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"access_token": "new"}

    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, data=None, **k):
            captured["data"] = data
            return FakeResp()

    monkeypatch.setattr(oo.httpx, "Client", FakeClient)
    out = oo.refresh_tokens("RT")
    assert out["access_token"] == "new"
    assert captured["data"]["grant_type"] == "refresh_token"
    assert captured["data"]["refresh_token"] == "RT"
    assert captured["data"]["client_id"] == oo.CLIENT_ID
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_openai_oauth.py -k "exchange or refresh" -v`
Expected: FAIL（函数不存在 / 无 `oo.httpx`）

- [ ] **Step 3: 实现**

在 `openai_oauth.py` 顶部 import 增加 `import httpx`，并追加：
```python
def exchange_code(code: str, code_verifier: str) -> dict:
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
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_openai_oauth.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/oauth/openai_oauth.py backend/tests/test_openai_oauth.py
git commit -m "feat(oauth): authorization_code 换取与 refresh_token 刷新"
```

---

## Task 5: token 服务（存储 / 取有效 token / 状态 / 登出）

**Files:**
- Modify: `backend/app/oauth/openai_oauth.py`
- Test: `backend/tests/test_openai_oauth.py`（追加）

> 说明：`store_tokens` 把一次 token dict 落库（解析 exp/account_id/plan/email）；`get_valid_access_token` 临期自动刷新（加线程锁防并发双刷）。

- [ ] **Step 1: 追加失败测试**

```python
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.oauth_credential import OAuthCredential


def _db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _jwt_with_exp(exp_ts: int) -> str:
    return _fake_jwt({
        "exp": exp_ts,
        "https://api.openai.com/auth": {"chatgpt_account_id": "acc", "chatgpt_plan_type": "plus"},
        "https://api.openai.com/profile": {"email": "a@b.com"},
    })


def test_store_tokens_parses_and_upserts():
    db = _db()
    exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    oo.store_tokens(db, {"access_token": _jwt_with_exp(exp), "refresh_token": "rt", "id_token": "idt"})
    row = db.query(OAuthCredential).filter_by(provider="openai").one()
    assert row.account_id == "acc"
    assert row.plan_type == "plus"
    assert row.account_email == "a@b.com"
    assert row.refresh_token == "rt"


def test_get_valid_access_token_refreshes_when_near_expiry(monkeypatch):
    db = _db()
    near = int((datetime.now(timezone.utc) + timedelta(seconds=60)).timestamp())  # < 5 分钟
    oo.store_tokens(db, {"access_token": _jwt_with_exp(near), "refresh_token": "old"})
    far = int((datetime.now(timezone.utc) + timedelta(hours=2)).timestamp())
    monkeypatch.setattr(oo, "refresh_tokens",
                        lambda rt: {"access_token": _jwt_with_exp(far), "refresh_token": "new"})
    token, account_id = oo.get_valid_access_token(db)
    assert account_id == "acc"
    row = db.query(OAuthCredential).filter_by(provider="openai").one()
    assert row.refresh_token == "new"  # 已刷新落库


def test_get_valid_access_token_raises_when_not_logged_in():
    db = _db()
    import pytest
    with pytest.raises(oo.NotLoggedInError):
        oo.get_valid_access_token(db)
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_openai_oauth.py -k "store or valid or logged" -v`
Expected: FAIL

- [ ] **Step 3: 实现**

在 `openai_oauth.py` 追加（顶部 import 增加 `import threading` 与 `from datetime import datetime, timezone`）：
```python
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
    row.expires_at = datetime.fromtimestamp(claims["exp"], tz=timezone.utc)
    row.last_refresh = datetime.now(timezone.utc)


def store_tokens(db, tok: dict) -> "OAuthCredential":
    from app.models.oauth_credential import OAuthCredential
    row = db.query(OAuthCredential).filter_by(provider="openai").first()
    if row is None:
        row = OAuthCredential(provider="openai", refresh_token="")
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
    remaining = (row.expires_at - now).total_seconds()
    if remaining < _REFRESH_MARGIN:
        with _refresh_lock:
            db.refresh(row)
            if (row.expires_at - datetime.now(timezone.utc)).total_seconds() < _REFRESH_MARGIN:
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
    return {
        "logged_in": True,
        "email": row.account_email,
        "plan": row.plan_type,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


def logout(db) -> None:
    from app.models.oauth_credential import OAuthCredential
    db.query(OAuthCredential).filter_by(provider="openai").delete()
    db.commit()
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_openai_oauth.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/oauth/openai_oauth.py backend/tests/test_openai_oauth.py
git commit -m "feat(oauth): token 服务（存储/临期刷新/状态/登出）"
```

---

## Task 6: 回调监听 + subscription_creds + codex client

**Files:**
- Modify: `backend/app/oauth/openai_oauth.py`
- Test: `backend/tests/test_openai_oauth.py`（追加）

> 监听设计：`start_login_listener(state)` 在后台线程起 `127.0.0.1:1455`，收到 `/auth/callback?code&state` → 自建 DB session → 查 pending 会话取 code_verifier → `exchange_code` → `store_tokens` → 会话标 success → 回 HTML → 关监听；超时 300s 标 error。`_handle_callback(query)` 抽成可单测的纯逻辑函数（不依赖真实 socket）。

- [ ] **Step 1: 追加失败测试**

```python
def test_handle_callback_success(monkeypatch):
    db = _db()
    from app.models.oauth_credential import OAuthLoginSession, OAuthCredential
    db.add(OAuthLoginSession(state="S1", code_verifier="V1", status="pending"))
    db.commit()
    far = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    monkeypatch.setattr(oo, "exchange_code",
                        lambda code, cv: {"access_token": _jwt_with_exp(far), "refresh_token": "rt"})
    ok = oo.handle_callback(db, {"code": "C", "state": "S1"})
    assert ok is True
    assert db.query(OAuthLoginSession).filter_by(state="S1").one().status == "success"
    assert db.query(OAuthCredential).filter_by(provider="openai").one().refresh_token == "rt"


def test_handle_callback_bad_state():
    db = _db()
    ok = oo.handle_callback(db, {"code": "C", "state": "NOPE"})
    assert ok is False


def test_subscription_creds(monkeypatch):
    db = _db()
    far = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    oo.store_tokens(db, {"access_token": _jwt_with_exp(far), "refresh_token": "rt"})
    monkeypatch.setattr(oo, "_open_session", lambda: db)
    base_url, token, account_id = oo.subscription_creds()
    assert base_url == oo.CODEX_BASE
    assert account_id == "acc"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_openai_oauth.py -k "callback or subscription_creds" -v`
Expected: FAIL

- [ ] **Step 3: 实现**

在 `openai_oauth.py` 追加（顶部 import 增加 `import logging`、`import threading`（已加）、`from http.server import BaseHTTPRequestHandler, HTTPServer`、`from urllib.parse import urlparse, parse_qs`、`import openai`）：
```python
log = logging.getLogger("oauth.openai")


def _open_session():
    """自建 DB session（回调线程/provider 无 db 时用）。"""
    from app.api.dependencies import get_session_factory
    return get_session_factory()()


def handle_callback(db, query: dict) -> bool:
    """处理回调 query（已解析为 {code, state}）。成功 True，state 不符 False。"""
    from app.models.oauth_credential import OAuthLoginSession
    state = query.get("state", "")
    code = query.get("code", "")
    sess = db.query(OAuthLoginSession).filter_by(state=state, status="pending").first()
    if sess is None or not code:
        return False
    try:
        tok = exchange_code(code, sess.code_verifier)
        store_tokens(db, tok)
        sess.status = "success"
        db.commit()
        return True
    except Exception as e:  # noqa: BLE001
        log.exception("OAuth 回调处理失败")
        sess.status = "error"
        sess.error = str(e)
        db.commit()
        return False


def start_login_listener(state: str, timeout: int = 300) -> None:
    """后台线程起 1455 监听，处理一次回调后关闭。端口占用直接抛错。"""
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
        try:
            server = HTTPServer(("127.0.0.1", CALLBACK_PORT), Handler)
        except OSError as e:
            log.error("无法绑定 1455 端口（可能 codex 正在登录）：%s", e)
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
        deadline = __import__("time").time() + timeout
        while not result_holder.get("done") and __import__("time").time() < deadline:
            server.handle_request()
        server.server_close()

    threading.Thread(target=serve, daemon=True).start()


def subscription_creds() -> tuple[str, str, str]:
    """供 provider 工厂用：返回 (CODEX_BASE, access_token, account_id)，自开 session。"""
    db = _open_session()
    try:
        token, account_id = get_valid_access_token(db)
        return CODEX_BASE, token, account_id
    finally:
        db.close()


def build_codex_client(access_token: str, account_id: str) -> "openai.AsyncOpenAI":
    return openai.AsyncOpenAI(
        base_url=CODEX_BASE,
        api_key=access_token,
        default_headers={"ChatGPT-Account-ID": account_id, "originator": ORIGINATOR},
    )
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_openai_oauth.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/oauth/openai_oauth.py backend/tests/test_openai_oauth.py
git commit -m "feat(oauth): 1455 回调监听 + subscription_creds + codex client 构造"
```

---

## Task 7: API 路由 + 注册（建表链路收口）

**Files:**
- Create: `backend/app/api/openai_oauth.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/test_api_openai_oauth.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_api_openai_oauth.py`:
```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth, config
from app.api.dependencies import get_db
from app.auth import create_token, hash_password
from app.main import create_app
from app.models import Base
from app.models.user import User


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.yaml")
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(config.get_settings().infra, "data_dir", str(tmp_path / "data"))
    auth._secret.cache_clear()
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sf = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    app = create_app()

    def override():
        s = sf()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    s = sf(); s.add(User(username="admin", password_hash=hash_password("admin"))); s.commit(); s.close()
    return TestClient(app), create_token("admin")


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_status_logged_out(client):
    c, tok = client
    r = c.get("/api/auth/openai/status", headers=_h(tok))
    assert r.status_code == 200
    assert r.json()["logged_in"] is False


def test_login_start_returns_authorize_url(client, monkeypatch):
    c, tok = client
    from app.api import openai_oauth as route
    monkeypatch.setattr(route.oo, "start_login_listener", lambda state: None)  # 不真起 1455
    r = c.post("/api/auth/openai/login/start", headers=_h(tok))
    assert r.status_code == 200
    assert r.json()["authorize_url"].startswith("https://auth.openai.com/oauth/authorize?")


def test_requires_auth(client):
    c, _ = client
    assert c.get("/api/auth/openai/status").status_code == 401
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_api_openai_oauth.py -v`
Expected: FAIL（路由不存在）

- [ ] **Step 3: 实现路由**

Create `backend/app/api/openai_oauth.py`:
```python
import secrets

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.logging import get_logger
from app.oauth import openai_oauth as oo
# 顶部 import 新模型：保证启动时注册到 Base.metadata（create_all 建表）—— 见 spec S1
from app.models.oauth_credential import OAuthCredential, OAuthLoginSession  # noqa: F401

log = get_logger("api.auth.openai")
router = APIRouter(prefix="/api/auth/openai", tags=["openai-oauth"])


@router.post("/login/start")
async def login_start(db: Session = Depends(get_db)):
    verifier, challenge = oo.gen_pkce()
    state = secrets.token_urlsafe(24)
    # 清理同 provider 旧的 pending 会话，避免堆积
    db.query(OAuthLoginSession).filter_by(status="pending").delete()
    db.add(OAuthLoginSession(state=state, code_verifier=verifier, status="pending"))
    db.commit()
    oo.start_login_listener(state)
    return {"authorize_url": oo.build_authorize_url(challenge, state), "state": state}


@router.get("/login/status")
async def login_status(state: str, db: Session = Depends(get_db)):
    sess = db.query(OAuthLoginSession).filter_by(state=state).first()
    if sess is None:
        return {"status": "error", "error": "会话不存在"}
    return {"status": sess.status, "error": sess.error}


@router.get("/status")
async def status(db: Session = Depends(get_db)):
    return oo.get_status(db)


@router.post("/logout")
async def logout(db: Session = Depends(get_db)):
    oo.logout(db)
    return {"status": "ok"}
```

- [ ] **Step 4: 注册 router**

修改 `backend/app/api/router.py`：顶部加 import，并在受保护区块注册。
```python
from app.api.openai_oauth import router as openai_oauth_router
```
在 `_guard` 注册区追加：
```python
api_router.include_router(openai_oauth_router, dependencies=_guard)
```

- [ ] **Step 5: 运行确认通过**

Run: `pytest tests/test_api_openai_oauth.py -v`
Expected: PASS

- [ ] **Step 6: 回归 + lint**

Run: `pytest -q && ruff check .`
Expected: 全绿（确认未破坏既有用例、新模型被 create_all 建表）

- [ ] **Step 7: 提交**

```bash
git add backend/app/api/openai_oauth.py backend/app/api/router.py backend/tests/test_api_openai_oauth.py
git commit -m "feat(api): /api/auth/openai 登录/状态/登出路由"
```

---

## Task 8: 前端 — openai tab 鉴权模式切换 + 登录 UI

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`（「模型配置」openai 供应商凭证区，约 line 349-357 的 `PROVIDER_TABS` / 凭证渲染处）

> 前端无强 TDD；以手动验收为主。先读 `Settings.tsx` 找到 openai 供应商凭证渲染处与保存逻辑，按既有控件风格加。

- [ ] **Step 1: 加鉴权模式状态与切换**

在 openai 供应商凭证区上方加单选（值绑 `providers.openai.auth_mode`，沿用页面既有 inputCls/按钮风格）：
- 「API Key」「订阅登录」两个选项。
- `auth_mode === "api_key"`：渲染现有 api_key 输入框。
- `auth_mode === "subscription"`：隐藏 api_key 输入，渲染登录区（下一步）。

- [ ] **Step 2: 登录区组件**

新增一个内联组件/区块：
```tsx
// 伪代码骨架，按页面现有 fetch 封装与样式落地
function OpenAISubscription() {
  const [status, setStatus] = useState<{logged_in:boolean; email?:string; plan?:string; expires_at?:string}>();
  const load = async () => setStatus(await api.get("/api/auth/openai/status"));
  useEffect(() => { load(); }, []);

  const login = async () => {
    const { authorize_url, state } = await api.post("/api/auth/openai/login/start");
    window.open(authorize_url, "_blank");
    // 轮询 2s 一次，最多 ~150 次（5 分钟）
    const timer = setInterval(async () => {
      const r = await api.get(`/api/auth/openai/login/status?state=${state}`);
      if (r.status === "success") { clearInterval(timer); load(); }
      if (r.status === "error") { clearInterval(timer); alert("登录失败: " + (r.error||"")); }
    }, 2000);
  };
  const logout = async () => { await api.post("/api/auth/openai/logout"); load(); };

  if (!status) return null;
  return status.logged_in
    ? <div>已登录：{status.email}（{status.plan}，到期 {status.expires_at}）<button onClick={logout}>退出登录</button></div>
    : <button onClick={login}>登录 ChatGPT</button>;
}
```
说明文案：「订阅模式仅支持 文案/生图/解析，不支持语音；生图固定用 gpt-5.5。」

- [ ] **Step 3: 保存 auth_mode**

确认保存设置（既有「保存」逻辑）会把 `providers.openai.auth_mode` 一并写回（settings 保存接口已整体回写 providers，无需额外端点）。

- [ ] **Step 4: 构建验证**

Run（在 `frontend/`）：`pnpm lint && pnpm build`
Expected: 通过

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/Settings.tsx
git commit -m "feat(frontend): openai 鉴权模式切换 + ChatGPT 登录 UI"
```

---

## 阶段一验收

- [ ] 本机起后端 + 前端（用户自行启动，勿代启），设置页 openai 选「订阅登录」→ 点登录 → 浏览器授权 → 回到设置页显示已登录（邮箱/plus/到期）。
- [ ] `pytest -q` 全绿；`oauth_credentials` / `oauth_login_sessions` 表已建。
- [ ] 登出可清除状态。

> 阶段一完成即验证了「灰色端点登录链路是否走得通」。确认后再进阶段二。

---

# 阶段二：Provider 集成（每路先 spike）

> ⚠️ 阶段二依赖未公开端点的精确契约。每个 Task 第 0 步为 **spike**：用本机已登录的 codex 抓一次真实请求确认格式，再写代码。spike 命令示例（PowerShell，用户本机执行）：
> 用 codex CLI 实际跑一次对应操作并开启 verbose / 抓包，或参考 `~/.codex/auth.json` 的 access_token 手测：
> ```powershell
> # 文本/流式确认（确认 stream=False 是否被接受、返回结构）
> # 用 access_token 对 https://chatgpt.com/backend-api/codex/responses 发一个最小 responses 请求
> ```
> 由实现者在该步把确认结论写入对应 Task 的注释后再继续。

## Task 9: 文本 provider 订阅分支

**Files:**
- Modify: `backend/app/providers/text/openai_text.py`
- Modify: `backend/app/pipeline/runner.py`（`_build_text_provider` line 30；`_build_summary_provider` line 159）
- Test: `backend/tests/test_openai_text_subscription.py`

- [ ] **Step 0: SPIKE** — 确认 `responses.create(stream=False)` 可用与 `output_text` 取值方式；若强制流式，记录在 provider 注释并改为内部消费流。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_openai_text_subscription.py`:
```python
import pytest

from app.providers.text.openai_text import OpenAITextProvider


class _FakeResponses:
    def __init__(self, holder): self._h = holder
    async def create(self, **kwargs):
        self._h["kwargs"] = kwargs
        class R: output_text = "HELLO"
        return R()


class _FakeClient:
    def __init__(self, holder): self.responses = _FakeResponses(holder)


@pytest.mark.asyncio
async def test_subscription_uses_responses_and_fresh_client(monkeypatch):
    holder = {}
    import app.providers.text.openai_text as mod
    monkeypatch.setattr(mod, "subscription_creds", lambda: ("https://chatgpt.com/backend-api/codex", "AT", "ACC"))
    monkeypatch.setattr(mod, "build_codex_client", lambda token, acc: _FakeClient(holder))
    p = OpenAITextProvider(api_key="", model="gpt-5.5", subscription=True)
    out = await p.generate("prompt", system_prompt="sys")
    assert out == "HELLO"
    assert holder["kwargs"]["model"] == "gpt-5.5"
    assert holder["kwargs"]["instructions"] == "sys"
    assert holder["kwargs"]["input"] == "prompt"
    assert holder["kwargs"]["store"] is False
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_openai_text_subscription.py -v`
Expected: FAIL（无 `subscription` 参数 / 无 `subscription_creds` 导入）

- [ ] **Step 3: 实现订阅分支**

修改 `openai_text.py`：顶部加 `from app.oauth.openai_oauth import subscription_creds, build_codex_client`；构造器加 `subscription: bool = False`；`generate` 分支：
```python
class OpenAITextProvider(TextProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o", base_url: str = "", max_tokens: int = 65535, subscription: bool = False):
        self._subscription = subscription
        self._model = model
        self._max_tokens = max_tokens or 65535
        if subscription:
            self._client = None  # 每次调用取新 token 建 client（防中途过期）
            self._base_url = "https://chatgpt.com/backend-api/codex"
        else:
            kwargs: dict = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            self._client = openai.AsyncOpenAI(**kwargs)
            self._base_url = base_url or "https://api.openai.com/v1"
        log.info("Initialized OpenAITextProvider model=%s subscription=%s", model, subscription)

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        if self._subscription:
            return await self._generate_subscription(prompt, system_prompt)
        # ...（保留原 chat.completions 实现不变）

    async def _generate_subscription(self, prompt: str, system_prompt: str) -> str:
        t0 = time.time()
        try:
            _, token, account_id = subscription_creds()
            client = build_codex_client(token, account_id)
            resp = await client.responses.create(
                model=self._model,
                instructions=system_prompt or "You are a helpful assistant.",
                input=prompt,
                store=False,
            )
            text = resp.output_text or ""
            log.info("generate(sub) done — %d chars in %.1fs", len(text), time.time() - t0)
            return text
        except Exception as e:
            log.exception("generate(sub) failed after %.1fs", time.time() - t0)
            raise ProviderError(service="文本生成", provider="openai", model=self._model, base_url=self._base_url, cause=e) from e
```

- [ ] **Step 4: 工厂接入订阅**

`runner.py` 的 `_build_text_provider`（line 30，无参，内部 `get_settings()`）：openai 分支改为读 auth_mode：
```python
def _build_text_provider():
    from app.config import resolve, get_settings
    cfg = get_settings()
    provider, base_url, api_key, model = resolve(cfg, "script")
    max_tokens = cfg.provider_creds(provider).max_output_tokens
    if provider == "claude":
        from app.providers.text.claude import ClaudeTextProvider
        return ClaudeTextProvider(api_key=api_key, model=model, base_url=base_url, max_tokens=max_tokens)
    from app.providers.text.openai_text import OpenAITextProvider
    sub = cfg.provider_creds("openai").auth_mode == "subscription"
    return OpenAITextProvider(api_key=api_key, model=model, base_url=base_url, max_tokens=max_tokens, subscription=sub)
```
对 `_build_summary_provider(cfg)`（line 159）的 openai 分支做同样处理（line 164-170 区块）：构建 `OpenAITextProvider` 时加 `subscription=cfg.provider_creds("openai").auth_mode == "subscription"`。

- [ ] **Step 5: 运行确认通过 + 回归**

Run: `pytest tests/test_openai_text_subscription.py -v && pytest -q`
Expected: PASS / 全绿

- [ ] **Step 6: 提交**

```bash
git add backend/app/providers/text/openai_text.py backend/app/pipeline/runner.py backend/tests/test_openai_text_subscription.py
git commit -m "feat(text): openai 订阅模式走 Responses API"
```

---

## Task 10: 生图 provider 订阅分支

**Files:**
- Modify: `backend/app/providers/image/openai_image.py`
- Modify: `backend/app/providers/image/__init__.py`
- Test: `backend/tests/test_image_openai_subscription.py`

- [ ] **Step 0: SPIKE** — 抓真实请求确认生图工具精确 schema（`tools=[{"type":"image_generation"}]` 还是自定义函数工具）、返回项类型（`image_generation_call`）与 base64 字段名。把结论写入 provider 注释；下方实现按通用形态写，spike 后按需微调字段名。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_image_openai_subscription.py`:
```python
import base64
import pytest

from app.providers.image.openai_image import OpenAIImageProvider


class _Item:
    type = "image_generation_call"
    def __init__(self, b64): self.result = b64


class _Resp:
    def __init__(self, b64): self.output = [_Item(b64)]


class _FakeResponses:
    def __init__(self, holder): self._h = holder
    async def create(self, **kwargs):
        self._h["kwargs"] = kwargs
        return _Resp(base64.b64encode(b"PNGDATA").decode())


class _FakeClient:
    def __init__(self, holder): self.responses = _FakeResponses(holder)


@pytest.mark.asyncio
async def test_subscription_image_uses_gpt55_and_tool(tmp_path, monkeypatch):
    holder = {}
    import app.providers.image.openai_image as mod
    monkeypatch.setattr(mod, "subscription_creds", lambda: ("base", "AT", "ACC"))
    monkeypatch.setattr(mod, "build_codex_client", lambda t, a: _FakeClient(holder))
    out = tmp_path / "x.png"
    p = OpenAIImageProvider(api_key="", model="ignored", subscription=True)
    res = await p.generate("a cat", size="1080x1920", output_path=str(out))
    assert out.read_bytes() == b"PNGDATA"
    assert holder["kwargs"]["model"] == "gpt-5.5"
    assert any(t.get("type") == "image_generation" for t in holder["kwargs"]["tools"])
    assert res.file_path == str(out)
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_image_openai_subscription.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`openai_image.py`：顶部加 `from app.oauth.openai_oauth import subscription_creds, build_codex_client`；构造器加 `subscription`/`account_id`；`generate` 分支：
```python
    def __init__(self, api_key: str, model: str = "gpt-image-1", base_url: str = "", subscription: bool = False, account_id: str = ""):
        self._subscription = subscription
        self._model = "gpt-5.5" if subscription else model  # 订阅生图端点强制 gpt-5.5
        if subscription:
            self._client = None
            self._base_url = "https://chatgpt.com/backend-api/codex"
        else:
            kwargs: dict = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            self._client = openai.AsyncOpenAI(**kwargs)
            self._base_url = base_url or "https://api.openai.com/v1"
        log.info("Initialized OpenAIImageProvider model=%s subscription=%s", self._model, subscription)

    async def generate(self, prompt: str, size: str = "1080x1920", output_path: str = "") -> AssetResult:
        if self._subscription:
            return await self._generate_subscription(prompt, output_path)
        # ...（保留原 images.generate 实现不变）

    async def _generate_subscription(self, prompt: str, output_path: str) -> AssetResult:
        import base64
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            _, token, account_id = subscription_creds()
            client = build_codex_client(token, account_id)
            resp = await client.responses.create(
                model="gpt-5.5", input=prompt, tools=[{"type": "image_generation"}],
            )
        except Exception as e:
            raise ProviderError(service="图片生成", provider="openai", model=self._model, base_url=self._base_url, cause=e) from e
        b64 = None
        for item in getattr(resp, "output", []) or []:
            if getattr(item, "type", "") == "image_generation_call":
                b64 = getattr(item, "result", None)
                break
        if not b64:
            raise RuntimeError("订阅生图无图片返回")
        Path(output_path).write_bytes(base64.b64decode(b64))
        return AssetResult(file_path=output_path)
```

- [ ] **Step 4: 工厂接入**

`image/__init__.py` 的 `build_image_provider`：openai 分支改为：
```python
    from app.providers.image.openai_image import OpenAIImageProvider
    if cfg.provider_creds("openai").auth_mode == "subscription":
        return OpenAIImageProvider(api_key="", model="gpt-5.5", subscription=True)
    return OpenAIImageProvider(api_key=api_key, model=model, base_url=base_url)
```

- [ ] **Step 5: 运行确认通过 + 回归**

Run: `pytest tests/test_image_openai_subscription.py -v && pytest -q`
Expected: PASS / 全绿

- [ ] **Step 6: 提交**

```bash
git add backend/app/providers/image/openai_image.py backend/app/providers/image/__init__.py backend/tests/test_image_openai_subscription.py
git commit -m "feat(image): openai 订阅模式 gpt-5.5 + image_generation 工具生图"
```

---

## Task 11: 文档解析（vision）订阅分支

**Files:**
- Modify: `backend/app/api/pipeline.py`（vision 构造处，约 line 312-314）
- Modify: `backend/app/services/document_import_pdf.py`（`_vision_extract` line 30）
- Test: `backend/tests/test_vision_subscription.py`

- [ ] **Step 0: SPIKE** — 确认 codex responses 端点接受图片 input 的格式（`input` 内 image 项结构）与取文本方式；记录在 `_vision_extract` 注释。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_vision_subscription.py`:
```python
import base64
import pytest

from app.config import ProviderCfg
from app.services.document_import_pdf import _vision_extract


@pytest.mark.asyncio
async def test_vision_subscription_calls_codex(monkeypatch):
    holder = {}

    class _Resp:
        output_text = "正文文本"

    class _Responses:
        async def create(self, **kw): holder["kw"] = kw; return _Resp()

    class _Client:
        responses = _Responses()

    import app.services.document_import_pdf as mod
    monkeypatch.setattr(mod, "subscription_creds", lambda: ("base", "AT", "ACC"))
    monkeypatch.setattr(mod, "build_codex_client", lambda t, a: _Client())
    cfg = ProviderCfg(provider="openai", model="gpt-5.5", auth_mode="subscription", account_id="ACC")
    out = await _vision_extract([b"\x89PNG"], cfg)
    assert out == "正文文本"
    assert holder["kw"]["model"] == "gpt-5.5"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_vision_subscription.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `_vision_extract` 分支**

`document_import_pdf.py`：顶部加 `from app.oauth.openai_oauth import subscription_creds, build_codex_client`；`_vision_extract` 开头加分支：
```python
async def _vision_extract(images_png: list[bytes], cfg) -> str:
    if getattr(cfg, "auth_mode", "api_key") == "subscription":
        return await _vision_extract_subscription(images_png)
    # ...（保留原裸 httpx /chat/completions 实现不变）


async def _vision_extract_subscription(images_png: list[bytes]) -> str:
    _, token, account_id = subscription_creds()
    client = build_codex_client(token, account_id)
    content = [{"type": "input_text", "text": "提取这份文档的正文为纯文本，只输出正文内容，不要任何解释或标注。"}]
    for png in images_png:
        b64 = base64.b64encode(png).decode()
        content.append({"type": "input_image", "image_url": f"data:image/png;base64,{b64}"})
    resp = await client.responses.create(
        model="gpt-5.5", input=[{"role": "user", "content": content}], store=False,
    )
    return resp.output_text or ""
```
> 注：input image 项结构（`input_image`/`image_url`）以 Step 0 spike 结论为准微调。

- [ ] **Step 4: vision 构造透传 auth_mode/account_id**

`api/pipeline.py` 约 line 312-314，vision 构造 `ProviderCfg` 处改为带上订阅信息：
```python
    vp, vb, vk, vm = resolve(cfg, "vision")
    creds = cfg.provider_creds(vp)
    auth_mode = creds.auth_mode
    account_id = ""
    if vp == "openai" and auth_mode == "subscription":
        vm = "gpt-5.5"  # 订阅解析用端点支持的模型
        from app.oauth.openai_oauth import subscription_creds
        try:
            _, _, account_id = subscription_creds()
        except Exception:
            account_id = ""
    vcfg = ProviderCfg(provider=vp, base_url=vb, model=vm, api_key=vk, auth_mode=auth_mode, account_id=account_id)
```
（把原来构造 `ProviderCfg(...)` 的那行替换为上面的 `vcfg`，并把后续传参用 `vcfg`。）

- [ ] **Step 5: 运行确认通过 + 回归**

Run: `pytest tests/test_vision_subscription.py -v && pytest -q`
Expected: PASS / 全绿

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/document_import_pdf.py backend/app/api/pipeline.py backend/tests/test_vision_subscription.py
git commit -m "feat(vision): openai 订阅模式解析走 codex responses"
```

---

## Task 12: TTS 订阅守卫（明确报错）

**Files:**
- Modify: `backend/app/providers/tts/__init__.py`（tts 工厂构造处）
- Test: `backend/tests/test_tts_subscription_guard.py`

> Codex 不出音频，订阅模式不支持 TTS。若用户把 openai 设为订阅、又选 openai 作为 tts_provider，需在构建 tts provider 时抛清晰错误，而非让 openai_tts 拿空 key 失败。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_tts_subscription_guard.py`:
```python
import pytest

from app.config import get_settings, reload_settings


def test_openai_subscription_tts_raises(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.yaml")
    cfg = config.get_settings()
    cfg.providers["openai"].auth_mode = "subscription"
    cfg.pipeline.tts_provider = "openai"
    from app.providers.tts import build_tts_provider  # 工厂函数名以实际为准
    with pytest.raises(ValueError, match="订阅"):
        build_tts_provider(cfg)
```

> 注：先读 `backend/app/providers/tts/__init__.py` 确认工厂函数实际名与签名（可能是 `build_tts_provider(cfg)`），按实际调整 import 与调用。

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_tts_subscription_guard.py -v`
Expected: FAIL（无守卫）

- [ ] **Step 3: 实现守卫**

在 tts 工厂里、解析出 provider 之后、构建 openai tts 之前加：
```python
    if provider == "openai" and cfg.provider_creds("openai").auth_mode == "subscription":
        raise ValueError("OpenAI 订阅模式不支持语音合成（TTS），请改用 edge-tts 或将 openai 切回 API Key 模式")
```

- [ ] **Step 4: 运行确认通过 + 回归**

Run: `pytest tests/test_tts_subscription_guard.py -v && pytest -q`
Expected: PASS / 全绿

- [ ] **Step 5: 提交**

```bash
git add backend/app/providers/tts/__init__.py backend/tests/test_tts_subscription_guard.py
git commit -m "feat(tts): openai 订阅模式不支持 TTS 时明确报错"
```

---

## 阶段二验收

- [ ] 订阅模式下跑一条完整任务：文案（Task 9）、生图（Task 10）成功产出；导入 PDF 解析（Task 11）成功。
- [ ] 切回 API Key 模式，全部用途仍正常（回归未破坏既有路径）。
- [ ] 选订阅 + TTS → 明确报错提示不支持。
- [ ] `pytest -q` 全绿；`ruff check .` 通过。

---

## 收尾

- [ ] 更新 `CLAUDE.md` 的 Configuration 段：说明 openai 支持 `auth_mode: api_key | subscription`，订阅模式在「模型配置」页登录，覆盖文本/生图/解析、不含 TTS，且属未公开端点的灰色用法。
- [ ] 合并分支（用户决定时机；勿擅自 push/merge）。

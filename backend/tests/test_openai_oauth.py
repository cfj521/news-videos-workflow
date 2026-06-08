import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.store.providers_store as ps
from app.models.base import Base
from app.oauth import openai_oauth as oo


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "MODEL_PROVIDERS_PATH", tmp_path / "model_providers.yaml")


def _b64(d) -> str:
    return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")


def _fake_tok(exp_delta_s: int) -> dict:
    exp = int((datetime.now(timezone.utc) + timedelta(seconds=exp_delta_s)).timestamp())
    payload = {
        "exp": exp,
        "https://api.openai.com/auth": {"chatgpt_account_id": "acc1", "chatgpt_plan_type": "plus"},
        "https://api.openai.com/profile": {"email": "u@e.com"},
    }
    jwt = f"h.{_b64(payload)}.s"
    return {"access_token": jwt, "refresh_token": "refresh1", "id_token": "id1"}


def _db():
    """真 sqlite in-memory session，供 handle_callback 读写 OAuthLoginSession。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


# ---- 纯逻辑：PKCE / authorize url / parse_claims ----


def test_gen_pkce_shapes():
    verifier, challenge = oo.gen_pkce()
    assert verifier and challenge
    assert "=" not in challenge and "+" not in challenge and "/" not in challenge  # base64url


def test_build_authorize_url():
    url = oo.build_authorize_url("CHAL", "STATE")
    assert url.startswith("https://auth.openai.com/oauth/authorize?")
    assert "client_id=app_EMoamEEZ73f0CkXaXp7hrann" in url
    assert "code_challenge=CHAL" in url
    assert "state=STATE" in url
    assert "scope=openid%20profile%20email%20offline_access" in url  # 空格须 %20
    assert "+" not in url


def test_parse_claims_extracts_nested_fields():
    tok = _fake_tok(3600)
    claims = oo.parse_claims(tok["access_token"])
    assert claims["account_id"] == "acc1"
    assert claims["plan_type"] == "plus"
    assert claims["email"] == "u@e.com"
    assert claims["exp"] is not None


# ---- exchange_code / refresh_tokens 的 HTTP POST（手写 FakeClient，无额外依赖）----


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
    assert captured["data"]["scope"] == oo.SCOPE


# ---- store 版 token 服务 ----


def test_store_tokens_writes_to_yaml():
    oo.store_tokens(_fake_tok(3600))
    d = ps.load_oauth("openai")
    assert d.refresh_token == "refresh1"
    assert d.account_id == "acc1" and d.plan_type == "plus" and d.account_email == "u@e.com"
    assert d.expires_at


def test_store_tokens_raises_when_exp_missing():
    payload = {  # 无 exp 声明
        "https://api.openai.com/auth": {"chatgpt_account_id": "acc1", "chatgpt_plan_type": "plus"},
        "https://api.openai.com/profile": {"email": "u@e.com"},
    }
    tok = {"access_token": f"h.{_b64(payload)}.s", "refresh_token": "rt"}
    with pytest.raises(ValueError):
        oo.store_tokens(tok)


def test_get_status_logged_out():
    assert oo.get_status() == {"logged_in": False}


def test_get_status_logged_in():
    oo.store_tokens(_fake_tok(3600))
    st = oo.get_status()
    assert st["logged_in"] is True and st["email"] == "u@e.com" and st["plan"] == "plus"


def test_logout_clears():
    oo.store_tokens(_fake_tok(3600))
    oo.logout()
    assert oo.get_status() == {"logged_in": False}


def test_get_valid_access_token_not_logged_in():
    with pytest.raises(oo.NotLoggedInError):
        oo.get_valid_access_token()


def test_get_valid_access_token_returns_when_fresh():
    tok = _fake_tok(3600)
    oo.store_tokens(tok)
    access, account_id = oo.get_valid_access_token()
    assert access == tok["access_token"] and account_id == "acc1"


def test_get_valid_access_token_refreshes_when_expiring(monkeypatch):
    oo.store_tokens(_fake_tok(60))
    new = _fake_tok(3600)
    monkeypatch.setattr(oo, "refresh_tokens", lambda rt: new)
    access, _ = oo.get_valid_access_token()
    assert access == new["access_token"]
    assert ps.load_oauth("openai").access_token == new["access_token"]


def test_get_valid_access_token_raises_when_expiring_but_no_refresh_token():
    # 手动写入一个临期但无 refresh_token 的 oauth
    from app.store.oauth_models import OAuthData
    ps.save_oauth("openai", OAuthData(
        access_token="x.y.z", refresh_token="",
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat(),
    ))
    with pytest.raises(oo.NotLoggedInError):
        oo.get_valid_access_token()


# ---- handle_callback：db 仅用于 OAuthLoginSession，token 走 providers_store ----


def test_handle_callback_success(monkeypatch):
    from app.models.oauth_credential import OAuthLoginSession
    db = _db()
    db.add(OAuthLoginSession(state="S1", code_verifier="V1", status="pending"))
    db.commit()
    monkeypatch.setattr(oo, "exchange_code", lambda code, cv: _fake_tok(3600))
    ok = oo.handle_callback(db, {"code": "C", "state": "S1"})
    assert ok is True
    assert db.query(OAuthLoginSession).filter_by(state="S1").one().status == "success"
    assert ps.load_oauth("openai").access_token  # token 已写进 providers_store


def test_handle_callback_bad_state():
    db = _db()
    ok = oo.handle_callback(db, {"code": "C", "state": "NOPE"})
    assert ok is False

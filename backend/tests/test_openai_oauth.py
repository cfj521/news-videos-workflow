import base64
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.oauth_credential import OAuthCredential
from app.oauth import openai_oauth as oo


def test_gen_pkce_shapes():
    verifier, challenge = oo.gen_pkce()
    assert 43 <= len(verifier) <= 128
    assert "=" not in verifier and "+" not in verifier and "/" not in verifier  # base64url 无填充
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
    assert captured["data"]["scope"] == oo.SCOPE


# ---- Task 5: token 服务 ----

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


def test_get_status_and_logout():
    db = _db()
    assert oo.get_status(db) == {"logged_in": False}
    exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    oo.store_tokens(db, {"access_token": _jwt_with_exp(exp), "refresh_token": "rt"})
    st = oo.get_status(db)
    assert st["logged_in"] is True
    assert st["email"] == "a@b.com"
    assert st["plan"] == "plus"
    assert st["expires_at"].endswith("+00:00")  # 带时区后缀
    oo.logout(db)
    assert oo.get_status(db) == {"logged_in": False}


def test_store_tokens_raises_when_exp_missing():
    db = _db()
    import pytest
    token = _fake_jwt({  # 无 exp 声明
        "https://api.openai.com/auth": {"chatgpt_account_id": "acc", "chatgpt_plan_type": "plus"},
        "https://api.openai.com/profile": {"email": "a@b.com"},
    })
    with pytest.raises(ValueError):
        oo.store_tokens(db, {"access_token": token, "refresh_token": "rt"})

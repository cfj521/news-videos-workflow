import base64
import json

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

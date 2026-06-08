from datetime import datetime, timedelta, timezone

import pytest

import app.store.providers_store as ps
from app.oauth import openai_oauth as oo


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "MODEL_PROVIDERS_PATH", tmp_path / "model_providers.yaml")


def _fake_tok(exp_delta_s: int) -> dict:
    import base64
    import json

    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")

    exp = int((datetime.now(timezone.utc) + timedelta(seconds=exp_delta_s)).timestamp())
    payload = {
        "exp": exp,
        "https://api.openai.com/auth": {"chatgpt_account_id": "acc1", "chatgpt_plan_type": "plus"},
        "https://api.openai.com/profile": {"email": "u@e.com"},
    }
    jwt = f"h.{b64(payload)}.s"
    return {"access_token": jwt, "refresh_token": "refresh1", "id_token": "id1"}


def test_store_tokens_writes_to_yaml():
    oo.store_tokens(_fake_tok(3600))
    d = ps.load_oauth("openai")
    assert d.refresh_token == "refresh1"
    assert d.account_id == "acc1" and d.plan_type == "plus" and d.account_email == "u@e.com"
    assert d.expires_at


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

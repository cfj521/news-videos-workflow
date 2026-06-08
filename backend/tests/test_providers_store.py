from pathlib import Path

import app.store.providers_store as ps
from app.config import ProviderCreds
from app.store.oauth_models import OAuthData


def test_oauthdata_defaults_empty():
    d = OAuthData()
    assert d.access_token == "" and d.refresh_token == ""
    assert d.expires_at == "" and d.account_id == ""


def test_oauthdata_roundtrip_dict():
    d = OAuthData(access_token="a", refresh_token="r", expires_at="2026-06-07T00:00:00+00:00",
                  account_id="acc", plan_type="plus", account_email="x@y.z",
                  id_token="idt", last_refresh="2026-06-07T00:00:00+00:00")
    out = d.model_dump()
    assert OAuthData(**out) == d


def _point_to_tmp(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ps, "MODEL_PROVIDERS_PATH", tmp_path / "model_providers.yaml")


def test_load_providers_empty(tmp_path, monkeypatch):
    _point_to_tmp(tmp_path, monkeypatch)
    assert ps.load_providers() == {}


def test_save_then_load_providers(tmp_path, monkeypatch):
    _point_to_tmp(tmp_path, monkeypatch)
    creds = {"openai": ProviderCreds(base_url="https://api.openai.com/v1", api_key="sk-x")}
    ps.save_providers(creds)
    got = ps.load_providers()
    assert got["openai"].api_key == "sk-x"
    assert got["openai"].base_url == "https://api.openai.com/v1"


def test_save_providers_preserves_oauth(tmp_path, monkeypatch):
    _point_to_tmp(tmp_path, monkeypatch)
    ps.save_oauth("openai", OAuthData(access_token="tok", refresh_token="r"))
    ps.save_providers({"openai": ProviderCreds(api_key="sk-new")})
    assert ps.load_oauth("openai").access_token == "tok"


def test_oauth_roundtrip_and_clear(tmp_path, monkeypatch):
    _point_to_tmp(tmp_path, monkeypatch)
    assert ps.load_oauth("openai") == OAuthData()
    ps.save_oauth("openai", OAuthData(access_token="a", refresh_token="r"))
    assert ps.load_oauth("openai").access_token == "a"
    ps.clear_oauth("openai")
    assert ps.load_oauth("openai") == OAuthData()

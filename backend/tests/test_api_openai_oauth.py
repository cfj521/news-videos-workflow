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

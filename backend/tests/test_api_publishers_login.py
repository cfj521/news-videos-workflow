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


def test_login_start_rejects_bad_platform(client):
    c, tok = client
    r = c.post("/api/publishers/login/start", json={"platform": "weibo", "account": "a"}, headers=_h(tok))
    assert r.status_code == 422


def test_login_start_rejects_bad_account(client):
    c, tok = client
    r = c.post("/api/publishers/login/start", json={"platform": "douyin", "account": "../bad"}, headers=_h(tok))
    assert r.status_code == 422


def test_login_start_creates_session_row(client, monkeypatch):
    c, tok = client
    from app.api import publishers as route

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(route, "_run_login_flow", noop)

    r = c.post("/api/publishers/login/start", json={"platform": "douyin", "account": "acct1"}, headers=_h(tok))
    assert r.status_code == 200
    sid = r.json()["sid"]

    st = c.get(f"/api/publishers/login/status?sid={sid}", headers=_h(tok))
    assert st.status_code == 200
    assert st.json()["status"] == "starting"


def test_login_status_unknown_sid(client):
    c, tok = client
    r = c.get("/api/publishers/login/status?sid=nope", headers=_h(tok))
    assert r.json()["status"] == "error"


def test_login_status_for_target(client, monkeypatch):
    c, tok = client
    c.post("/api/publishers/", json={"name": "抖音", "platform": "douyin",
           "config_json": '{"account": "acct1"}'}, headers=_h(tok))
    from app.api import publishers as route

    async def fake_check(platform, account, deep=False):
        return True
    monkeypatch.setattr(route.sau_runner, "check_login", fake_check)
    r = c.get("/api/publishers/douyin/login-status", headers=_h(tok))
    assert r.status_code == 200
    assert r.json()["logged_in"] is True


def test_login_status_wrong_platform(client):
    c, tok = client
    c.post("/api/publishers/", json={"name": "b", "platform": "bilibili",
           "config_json": '{"sessdata": "s"}'}, headers=_h(tok))
    r = c.get("/api/publishers/b/login-status", headers=_h(tok))
    assert r.status_code == 422


def test_login_start_rejects_concurrent(client, monkeypatch):
    c, tok = client
    from app.api import publishers as route

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(route, "_run_login_flow", noop)

    r1 = c.post("/api/publishers/login/start", json={"platform": "douyin", "account": "acct1"}, headers=_h(tok))
    assert r1.status_code == 200
    # 同账号再次发起：第一个仍 starting（noop 未推进）→ 409
    r2 = c.post("/api/publishers/login/start", json={"platform": "douyin", "account": "acct1"}, headers=_h(tok))
    assert r2.status_code == 409
    # 不同账号不受影响
    r3 = c.post("/api/publishers/login/start", json={"platform": "douyin", "account": "acct2"}, headers=_h(tok))
    assert r3.status_code == 200

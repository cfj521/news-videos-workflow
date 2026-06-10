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


def _make_target(c, tok, name, platform, slug, config_json=None):
    body = {"name": name, "platform": platform, "slug": slug}
    if config_json:
        body["config_json"] = config_json
    r = c.post("/api/publishers/", json=body, headers=_h(tok))
    assert r.status_code == 201
    return r.json()["id"]  # slug


def test_login_start_rejects_bad_platform(client):
    c, tok = client
    r = c.post("/api/publishers/login/start", json={"platform": "weibo", "account": "uuid1"}, headers=_h(tok))
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

    # 保存前即可扫码：直接用 (platform, account=UUID)，无需先建账号
    r = c.post("/api/publishers/login/start", json={"platform": "douyin", "account": "uuid1"}, headers=_h(tok))
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
    slug = _make_target(c, tok, "抖音", "douyin", "dy1", config_json='{"account": "uuid1"}')
    from app.api import publishers as route

    async def fake_check(platform, account, deep=False):
        return True
    monkeypatch.setattr(route.sau_runner, "check_login", fake_check)
    r = c.get(f"/api/publishers/{slug}/login-status", headers=_h(tok))
    assert r.status_code == 200
    assert r.json()["logged_in"] is True


def test_login_status_wrong_platform(client):
    c, tok = client
    slug = _make_target(c, tok, "B站", "bilibili", "bili1", config_json='{"sessdata": "s"}')
    r = c.get(f"/api/publishers/{slug}/login-status", headers=_h(tok))
    assert r.status_code == 422


def test_login_start_supersedes_previous(client, monkeypatch):
    c, tok = client
    from app.api import publishers as route
    from app.models.browser_login_session import BrowserLoginSession

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(route, "_run_login_flow", noop)
    killed = []
    monkeypatch.setattr(route.sau_runner, "kill_login_worker", lambda p, a: killed.append((p, a)))

    r1 = c.post("/api/publishers/login/start", json={"platform": "douyin", "account": "uuid1"}, headers=_h(tok))
    assert r1.status_code == 200
    sid1 = r1.json()["sid"]
    # 同账号再次发起：不再 409，而是杀旧 worker + 清旧会话，重开
    r2 = c.post("/api/publishers/login/start", json={"platform": "douyin", "account": "uuid1"}, headers=_h(tok))
    assert r2.status_code == 200
    sid2 = r2.json()["sid"]
    assert sid2 != sid1
    assert ("douyin", "uuid1") in killed  # 旧 worker 被请求杀掉

    # 旧 sid 已被清掉，只剩新会话
    assert c.get(f"/api/publishers/login/status?sid={sid1}", headers=_h(tok)).json()["status"] == "error"
    assert c.get(f"/api/publishers/login/status?sid={sid2}", headers=_h(tok)).json()["status"] == "starting"

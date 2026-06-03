"""登录验证：口令哈希、令牌签发/校验、登录接口与用户管理 CRUD。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth, config
from app.api.dependencies import get_db
from app.auth import hash_password, verify_password
from app.main import create_app
from app.models import Base  # noqa: F401 – 注册 ORM 模型
from app.models.user import User


# ─── 单元：口令哈希 ───────────────────────────────────────────

def test_password_hash_roundtrip():
    h = hash_password("admin")
    assert h != "admin"  # 不明文存储
    assert h.startswith("pbkdf2_sha256$")
    assert verify_password("admin", h)
    assert not verify_password("wrong", h)


def test_password_hash_is_salted():
    assert hash_password("x") != hash_password("x")  # 每次盐不同


# ─── 单元：令牌 ───────────────────────────────────────────────

def test_token_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.yaml")
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(config.get_settings().infra, "data_dir", str(tmp_path / "data"))
    auth._secret.cache_clear()
    token = auth.create_token("admin")
    assert auth.verify_token(token) == "admin"
    assert auth.verify_token(token + "x") is None
    assert auth.verify_token("garbage") is None


def test_token_expired(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.yaml")
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(config.get_settings().infra, "data_dir", str(tmp_path / "data"))
    auth._secret.cache_clear()
    monkeypatch.setattr(auth, "_TOKEN_TTL", -10)  # 已过期
    token = auth.create_token("admin")
    assert auth.verify_token(token) is None


# ─── 集成：登录 + 守卫 + 用户管理 ────────────────────────────

@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.yaml")
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(config.get_settings().infra, "data_dir", str(tmp_path / "data"))
    auth._secret.cache_clear()
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sf = sessionmaker(bind=engine)
    app = create_app()
    Base.metadata.create_all(engine)

    def override_get_db():
        s = sf()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    # 播种默认管理员
    s = sf()
    s.add(User(username="admin", password_hash=hash_password("admin")))
    s.commit()
    s.close()
    return TestClient(app), sf


def _login(client, username="admin", password="admin"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_login_success_and_failure(env):
    client, _ = env
    assert client.post("/api/auth/login", json={"username": "admin", "password": "admin"}).status_code == 200
    assert client.post("/api/auth/login", json={"username": "admin", "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "ghost", "password": "x"}).status_code == 401


def test_protected_route_requires_token(env):
    client, _ = env
    # 无 token 访问业务接口被拦
    assert client.get("/api/sources/").status_code == 401
    # 带 token 放行
    token = _login(client)
    assert client.get("/api/sources/", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_me(env):
    client, _ = env
    token = _login(client)
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["username"] == "admin"


def test_change_password(env):
    client, _ = env
    token = _login(client)
    h = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/auth/password", json={"old_password": "bad", "new_password": "n"}, headers=h).status_code == 400
    assert client.post("/api/auth/password", json={"old_password": "admin", "new_password": "newpass"}, headers=h).status_code == 200
    # 旧密码失效，新密码可登录
    assert client.post("/api/auth/login", json={"username": "admin", "password": "admin"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": "newpass"}).status_code == 200


def test_user_management(env):
    client, _ = env
    token = _login(client)
    h = {"Authorization": f"Bearer {token}"}
    # 新增
    r = client.post("/api/auth/users", json={"username": "editor", "password": "pw"}, headers=h)
    assert r.status_code == 200
    new_id = r.json()["id"]
    # 重复用户名冲突
    assert client.post("/api/auth/users", json={"username": "editor", "password": "pw"}, headers=h).status_code == 409
    # 列表含两人
    assert {u["username"] for u in client.get("/api/auth/users", headers=h).json()} == {"admin", "editor"}
    # 新用户可登录
    assert client.post("/api/auth/login", json={"username": "editor", "password": "pw"}).status_code == 200
    # 重置其密码
    assert client.post(f"/api/auth/users/{new_id}/password", json={"new_password": "pw2"}, headers=h).status_code == 200
    assert client.post("/api/auth/login", json={"username": "editor", "password": "pw2"}).status_code == 200
    # 删除
    assert client.delete(f"/api/auth/users/{new_id}", headers=h).status_code == 200
    assert {u["username"] for u in client.get("/api/auth/users", headers=h).json()} == {"admin"}


def test_cannot_delete_self_or_last_user(env):
    client, sf = env
    token = _login(client)
    h = {"Authorization": f"Bearer {token}"}
    me_id = client.get("/api/auth/users", headers=h).json()[0]["id"]
    # 不能删自己
    assert client.delete(f"/api/auth/users/{me_id}", headers=h).status_code == 400

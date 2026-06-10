import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.auth import get_current_user
from app.main import create_app
from app.models import Base  # noqa: F401
from app import config


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config, "_settings", None)
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
    app.dependency_overrides[get_current_user] = lambda: "admin"
    return TestClient(app)


def test_prompt_defaults_endpoint(client):
    r = client.get("/api/settings/prompts/defaults")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 6
    assert "label" in data["roundup_article"] and "default" in data["roundup_article"]


def test_put_prompts_roundtrip_keeps_ellipsis(client):
    # 提示词改由 prompt_presets 管理；往返不应破坏「...」，且生效预设镜像到 prompts
    presets = [{"name": "预设 1", "values": {"summary_meta": "标题...简介"}}]
    presets += [{"name": f"预设 {i}", "values": {}} for i in range(2, 6)]
    r = client.put("/api/settings/", json={"prompt_presets": {"active": 0, "presets": presets}})
    assert r.status_code == 200
    got = client.get("/api/settings/").json()
    assert got["prompt_presets"]["presets"][0]["values"]["summary_meta"] == "标题...简介"
    assert got["prompts"]["summary_meta"] == "标题...简介"  # active 预设镜像


def test_active_preset_drives_mirror(client):
    # 切换 active 即改变生效（镜像）提示词
    presets = [
        {"name": "中文", "values": {"summary_meta": "ZH-META"}},
        {"name": "英文", "values": {"summary_meta": "EN-META"}},
    ] + [{"name": f"预设 {i}", "values": {}} for i in range(3, 6)]
    client.put("/api/settings/", json={"prompt_presets": {"active": 1, "presets": presets}})
    got = client.get("/api/settings/").json()
    assert got["prompt_presets"]["active"] == 1
    assert got["prompts"]["summary_meta"] == "EN-META"

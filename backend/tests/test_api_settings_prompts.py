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
    assert len(data) == 8
    assert "label" in data["roundup_article"] and "default" in data["roundup_article"]


def test_put_prompts_roundtrip_keeps_ellipsis(client):
    r = client.put("/api/settings/", json={"prompts": {"summary_meta": "标题...简介"}})
    assert r.status_code == 200
    got = client.get("/api/settings/").json()
    assert got["prompts"]["summary_meta"] == "标题...简介"

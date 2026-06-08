import json

import pytest
from fastapi.testclient import TestClient

import app.store.sources_store as ss
from app.auth import get_current_user
from app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "NEWS_SOURCES_PATH", tmp_path / "news_sources.yaml")
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: "admin"
    return TestClient(app)


def test_create_returns_slug_id(client):
    r = client.post("/api/sources/", json={"name": "Hacker News", "type": "api",
                                           "url": "https://hn.algolia.com/api/v1/"})
    assert r.status_code == 201
    assert r.json()["id"] == "hacker_news"


def test_list_patch_delete(client):
    client.post("/api/sources/", json={"name": "HN", "type": "api", "url": "u"})
    assert len(client.get("/api/sources/").json()) == 1
    assert client.patch("/api/sources/hn", json={"enabled": False}).json()["enabled"] is False
    assert client.delete("/api/sources/hn").status_code == 204
    assert client.get("/api/sources/").json() == []


def test_patch_missing_404(client):
    assert client.patch("/api/sources/nope", json={"enabled": False}).status_code == 404


def test_config_json_roundtrip(client):
    r = client.post("/api/sources/", json={"name": "AIHot", "type": "api", "url": "u",
                                           "config_json": json.dumps({"provider": "aihot"})})
    assert json.loads(r.json()["config_json"])["provider"] == "aihot"


def test_batch_update(client):
    a = client.post("/api/sources/", json={"name": "A", "type": "rss", "url": "a"}).json()["id"]
    b = client.post("/api/sources/", json={"name": "B", "type": "rss", "url": "b"}).json()["id"]
    r = client.post("/api/sources/batch", json={"ids": [a, b], "enabled": False})
    assert r.status_code == 200
    assert all(s["enabled"] is False for s in r.json())

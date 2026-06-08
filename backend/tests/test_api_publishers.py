import json

import pytest
from fastapi.testclient import TestClient

import app.store.targets_store as ts
from app.auth import get_current_user
from app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "TARGETS_PATH", tmp_path / "publish_targets.yaml")
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: "admin"
    return TestClient(app)


def test_create_returns_slug_id(client):
    r = client.post("/api/publishers/", json={"name": "YouTube", "platform": "youtube",
                                              "config_json": json.dumps({"client_id": "x"})})
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == "youtube"
    assert json.loads(body["config_json"])["client_id"] == "x"


def test_list_and_patch_and_delete(client):
    client.post(
        "/api/publishers/",
        json={"name": "YouTube", "platform": "youtube", "config_json": "{}"},
    )
    assert len(client.get("/api/publishers/").json()) == 1
    r = client.patch("/api/publishers/youtube", json={"enabled": False})
    assert r.json()["enabled"] is False
    assert client.delete("/api/publishers/youtube").status_code == 200
    assert client.get("/api/publishers/").json() == []


def test_patch_missing_404(client):
    assert client.patch("/api/publishers/nope", json={"enabled": False}).status_code == 404


def test_delete_missing_404(client):
    assert client.delete("/api/publishers/nope").status_code == 404

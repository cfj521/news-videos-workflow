import pytest
from fastapi.testclient import TestClient

import app.pipeline.scheduler as scheduler
import app.store.schedules_store as ss
from app.auth import get_current_user
from app.main import create_app

PAYLOAD = {"video_route": "hyperframes", "time_range": "7d", "selected_stages": [1, 2]}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "SCHEDULE_PATH", tmp_path / "schedule.yaml")
    # 隔离真实调度器：API 不真正注册/触发
    monkeypatch.setattr(scheduler, "register", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "unregister", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "next_run_for", lambda slug: None)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: "admin"
    return TestClient(app)


def test_create_daily_returns_slug(client):
    r = client.post("/api/schedules/", json={
        "name": "Daily AI", "freq": "daily", "run_at": "2026-06-15T08:00:00", "payload": PAYLOAD})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"] == "daily_ai" and body["freq"] == "daily" and body["enabled"] is True


def test_create_once_in_past_rejected(client):
    r = client.post("/api/schedules/", json={
        "name": "Old", "freq": "once", "run_at": "2000-01-01T08:00:00", "payload": PAYLOAD})
    assert r.status_code == 400


def test_list_patch_toggle_delete(client):
    client.post("/api/schedules/", json={
        "name": "Daily AI", "freq": "daily", "run_at": "2026-06-15T08:00:00", "payload": PAYLOAD})
    assert len(client.get("/api/schedules/").json()) == 1
    r = client.patch("/api/schedules/daily_ai", json={"enabled": False})
    assert r.json()["enabled"] is False
    assert client.delete("/api/schedules/daily_ai").status_code == 200
    assert client.get("/api/schedules/").json() == []


def test_run_now_invokes_fire(client, monkeypatch):
    client.post("/api/schedules/", json={
        "name": "Daily AI", "freq": "daily", "run_at": "2026-06-15T08:00:00", "payload": PAYLOAD})
    fired = []
    monkeypatch.setattr(scheduler, "_fire", lambda slug, factory: fired.append(slug))
    assert client.post("/api/schedules/daily_ai/run-now").status_code == 200
    assert fired == ["daily_ai"]


def test_patch_missing_404(client):
    assert client.patch("/api/schedules/nope", json={"enabled": False}).status_code == 404

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


def test_patch_full_edit_changes_fields(client):
    client.post("/api/schedules/", json={
        "name": "Daily AI", "freq": "daily", "run_at": "2026-06-15T08:00:00", "payload": PAYLOAD})
    r = client.patch("/api/schedules/daily_ai", json={
        "name": "周更", "freq": "weekly", "run_at": "2026-06-20T09:30:00",
        "payload": {"video_route": "comfyui", "time_range": "3d", "selected_stages": [1, 2, 3]}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "周更" and body["freq"] == "weekly"
    assert body["payload"]["video_route"] == "comfyui"   # payload 随 read 返回，供前端编辑预填
    lst = client.get("/api/schedules/").json()
    assert lst[0]["freq"] == "weekly" and lst[0]["name"] == "周更"
    assert lst[0]["payload"]["video_route"] == "comfyui"


def test_patch_edit_to_once_past_rejected(client):
    client.post("/api/schedules/", json={
        "name": "Daily AI", "freq": "daily", "run_at": "2026-06-15T08:00:00", "payload": PAYLOAD})
    r = client.patch("/api/schedules/daily_ai", json={"freq": "once", "run_at": "2000-01-01T08:00:00"})
    assert r.status_code == 400


def test_patch_pure_toggle_skips_once_past_check(client):
    # 模拟一条「已触发」的 once：enabled=False、run_at 在过去（store 直写，因 API 不允许建过去的 once）
    ss.create_schedule(name="Old Once", freq="once", run_at="2000-01-01T08:00:00",
                       payload=PAYLOAD, enabled=False, slug="old_once")
    # 纯启停 PATCH 不含 freq/run_at，不应被 once 过期校验拦截
    r = client.patch("/api/schedules/old_once", json={"enabled": True})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True

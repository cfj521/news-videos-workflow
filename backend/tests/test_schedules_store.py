import pytest

import app.store.schedules_store as ss

PAYLOAD = {"video_route": "hyperframes", "time_range": "7d", "selected_stages": [1, 2]}


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "SCHEDULE_PATH", tmp_path / "schedule.yaml")


def test_list_empty():
    assert ss.list_schedules() == []


def test_create_generates_slug_and_defaults():
    s = ss.create_schedule(name="Daily AI", freq="daily", run_at="2026-06-15T08:00:00", payload=PAYLOAD)
    assert s.slug == "daily_ai"
    assert s.name == "Daily AI" and s.freq == "daily" and s.enabled is True
    assert s.run_at == "2026-06-15T08:00:00"
    assert s.payload == PAYLOAD
    assert s.created_at and s.last_run_at is None and s.last_run_id is None


def test_create_chinese_name_falls_back_to_freq():
    s = ss.create_schedule(name="每日早八", freq="weekly", run_at="2026-06-15T08:00:00", payload={})
    assert s.slug == "weekly"


def test_create_collision_appends_number():
    ss.create_schedule(name="Daily AI", freq="daily", run_at="2026-06-15T08:00:00", payload={})
    s2 = ss.create_schedule(name="Daily AI", freq="daily", run_at="2026-06-15T08:00:00", payload={})
    assert s2.slug == "daily_ai_1"


def test_get_update_delete_roundtrip():
    ss.create_schedule(name="Daily AI", freq="daily", run_at="2026-06-15T08:00:00", payload={})
    ss.update_schedule("daily_ai", {"enabled": False, "last_run_id": 42})
    got = ss.get_schedule("daily_ai")
    assert got.enabled is False and got.last_run_id == 42
    assert ss.delete_schedule("daily_ai") is True
    assert ss.get_schedule("daily_ai") is None


def test_update_missing_returns_none():
    assert ss.update_schedule("nope", {"enabled": False}) is None


def test_ensure_file_creates_placeholder(tmp_path, monkeypatch):
    p = tmp_path / "schedule.yaml"
    monkeypatch.setattr(ss, "SCHEDULE_PATH", p)
    ss.ensure_file()
    assert p.exists()

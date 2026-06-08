import pytest

import app.pipeline.scheduler as sched_mod
from app.pipeline import scheduler
from app.store.schedules_store import ScheduleData


def _sched(freq, run_at):
    return ScheduleData(slug="s", name="s", freq=freq, run_at=run_at, payload={})


def test_once_spec_is_date_trigger():
    kind, kw = scheduler._trigger_spec(_sched("once", "2026-06-15T08:30:00"))
    assert kind == "date"
    assert kw["run_date"].hour == 8 and kw["run_date"].minute == 30


def test_daily_spec_takes_hour_minute():
    kind, kw = scheduler._trigger_spec(_sched("daily", "2026-06-15T08:30:00"))
    assert kind == "cron"
    assert kw == {"hour": 8, "minute": 30}


def test_weekly_sunday_maps_to_day_of_week_6():
    # 2026-06-14 是周日 → weekday()==6（钉死：不可被「0=周日」习惯改坏）
    kind, kw = scheduler._trigger_spec(_sched("weekly", "2026-06-14T09:00:00"))
    assert kind == "cron"
    assert kw == {"day_of_week": 6, "hour": 9, "minute": 0}


def test_monthly_spec_takes_day():
    kind, kw = scheduler._trigger_spec(_sched("monthly", "2026-06-15T08:30:00"))
    assert kind == "cron"
    assert kw == {"day": 15, "hour": 8, "minute": 30}


def test_unknown_freq_raises():
    with pytest.raises(ValueError):
        scheduler._trigger_spec(_sched("yearly", "2026-06-15T08:30:00"))


class _FakeRun:
    id = 99


class _FakeEngine:
    def __init__(self, db):
        pass

    def create_run(self, **kwargs):
        _FakeEngine.last_kwargs = kwargs
        return _FakeRun()


class _FakeSession:
    def close(self):
        pass


def _factory():
    return _FakeSession()


@pytest.fixture
def _patch_fire(monkeypatch):
    """隔离 _fire 的外部依赖：store 读/写、create_run、serial_submit。"""
    submitted = []
    updated = {}
    monkeypatch.setattr(sched_mod, "PipelineEngine", _FakeEngine)
    monkeypatch.setattr(sched_mod, "serial_submit", lambda fn, *a, **k: submitted.append((fn, a)))
    monkeypatch.setattr(sched_mod, "update_schedule", lambda slug, patch: updated.update({slug: patch}))
    monkeypatch.setattr(sched_mod, "unregister", lambda slug: updated.setdefault("_unregistered", []).append(slug))
    return submitted, updated


def test_fire_daily_creates_run_with_mode_auto(_patch_fire, monkeypatch):
    submitted, updated = _patch_fire
    monkeypatch.setattr(sched_mod, "get_schedule", lambda slug: ScheduleData(
        slug="s", name="s", freq="daily", run_at="2026-06-15T08:00:00",
        enabled=True, payload={"video_route": "hyperframes", "mode": "manual"}))
    sched_mod._fire("s", _factory)
    assert _FakeEngine.last_kwargs["mode"] == "auto"          # 强制 auto
    assert _FakeEngine.last_kwargs["video_route"] == "hyperframes"
    assert submitted and submitted[0][1][0] == 99             # serial_submit(run.id=99)
    assert updated["s"]["last_run_id"] == 99
    assert "enabled" not in updated["s"]                      # daily 不停用


def test_fire_once_disables_and_unregisters(_patch_fire, monkeypatch):
    submitted, updated = _patch_fire
    monkeypatch.setattr(sched_mod, "get_schedule", lambda slug: ScheduleData(
        slug="s", name="s", freq="once", run_at="2026-06-15T08:00:00",
        enabled=True, payload={}))
    sched_mod._fire("s", _factory)
    assert updated["s"]["enabled"] is False
    assert updated["_unregistered"] == ["s"]


def test_fire_skips_when_disabled(_patch_fire, monkeypatch):
    submitted, updated = _patch_fire
    monkeypatch.setattr(sched_mod, "get_schedule", lambda slug: ScheduleData(
        slug="s", name="s", freq="daily", run_at="2026-06-15T08:00:00",
        enabled=False, payload={}))
    sched_mod._fire("s", _factory)
    assert submitted == []


def test_monthly_day_under_29_uses_exact_day():
    kind, kw = scheduler._trigger_spec(_sched("monthly", "2024-12-15T08:30:00"))
    assert kind == "cron"
    assert kw == {"day": 15, "hour": 8, "minute": 30}


def test_monthly_day_31_maps_to_last():
    kind, kw = scheduler._trigger_spec(_sched("monthly", "2024-12-31T08:30:00"))
    assert kind == "cron"
    assert kw == {"day": "last", "hour": 8, "minute": 30}


def test_monthly_day_29_maps_to_last():
    kind, kw = scheduler._trigger_spec(_sched("monthly", "2024-12-29T09:00:00"))
    assert kw["day"] == "last"

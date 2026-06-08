import pytest

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

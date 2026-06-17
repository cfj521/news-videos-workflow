from types import SimpleNamespace
from app.pipeline.cover import resolve_cover_text


def _run(**kw):
    base = dict(aihot_config=None, time_range="7d", created_at="2026-06-18T01:00:00+00:00")
    base.update(kw)
    return SimpleNamespace(**base)


def test_period_normal_source_days():
    assert resolve_cover_text("{period}AI资讯", _run(time_range="7d")) == "最近7天AI资讯"

def test_period_normal_source_month():
    assert resolve_cover_text("{period}AI资讯", _run(time_range="1m")) == "最近1个月AI资讯"

def test_period_aihot_daily():
    assert resolve_cover_text("{period}AI资讯", _run(aihot_config='{"method": "daily"}')) == "每日AI资讯"

def test_period_aihot_weekly():
    assert resolve_cover_text("{period}AI资讯", _run(aihot_config='{"method": "weekly"}')) == "每周AI资讯"

def test_days_and_date():
    assert resolve_cover_text("{days}天·{date}", _run(time_range="7d")) == "7天·2026-06-18"

def test_empty_template():
    assert resolve_cover_text("", _run()) == ""

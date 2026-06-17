from types import SimpleNamespace
from app.pipeline.cover import resolve_cover_text, build_cover_entry, COVER_FALLBACK_MS
from app.config import CoverCfg


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


def test_build_cover_entry_with_audio():
    cfg = CoverCfg(enabled=True, title_template="{period}AI资讯", subtitle="每天3分钟", font_size=80)
    e = build_cover_entry(cfg, _run(time_range="7d"), image_rel="assets/cover_image.png",
                          audio_rel="assets/cover_audio.mp3", audio_ms=5200)
    assert e["is_cover"] is True
    assert e["scene_id"] == 0
    assert e["start_ms"] == 0 and e["end_ms"] == 5200 and e["audio_duration_ms"] == 5200
    assert e["title"] == "最近7天AI资讯"
    assert e["subtitle"] == "每天3分钟"
    assert e["cover_font_size"] == 80
    assert e["image_path"] == "assets/cover_image.png"
    assert e["audio_path"] == "assets/cover_audio.mp3"
    assert e["subtitle_lines"] == []

def test_build_cover_entry_no_audio_fallback():
    cfg = CoverCfg(enabled=True)
    e = build_cover_entry(cfg, _run(), image_rel="", audio_rel="", audio_ms=0)
    assert e["end_ms"] == COVER_FALLBACK_MS
    assert e["audio_path"] == ""

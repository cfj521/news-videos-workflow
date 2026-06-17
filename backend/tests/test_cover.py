from types import SimpleNamespace
from app.pipeline.cover import (
    resolve_cover_text,
    build_cover_entry,
    COVER_NARRATION_TAIL_MS,
    COVER_SILENT_FALLBACK_MS,
)
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

def test_date_daily_single_day():
    # 日报：单日
    assert resolve_cover_text("{date}", _run(aihot_config='{"method": "daily"}', time_range="1d")) == "2026-06-18"

def test_date_weekly_span():
    # 周报：本期跨度（7d → 06.12-06.18）
    assert resolve_cover_text("{date}", _run(aihot_config='{"method": "weekly"}', time_range="7d")) == "06.12-06.18"

def test_date_monthly_year_month():
    # 月报：年.月
    assert resolve_cover_text("{date}", _run(aihot_config='{"method": "monthly"}', time_range="1m")) == "2026.06"

def test_date_normal_source_single_day():
    # 普通源（无 method）：单日
    assert resolve_cover_text("{date}", _run(time_range="7d")) == "2026-06-18"

def test_title_variable():
    # {title} = 视频 meta 标题
    assert resolve_cover_text("{title}", _run(), meta_title="AI圈大爆发") == "AI圈大爆发"

def test_title_variable_empty_when_missing():
    assert resolve_cover_text("副标题{title}", _run()) == "副标题"

def test_build_cover_entry_resolves_title_in_subtitle():
    cfg = CoverCfg(enabled=True, subtitle="{title}")
    e = build_cover_entry(cfg, _run(), image_rel="", audio_rel="", audio_ms=0, meta_title="本周AI大事件")
    assert e["subtitle"] == "本周AI大事件"

def test_cover_text_color_passthrough():
    cfg = CoverCfg(enabled=True, text_color="#FF0000")
    e = build_cover_entry(cfg, _run(), image_rel="", audio_rel="", audio_ms=0)
    assert e["cover_text_color"] == "#FF0000"

def test_empty_template():
    assert resolve_cover_text("", _run()) == ""


def test_build_cover_entry_with_audio():
    cfg = CoverCfg(enabled=True, title_template="{period}AI资讯", subtitle="每天3分钟", font_size=80)
    e = build_cover_entry(cfg, _run(time_range="7d"), image_rel="assets/cover_image.png",
                          audio_rel="assets/cover_audio.mp3", audio_ms=5200)
    assert e["is_cover"] is True
    assert e["scene_id"] == 0
    # 有旁白：场景时长 = 旁白 + 1s 尾留；audio_duration_ms 仍为旁白真实时长
    assert e["start_ms"] == 0
    assert e["end_ms"] == 5200 + COVER_NARRATION_TAIL_MS
    assert e["audio_duration_ms"] == 5200
    assert e["title"] == "最近7天AI资讯"
    assert e["subtitle"] == "每天3分钟"
    assert e["cover_font_size"] == 80
    assert e["image_path"] == "assets/cover_image.png"
    assert e["audio_path"] == "assets/cover_audio.mp3"
    assert e["subtitle_lines"] == []

def test_build_cover_entry_no_audio_uses_silent_duration():
    cfg = CoverCfg(enabled=True, silent_duration=3.0)
    e = build_cover_entry(cfg, _run(), image_rel="", audio_rel="", audio_ms=0)
    assert e["end_ms"] == 3000  # 无旁白：用配置 silent_duration（默认 3s）
    assert e["audio_duration_ms"] == 0
    assert e["audio_path"] == ""

def test_build_cover_entry_no_audio_custom_silent_duration():
    cfg = CoverCfg(enabled=True, silent_duration=5.0)
    e = build_cover_entry(cfg, _run(), image_rel="", audio_rel="", audio_ms=0)
    assert e["end_ms"] == 5000

def test_build_cover_entry_no_audio_zero_silent_falls_back():
    cfg = CoverCfg(enabled=True, silent_duration=0)
    e = build_cover_entry(cfg, _run(), image_rel="", audio_rel="", audio_ms=0)
    assert e["end_ms"] == COVER_SILENT_FALLBACK_MS

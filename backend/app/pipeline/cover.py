"""视频固定封面（片头）纯逻辑：文案解析 + 封面 timeline entry 组装。"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

COVER_FALLBACK_MS = 4000  # 旁白为空时封面兜底时长


def _fmt_time_range(tr: str) -> str:
    m = re.fullmatch(r"\s*(\d+)\s*([dwmy])\s*", tr or "")
    if not m:
        return tr or ""
    unit = {"d": "天", "w": "周", "m": "个月", "y": "年"}.get(m.group(2), "")
    return f"{m.group(1)}{unit}"


def _aihot_method(run) -> str:
    raw = getattr(run, "aihot_config", None)
    if not raw:
        return ""
    try:
        return (json.loads(raw) or {}).get("method", "") or ""
    except Exception:
        return ""


def resolve_cover_text(template: str, run) -> str:
    """把封面模板里的 {period}/{days}/{date} 按 run 填充。"""
    if not template:
        return ""
    tr = getattr(run, "time_range", "") or ""
    method = _aihot_method(run)
    period = {"daily": "每日", "weekly": "每周", "monthly": "每月"}.get(method) or f"最近{_fmt_time_range(tr)}"
    days_m = re.match(r"\s*(\d+)", tr)
    days = days_m.group(1) if days_m else ""
    date_str = ""
    created = getattr(run, "created_at", None)
    try:
        if isinstance(created, str) and created:
            date_str = datetime.fromisoformat(created).astimezone().strftime("%Y-%m-%d")
        elif isinstance(created, datetime):
            date_str = created.astimezone().strftime("%Y-%m-%d")
    except Exception:
        date_str = ""
    if not date_str:
        date_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    return (template.replace("{period}", period).replace("{days}", days).replace("{date}", date_str))


def build_cover_entry(cfg, run, *, image_rel: str, audio_rel: str, audio_ms: int) -> dict:
    """组装 timeline 头部的封面 entry（视觉字段全内联）。"""
    dur = audio_ms if audio_ms and audio_ms > 0 else COVER_FALLBACK_MS
    return {
        "scene_id": 0, "is_cover": True, "start_ms": 0, "end_ms": dur,
        "image_path": image_rel, "audio_path": audio_rel or "", "audio_duration_ms": dur,
        "title": resolve_cover_text(cfg.title_template, run),
        "subtitle": resolve_cover_text(cfg.subtitle, run),
        "cover_font_size": cfg.font_size,
        "subtitle_text": "", "subtitle_lines": [],
    }

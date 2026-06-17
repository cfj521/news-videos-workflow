"""视频固定封面（片头）纯逻辑：文案解析 + 封面 timeline entry 组装 + 素材准备。"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

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


async def prepare_cover_assets(cfg_cover, run, run_dir, tts, *, override_image: str = "") -> "dict | None":
    """封面启用且非纯音频时，备好封面图/音频并返回封面 entry；否则 None。

    - 图：override_image（per-run）优先，否则 cfg_cover.image（仓库根相对或绝对）；
      拷到 run_dir/assets/cover_image.png。
    - 音：narration 解析后非空且有 tts 则 TTS 出 run_dir/assets/cover_audio.mp3。
    - 返回的 entry 里 image_path/audio_path 用【绝对路径】（与场景资产一致，
      供 _render_html relative_to(run_dir) 正确相对化为 assets/...）。
    """
    if not cfg_cover.enabled:
        return None
    run_dir = Path(run_dir)
    assets = run_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    # ── 封面图：override_image > cfg_cover.image；仓库根相对路径自动补全 ──
    image_abs = ""
    src_img = override_image or cfg_cover.image
    if src_img:
        sp = Path(src_img)
        if not sp.is_absolute():
            # 相对路径解析为仓库根（cover.py 在 backend/app/pipeline/，parents[3] = 仓库根）
            sp = Path(__file__).resolve().parents[3] / src_img
        if sp.is_file():
            dst = assets / "cover_image.png"
            shutil.copyfile(sp, dst)
            image_abs = str(dst.resolve())

    # ── 封面旁白 TTS：narration 非空且有 tts provider 则合成音频 ──
    audio_abs, audio_ms = "", 0
    narration = resolve_cover_text(cfg_cover.narration, run)
    if narration and tts is not None:
        from app.providers.tts.audio_duration import measure_audio_ms
        out = str((assets / "cover_audio.mp3").resolve())
        await tts.synthesize(text=narration, output_path=out)
        measured = measure_audio_ms(out) or 0
        if measured > 0:
            audio_ms = measured
            audio_abs = out

    return build_cover_entry(cfg_cover, run, image_rel=image_abs, audio_rel=audio_abs, audio_ms=audio_ms)

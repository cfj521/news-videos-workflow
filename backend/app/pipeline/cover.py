"""视频固定封面（片头）纯逻辑：文案解析 + 封面 timeline entry 组装 + 素材准备。"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

COVER_NARRATION_TAIL_MS = 1000  # 有旁白时，旁白结束后多停留 1s 再切场景
COVER_SILENT_FALLBACK_MS = 3000  # 无旁白且未配置 silent_duration 时的兜底时长


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


def _range_days(tr: str) -> int:
    """把 time_range（如 7d / 1w / 1m）换算成天数；解析失败返回 0。"""
    m = re.fullmatch(r"\s*(\d+)\s*([dwmy])\s*", tr or "")
    if not m:
        return 0
    return int(m.group(1)) * {"d": 1, "w": 7, "m": 30, "y": 365}[m.group(2)]


def _run_dt(run) -> datetime:
    """取 run 的制作时间（created_at，本地时区）；缺失/解析失败回退当前时间。"""
    created = getattr(run, "created_at", None)
    try:
        if isinstance(created, str) and created:
            return datetime.fromisoformat(created).astimezone()
        if isinstance(created, datetime):
            return created.astimezone()
    except Exception:
        pass
    return datetime.now(timezone.utc).astimezone()


def resolve_cover_text(template: str, run) -> str:
    """把封面模板里的 {period}/{days}/{date} 按 run 填充。

    {date} 按报告类型自适应：
    - 日报 / 普通源：单日（如 2026-06-18）
    - 周报：本期跨度（如 06.12-06.18，按 time_range 推算）
    - 月报：年.月（如 2026.06）
    """
    if not template:
        return ""
    tr = getattr(run, "time_range", "") or ""
    method = _aihot_method(run)
    period = {"daily": "每日", "weekly": "每周", "monthly": "每月"}.get(method) or f"最近{_fmt_time_range(tr)}"
    days_m = re.match(r"\s*(\d+)", tr)
    days = days_m.group(1) if days_m else ""
    base = _run_dt(run)
    if method == "monthly":
        date_str = base.strftime("%Y.%m")
    elif method == "weekly":
        span = _range_days(tr) or 7
        start = base - timedelta(days=span - 1)
        date_str = f"{start.strftime('%m.%d')}-{base.strftime('%m.%d')}"
    else:
        date_str = base.strftime("%Y-%m-%d")
    return (template.replace("{period}", period).replace("{days}", days).replace("{date}", date_str))


def build_cover_entry(cfg, run, *, image_rel: str, audio_rel: str, audio_ms: int) -> dict:
    """组装 timeline 头部的封面 entry（视觉字段全内联）。

    时长规则：
    - 有旁白：场景时长 = 旁白时长 + 1s 尾留（COVER_NARRATION_TAIL_MS），让语音念完再停 1s 才切场景；
      audio_duration_ms 仍为旁白真实时长（音频只播一遍，末尾 1s 静默停留）。
    - 无旁白：场景时长 = cfg.silent_duration（秒，默认 3s），audio_duration_ms 为 0。
    """
    if audio_ms and audio_ms > 0:
        end_ms = audio_ms + COVER_NARRATION_TAIL_MS
        audio_dur = audio_ms
    else:
        silent_s = getattr(cfg, "silent_duration", 0) or 0
        end_ms = int(silent_s * 1000) if silent_s > 0 else COVER_SILENT_FALLBACK_MS
        audio_dur = 0
    return {
        "scene_id": 0, "is_cover": True, "start_ms": 0, "end_ms": end_ms,
        "image_path": image_rel, "audio_path": audio_rel or "", "audio_duration_ms": audio_dur,
        "title": resolve_cover_text(cfg.title_template, run),
        "subtitle": resolve_cover_text(cfg.subtitle, run),
        "cover_font_size": cfg.font_size,
        "cover_text_color": getattr(cfg, "text_color", "") or "#FFFFFF",  # 标题+副标题统一颜色
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

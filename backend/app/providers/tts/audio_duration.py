"""用 ffprobe 读音频真实时长（ffmpeg 为项目硬依赖，必在 PATH）。

各 TTS provider 原先按「字数×固定速率」估算时长，对英文严重偏长（约 4 倍），
导致时间轴分镜时长与真实语音不符。现统一改为测量真实时长；测不到（返回 0）
由调用方直接报错，绝不再估算。
"""
import json
import subprocess

from app.logging import get_logger

log = get_logger("provider.tts.duration")


def measure_audio_ms(path: str) -> int:
    """返回音频真实时长(ms)；测量失败返回 0（调用方应回退到估算）。"""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
            capture_output=True, timeout=30, text=True,
        )
        dur = json.loads(proc.stdout or "{}").get("format", {}).get("duration")
        return int(float(dur) * 1000) if dur else 0
    except Exception as e:  # noqa: BLE001
        log.warning("measure_audio_ms 失败(%s)：%s", path, e)
        return 0

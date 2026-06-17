import asyncio
import time
from pathlib import Path

import edge_tts

from app.logging import get_logger
from app.providers.base import AssetResult, ProviderError, TTSProvider
from app.providers.tts.audio_duration import measure_audio_ms

log = get_logger("provider.tts.edge")

# edge-tts 走微软在线语音服务（受限网络/代理下偶发卡顿 150–400s）。单次合成正常仅几秒，
# 故设较宽的单次超时 + 多次重试：把"死等 5 分钟"变成"超时即重试，通常下一次几秒搞定"。
_ATTEMPT_TIMEOUT_S = 60.0
_MAX_ATTEMPTS = 3


class EdgeTTSProvider(TTSProvider):
    def __init__(self, default_voice: str = "zh-CN-XiaoxiaoNeural"):
        self._default_voice = default_voice
        log.info("Initialized EdgeTTSProvider voice=%s", default_voice)

    async def synthesize(self, text: str, voice: str = "", speed: float = 1.0, output_path: str = "") -> AssetResult:
        voice = voice or self._default_voice
        rate_pct = int((speed - 1) * 100)
        rate_str = f"+{rate_pct}%" if rate_pct >= 0 else f"{rate_pct}%"

        log.debug("synthesize() text=%d chars, voice=%s, rate=%s → %s", len(text), voice, rate_str, output_path)
        t0 = time.time()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # 单次合成加超时 + 重试：网络/代理偶发卡顿时快速失败重试，不再死等
        last_err: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            a0 = time.time()
            try:
                communicate = edge_tts.Communicate(text, voice, rate=rate_str)
                await asyncio.wait_for(communicate.save(output_path), timeout=_ATTEMPT_TIMEOUT_S)
                last_err = None
                break
            except Exception as e:  # 含 asyncio.TimeoutError（TimeoutError 子类）
                last_err = e
                kind = f"超时(>{_ATTEMPT_TIMEOUT_S:.0f}s)" if isinstance(e, asyncio.TimeoutError) else f"失败: {e}"
                tail = "，重试" if attempt < _MAX_ATTEMPTS else "，放弃"
                log.warning("synthesize() 第 %d/%d 次%s（%.1fs）%s", attempt, _MAX_ATTEMPTS, kind, time.time() - a0, tail)
        if last_err is not None:
            log.error("synthesize() %d 次均失败，累计 %.1fs", _MAX_ATTEMPTS, time.time() - t0)
            raise ProviderError(service="语音合成", provider="edge-tts", model=voice, cause=last_err) from last_err

        file_size = Path(output_path).stat().st_size if Path(output_path).exists() else 0
        # 必须测到真实时长；测不到（文件缺失/无效）直接报错，绝不估算
        duration_ms = measure_audio_ms(output_path)
        if duration_ms <= 0:
            raise ProviderError(service="语音合成", provider="edge-tts", model=voice,
                                cause=RuntimeError(f"无法读取合成音频时长（文件缺失或无效）：{output_path}"))
        log.info("synthesize() done — %d bytes, %dms in %.1fs → %s", file_size, duration_ms, time.time() - t0, output_path)

        return AssetResult(file_path=output_path, duration_ms=duration_ms)

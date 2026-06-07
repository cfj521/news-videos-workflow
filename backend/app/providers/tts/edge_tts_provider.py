import time
from pathlib import Path

import edge_tts

from app.logging import get_logger
from app.providers.base import AssetResult, ProviderError, TTSProvider
from app.providers.tts.audio_duration import measure_audio_ms

log = get_logger("provider.tts.edge")


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

        try:
            communicate = edge_tts.Communicate(text, voice, rate=rate_str)
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            await communicate.save(output_path)
        except Exception as e:
            log.exception("synthesize() failed after %.1fs", time.time() - t0)
            raise ProviderError(service="语音合成", provider="edge-tts", model=voice, cause=e) from e

        file_size = Path(output_path).stat().st_size if Path(output_path).exists() else 0
        # 必须测到真实时长；测不到（文件缺失/无效）直接报错，绝不估算
        duration_ms = measure_audio_ms(output_path)
        if duration_ms <= 0:
            raise ProviderError(service="语音合成", provider="edge-tts", model=voice,
                                cause=RuntimeError(f"无法读取合成音频时长（文件缺失或无效）：{output_path}"))
        log.info("synthesize() done — %d bytes, %dms in %.1fs → %s", file_size, duration_ms, time.time() - t0, output_path)

        return AssetResult(file_path=output_path, duration_ms=duration_ms)

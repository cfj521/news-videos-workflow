from pathlib import Path

import edge_tts

from app.providers.base import AssetResult, TTSProvider


class EdgeTTSProvider(TTSProvider):
    def __init__(self, default_voice: str = "zh-CN-XiaoxiaoNeural"):
        self._default_voice = default_voice

    async def synthesize(
        self,
        text: str,
        voice: str = "",
        speed: float = 1.0,
        output_path: str = "",
    ) -> AssetResult:
        voice = voice or self._default_voice
        rate_pct = int((speed - 1) * 100)
        rate_str = f"+{rate_pct}%" if rate_pct >= 0 else f"{rate_pct}%"

        communicate = edge_tts.Communicate(text, voice, rate=rate_str)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        await communicate.save(output_path)

        duration_ms = self._estimate_duration(text, speed)

        return AssetResult(file_path=output_path, duration_ms=duration_ms)

    def _estimate_duration(self, text: str, speed: float) -> int:
        chars = len(text)
        chars_per_second = 4.0 * speed
        return int((chars / chars_per_second) * 1000)

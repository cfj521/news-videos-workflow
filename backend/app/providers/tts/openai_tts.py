import time
from pathlib import Path

import openai

from app.logging import get_logger
from app.providers.base import AssetResult, ProviderError, TTSProvider

log = get_logger("provider.tts.openai")


class OpenAITTSProvider(TTSProvider):
    """OpenAI 兼容语音合成（/audio/speech）。base_url/api_key 与文本/图片共用同一 openai 供应商。"""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini-tts", base_url: str = "", default_voice: str = "alloy"):
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = openai.AsyncOpenAI(**kwargs)
        self._model = model or "gpt-4o-mini-tts"
        self._default_voice = default_voice or "alloy"
        self._base_url = base_url or "https://api.openai.com/v1"
        log.info("Initialized OpenAITTSProvider model=%s base_url=%s", self._model, base_url or "(default)")

    async def synthesize(self, text: str, voice: str = "", speed: float = 1.0, output_path: str = "") -> AssetResult:
        voice = voice or self._default_voice
        t0 = time.time()
        try:
            resp = await self._client.audio.speech.create(
                model=self._model, voice=voice, input=text, response_format="mp3", speed=speed or 1.0,
            )
            audio = await resp.aread()
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_bytes(audio)
        except Exception as e:
            log.exception("synthesize() failed after %.1fs", time.time() - t0)
            raise ProviderError(service="语音合成", provider="openai", model=self._model, base_url=self._base_url, cause=e) from e

        size = Path(output_path).stat().st_size if Path(output_path).exists() else 0
        dur = int((len(text) / (4.0 * (speed or 1.0))) * 1000)
        log.info("synthesize() done — %d bytes, voice=%s in %.1fs → %s", size, voice, time.time() - t0, output_path)
        return AssetResult(file_path=output_path, duration_ms=dur)

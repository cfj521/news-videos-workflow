import asyncio
import time
from pathlib import Path

import httpx

from app.logging import get_logger
from app.providers.base import AssetResult, ProviderError, TTSProvider

log = get_logger("provider.tts.dashscope")


class DashScopeTTSProvider(TTSProvider):
    """阿里云语音（DashScope 原生 SDK）。按模型分支：

    - qwen3-tts-flash 等：qwen_tts.SpeechSynthesizer.call → response.output.audio.url（wav，下载）。
    - cosyvoice-v3-flash 等：audio.tts_v2.SpeechSynthesizer(model, voice).call(text) → 直接返回 mp3 字节。
    api_key 与文本/图片共用同一 dashscope 供应商。
    """

    def __init__(self, api_key: str, model: str = "qwen3-tts-flash", default_voice: str = "Cherry"):
        self._api_key = api_key
        self._model = model or "qwen3-tts-flash"
        self._default_voice = default_voice or "Cherry"
        log.info("Initialized DashScopeTTSProvider model=%s", self._model)

    def _synth_bytes(self, text: str, voice: str) -> bytes:
        """同步合成，返回音频字节（放线程池调用）。"""
        import dashscope
        dashscope.api_key = self._api_key
        if self._model.startswith("cosyvoice"):
            from dashscope.audio.tts_v2 import SpeechSynthesizer
            audio = SpeechSynthesizer(model=self._model, voice=voice).call(text)
            if not audio:
                raise RuntimeError("cosyvoice 返回空音频")
            return audio
        # qwen-tts：返回音频 URL，需下载
        resp = dashscope.audio.qwen_tts.SpeechSynthesizer.call(
            model=self._model, api_key=self._api_key, text=text, voice=voice,
        )
        if getattr(resp, "status_code", 200) != 200:
            raise RuntimeError(f"qwen-tts 失败: {getattr(resp, 'message', resp)}")
        au = resp.output.audio
        url = au["url"] if isinstance(au, dict) else getattr(au, "url", "")
        if not url:
            raise RuntimeError("qwen-tts 响应缺少音频 URL")
        with httpx.Client(timeout=60) as c:
            r = c.get(url)
            r.raise_for_status()
            return r.content

    async def synthesize(self, text: str, voice: str = "", speed: float = 1.0, output_path: str = "") -> AssetResult:
        voice = voice or self._default_voice
        t0 = time.time()
        try:
            audio = await asyncio.to_thread(self._synth_bytes, text, voice)
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_bytes(audio)  # ffmpeg/moviepy 按内容识别格式
        except Exception as e:
            log.exception("synthesize() failed after %.1fs", time.time() - t0)
            raise ProviderError(service="语音合成", provider="dashscope", model=self._model, cause=e) from e

        size = Path(output_path).stat().st_size if Path(output_path).exists() else 0
        dur = int((len(text) / (4.0 * (speed or 1.0))) * 1000)
        log.info("synthesize() done — %d bytes, voice=%s in %.1fs → %s", size, voice, time.time() - t0, output_path)
        return AssetResult(file_path=output_path, duration_ms=dur)

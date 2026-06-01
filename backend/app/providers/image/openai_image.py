import time
from pathlib import Path

import httpx
import openai

from app.logging import get_logger
from app.providers.base import AssetResult, ImageProvider, ProviderError

log = get_logger("provider.image.openai")

SIZE_MAP = {
    "1080x1920": "1024x1792",
    "1920x1080": "1792x1024",
    "1024x1024": "1024x1024",
}


class OpenAIImageProvider(ImageProvider):
    def __init__(self, api_key: str, model: str = "gpt-image-1", base_url: str = ""):
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = openai.AsyncOpenAI(**kwargs)
        self._model = model
        self._base_url = base_url or "https://api.openai.com/v1"
        log.info("Initialized OpenAIImageProvider model=%s", model)

    async def generate(self, prompt: str, size: str = "1080x1920", output_path: str = "") -> AssetResult:
        api_size = self._map_size(size)
        log.debug("generate() prompt='%s' size=%s→%s output=%s", prompt[:80], size, api_size, output_path)
        t0 = time.time()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        try:
            response = await self._client.images.generate(
                model=self._model, prompt=prompt, size=api_size, quality="high", n=1,
            )
        except Exception as e:
            log.exception("images.generate() API call failed after %.1fs", time.time() - t0)
            raise ProviderError(service="图片生成", provider="openai", model=self._model, base_url=self._base_url, cause=e) from e

        item = response.data[0]

        if hasattr(item, "b64_json") and item.b64_json:
            import base64
            image_data = base64.b64decode(item.b64_json)
            Path(output_path).write_bytes(image_data)
            log.info("generate() done — b64 %d bytes in %.1fs → %s", len(image_data), time.time() - t0, output_path)
        elif hasattr(item, "url") and item.url:
            async with httpx.AsyncClient(timeout=60) as http:
                resp = await http.get(item.url)
                resp.raise_for_status()
                Path(output_path).write_bytes(resp.content)
                log.info("generate() done — url download %d bytes in %.1fs → %s", len(resp.content), time.time() - t0, output_path)
        else:
            log.error("generate() — no image data in response")
            raise RuntimeError("No image data in response")

        return AssetResult(file_path=output_path)

    def _map_size(self, size: str) -> str:
        return SIZE_MAP.get(size, "1024x1792")

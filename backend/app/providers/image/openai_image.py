import time
from pathlib import Path

import httpx
import openai

from app.logging import get_logger
from app.oauth.openai_oauth import build_codex_client, subscription_creds
from app.providers.base import AssetResult, ImageProvider, ProviderError

log = get_logger("provider.image.openai")

# DALL-E / gpt-image-1 的 size 映射（api_key 模式）
SIZE_MAP = {
    "1080x1920": "1024x1792",
    "1920x1080": "1792x1024",
    "1024x1024": "1024x1024",
}

# 订阅(Responses image_generation 工具)支持的 size：竖/横/方/auto
_SUB_SIZE_MAP = {"1080x1920": "1024x1536", "1920x1080": "1536x1024", "1024x1024": "1024x1024"}


class OpenAIImageProvider(ImageProvider):
    def __init__(self, api_key: str, model: str = "gpt-image-1", base_url: str = "", subscription: bool = False):
        self._subscription = subscription
        if subscription:
            # 订阅模式：token 每次调用时实时获取，不在 __init__ 建立客户端
            self._client = None
            self._model = "gpt-5.5"
            self._base_url = "https://chatgpt.com/backend-api/codex"
        else:
            kwargs: dict = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            self._client = openai.AsyncOpenAI(**kwargs)
            self._model = model
            self._base_url = base_url or "https://api.openai.com/v1"
        log.info("Initialized OpenAIImageProvider model=%s subscription=%s", self._model, subscription)

    async def generate(self, prompt: str, size: str = "1080x1920", output_path: str = "") -> AssetResult:
        if self._subscription:
            return await self._generate_subscription(prompt, size, output_path)

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

    async def _generate_subscription(self, prompt: str, size: str, output_path: str) -> AssetResult:
        """订阅模式：走 Responses image_generation 工具流式生图（gpt-5.5 固定端点）。"""
        import base64
        t0 = time.time()
        tool_size = _SUB_SIZE_MAP.get(size, "auto")
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            _, token, account_id = subscription_creds()
            client = build_codex_client(token, account_id)
            img_b64 = None
            async with client.responses.stream(
                model="gpt-5.5",
                instructions="Generate the requested image.",
                input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
                tools=[{"type": "image_generation", "size": tool_size}],
                store=False,
            ) as stream:
                async for event in stream:
                    if event.type == "response.output_item.done":
                        item = getattr(event, "item", None)
                        if getattr(item, "type", None) == "image_generation_call":
                            img_b64 = getattr(item, "result", None) or img_b64
                    elif event.type == "response.image_generation_call.partial_image":
                        img_b64 = getattr(event, "partial_image_b64", None) or img_b64
        except Exception as e:
            log.exception("generate(sub) image failed after %.1fs", time.time() - t0)
            raise ProviderError(service="图片生成", provider="openai", model=self._model, base_url=self._base_url, cause=e) from e
        if not img_b64:
            raise ProviderError(service="图片生成", provider="openai", model=self._model, base_url=self._base_url, cause=RuntimeError("订阅生图无图片返回"))
        Path(output_path).write_bytes(base64.b64decode(img_b64))
        log.info("generate(sub) image done in %.1fs → %s", time.time() - t0, output_path)
        return AssetResult(file_path=output_path)

    def _map_size(self, size: str) -> str:
        return SIZE_MAP.get(size, "1024x1792")

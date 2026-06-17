import re
import time
from pathlib import Path

import httpx
import openai

from app.logging import get_logger
from app.oauth.openai_oauth import build_codex_client, subscription_creds
from app.providers.base import AssetResult, ImageProvider, ProviderError

log = get_logger("provider.image.openai")

# DALL-E / gpt-image-1 的 size 映射（api_key 模式）：这些模型只支持固定档位，按比例就近映射。
# gpt-image-2 不走这张表，它原生支持任意分辨率（见 _align_gpt_image_2_size）。
SIZE_MAP = {
    "720x1280": "1024x1792",   # 竖屏 HD
    "1280x720": "1792x1024",   # 横屏 HD
    "1080x1920": "1024x1792",  # 竖屏 FHD
    "1920x1080": "1792x1024",  # 横屏 FHD
    "1024x1024": "1024x1024",  # 方形
}

# 订阅(Responses image_generation 工具)支持的 size：竖/横/方/auto
_SUB_SIZE_MAP = {
    "720x1280": "1024x1536", "1280x720": "1536x1024",
    "1080x1920": "1024x1536", "1920x1080": "1536x1024", "1024x1024": "1024x1024",
}

# gpt-image-2 自定义分辨率约束（官方文档）
_G2_MAX_EDGE = 3840
_G2_MAX_RATIO = 3
_G2_MIN_PIXELS = 655_360
_G2_MAX_PIXELS = 8_294_400


def _img_dimensions(data: bytes) -> str:
    """从图片字节解析实际 'WxH'（仅 PNG / JPEG，解析失败返回 '?'）。

    零依赖（不引 Pillow）：PNG 读 IHDR，JPEG 扫 SOF 标记。仅用于日志核对
    "请求尺寸 vs 实际出图尺寸"，定位 provider 不按 size 出图（如选横版却出竖版）。
    """
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            w = int.from_bytes(data[16:20], "big")
            h = int.from_bytes(data[20:24], "big")
            return f"{w}x{h}"
        if data[:2] == b"\xff\xd8":  # JPEG：逐段跳到 SOF（含宽高）
            i = 2
            n = len(data)
            while i + 9 < n:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    h = int.from_bytes(data[i + 5:i + 7], "big")
                    w = int.from_bytes(data[i + 7:i + 9], "big")
                    return f"{w}x{h}"
                i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    except Exception:
        pass
    return "?"


def _align_gpt_image_2_size(size: str) -> str | None:
    """把 WxH 对齐到 gpt-image-2 的约束并返回 'WxH'；无法满足返回 None（交回档位映射）。

    gpt-image-2 接受任意分辨率：宽高均为 16 的倍数、最长边 ≤3840、长短比 ≤3:1、
    总像素 65.5万~829万。对不合 16 倍数的尺寸（如 1080 系）四舍五入对齐到最近 16 倍数
    （1080→1088，近乎无损）；1024x1024 / 720x1280 / 1280x720 等已合法的原样透传，精确出图。
    """
    m = re.fullmatch(r"\s*(\d+)x(\d+)\s*", size)
    if not m:
        return None
    w = max(16, round(int(m.group(1)) / 16) * 16)
    h = max(16, round(int(m.group(2)) / 16) * 16)
    long_edge, short_edge = max(w, h), min(w, h)
    if long_edge > _G2_MAX_EDGE or long_edge > _G2_MAX_RATIO * short_edge:
        return None
    if not (_G2_MIN_PIXELS <= w * h <= _G2_MAX_PIXELS):
        return None
    return f"{w}x{h}"


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
            log.info("generate() done — b64 %d bytes, req=%s→%s actual=%s in %.1fs → %s",
                     len(image_data), size, api_size, _img_dimensions(image_data), time.time() - t0, output_path)
        elif hasattr(item, "url") and item.url:
            async with httpx.AsyncClient(timeout=60) as http:
                resp = await http.get(item.url)
                resp.raise_for_status()
                Path(output_path).write_bytes(resp.content)
                log.info("generate() done — url download %d bytes, req=%s→%s actual=%s in %.1fs → %s",
                         len(resp.content), size, api_size, _img_dimensions(resp.content), time.time() - t0, output_path)
        else:
            log.error("generate() — no image data in response")
            raise RuntimeError("No image data in response")

        return AssetResult(file_path=output_path)

    async def _generate_subscription(self, prompt: str, size: str, output_path: str) -> AssetResult:
        """订阅模式：走 Responses image_generation 工具流式生图（gpt-5.5 固定端点）。"""
        import base64
        t0 = time.time()
        tool_size = _SUB_SIZE_MAP.get(size, "auto")
        # 先打请求映射：req 是流水线要的尺寸，tool 是传给订阅 image_generation 工具的档位
        # （订阅工具只有 1024x1024 / 1024x1536 竖 / 1536x1024 横；未命中映射表则退化成 auto，模型自选比例）
        log.info("generate(sub) start — req=%s → tool=%s, output=%s", size, tool_size, output_path)
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
        data = base64.b64decode(img_b64)
        Path(output_path).write_bytes(data)
        actual = _img_dimensions(data)
        log.info("generate(sub) image done in %.1fs — req=%s tool=%s actual=%s (%d bytes) → %s",
                 time.time() - t0, size, tool_size, actual, len(data), output_path)
        if tool_size != "auto" and actual not in ("?", tool_size):
            log.warning("generate(sub) 实际 %s ≠ 请求档位 %s（订阅工具未严格按 size 出图）", actual, tool_size)
        return AssetResult(file_path=output_path)

    def _map_size(self, size: str) -> str:
        # gpt-image-2 原生支持任意分辨率：合法则透传/对齐（精确出图），避免把 1280x720 这类降级到 DALL-E 档位。
        if self._model.startswith("gpt-image-2"):
            aligned = _align_gpt_image_2_size(size)
            if aligned:
                return aligned
        return SIZE_MAP.get(size, "1024x1792")

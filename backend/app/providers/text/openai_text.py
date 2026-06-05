import time

import openai

from app.logging import get_logger
from app.providers.base import ProviderError, TextProvider

log = get_logger("provider.text.openai")


class OpenAITextProvider(TextProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o", base_url: str = "", max_tokens: int = 65535):
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = openai.AsyncOpenAI(**kwargs)
        self._model = model
        self._max_tokens = max_tokens or 65535
        self._base_url = base_url or "https://api.openai.com/v1"
        log.info("Initialized OpenAITextProvider model=%s base_url=%s", model, base_url or "(default)")

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        log.debug("generate() prompt=%d chars, system=%d chars, model=%s", len(prompt), len(system_prompt), self._model)
        t0 = time.time()

        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_completion_tokens=self._max_tokens,
            )
            text = response.choices[0].message.content or ""
            usage = response.usage
            log.info("generate() done — %d chars in %.1fs, tokens=%s/%s", len(text), time.time() - t0, getattr(usage, "prompt_tokens", "?"), getattr(usage, "completion_tokens", "?"))
            return text
        except Exception as e:
            log.exception("generate() failed after %.1fs", time.time() - t0)
            raise ProviderError(service="文本生成", provider="openai", model=self._model, base_url=self._base_url, cause=e) from e

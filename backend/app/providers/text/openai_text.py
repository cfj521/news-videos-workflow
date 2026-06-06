import time

import openai

from app.logging import get_logger
from app.oauth.openai_oauth import build_codex_client, subscription_creds
from app.providers.base import ProviderError, TextProvider

log = get_logger("provider.text.openai")


class OpenAITextProvider(TextProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: str = "",
        max_tokens: int = 65535,
        subscription: bool = False,
    ):
        self._subscription = subscription
        self._model = model
        self._max_tokens = max_tokens or 65535
        if subscription:
            # 订阅模式：token 每次调用时实时获取，不在 __init__ 建立客户端
            self._client = None
            self._base_url = "https://chatgpt.com/backend-api/codex"
        else:
            kwargs: dict = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            self._client = openai.AsyncOpenAI(**kwargs)
            self._base_url = base_url or "https://api.openai.com/v1"
        log.info(
            "Initialized OpenAITextProvider model=%s subscription=%s base_url=%s",
            model, subscription, self._base_url,
        )

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        if self._subscription:
            return await self._generate_subscription(prompt, system_prompt)

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

    async def _generate_subscription(self, prompt: str, system_prompt: str = "") -> str:
        """订阅模式：走 Responses 流式 API，手动累积 output_text.delta（非流式被拒绝）。"""
        log.debug("generate(sub) prompt=%d chars, model=%s", len(prompt), self._model)
        t0 = time.time()
        try:
            _, token, account_id = subscription_creds()
            client = build_codex_client(token, account_id)
            parts: list[str] = []
            async with client.responses.stream(
                model=self._model,
                instructions=system_prompt or "You are a helpful assistant.",
                input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
                store=False,
            ) as stream:
                async for event in stream:
                    if event.type == "response.output_text.delta":
                        parts.append(event.delta)
            text = "".join(parts)
            log.info("generate(sub) done — %d chars in %.1fs", len(text), time.time() - t0)
            return text
        except Exception as e:
            log.exception("generate(sub) failed after %.1fs", time.time() - t0)
            raise ProviderError(service="文本生成", provider="openai", model=self._model, base_url=self._base_url, cause=e) from e

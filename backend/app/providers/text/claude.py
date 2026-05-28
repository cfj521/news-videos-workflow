import time

import anthropic

from app.logging import get_logger
from app.providers.base import TextProvider

log = get_logger("provider.text.claude")


class ClaudeTextProvider(TextProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6", base_url: str = ""):
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = anthropic.AsyncAnthropic(**kwargs)
        self._model = model
        log.info("Initialized ClaudeTextProvider model=%s base_url=%s", model, base_url or "(default)")

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        log.debug("generate() prompt=%d chars, system=%d chars, model=%s", len(prompt), len(system_prompt), self._model)
        t0 = time.time()

        kwargs: dict = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        try:
            message = await self._client.messages.create(**kwargs)
            text = message.content[0].text
            log.info("generate() done — %d chars in %.1fs, usage=%s", len(text), time.time() - t0, getattr(message, "usage", None))
            return text
        except Exception:
            log.exception("generate() failed after %.1fs", time.time() - t0)
            raise

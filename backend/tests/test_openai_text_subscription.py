import pytest

from app.providers.text.openai_text import OpenAITextProvider


class _Ev:
    def __init__(self, type, delta=None):
        self.type = type
        self.delta = delta


class _FakeStream:
    def __init__(self, events):
        self._events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        async def gen():
            for e in self._events:
                yield e
        return gen()


class _FakeResponses:
    def __init__(self, holder):
        self._h = holder

    def stream(self, **kwargs):
        self._h["kwargs"] = kwargs
        return _FakeStream([
            _Ev("response.output_text.delta", "PO"),
            _Ev("response.output_text.delta", "NG"),
            _Ev("response.output_text.done"),
        ])


class _FakeClient:
    def __init__(self, holder):
        self.responses = _FakeResponses(holder)


@pytest.mark.asyncio
async def test_subscription_streams_and_accumulates(monkeypatch):
    holder = {}
    import app.providers.text.openai_text as mod
    monkeypatch.setattr(mod, "subscription_creds", lambda: ("https://chatgpt.com/backend-api/codex", "AT", "ACC"))
    monkeypatch.setattr(mod, "build_codex_client", lambda token, acc: _FakeClient(holder))
    p = OpenAITextProvider(api_key="", model="gpt-5.5", subscription=True)
    out = await p.generate("hello", system_prompt="sys")
    assert out == "PONG"
    kw = holder["kwargs"]
    assert kw["model"] == "gpt-5.5"
    assert kw["instructions"] == "sys"
    assert kw["store"] is False
    # input 必须是 list，含 input_text
    assert isinstance(kw["input"], list)
    assert kw["input"][0]["content"][0]["type"] == "input_text"
    assert kw["input"][0]["content"][0]["text"] == "hello"

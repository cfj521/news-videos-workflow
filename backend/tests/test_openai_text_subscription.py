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


@pytest.mark.asyncio
async def test_subscription_delta_none_guarded(monkeypatch):
    """delta 为 None 时不应让 "".join 崩溃（守卫 event.delta or ""）。"""
    holder = {}
    import app.providers.text.openai_text as mod
    monkeypatch.setattr(mod, "subscription_creds", lambda: ("base", "AT", "ACC"))

    class _NoneResponses:
        def stream(self, **kwargs):
            return _FakeStream([
                _Ev("response.output_text.delta", "A"),
                _Ev("response.output_text.delta", None),  # None delta
                _Ev("response.output_text.delta", "B"),
            ])

    class _NoneClient:
        def __init__(self):
            self.responses = _NoneResponses()

    monkeypatch.setattr(mod, "build_codex_client", lambda token, acc: _NoneClient())
    p = OpenAITextProvider(api_key="", model="m", subscription=True)
    out = await p.generate("hi")
    assert out == "AB"


def test_factory_not_subscription_when_provider_is_third_party(monkeypatch):
    """工厂关键 correctness：script provider 是第三方 openai 兼容 provider（dashscope）时，
    即便 openai 自身处于 subscription，也不得启用订阅（否则误打到 codex）。"""
    from app.config import PipelineCfg, ProviderCreds, Settings
    import app.pipeline.runner as runner

    settings = Settings(
        pipeline=PipelineCfg(script_provider="dashscope", script_model="qwen3.6-plus"),
        providers={
            "openai": ProviderCreds(api_key="sk-x", auth_mode="subscription"),
            "dashscope": ProviderCreds(
                api_key="ds-x",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
        },
    )
    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    provider = runner._build_text_provider()
    # 走的是 OpenAITextProvider（openai 兼容），但绝不能是订阅模式
    assert provider._subscription is False


def test_factory_subscription_when_provider_is_openai(monkeypatch):
    """对照：script provider 就是 openai 且 auth_mode=subscription 时，应启用订阅。"""
    from app.config import PipelineCfg, ProviderCreds, Settings
    import app.pipeline.runner as runner

    settings = Settings(
        pipeline=PipelineCfg(script_provider="openai", script_model="gpt-5.5"),
        providers={
            "openai": ProviderCreds(api_key="sk-x", auth_mode="subscription"),
        },
    )
    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    provider = runner._build_text_provider()
    assert provider._subscription is True

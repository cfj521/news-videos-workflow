import base64
import pytest

from app.providers.image.openai_image import OpenAIImageProvider


class _Item:
    type = "image_generation_call"
    def __init__(self, b64):
        self.result = b64


class _Ev:
    def __init__(self, type, item=None, partial_image_b64=None):
        self.type = type
        self.item = item
        self.partial_image_b64 = partial_image_b64


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
        b64 = base64.b64encode(b"PNGDATA").decode()
        return _FakeStream([_Ev("response.output_item.done", item=_Item(b64))])


class _FakeClient:
    def __init__(self, holder):
        self.responses = _FakeResponses(holder)


@pytest.mark.asyncio
async def test_subscription_image_streams_gpt55_tool_and_size(tmp_path, monkeypatch):
    holder = {}
    import app.providers.image.openai_image as mod
    monkeypatch.setattr(mod, "subscription_creds", lambda: ("base", "AT", "ACC"))
    monkeypatch.setattr(mod, "build_codex_client", lambda t, a: _FakeClient(holder))
    out = tmp_path / "x.png"
    p = OpenAIImageProvider(api_key="", model="ignored", subscription=True)
    res = await p.generate("a cat", size="1080x1920", output_path=str(out))
    assert out.read_bytes() == b"PNGDATA"
    assert res.file_path == str(out)
    kw = holder["kwargs"]
    assert kw["model"] == "gpt-5.5"
    assert kw["store"] is False
    assert isinstance(kw["input"], list)
    tools = kw["tools"]
    assert any(t.get("type") == "image_generation" for t in tools)
    # 竖屏 1080x1920 → 1024x1536
    assert tools[0]["size"] == "1024x1536"

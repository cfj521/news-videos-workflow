import pytest

from app.config import ProviderCfg
from app.services.document_import_pdf import _vision_extract


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
            _Ev("response.output_text.delta", "正文"),
            _Ev("response.output_text.delta", "内容"),
        ])


class _FakeClient:
    def __init__(self, holder):
        self.responses = _FakeResponses(holder)


@pytest.mark.asyncio
async def test_vision_subscription_streams_codex(monkeypatch):
    holder = {}
    import app.services.document_import_pdf as mod
    monkeypatch.setattr(mod, "subscription_creds", lambda: ("base", "AT", "ACC"))
    monkeypatch.setattr(mod, "build_codex_client", lambda t, a: _FakeClient(holder))
    cfg = ProviderCfg(provider="openai", model="gpt-5.5", auth_mode="subscription", account_id="ACC")
    out = await _vision_extract([b"\x89PNG\r\n\x1a\n"], cfg)
    assert out == "正文内容"
    kw = holder["kwargs"]
    assert kw["model"] == "gpt-5.5"
    assert kw["store"] is False
    content = kw["input"][0]["content"]
    # 含一段 input_text + 一张 input_image，image_url 必须是字符串 data URL
    assert content[0]["type"] == "input_text"
    img = [c for c in content if c["type"] == "input_image"][0]
    assert isinstance(img["image_url"], str)
    assert img["image_url"].startswith("data:image/png;base64,")

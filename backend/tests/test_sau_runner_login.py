import asyncio

import pytest

from app.providers.publisher import sau_runner as r


class FakeStream:
    def __init__(self, lines: list[bytes]):
        self._lines = lines

    async def readline(self):
        return self._lines.pop(0) if self._lines else b""


class FakeProc:
    def __init__(self, lines, returncode=0):
        self.stdout = FakeStream(lines)
        self.stderr = FakeStream([])
        self.returncode = returncode
        self.pid = 99

    async def wait(self):
        return self.returncode


@pytest.mark.asyncio
async def test_run_login_emits_qr_then_success(monkeypatch):
    lines = [b'{"qr": "data:image/png;base64,AAA"}\n', b'{"result": "success"}\n', b""]

    async def fake_exec(*a, **k):
        return FakeProc(lines)
    monkeypatch.setattr(r.asyncio, "create_subprocess_exec", fake_exec)

    seen = []
    ok, status = await r.run_login("douyin", "acct1", on_qr=seen.append)
    assert seen == ["data:image/png;base64,AAA"]
    assert ok is True
    assert status == "success"


@pytest.mark.asyncio
async def test_run_login_invalid_account(monkeypatch):
    ok, status = await r.run_login("douyin", "../bad", on_qr=lambda x: None)
    assert ok is False
    assert status == "failed"

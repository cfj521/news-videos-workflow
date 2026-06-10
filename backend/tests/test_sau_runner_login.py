import pytest

from app.providers.publisher import sau_runner as r


class FakeStdout:
    def __init__(self, lines: list[bytes]):
        self._lines = list(lines)

    def readline(self) -> bytes:
        return self._lines.pop(0) if self._lines else b""


class FakeProc:
    def __init__(self, lines, returncode=0):
        self.stdout = FakeStdout(lines)
        self.returncode = returncode
        self.pid = 99

    def wait(self):
        return self.returncode


def _patch_popen(monkeypatch, proc):
    monkeypatch.setattr(r.subprocess, "Popen", lambda argv, **k: proc)


@pytest.mark.asyncio
async def test_run_login_emits_qr_then_success(monkeypatch):
    lines = [b'{"qr": "data:image/png;base64,AAA"}\n', b'{"result": "success"}\n']
    _patch_popen(monkeypatch, FakeProc(lines))

    seen = []
    ok, status = await r.run_login("douyin", "acct1", on_qr=seen.append)
    assert seen == ["data:image/png;base64,AAA"]
    assert ok is True
    assert status == "success"


@pytest.mark.asyncio
async def test_run_login_failed_result(monkeypatch):
    # worker 报失败（带非 JSON 噪声行）→ status failed
    lines = [b'Traceback noise line\n', b'{"result": "failed", "error": "boom"}\n']
    _patch_popen(monkeypatch, FakeProc(lines))
    ok, status = await r.run_login("douyin", "acct1", on_qr=lambda x: None)
    assert ok is False
    assert status == "failed"


@pytest.mark.asyncio
async def test_run_login_invalid_account(monkeypatch):
    ok, status = await r.run_login("douyin", "../bad", on_qr=lambda x: None)
    assert ok is False
    assert status == "failed"

import asyncio

import pytest

from app.providers.publisher import sau_runner as r


class FakeProc:
    def __init__(self, returncode=0, out=b"ok", err=b""):
        self.returncode = returncode
        self._out = out
        self._err = err
        self.pid = 4321
        self.killed = False

    async def communicate(self):
        return self._out, self._err

    def kill(self):
        self.killed = True


def _patch_exec(monkeypatch, proc, capture):
    async def fake_exec(*args, **kwargs):
        capture["args"] = args
        capture["env"] = kwargs.get("env")
        return proc
    monkeypatch.setattr(r.asyncio, "create_subprocess_exec", fake_exec)


@pytest.mark.asyncio
async def test_run_upload_success_builds_correct_argv(monkeypatch):
    monkeypatch.setattr(r, "resolve_sau", lambda: "/bin/sau")
    cap = {}
    _patch_exec(monkeypatch, FakeProc(returncode=0), cap)
    ok, msg = await r.run_upload("douyin", "acct1", "v.mp4", "标题", "简介", ["a,b", "c"])
    assert ok is True
    argv = cap["args"]
    assert argv[:5] == ("/bin/sau", "douyin", "upload-video", "--account", "acct1")
    assert "--file" in argv and "v.mp4" in argv
    assert "--tags" in argv and "a,b,c" in argv
    assert "--headless" in argv
    assert cap["env"]["PYTHONIOENCODING"] == "utf-8"


@pytest.mark.asyncio
async def test_run_upload_not_installed(monkeypatch):
    monkeypatch.setattr(r, "resolve_sau", lambda: None)
    ok, msg = await r.run_upload("douyin", "acct1", "v.mp4", "t", "d", [])
    assert ok is False
    assert "未安装" in msg


@pytest.mark.asyncio
async def test_run_upload_invalid_account(monkeypatch):
    monkeypatch.setattr(r, "resolve_sau", lambda: "/bin/sau")
    ok, msg = await r.run_upload("douyin", "../bad", "v.mp4", "t", "d", [])
    assert ok is False
    assert "账号" in msg


@pytest.mark.asyncio
async def test_run_upload_failure_maps_error(monkeypatch):
    monkeypatch.setattr(r, "resolve_sau", lambda: "/bin/sau")
    cap = {}
    _patch_exec(monkeypatch, FakeProc(returncode=1, err=b"cookie is missing or expired"), cap)
    ok, msg = await r.run_upload("douyin", "acct1", "v.mp4", "t", "d", [])
    assert ok is False
    assert "登录态失效" in msg


@pytest.mark.asyncio
async def test_run_upload_timeout_kills(monkeypatch):
    monkeypatch.setattr(r, "resolve_sau", lambda: "/bin/sau")
    proc = FakeProc()

    async def fake_exec(*a, **k):
        return proc
    monkeypatch.setattr(r.asyncio, "create_subprocess_exec", fake_exec)

    async def fake_wait_for(coro, timeout):
        coro.close()
        raise asyncio.TimeoutError
    monkeypatch.setattr(r.asyncio, "wait_for", fake_wait_for)
    killed = {}
    monkeypatch.setattr(r, "kill_process_tree", lambda p: killed.setdefault("k", True))

    ok, msg = await r.run_upload("douyin", "acct1", "v.mp4", "t", "d", [])
    assert ok is False
    assert "超时" in msg
    assert killed.get("k") is True

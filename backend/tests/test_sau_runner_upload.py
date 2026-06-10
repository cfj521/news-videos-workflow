import subprocess

import pytest

from app.providers.publisher import sau_runner as r


class FakeProc:
    """假阻塞子进程：communicate 返回 (out, err) 或抛 TimeoutExpired。"""

    def __init__(self, returncode=0, out=b"ok", err=b"", timeout=False):
        self.returncode = returncode
        self._out = out
        self._err = err
        self.pid = 4321
        self._timeout = timeout
        self._calls = 0

    def communicate(self, timeout=None):
        self._calls += 1
        if self._timeout and self._calls == 1:
            raise subprocess.TimeoutExpired(cmd="sau", timeout=timeout)
        return self._out, self._err

    def kill(self):
        pass


def _patch_popen(monkeypatch, proc, capture):
    def fake_popen(argv, **kwargs):
        capture["argv"] = argv
        capture["env"] = kwargs.get("env")
        return proc
    monkeypatch.setattr(r.subprocess, "Popen", fake_popen)


@pytest.mark.asyncio
async def test_run_upload_success_builds_correct_argv(monkeypatch):
    monkeypatch.setattr(r, "resolve_sau", lambda: "/bin/sau")
    cap = {}
    _patch_popen(monkeypatch, FakeProc(returncode=0), cap)
    ok, msg = await r.run_upload("douyin", "acct1", "v.mp4", "标题", "简介", ["a,b", "c"])
    assert ok is True
    argv = cap["argv"]
    assert argv[:5] == ["/bin/sau", "douyin", "upload-video", "--account", "acct1"]
    assert "--file" in argv and "v.mp4" in argv
    assert "--tags" in argv and "a,b,c" in argv  # 清洗后逗号 join
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
    _patch_popen(monkeypatch, FakeProc(returncode=1, err=b"cookie is missing or expired"), cap)
    ok, msg = await r.run_upload("douyin", "acct1", "v.mp4", "t", "d", [])
    assert ok is False
    assert "登录态失效" in msg


@pytest.mark.asyncio
async def test_run_upload_timeout_kills(monkeypatch):
    monkeypatch.setattr(r, "resolve_sau", lambda: "/bin/sau")
    cap = {}
    _patch_popen(monkeypatch, FakeProc(timeout=True), cap)
    killed = {}
    monkeypatch.setattr(r, "kill_process_tree", lambda p: killed.setdefault("k", True))
    ok, msg = await r.run_upload("douyin", "acct1", "v.mp4", "t", "d", [])
    assert ok is False
    assert "超时" in msg
    assert killed.get("k") is True

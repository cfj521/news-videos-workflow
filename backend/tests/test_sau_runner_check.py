import pytest

from app.providers.publisher import sau_runner as r


@pytest.mark.asyncio
async def test_check_shallow_uses_cookie_file(monkeypatch, tmp_path):
    f = tmp_path / "douyin_acct1.json"
    monkeypatch.setattr(r, "cookie_path", lambda p, a: f)
    assert await r.check_login("douyin", "acct1") is False
    f.write_text("{}")
    assert await r.check_login("douyin", "acct1") is True


@pytest.mark.asyncio
async def test_check_invalid_account_false(monkeypatch):
    assert await r.check_login("douyin", "../bad") is False


@pytest.mark.asyncio
async def test_check_deep_uses_exit_code(monkeypatch):
    monkeypatch.setattr(r, "resolve_sau", lambda: "/bin/sau")

    class P:
        returncode = 0
        pid = 1

        async def communicate(self):
            return b"valid", b""

    async def fake_exec(*a, **k):
        return P()
    monkeypatch.setattr(r.asyncio, "create_subprocess_exec", fake_exec)
    assert await r.check_login("douyin", "acct1", deep=True) is True

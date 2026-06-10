import pytest

from app.providers.publisher.douyin import DouyinPublisher
from app.providers.publisher.kuaishou import KuaishouPublisher


@pytest.mark.asyncio
async def test_no_account():
    res = await DouyinPublisher(account="").publish("v.mp4", None, "t", "d", ["x"])
    assert res.status == "failed" and "未配置账号" in res.error_message


@pytest.mark.asyncio
async def test_not_logged_in(monkeypatch, tmp_path):
    from app.providers.publisher import sau_runner
    monkeypatch.setattr(sau_runner, "cookie_path", lambda p, a: tmp_path / "missing.json")
    res = await DouyinPublisher(account="acct1").publish("v.mp4", None, "t", "d", [])
    assert res.status == "failed" and "未登录" in res.error_message


@pytest.mark.asyncio
async def test_success(monkeypatch, tmp_path):
    from app.providers.publisher import sau_runner
    f = tmp_path / "douyin_acct1.json"; f.write_text("{}")
    monkeypatch.setattr(sau_runner, "cookie_path", lambda p, a: f)

    async def ok(*a, **k):
        return True, "submitted"
    monkeypatch.setattr(sau_runner, "run_upload", ok)
    res = await DouyinPublisher(account="acct1").publish("v.mp4", None, "标题", "简介", ["a"])
    assert res.status == "success"
    assert res.platform == "douyin"


@pytest.mark.asyncio
async def test_failure_propagates_message(monkeypatch, tmp_path):
    from app.providers.publisher import sau_runner
    f = tmp_path / "kuaishou_acct1.json"; f.write_text("{}")
    monkeypatch.setattr(sau_runner, "cookie_path", lambda p, a: f)

    async def fail(*a, **k):
        return False, "登录态失效，请重新扫码登录"
    monkeypatch.setattr(sau_runner, "run_upload", fail)
    res = await KuaishouPublisher(account="acct1").publish("v.mp4", None, "t", "d", [])
    assert res.status == "failed" and "登录态失效" in res.error_message
    assert res.platform == "kuaishou"

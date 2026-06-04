import json
from types import SimpleNamespace

import pytest

from app.providers.publisher import build_publishers
from app.providers.publisher.bilibili import BilibiliPublisher


def _target(platform, enabled=True, name=None, **cfg):
    return SimpleNamespace(platform=platform, enabled=enabled, name=name or platform,
                           config_json=json.dumps(cfg) if cfg else None)


def test_cookie_uses_real_names_and_drops_empty():
    # 只给必填两项：cookie 用 B 站真实大小写名，且不含空值项
    pub = BilibiliPublisher(sessdata="s", bili_jct="j")
    assert pub._cookie == {"SESSDATA": "s", "bili_jct": "j"}


def test_biliup_cookie_nested_format():
    # biliup 1.2.0 的 login_by_cookies 要 {'cookie_info': {'cookies': [{name,value}]}}
    pub = BilibiliPublisher(sessdata="s", bili_jct="j", dede_user_id="9")
    nested = pub._biliup_cookie()
    cookies = nested["cookie_info"]["cookies"]
    assert {"name": "SESSDATA", "value": "s"} in cookies
    assert {"name": "bili_jct", "value": "j"} in cookies
    assert {"name": "DedeUserID", "value": "9"} in cookies


def test_cookie_full_set():
    pub = BilibiliPublisher(sessdata="s", bili_jct="j", dede_user_id="123",
                            buvid3="b3", buvid4="b4", ac_time_value="ac")
    assert pub._cookie == {
        "SESSDATA": "s", "bili_jct": "j", "DedeUserID": "123",
        "buvid3": "b3", "buvid4": "b4", "ac_time_value": "ac",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs,missing", [
    ({}, "SESSDATA"),
    ({"sessdata": "s"}, "bili_jct"),
    ({"bili_jct": "j"}, "SESSDATA"),
])
async def test_publish_rejects_missing_required(kwargs, missing):
    pub = BilibiliPublisher(**kwargs)
    res = await pub.publish(video_path="v.mp4", thumbnail_path=None, title="t", description="d", tags=["x"])
    assert res.status == "failed"
    assert missing in res.error_message


def test_extract_bvid_handles_str_and_dict():
    assert BilibiliPublisher._extract_bvid("BV1xx") == "BV1xx"
    assert BilibiliPublisher._extract_bvid({"data": {"bvid": "BV1yy"}}) == "BV1yy"
    assert BilibiliPublisher._extract_bvid({"bvid": "BV1zz"}) == "BV1zz"
    assert BilibiliPublisher._extract_bvid(None) == ""


def test_build_publishers_bilibili_from_target():
    t = _target("bilibili", sessdata="s", bili_jct="j", dede_user_id="9", buvid3="b3", tid="122")
    pubs = build_publishers([t])
    # 新接口：返回 [(target, adapter)]，以账号为单位
    assert len(pubs) == 1
    target, b = pubs[0]
    assert target is t
    assert isinstance(b, BilibiliPublisher)
    assert b._cookie["SESSDATA"] == "s" and b._cookie["DedeUserID"] == "9"
    assert b._tid == 122  # 字符串 tid 容错转 int


def test_build_publishers_keeps_multiple_accounts_same_platform():
    # 同一平台多账号不再互相覆盖，各自保留
    t1 = _target("bilibili", name="主号", sessdata="s1", bili_jct="j1")
    t2 = _target("bilibili", name="小号", sessdata="s2", bili_jct="j2")
    pubs = build_publishers([t1, t2])
    assert [t.name for t, _ in pubs] == ["主号", "小号"]


def test_build_publishers_skips_disabled_and_unknown():
    pubs = build_publishers([
        _target("bilibili", enabled=False, sessdata="s", bili_jct="j"),
        _target("weibo", foo="x"),
    ])
    assert pubs == []

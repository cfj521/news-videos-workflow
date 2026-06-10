from pathlib import Path

from app.providers.publisher import sau_runner as r


def test_safe_account_accepts_valid():
    assert r.safe_account("acct_1-x") == "acct_1-x"


def test_safe_account_rejects_invalid():
    assert r.safe_account("../etc") == ""
    assert r.safe_account("大号") == ""
    assert r.safe_account("Has Space") == ""
    assert r.safe_account("") == ""


def test_cookie_path_under_publish_cookies():
    p = r.cookie_path("douyin", "acct1")
    assert p.name == "douyin_acct1.json"
    assert p.parent.name == "cookies"
    assert p.parent.parent.name == "publish_cookies"


def test_sanitize_tags_splits_and_filters():
    out = r.sanitize_tags(["a,b", " c ", "-bad", "", "#tag", "d", "e", "f", "g"])
    assert out == ["a", "b", "c", "tag", "d"]


def test_sanitize_text_strips_leading_dash_and_space():
    assert r.sanitize_text("  -hello ") == "hello"
    assert r.sanitize_text("normal") == "normal"

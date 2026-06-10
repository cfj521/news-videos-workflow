import json

from app.providers.publisher import sau_login_worker as w


def test_emit_line_is_json(capsys):
    w._emit({"qr": "data:image/png;base64,AAA"})
    out = capsys.readouterr().out.strip()
    assert json.loads(out) == {"qr": "data:image/png;base64,AAA"}


def test_pick_setup_known_platforms():
    assert w._setup_name("douyin") == "douyin_setup"
    assert w._setup_name("kuaishou") == "ks_setup"


def test_pick_setup_unknown_raises():
    import pytest
    with pytest.raises(ValueError):
        w._setup_name("weibo")

from app.providers.publisher import sau_runner as r


def test_ensure_cookies_dir_creates_nested(monkeypatch, tmp_path):
    target = tmp_path / "publish_cookies" / "cookies"
    monkeypatch.setattr(r, "_COOKIES_DIR", target)
    assert not target.exists()
    r.ensure_cookies_dir()
    assert target.is_dir()
    # 幂等
    r.ensure_cookies_dir()
    assert target.is_dir()

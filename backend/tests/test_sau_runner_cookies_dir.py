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


def test_ensure_sau_runtime_copies_stealth(monkeypatch, tmp_path):
    # BASE_DIR 被指向 publish_cookies 后，需把 SAU 包内静态资源 stealth.min.js 复制到 BASE_DIR/utils
    cookies = tmp_path / "publish_cookies" / "cookies"
    monkeypatch.setattr(r, "_COOKIES_DIR", cookies)
    src_dir = tmp_path / "pkg_utils"
    src_dir.mkdir()
    (src_dir / "stealth.min.js").write_text("JS")
    monkeypatch.setattr(r, "_sau_utils_dir", lambda: src_dir)

    r.ensure_sau_runtime()
    dst = tmp_path / "publish_cookies" / "utils" / "stealth.min.js"
    assert dst.read_text() == "JS"
    assert cookies.is_dir()


def test_ensure_sau_runtime_tolerates_missing_package(monkeypatch, tmp_path):
    # 找不到 SAU utils 包时不报错（仅跳过资源复制）
    cookies = tmp_path / "publish_cookies" / "cookies"
    monkeypatch.setattr(r, "_COOKIES_DIR", cookies)
    monkeypatch.setattr(r, "_sau_utils_dir", lambda: None)
    r.ensure_sau_runtime()  # 不抛
    assert cookies.is_dir()

from pathlib import Path


def test_base_dir_points_to_repo_publish_cookies():
    from app.providers.publisher.sau_conf import conf
    assert isinstance(conf.BASE_DIR, Path)
    assert conf.BASE_DIR.name == "publish_cookies"
    assert (conf.BASE_DIR.parent / "backend").is_dir()


def test_conf_has_all_names_sau_imports():
    from app.providers.publisher.sau_conf import conf
    for name in ("BASE_DIR", "XHS_SERVER", "LOCAL_CHROME_PATH", "LOCAL_CHROME_HEADLESS", "DEBUG_MODE"):
        assert hasattr(conf, name), f"conf 缺少 {name}"

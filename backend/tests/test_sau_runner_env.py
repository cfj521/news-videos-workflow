from app.providers.publisher import sau_runner as r


def test_resolve_sau_uses_which(monkeypatch):
    monkeypatch.setattr(r.shutil, "which", lambda name: "/fake/bin/sau" if name == "sau" else None)
    assert r.resolve_sau() == "/fake/bin/sau"


def test_resolve_sau_none_when_missing(monkeypatch):
    monkeypatch.setattr(r.shutil, "which", lambda name: None)
    monkeypatch.setattr(r.Path, "exists", lambda self: False)
    assert r.resolve_sau() is None


def test_subprocess_env_injects_conf_pythonpath():
    env = r.subprocess_env()
    assert str(r._SAU_CONF_DIR) in env["PYTHONPATH"]
    assert env["PYTHONIOENCODING"] == "utf-8"

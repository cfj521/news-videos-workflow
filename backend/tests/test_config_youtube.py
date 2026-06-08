import app.config as cfgmod
import app.store.targets_store as ts
from app.config import Settings, YouTubeCfg


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(ts, "TARGETS_PATH", tmp_path / "publish_targets.yaml")
    import app.store.providers_store as ps
    monkeypatch.setattr(ps, "MODEL_PROVIDERS_PATH", tmp_path / "model_providers.yaml")
    cfgmod._settings = None


def test_save_settings_writes_youtube_to_targets_store(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    s = Settings()
    s.youtube = YouTubeCfg(client_id="cid", client_secret="sec")
    cfgmod.save_settings(s)
    import yaml
    raw = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8")) or {}
    assert "youtube" not in raw
    assert ts.load_youtube_client() == {"client_id": "cid", "client_secret": "sec"}


def test_get_settings_injects_youtube_from_store(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    ts.save_youtube_client({"client_id": "from_store", "client_secret": "s2"})
    cfgmod._settings = None
    s = cfgmod.get_settings()
    assert s.youtube.client_id == "from_store" and s.youtube.client_secret == "s2"

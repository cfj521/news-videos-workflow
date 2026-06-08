import app.config as cfgmod
import app.store.sources_store as ss
from app.config import CollectorsCfg, Settings


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(ss, "NEWS_SOURCES_PATH", tmp_path / "news_sources.yaml")
    import app.store.providers_store as ps
    import app.store.targets_store as ts
    monkeypatch.setattr(ps, "MODEL_PROVIDERS_PATH", tmp_path / "model_providers.yaml")
    monkeypatch.setattr(ts, "TARGETS_PATH", tmp_path / "publish_targets.yaml")
    cfgmod._settings = None


def test_save_settings_writes_collectors_to_store(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    s = Settings()
    s.collectors = CollectorsCfg(tavily_key="tk", brave_key="", serper_key="")
    cfgmod.save_settings(s)
    import yaml
    raw = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8")) or {}
    assert "collectors" not in raw
    assert ss.load_search_keys()["tavily_key"] == "tk"


def test_get_settings_injects_collectors_from_store(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    ss.save_search_keys({"tavily_key": "from_store", "brave_key": "", "serper_key": ""})
    cfgmod._settings = None
    s = cfgmod.get_settings()
    assert s.collectors.tavily_key == "from_store"

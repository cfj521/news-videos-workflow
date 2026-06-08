from pathlib import Path

import app.config as cfgmod
import app.store.providers_store as ps
from app.config import ProviderCreds, Settings


def _isolate(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(ps, "MODEL_PROVIDERS_PATH", tmp_path / "model_providers.yaml")
    cfgmod._settings = None  # 清缓存


def test_save_settings_writes_providers_to_store_not_config(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    s = Settings()
    s.providers = {"openai": ProviderCreds(api_key="sk-z")}
    cfgmod.save_settings(s)
    import yaml
    raw_cfg = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8")) or {}
    assert "providers" not in raw_cfg
    assert ps.load_providers()["openai"].api_key == "sk-z"


def test_get_settings_injects_providers_from_store(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    ps.save_providers({"openai": ProviderCreds(api_key="sk-from-store")})
    cfgmod._settings = None
    s = cfgmod.get_settings()
    assert s.provider_creds("openai").api_key == "sk-from-store"

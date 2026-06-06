"""Task 12: openai 订阅模式使用 TTS 时应明确报错，而非用空 api_key 走到 openai 失败。"""
import pytest


def test_openai_subscription_tts_raises(tmp_path, monkeypatch):
    """openai 订阅模式 + tts_provider=openai → 应抛出 ValueError 含"订阅"。"""
    from app import config
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.yaml")
    cfg = config.get_settings()
    # 确保 openai provider 存在
    from app.config import ProviderCreds
    cfg.providers.setdefault("openai", ProviderCreds())
    cfg.providers["openai"].auth_mode = "subscription"
    cfg.pipeline.tts_provider = "openai"

    from app.providers.tts import build_tts_provider
    with pytest.raises(ValueError, match="订阅"):
        build_tts_provider(cfg)


def test_openai_apikey_tts_ok(tmp_path, monkeypatch):
    """api_key 模式 + tts_provider=openai → 守卫不介入，能正常返回 provider 实例。"""
    from app import config
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.yaml")
    cfg = config.get_settings()
    from app.config import ProviderCreds
    cfg.providers.setdefault("openai", ProviderCreds())
    cfg.providers["openai"].auth_mode = "api_key"
    cfg.providers["openai"].api_key = "sk-test"
    cfg.pipeline.tts_provider = "openai"

    from app.providers.tts import build_tts_provider
    # 不应抛 ValueError("订阅...")；OpenAITTSProvider.__init__ 只建 client，不需网络
    prov = build_tts_provider(cfg)
    assert prov is not None


def test_edge_tts_unaffected(tmp_path, monkeypatch):
    """edge-tts 路径与守卫无关，应正常返回 EdgeTTSProvider 实例。"""
    from app import config
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.yaml")
    cfg = config.get_settings()
    cfg.pipeline.tts_provider = "edge-tts"

    from app.providers.tts import build_tts_provider
    prov = build_tts_provider(cfg)
    assert prov is not None

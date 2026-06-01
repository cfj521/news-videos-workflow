from app import config
from app.providers.image import build_image_provider
from app.providers.image.comfyui_image import ComfyUIImageProvider
from app.providers.image.openai_image import OpenAIImageProvider


def test_factory_picks_comfyui(monkeypatch):
    monkeypatch.setattr(config, "_settings", config.Settings(
        image={"provider": "comfyui", "base_url": "http://127.0.0.1:8188", "model": "qwen", "api_key": ""}))
    p = build_image_provider(config.get_settings())
    assert isinstance(p, ComfyUIImageProvider)


def test_factory_picks_commercial_by_default(monkeypatch):
    monkeypatch.setattr(config, "_settings", config.Settings(
        image={"provider": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-image-1", "api_key": "k"}))
    p = build_image_provider(config.get_settings())
    assert isinstance(p, OpenAIImageProvider)


def test_comfyui_cfg_defaults():
    s = config.Settings()
    assert s.comfyui.workflows_dir == "comfyui/workflows/api"
    assert s.comfyui.default_negative

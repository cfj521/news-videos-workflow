from app import config
from app.providers.image import build_image_provider
from app.providers.image.comfyui_image import ComfyUIImageProvider
from app.providers.image.openai_image import OpenAIImageProvider


def test_factory_picks_comfyui(monkeypatch):
    monkeypatch.setattr(config, "_settings", config.Settings(
        pipeline={"image_provider": "comfyui", "image_model": "qwen"}))
    p = build_image_provider(config.get_settings())
    assert isinstance(p, ComfyUIImageProvider)


def test_factory_picks_commercial(monkeypatch):
    monkeypatch.setattr(config, "_settings", config.Settings(
        providers={"openai": {"base_url": "https://api.openai.com/v1", "api_key": "k"}},
        pipeline={"image_provider": "openai", "image_model": "gpt-image-1"}))
    p = build_image_provider(config.get_settings())
    assert isinstance(p, OpenAIImageProvider)


def test_comfyui_cfg_defaults():
    s = config.Settings()
    assert s.comfyui.workflows_dir == "comfyui/workflows/api"
    assert s.comfyui.default_negative

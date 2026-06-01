def build_image_provider(cfg):
    """按 cfg.image.provider 选商用或 ComfyUI 图片 provider。runner Stage3 与 api regen 共用。"""
    from app.providers.image.openai_image import OpenAIImageProvider
    if cfg.image.provider == "comfyui":
        from app.providers.image.comfyui_image import ComfyUIImageProvider
        return ComfyUIImageProvider(
            server_url=cfg.image.base_url or "http://127.0.0.1:8188",
            workflow=cfg.image.model or "z_image",
            workflows_dir=cfg.comfyui.workflows_dir,
            negative=cfg.comfyui.default_negative,
        )
    return OpenAIImageProvider(api_key=cfg.image.api_key, model=cfg.image.model, base_url=cfg.image.base_url)

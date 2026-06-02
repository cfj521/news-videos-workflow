def build_image_provider(cfg):
    """按 cfg.image.provider 选商用或 ComfyUI 图片 provider。runner Stage3 与 api regen 共用。"""
    from app.providers.image.openai_image import OpenAIImageProvider
    if cfg.image.provider == "comfyui":
        from app.providers.image.comfyui_image import ComfyUIImageProvider
        c = cfg.comfyui
        params = c.image_params.get(c.image_workflow)
        return ComfyUIImageProvider(
            server_url=c.server_url,          # 图片与视频共用 comfyui.server_url
            workflow=c.image_workflow,        # workflow 选择移到 comfyui 组
            workflows_dir=c.workflows_dir,
            negative=c.default_negative,
            steps=params.steps if params else 9,
            cfg=params.cfg if params else 1.0,
        )
    return OpenAIImageProvider(api_key=cfg.image.api_key, model=cfg.image.model, base_url=cfg.image.base_url)

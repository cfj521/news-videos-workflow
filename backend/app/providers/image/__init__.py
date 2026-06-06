def build_image_provider(cfg):
    """按 pipeline 选型（image）选商用或 ComfyUI 图片 provider。runner Stage3 与 api regen 共用。"""
    from app.config import resolve
    provider, base_url, api_key, model = resolve(cfg, "image")
    if provider == "comfyui":
        from app.providers.image.comfyui_image import ComfyUIImageProvider
        c = cfg.comfyui
        workflow = model or "z_image_turbo"     # comfyui 时 image_model 即图片 workflow key
        params = c.image_params.get(workflow)
        return ComfyUIImageProvider(
            server_url=c.server_url,          # 图片与视频共用 comfyui.server_url
            workflow=workflow,
            workflows_dir=c.workflows_dir,
            negative=c.default_negative,
            steps=params.steps if params else 9,
            cfg=params.cfg if params else 1.0,
        )
    from app.providers.image.openai_image import OpenAIImageProvider
    if provider == "openai" and cfg.provider_creds("openai").auth_mode == "subscription":
        return OpenAIImageProvider(api_key="", model="gpt-5.5", subscription=True)
    return OpenAIImageProvider(api_key=api_key, model=model, base_url=base_url)

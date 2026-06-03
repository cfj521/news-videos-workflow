def build_video_provider(cfg, mode: str = "i2v"):
    """按 cfg.comfyui 选中的视频 workflow 构造 ComfyUI 视频 provider。

    从 cfg.comfyui.video_params[选中 workflow] 取 steps/cfg；runner Stage5 与 api 重渲共用，避免逻辑漂移。
    mode="i2v"（默认，流水线用）或 "t2v"（文生视频，需对应 t2v 工作流）。
    """
    from app.providers.video.comfyui_video import ComfyUIVideoProvider

    c = cfg.comfyui
    params = c.video_params.get(c.video_workflow)
    steps = params.steps if params else 20
    cfg_val = params.cfg if params else 5.0
    return ComfyUIVideoProvider(
        server_url=c.server_url, workflow=c.video_workflow,
        workflows_dir=c.workflows_dir, fps=c.video_fps,
        negative=c.default_negative, steps=steps, cfg=cfg_val, mode=mode,
    )

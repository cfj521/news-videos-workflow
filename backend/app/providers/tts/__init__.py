"""语音合成 provider 工厂：按流水线选型(tts_provider)返回对应实现，凭证与文本/图片共用供应商库。"""
from app.providers.base import TTSProvider


def build_tts_provider(cfg, provider: str = "", model: str = "", voice: str = "") -> TTSProvider:
    """按 provider(edge-tts|openai|dashscope) 构建语音 provider。

    缺省取流水线选型；openai/dashscope 的 base_url/api_key 取自 providers 库（与文本/图片共用）。
    """
    pipe = cfg.pipeline
    provider = provider or pipe.tts_provider or "edge-tts"
    model = model or pipe.tts_model
    voice = voice or pipe.tts_voice

    if provider == "openai":
        from app.providers.tts.openai_tts import OpenAITTSProvider
        creds = cfg.provider_creds("openai")
        return OpenAITTSProvider(api_key=creds.api_key, model=model or "gpt-4o-mini-tts",
                                 base_url=creds.base_url, default_voice=voice or "alloy")
    if provider == "dashscope":
        from app.providers.tts.dashscope_tts import DashScopeTTSProvider
        creds = cfg.provider_creds("dashscope")
        return DashScopeTTSProvider(api_key=creds.api_key, model=model or "qwen3-tts-flash",
                                    default_voice=voice or "Cherry")
    # 默认 edge-tts（微软免费）
    from app.providers.tts.edge_tts_provider import EdgeTTSProvider
    return EdgeTTSProvider(default_voice=voice or "zh-CN-XiaoxiaoNeural")

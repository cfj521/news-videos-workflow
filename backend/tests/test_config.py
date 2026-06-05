def test_config_loads_defaults():
    from app.config import Settings

    settings = Settings()
    assert settings.pipeline.default_time_range == "7d"
    assert settings.pipeline.default_max_articles == 5
    assert settings.pipeline.default_video_route == "comfyui"
    assert settings.pipeline.default_language == "zh"
    assert settings.DATABASE_URL == "sqlite:///../data/news_videos.db"
    # 选型与供应商参数库（新结构）
    assert settings.pipeline.script_provider == "claude"
    assert settings.pipeline.script_model == "claude-sonnet-4-6"
    assert settings.pipeline.tts_provider == "edge-tts"
    assert settings.pipeline.tts_voice == "zh-CN-XiaoxiaoNeural"
    assert "openai" in settings.providers
    assert settings.providers["claude"].base_url == "https://api.anthropic.com"


def test_config_from_dict():
    from app.config import Settings

    settings = Settings(
        providers={"openai": {"base_url": "https://api.openai.com/v1", "api_key": "test"}},
        pipeline={"script_provider": "openai", "script_model": "gpt-4.1",
                  "image_provider": "openai", "image_model": "dall-e-3"},
    )
    assert settings.pipeline.script_provider == "openai"
    assert settings.pipeline.script_model == "gpt-4.1"
    assert settings.pipeline.image_model == "dall-e-3"
    assert settings.providers["openai"].api_key == "test"


def test_data_dir_creation(tmp_path):
    from app.config import Settings

    settings = Settings(
        infra={"database_url": "sqlite:///test.db", "data_dir": str(tmp_path / "data")},
    )
    settings.ensure_data_dirs()
    assert (tmp_path / "data" / "runs").is_dir()
    assert (tmp_path / "data" / "history").is_dir()


def test_pipeline_cfg_has_no_legacy_toggles():
    from app.config import PipelineCfg
    cfg = PipelineCfg()
    assert not hasattr(cfg, "enable_dedup")
    assert not hasattr(cfg, "enable_scoring")
    assert not hasattr(cfg, "enable_summary")
    assert hasattr(cfg, "dedup_lookback")  # 保留


def test_vision_cfg_defaults():
    from app.config import Settings
    s = Settings()
    assert s.pipeline.vision_provider == "openai"
    assert s.pipeline.vision_model == "gpt-4o"
    assert s.providers["openai"].base_url == "https://api.openai.com/v1"


def test_migrate_legacy_config():
    """旧结构（每用途内嵌 provider）应迁移为 providers 库 + pipeline 选型。"""
    from app.config import Settings, _migrate_legacy

    raw = {
        "text": {"provider": "claude", "base_url": "https://api.anthropic.com", "model": "claude-x", "api_key": "k-text"},
        "image": {"provider": "comfyui", "model": "gpt-image-1"},
        "tts": {"provider": "edge-tts", "voice": "en-US-JennyNeural"},
        "summary": {"provider": "openai", "model": "gpt-5", "api_key": "k-sum", "max_length": 200},
        "comfyui": {"image_workflow": "qwen", "video_workflow": "wan14b", "video_fps": 30},
    }
    s = Settings(**_migrate_legacy(raw))
    assert s.pipeline.script_provider == "claude"
    assert s.pipeline.script_model == "claude-x"
    assert s.providers["claude"].api_key == "k-text"
    assert s.pipeline.image_provider == "comfyui"
    assert s.pipeline.image_model == "qwen"          # comfyui 时取 image_workflow
    assert s.pipeline.tts_voice == "en-US-JennyNeural"
    assert s.pipeline.summary_max_length == 200
    assert s.providers["openai"].api_key == "k-sum"
    assert s.pipeline.video_model == "wan14b"
    assert s.pipeline.video_fps == 30

def test_config_loads_defaults():
    from app.config import Settings

    settings = Settings()
    assert settings.pipeline.default_time_range == "7d"
    assert settings.pipeline.default_max_articles == 5
    assert settings.pipeline.default_video_route == "hyperframes"
    assert settings.pipeline.default_language == "zh"
    assert settings.DATABASE_URL == "sqlite:///../data/news_videos.db"
    assert settings.text.provider == "claude"
    assert settings.text.model == "claude-sonnet-4-6"
    assert settings.image.provider == "openai"
    assert settings.image.model == "gpt-image-1"
    assert settings.tts.provider == "edge-tts"
    assert settings.tts.voice == "zh-CN-XiaoxiaoNeural"


def test_config_from_dict():
    from app.config import Settings

    settings = Settings(
        text={"provider": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-4.1", "api_key": "test"},
        image={"provider": "openai", "base_url": "", "model": "dall-e-3", "api_key": "test"},
    )
    assert settings.text.provider == "openai"
    assert settings.text.model == "gpt-4.1"
    assert settings.image.model == "dall-e-3"


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
    assert s.vision.provider == "openai"
    assert s.vision.model == "gpt-4o"
    assert s.vision.base_url == "https://api.openai.com/v1"

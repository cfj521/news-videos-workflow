def test_config_loads_defaults():
    from app.config import Settings
    settings = Settings(
        ANTHROPIC_API_KEY="test-key",
        OPENAI_API_KEY="test-key",
    )
    assert settings.DEFAULT_TIME_RANGE == "7d"
    assert settings.DEFAULT_MAX_ARTICLES == 5
    assert settings.DEFAULT_VIDEO_ROUTE == "hyperframes"
    assert settings.DEFAULT_LANGUAGE == "zh"
    assert settings.DATABASE_URL == "sqlite:///./data/news_videos.db"


def test_data_dir_creation(tmp_path):
    from app.config import Settings
    settings = Settings(
        ANTHROPIC_API_KEY="test-key",
        OPENAI_API_KEY="test-key",
        DATA_DIR=str(tmp_path / "data"),
    )
    settings.ensure_data_dirs()
    assert (tmp_path / "data" / "runs").is_dir()
    assert (tmp_path / "data" / "history").is_dir()

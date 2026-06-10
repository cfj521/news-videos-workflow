def test_config_loads_defaults():
    from app.config import Settings

    settings = Settings()
    assert settings.pipeline.default_time_range == "7d"
    assert settings.pipeline.default_max_articles == 5
    assert settings.pipeline.default_video_route == "comfyui"
    assert settings.pipeline.default_language == "zh"
    assert settings.DATABASE_URL == "sqlite:///../data/news_videos.db"
    # 选型与供应商参数库（新结构）
    assert settings.pipeline.script_provider == "openai"
    assert settings.pipeline.script_model == "gpt-5.5"
    assert settings.pipeline.tts_provider == "edge-tts"
    assert settings.pipeline.tts_voice == "zh-CN-XiaoxiaoNeural"
    assert "openai" in settings.providers
    assert "claude" not in settings.providers  # anthropic 已移除
    assert settings.providers["openai"].base_url == "https://api.openai.com/v1"


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
        "text": {"provider": "dashscope", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-x", "api_key": "k-text"},
        "image": {"provider": "comfyui", "model": "gpt-image-1"},
        "tts": {"provider": "edge-tts", "voice": "en-US-JennyNeural"},
        "summary": {"provider": "openai", "model": "gpt-5", "api_key": "k-sum", "max_length": 200},
        "comfyui": {"image_workflow": "qwen", "video_workflow": "wan14b", "video_fps": 30},
    }
    s = Settings(**_migrate_legacy(raw))
    assert s.pipeline.script_provider == "dashscope"
    assert s.pipeline.script_model == "qwen-x"
    assert s.providers["dashscope"].api_key == "k-text"
    assert s.pipeline.image_provider == "comfyui"
    assert s.pipeline.image_model == "qwen"          # comfyui 时取 image_workflow
    assert s.pipeline.tts_voice == "en-US-JennyNeural"
    assert s.pipeline.summary_max_length == 200
    assert s.providers["openai"].api_key == "k-sum"
    assert s.pipeline.video_model == "wan14b"
    assert s.pipeline.video_fps == 30


def test_overlay_defaults():
    from app.config import Settings
    s = Settings()
    assert s.overlay.enabled is True
    assert s.overlay.font_file.endswith("msyh.ttc")
    assert s.overlay.font_size_ratio == 0.035
    assert s.overlay.bg_opacity == 0.45
    assert s.overlay.color == "#FFFFFF"


def test_pipeline_cfg_has_no_aihot_top_n():
    from app.config import PipelineCfg
    assert not hasattr(PipelineCfg(), "aihot_top_n")


def test_scoring_cfg_defaults():
    from app.config import Settings
    s = Settings()
    assert s.scoring.w_final_llm == 0.6 and s.scoring.w_final_rule == 0.4
    assert s.scoring.concurrency == 5 and s.scoring.llm_candidate_cap == 25
    assert s.scoring.min_score == 0.35
    assert s.scoring.fresh_full_days == 7 and s.scoring.fresh_floor_days == 30
    assert s.scoring.fresh_week_end == 0.9 and s.scoring.fresh_floor == 0.3


def test_scoring_cfg_validation_rejects_bad_curve():
    from app.config import ScoringCfg
    c = ScoringCfg(fresh_floor=0.95, fresh_week_end=0.9)
    assert c.fresh_floor <= c.fresh_week_end

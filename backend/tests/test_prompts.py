from app.config import Settings


def test_settings_has_empty_prompts_by_default():
    s = Settings()
    assert s.prompts.roundup_article == ""
    assert s.prompts.news_scoring == ""
    for k in ("roundup_article", "daily_batch", "summary_meta", "weekly_digest",
              "image_regen", "article_summary", "news_scoring"):
        assert hasattr(s.prompts, k)


def test_settings_prompts_roundtrip():
    s = Settings(prompts={"roundup_article": "自定义"})
    assert s.prompts.roundup_article == "自定义"
    assert s.model_dump()["prompts"]["roundup_article"] == "自定义"

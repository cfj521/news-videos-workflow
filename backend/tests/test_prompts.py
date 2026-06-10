import pytest
from app.config import Settings


def test_settings_has_empty_prompts_by_default():
    s = Settings()
    assert s.prompts.roundup_article == ""
    assert s.prompts.news_scoring == ""
    for k in ("roundup_article", "summary_meta", "weekly_digest",
              "image_regen", "article_summary", "news_scoring"):
        assert hasattr(s.prompts, k)


def test_settings_prompts_roundtrip():
    s = Settings(prompts={"roundup_article": "自定义"})
    assert s.prompts.roundup_article == "自定义"
    assert s.model_dump()["prompts"]["roundup_article"] == "自定义"


from app.prompts import DEFAULTS, PROMPTS, resolve_prompt
from app import config


def test_defaults_have_6_entries():
    assert len(PROMPTS) == 6
    assert set(DEFAULTS) == {"roundup_article", "summary_meta",
                             "weekly_digest", "image_regen",
                             "article_summary", "news_scoring"}


def test_default_content_enforces_asian_chinese():
    for key in ("roundup_article", "image_regen"):
        text = DEFAULTS[key]
        assert "Asian" in text or "Chinese" in text


def test_resolve_prefers_override(monkeypatch):
    monkeypatch.setattr(config, "_settings", config.Settings(prompts={"news_scoring": "我的评分"}))
    assert resolve_prompt("news_scoring") == "我的评分"


def test_resolve_falls_back_to_default_on_blank(monkeypatch):
    monkeypatch.setattr(config, "_settings", config.Settings(prompts={"news_scoring": "   "}))
    assert resolve_prompt("news_scoring") == DEFAULTS["news_scoring"]


def test_scoring_uses_resolver(monkeypatch):
    import app.services.scoring as scoring
    monkeypatch.setattr(config, "_settings", config.Settings(prompts={"news_scoring": "SCORE_OVERRIDE"}))
    from app.prompts import resolve_prompt
    assert resolve_prompt("news_scoring") == "SCORE_OVERRIDE"
    assert not hasattr(scoring, "SCORING_SYSTEM_PROMPT")


def test_news_scoring_language_lens(monkeypatch):
    # 清除 config 中可能存在的用户覆盖，确保测试走内置默认值
    monkeypatch.setattr(config, "_settings", config.Settings(prompts={"news_scoring": "", "news_scoring_en": ""}))
    from app.prompts import resolve_prompt
    zh = resolve_prompt("news_scoring", "zh")
    en = resolve_prompt("news_scoring", "en")
    assert "中国" in zh          # 中文版含中国视野
    assert "中国" not in en       # 英文版纯国际视野
    assert "0-10" in zh and "0-10" in en

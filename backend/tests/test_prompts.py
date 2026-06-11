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


def test_fill_preset1_defaults_fills_empty():
    from app.config import PromptPresetCfg, PromptPresetsCfg, _fill_preset1_defaults
    from app.prompts import DEFAULTS, DEFAULTS_EN

    presets = PromptPresetsCfg(presets=[PromptPresetCfg(name="预设 1"),
                                        PromptPresetCfg(name="预设 2")])
    _fill_preset1_defaults(presets, None)
    p1 = presets.presets[0].values
    assert p1.roundup_article == DEFAULTS["roundup_article"]
    assert p1.roundup_article_en == DEFAULTS_EN["roundup_article"]
    assert p1.news_scoring == DEFAULTS["news_scoring"]
    # 预设 2 不动（保持空白槽）
    assert presets.presets[1].values.roundup_article == ""


def test_fill_preset1_keeps_custom_and_prefers_legacy():
    from app.config import PromptPresetCfg, PromptPresetsCfg, PromptsCfg, _fill_preset1_defaults

    presets = PromptPresetsCfg(presets=[
        PromptPresetCfg(name="预设 1", values=PromptsCfg(roundup_article="MINE"))
    ])
    _fill_preset1_defaults(presets, {"news_scoring": "LEGACY"})
    p1 = presets.presets[0].values
    assert p1.roundup_article == "MINE"      # 已有自定义不覆盖
    assert p1.news_scoring == "LEGACY"       # 旧 config.yaml 的 prompts 优先于内置默认
    assert p1.summary_meta.strip() != ""     # 其余空字段补内置默认


def test_news_scoring_language_lens(monkeypatch):
    # 清除 config 中可能存在的用户覆盖，确保测试走内置默认值
    monkeypatch.setattr(config, "_settings", config.Settings(prompts={"news_scoring": "", "news_scoring_en": ""}))
    from app.prompts import resolve_prompt
    zh = resolve_prompt("news_scoring", "zh")
    en = resolve_prompt("news_scoring", "en")
    assert "中国" in zh          # 中文版含中国视野
    assert "中国" not in en       # 英文版纯国际视野
    assert "0-10" in zh and "0-10" in en

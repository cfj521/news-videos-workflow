import json

from app.pipeline.runner import _article_from_dict, _load_articles


def test_article_from_dict_maps_fields():
    a = _article_from_dict({"title": "T", "content": "C", "url": "https://x", "source": "S", "summary": "sm", "aihot_method": "daily"})
    assert a.title == "T"
    assert a.source_url == "https://x"
    assert a.source_name == "S"
    assert a.summary == "sm"
    assert a.metadata["aihot_method"] == "daily"


def test_article_from_dict_no_aihot_method():
    a = _article_from_dict({"title": "T", "content": "C", "url": "u", "source": "s"})
    assert a.metadata == {}


def test_load_articles_reads_file(tmp_path):
    (tmp_path / "articles.json").write_text(json.dumps([{"title": "T", "content": "C", "url": "u", "source": "s"}]), encoding="utf-8")
    arts = _load_articles(tmp_path)
    assert len(arts) == 1 and arts[0].title == "T"


def test_load_articles_missing_returns_empty(tmp_path):
    assert _load_articles(tmp_path) == []


def test_load_articles_non_list_returns_empty(tmp_path):
    (tmp_path / "articles.json").write_text("null", encoding="utf-8")
    assert _load_articles(tmp_path) == []


def test_save_and_reload_preserves_daily_sections(tmp_path):
    import json
    from app.providers.base import RawArticleData
    from app.pipeline.runner import _save_articles, _load_articles
    secs = [{"label": "模型", "items": [{"title": "A", "summary": "sa", "sourceUrl": "u", "sourceName": "s"}]}]
    art = RawArticleData(title="日报", content="c", source_url="https://aihot.virxact.com", source_name="AI HOT 日报",
                         metadata={"source_group": "aihot", "aihot_method": "daily", "daily_sections": secs})
    _save_articles([art], tmp_path)
    raw = json.loads((tmp_path / "articles.json").read_text(encoding="utf-8"))
    assert raw[0]["daily_sections"] == secs
    reloaded = _load_articles(tmp_path)
    assert reloaded[0].metadata["daily_sections"] == secs


def test_save_and_reload_preserves_source_group(tmp_path):
    """source_group 经 _save_articles/_load_articles 往返后必须保留，否则 AI HOT 直用路由永不触发。"""
    from app.providers.base import RawArticleData
    from app.pipeline.runner import _save_articles, _load_articles
    import json

    secs = [{"label": "热点", "items": [{"title": "T", "summary": "s", "sourceUrl": "u", "sourceName": "n"}]}]
    art = RawArticleData(
        title="AI 日报",
        content="c",
        source_url="https://aihot.example.com",
        source_name="AI HOT 日报",
        metadata={"source_group": "aihot", "aihot_method": "daily", "daily_sections": secs},
    )
    _save_articles([art], tmp_path)

    # 中间文件验证：source_group 应写入 JSON
    raw = json.loads((tmp_path / "articles.json").read_text(encoding="utf-8"))
    assert raw[0].get("source_group") == "aihot", "articles.json 未保存 source_group"

    # 往返验证：重载后 metadata 必须还原 source_group
    reloaded = _load_articles(tmp_path)
    assert reloaded[0].metadata.get("source_group") == "aihot", "重载后 source_group 丢失"
    assert reloaded[0].metadata.get("aihot_method") == "daily"
    assert reloaded[0].metadata.get("daily_sections") == secs


def test_write_scoring_json(tmp_path):
    from app.pipeline.runner import _write_scoring_json
    _write_scoring_json(tmp_path, {"pool": 3, "candidates": []})
    import json
    data = json.loads((tmp_path / "scoring.json").read_text(encoding="utf-8"))
    assert data["pool"] == 3
    _write_scoring_json(tmp_path / "nope", None)   # None 不写、不报错


def test_save_articles_preserves_score_fields(tmp_path):
    from app.pipeline.runner import _save_articles, _load_articles
    from app.providers.base import RawArticleData
    a = RawArticleData(title="t", content="c", source_url="u", source_name="s",
                       metadata={"score_final": 0.81, "score_reason": "重要"})
    _save_articles([a], tmp_path)
    back = _load_articles(tmp_path)
    assert back[0].metadata.get("score_final") == 0.81
    assert back[0].metadata.get("score_reason") == "重要"


def test_save_load_preserves_aihot_dates(tmp_path):
    from app.pipeline.runner import _save_articles, _load_articles
    from app.providers.base import RawArticleData
    from datetime import datetime, timezone
    daily = RawArticleData(title="日报", content="c", source_url="u", source_name="AI HOT 日报",
        metadata={"source_group": "aihot", "aihot_method": "daily", "report_date": "2026-06-01"})
    item = RawArticleData(title="动态", content="c", source_url="u2", source_name="AI HOT",
        metadata={"source_group": "aihot", "aihot_method": "items"},
        published_at=datetime(2026, 6, 5, tzinfo=timezone.utc))
    _save_articles([daily, item], tmp_path)
    back = _load_articles(tmp_path)
    assert back[0].metadata.get("report_date") == "2026-06-01"
    assert back[1].published_at is not None and back[1].published_at.year == 2026

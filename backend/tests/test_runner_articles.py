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

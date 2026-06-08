import pytest

import app.store.sources_store as ss


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "NEWS_SOURCES_PATH", tmp_path / "news_sources.yaml")


def test_list_empty():
    assert ss.list_sources() == []


def test_create_generates_slug():
    s = ss.create_source(name="Hacker News", type="api", url="https://hn.algolia.com/api/v1/")
    assert s.slug == "hacker_news"
    assert s.name == "Hacker News" and s.type == "api"
    assert s.enabled is True and s.priority == 5 and s.category == "general"
    assert s.config == {}


def test_create_chinese_name_falls_back_to_type():
    s = ss.create_source(name="机器之心", type="rss", url="https://x.com/feed")
    assert s.slug == "rss"


def test_create_collision():
    ss.create_source(name="News", type="rss", url="u1")
    s2 = ss.create_source(name="News", type="rss", url="u2")
    assert s2.slug == "news_1"


def test_get_update_delete():
    ss.create_source(name="HN", type="api", url="u", config={"provider": "aihot"})
    assert ss.get_source("hn").config["provider"] == "aihot"
    ss.update_source("hn", {"enabled": False, "priority": 9})
    got = ss.get_source("hn")
    assert got.enabled is False and got.priority == 9
    assert ss.delete_source("hn") is True
    assert ss.get_source("hn") is None


def test_update_missing_returns_none():
    assert ss.update_source("nope", {"enabled": False}) is None


def test_batch_update_enabled_and_priority():
    ss.create_source(name="A", type="rss", url="a", slug="a")
    ss.create_source(name="B", type="rss", url="b", slug="b")
    updated = ss.batch_update(["a", "b"], enabled=False, priority_map={"a": 3})
    assert len(updated) == 2
    assert ss.get_source("a").enabled is False and ss.get_source("a").priority == 3
    assert ss.get_source("b").enabled is False


def test_search_keys_roundtrip():
    assert ss.load_search_keys() == {"tavily_key": "", "brave_key": "", "serper_key": ""}
    ss.save_search_keys({"tavily_key": "tk", "brave_key": "", "serper_key": ""})
    assert ss.load_search_keys()["tavily_key"] == "tk"

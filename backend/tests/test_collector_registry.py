from app.providers.collector import create_collector_registry


def test_registry_has_all_collectors():
    registry = create_collector_registry()
    assert "rss" in registry
    assert "hackernews_algolia" in registry
    assert "tavily" in registry
    assert "google_news_rss" in registry
    assert "brave_search" in registry

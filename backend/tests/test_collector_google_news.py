from app.providers.collector.google_news import GoogleNewsCollector


def test_build_url_keyword_search():
    collector = GoogleNewsCollector()
    url = collector._build_url(
        search_query="AI 人工智能",
        hl="zh-CN",
        gl="CN",
        ceid="CN:zh",
        time_range="7d",
    )
    assert "search?q=" in url
    assert "when%3A7d" in url or "when:7d" in url
    assert "hl=zh-CN" in url


def test_build_url_topic():
    collector = GoogleNewsCollector()
    url = collector._build_url(
        topic="TECHNOLOGY",
        hl="en-US",
        gl="US",
        ceid="US:en",
        time_range="7d",
    )
    assert "topic/TECHNOLOGY" in url


def test_build_url_default_headlines():
    collector = GoogleNewsCollector()
    url = collector._build_url(hl="en-US", gl="US", ceid="US:en", time_range="7d")
    assert "news.google.com/rss?" in url
    assert "search" not in url
    assert "topic" not in url

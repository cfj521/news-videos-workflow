from datetime import datetime, timedelta, timezone

from app.providers.base import RawArticleData
from app.services.scoring import ScoringService


def _article(title="Test", published_hours_ago=1, source_name="TechCrunch"):
    return RawArticleData(
        title=title,
        content="Content about AI and machine learning",
        source_url="https://example.com",
        source_name=source_name,
        published_at=datetime.now(timezone.utc) - timedelta(hours=published_hours_ago),
    )


def test_score_basic():
    service = ScoringService()
    score = service.score(_article())
    assert 0 < score <= 1.0


def test_newer_scores_higher():
    service = ScoringService()
    new_article = _article(published_hours_ago=1)
    old_article = _article(published_hours_ago=72)
    assert service.score(new_article) > service.score(old_article)


def test_high_priority_source_scores_higher():
    service = ScoringService(source_weights={"MarkTechPost": 1.0, "Unknown Blog": 0.3})
    trusted = _article(source_name="MarkTechPost")
    unknown = _article(source_name="Unknown Blog")
    assert service.score(trusted) > service.score(unknown)


def test_select_top_n():
    service = ScoringService()
    articles = [
        _article(title="A", published_hours_ago=100),
        _article(title="B", published_hours_ago=1),
        _article(title="C", published_hours_ago=50),
    ]
    top = service.select_top(articles, n=2)
    assert len(top) == 2
    assert top[0].title == "B"

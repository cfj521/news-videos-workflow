from datetime import datetime, timedelta, timezone
from app.providers.base import RawArticleData
from app.services.scoring import ScoringService


def _art(title="t", content="c", url="", source="", published_at=None):
    return RawArticleData(title=title, content=content, source_url=url,
                          source_name=source, published_at=published_at)


def test_source_score_tiers():
    s = ScoringService()
    assert s._source_score(_art(url="https://www.anthropic.com/news/x")) == 1.0
    assert s._source_score(_art(source="Hacker News")) == 0.88
    assert s._source_score(_art(source="TechCrunch")) == 0.7
    assert s._source_score(_art(source="Tavily")) == 0.5
    assert s._source_score(_art(source="某不知名站")) == 0.5


def test_recency_score_piecewise():
    s = ScoringService()
    now = datetime.now(timezone.utc)
    assert s._recency_score(now) == 1.0
    assert abs(s._recency_score(now - timedelta(days=7)) - 0.9) < 1e-6
    assert abs(s._recency_score(now - timedelta(days=30)) - 0.3) < 1e-6
    assert s._recency_score(now - timedelta(days=60)) == 0.3
    assert s._recency_score(None) == 0.3
    assert s._recency_score(now - timedelta(days=3)) > s._recency_score(now - timedelta(days=15))


def test_keyword_score_language_lens():
    s = ScoringService()
    zh = s._keyword_score("DeepSeek 发布新模型", "国产大模型突破", "zh")
    en = s._keyword_score("DeepSeek 发布新模型", "国产大模型突破", "en")
    assert zh > en
    assert s._keyword_score("crypto casino 招聘", "赌博", "zh") >= 0.0
    assert s._keyword_score("OpenAI agent", "", "en") > 0.4


def test_rule_score_normalized():
    s = ScoringService()
    r = s._rule_score(_art(source="Hacker News", title="OpenAI agent",
                           published_at=datetime.now(timezone.utc)), "en")
    assert 0.0 <= r <= 1.0

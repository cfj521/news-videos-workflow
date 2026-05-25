from app.providers.base import RawArticleData
from app.services.dedup import DedupService


def _article(title: str, content: str = "default content") -> RawArticleData:
    return RawArticleData(
        title=title,
        content=content,
        source_url=f"https://example.com/{title.replace(' ', '-')}",
        source_name="Test",
    )


def test_dedup_identical_titles():
    service = DedupService()
    articles = [_article("AI Breakthrough in 2026"), _article("AI Breakthrough in 2026")]
    result = service.deduplicate(articles)
    assert len(result) == 1


def test_dedup_similar_titles():
    service = DedupService(title_threshold=0.8)
    articles = [
        _article("AI Breakthrough Announced Today"),
        _article("AI Breakthrough Was Announced Today"),
    ]
    result = service.deduplicate(articles)
    assert len(result) == 1


def test_dedup_different_titles():
    service = DedupService()
    articles = [_article("AI Breakthrough in 2026"), _article("New Quantum Computer Developed")]
    result = service.deduplicate(articles)
    assert len(result) == 2


def test_dedup_against_history():
    service = DedupService()
    history_fingerprints = [service.fingerprint("AI Breakthrough in 2026")]
    articles = [_article("AI Breakthrough in 2026"), _article("Brand New Topic")]
    result = service.deduplicate(articles, history_fingerprints)
    assert len(result) == 1
    assert result[0].title == "Brand New Topic"


def test_fingerprint_deterministic():
    service = DedupService()
    fp1 = service.fingerprint("Hello World")
    fp2 = service.fingerprint("Hello World")
    assert fp1 == fp2

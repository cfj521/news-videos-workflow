from app.providers.base import CollectorProvider, RawArticleData
from app.services.compliance import ComplianceService
from app.services.dedup import DedupService
from app.services.scoring import ScoringService


async def run_stage1(
    sources: list[dict],
    collectors: dict[str, CollectorProvider],
    time_range: str = "7d",
    max_articles: int = 5,
    history_fingerprints: list[str] | None = None,
) -> list[RawArticleData]:
    all_articles: list[RawArticleData] = []

    for source in sources:
        source_type = source.get("type", "rss")
        collector = collectors.get(source_type)
        if not collector:
            continue

        try:
            articles = await collector.collect(
                source_config=source,
                time_range=time_range,
            )
            all_articles.extend(articles)
        except Exception:
            continue

    dedup = DedupService()
    deduplicated = dedup.deduplicate(all_articles, history_fingerprints)

    compliance = ComplianceService()
    compliant: list[RawArticleData] = []
    for article in deduplicated:
        result = compliance.check(article.content, article.title)
        if result.status != "blocked":
            compliant.append(article)

    scoring = ScoringService()
    selected = scoring.select_top(compliant, n=max_articles)

    return selected

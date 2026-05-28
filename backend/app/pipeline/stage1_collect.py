from app.logging import get_logger
from app.providers.base import CollectorProvider, RawArticleData
from app.services.compliance import ComplianceService
from app.services.dedup import DedupService
from app.services.scoring import ScoringService

log = get_logger("stage1")


async def run_stage1(
    sources: list[dict],
    collectors: dict[str, CollectorProvider],
    time_range: str = "7d",
    max_articles: int = 5,
    history_fingerprints: list[str] | None = None,
    enable_dedup: bool = True,
    enable_scoring: bool = True,
) -> list[RawArticleData]:
    all_articles: list[RawArticleData] = []

    for source in sources:
        source_type = source.get("type", "rss")
        source_name = source.get("name", source_type)
        collector = collectors.get(source_type)
        if not collector:
            log.warning("No collector for type '%s' (source: %s), skipping", source_type, source_name)
            continue

        try:
            articles = await collector.collect(source_config=source, time_range=time_range)
            log.info("Source '%s' (%s) → %d articles", source_name, source_type, len(articles))
            all_articles.extend(articles)
        except Exception:
            log.exception("Collector failed for source '%s' (%s)", source_name, source_type)

    log.info("Total raw articles: %d", len(all_articles))

    if enable_dedup:
        dedup = DedupService()
        deduplicated = dedup.deduplicate(all_articles, history_fingerprints)
        log.info("After dedup: %d (removed %d)", len(deduplicated), len(all_articles) - len(deduplicated))
    else:
        deduplicated = all_articles
        log.info("Dedup disabled, keeping all %d articles", len(deduplicated))

    compliance = ComplianceService()
    compliant: list[RawArticleData] = []
    blocked = 0
    for article in deduplicated:
        result = compliance.check(article.content, article.title)
        if result.status != "blocked":
            compliant.append(article)
        else:
            blocked += 1
            log.info("Blocked: '%s' — %s", article.title, result.reason)
    if blocked:
        log.info("Compliance blocked %d articles", blocked)

    if enable_scoring:
        scoring = ScoringService()
        selected = scoring.select_top(compliant, n=max_articles)
        log.info("Selected top %d articles (from %d compliant)", len(selected), len(compliant))
    else:
        selected = compliant[:max_articles]
        log.info("Scoring disabled, taking first %d articles", len(selected))

    return selected

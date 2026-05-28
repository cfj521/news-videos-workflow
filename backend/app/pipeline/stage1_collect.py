from app.logging import get_logger
from app.providers.base import CollectorProvider, RawArticleData
from app.services.compliance import ComplianceService
from app.services.dedup import DedupService
from app.services.scoring import ScoringService

log = get_logger("stage1")


def _filter_compliant(articles: list[RawArticleData]) -> list[RawArticleData]:
    compliance = ComplianceService()
    out: list[RawArticleData] = []
    blocked = 0
    for a in articles:
        if compliance.check(a.content, a.title).status != "blocked":
            out.append(a)
        else:
            blocked += 1
            log.info("Blocked: '%s'", a.title)
    if blocked:
        log.info("Compliance blocked %d articles", blocked)
    return out


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

    is_aihot = bool(all_articles) and all_articles[0].metadata.get("source_group") == "aihot"

    # AI HOT：聚合平台已精选/去重，跳过去重与评分，仅做合规与截断
    if is_aihot:
        method = all_articles[0].metadata.get("aihot_method", "items")
        compliant = _filter_compliant(all_articles)
        if method == "daily":
            log.info("AI HOT daily — single-doc passthrough")
            return compliant[:1]
        log.info("AI HOT items — taking top %d (no dedup/scoring)", max_articles)
        return compliant[:max_articles]

    # 普通源：始终去重 → 合规 → 评分挑 top N
    dedup = DedupService()
    deduplicated = dedup.deduplicate(all_articles, history_fingerprints)
    log.info("After dedup: %d (removed %d)", len(deduplicated), len(all_articles) - len(deduplicated))
    compliant = _filter_compliant(deduplicated)
    scoring = ScoringService()
    selected = scoring.select_top(compliant, n=max_articles)
    log.info("Selected top %d articles (from %d compliant)", len(selected), len(compliant))
    return selected

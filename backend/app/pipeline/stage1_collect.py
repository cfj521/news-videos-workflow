from app.logging import get_logger
from app.providers.base import CollectorProvider, ProviderError, RawArticleData
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
    errors: list[tuple[str, Exception]] = []
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
        except Exception as e:
            log.exception("Collector failed for source '%s' (%s)", source_name, source_type)
            errors.append((source_name, e))

    # 所有源都失败、一篇都没采到 → 抛出带源头的错误（而非静默返回空，让用户看到每个源为何失败）
    if not all_articles and errors:
        if len(errors) == 1:
            name, exc = errors[0]
            raise ProviderError(service="采集", provider=name, cause=exc)
        names = "、".join(n for n, _ in errors)
        detail = "；".join(f"{n}: {type(e).__name__}" for n, e in errors)
        raise ProviderError(service="采集", provider=names, cause=RuntimeError(detail))

    log.info("Total raw articles: %d", len(all_articles))

    is_aihot = bool(all_articles) and all_articles[0].metadata.get("source_group") == "aihot"

    # AI HOT：聚合平台已精选/审编，跳过去重、评分，也跳过本地合规过滤。
    # 本地关键词合规是为原始网页抓取设计的，会因正常新闻词（如"暴力/事故"）误删已审编内容；
    # 既然去重/评分都因"聚合源已处理"而跳过，合规同理。日报/周报为单篇汇总，items 取前 N。
    if is_aihot:
        method = all_articles[0].metadata.get("aihot_method", "items")
        if method in ("daily", "weekly"):
            log.info("AI HOT %s — single-doc passthrough (curated, no dedup/scoring/compliance)", method)
            return all_articles[:1]
        log.info("AI HOT items — passthrough %d (选取交给 stage2 评分)", len(all_articles))
        return all_articles

    # 普通源：始终去重 → 合规 → 评分挑 top N
    dedup = DedupService()
    deduplicated = dedup.deduplicate(all_articles, history_fingerprints)
    log.info("After dedup: %d (removed %d)", len(deduplicated), len(all_articles) - len(deduplicated))
    compliant = _filter_compliant(deduplicated)
    scoring = ScoringService()
    selected = (await scoring.select_top(compliant, None, "zh", n=max_articles)).selected
    log.info("Selected top %d articles (from %d compliant)", len(selected), len(compliant))
    return selected

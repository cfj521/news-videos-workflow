import time
from datetime import datetime, timedelta, timezone

import httpx

from app.logging import get_logger
from app.providers.base import CollectorProvider, RawArticleData

log = get_logger("collector.scraping")

TIME_RANGE_MAP = {"1d": timedelta(days=1), "3d": timedelta(days=3), "7d": timedelta(days=7), "15d": timedelta(days=15), "1m": timedelta(days=30)}


class ScrapingCollector(CollectorProvider):
    """Generic web scraping collector using CSS selectors defined in source_config."""

    async def collect(self, source_config: dict, time_range: str, max_items: int = 30) -> list[RawArticleData]:
        source_name = source_config.get("name", "Scrape")
        base_url = source_config.get("url", "")
        list_cfg = source_config.get("list_page", {})
        detail_cfg = source_config.get("detail_page", {})

        if not base_url or not list_cfg.get("article_selector"):
            log.warning("Scraping source '%s' missing url or article_selector", source_name)
            return []

        log.debug("Scraping %s", base_url)
        t0 = time.time()

        try:
            from scrapling import Fetcher
        except ImportError:
            log.error("scrapling not installed: pip install 'scrapling[all]'")
            return []

        fetcher = Fetcher(auto_match=True)
        articles: list[RawArticleData] = []
        max_pages = source_config.get("max_pages", 1)

        page_url = base_url
        for page_num in range(max_pages):
            try:
                page = fetcher.get(page_url)
            except Exception:
                log.exception("Failed to fetch page %d: %s", page_num + 1, page_url)
                break

            items = page.css(list_cfg["article_selector"])
            if not items:
                break

            for item in items:
                title_el = item.css_first(list_cfg.get("title_selector", "a"))
                link_el = item.css_first(list_cfg.get("link_selector", "a"))
                if not title_el or not link_el:
                    continue

                title = title_el.text().strip()
                link = link_el.attrib.get("href", "")
                if link and not link.startswith("http"):
                    link = base_url.rstrip("/") + "/" + link.lstrip("/")

                content = ""
                if detail_cfg.get("content_selector"):
                    try:
                        detail = fetcher.get(link)
                        content_el = detail.css_first(detail_cfg["content_selector"])
                        if content_el:
                            content = content_el.text().strip()
                    except Exception:
                        log.warning("Failed to fetch detail: %s", link)

                articles.append(RawArticleData(
                    title=title,
                    content=content[:3000],
                    source_url=link,
                    source_name=source_name,
                    category=source_config.get("category", "general"),
                    language=source_config.get("language", "zh"),
                ))

                if len(articles) >= max_items:
                    break

            if len(articles) >= max_items:
                break

            next_sel = source_config.get("pagination", {}).get("next_page_selector")
            if next_sel:
                next_el = page.css_first(next_sel)
                if next_el:
                    page_url = next_el.attrib.get("href", "")
                    if page_url and not page_url.startswith("http"):
                        page_url = base_url.rstrip("/") + "/" + page_url.lstrip("/")
                else:
                    break
            else:
                break

        log.info("Collected %d articles from %s in %.1fs", len(articles), source_name, time.time() - t0)
        return articles

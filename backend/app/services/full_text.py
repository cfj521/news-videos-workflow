import re
import time
from html.parser import HTMLParser

import httpx

from app.logging import get_logger

log = get_logger("service.full_text")


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._texts: list[str] = []
        self._skip_tags = {"script", "style", "nav", "header", "footer", "aside"}
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._skip_tags and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._texts.append(text)

    def get_text(self) -> str:
        return "\n".join(self._texts)


class FullTextFetcher:
    async def fetch(self, url: str) -> str:
        log.debug("Fetching full text: %s", url)
        t0 = time.time()
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        text = self._extract_content(resp.text)
        log.info("Fetched %d chars from %s in %.1fs", len(text), url, time.time() - t0)
        return text

    def _extract_content(self, html: str) -> str:
        article_match = re.search(r"<article[^>]*>(.*?)</article>", html, re.DOTALL | re.IGNORECASE)
        target_html = article_match.group(1) if article_match else html
        extractor = _TextExtractor()
        extractor.feed(target_html)
        return extractor.get_text()

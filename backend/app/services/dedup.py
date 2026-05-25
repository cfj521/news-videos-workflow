import hashlib
from difflib import SequenceMatcher

from app.providers.base import RawArticleData


class DedupService:
    def __init__(self, title_threshold: float = 0.85):
        self.title_threshold = title_threshold

    def deduplicate(
        self,
        articles: list[RawArticleData],
        history_fingerprints: list[str] | None = None,
    ) -> list[RawArticleData]:
        history_fps = set(history_fingerprints or [])
        seen_titles: list[str] = []
        seen_fps: set[str] = set()
        result: list[RawArticleData] = []

        for article in articles:
            fp = self.fingerprint(article.title)

            if fp in history_fps or fp in seen_fps:
                continue

            if self._is_similar_to_any(article.title, seen_titles):
                continue

            seen_titles.append(article.title)
            seen_fps.add(fp)
            result.append(article)

        return result

    def _is_similar_to_any(self, title: str, existing: list[str]) -> bool:
        normalized = title.lower().strip()
        for existing_title in existing:
            ratio = SequenceMatcher(None, normalized, existing_title.lower().strip()).ratio()
            if ratio >= self.title_threshold:
                return True
        return False

    def fingerprint(self, text: str) -> str:
        normalized = text.lower().strip()
        return hashlib.md5(normalized.encode()).hexdigest()

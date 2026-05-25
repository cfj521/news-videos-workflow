from datetime import datetime, timezone

from app.providers.base import RawArticleData

DEFAULT_SOURCE_WEIGHTS = {
    "Hacker News": 0.9,
    "MarkTechPost": 1.0,
    "TechCrunch": 0.9,
    "机器之心": 1.0,
    "36氪": 0.8,
    "量子位": 0.9,
    "Tavily": 0.7,
    "Brave Search": 0.7,
    "Google News": 0.6,
}

AI_KEYWORDS = [
    "ai",
    "artificial intelligence",
    "llm",
    "gpt",
    "claude",
    "machine learning",
    "deep learning",
    "neural network",
    "transformer",
    "人工智能",
    "大模型",
    "深度学习",
    "机器学习",
    "神经网络",
]


class ScoringService:
    def __init__(self, source_weights: dict[str, float] | None = None):
        self.source_weights = source_weights or DEFAULT_SOURCE_WEIGHTS

    def score(self, article: RawArticleData) -> float:
        source_w = self.source_weights.get(article.source_name, 0.5)
        recency_w = self._recency_weight(article.published_at)
        relevance_w = self._relevance_weight(article.title, article.content)

        return source_w * 0.3 + recency_w * 0.4 + relevance_w * 0.3

    def select_top(
        self,
        articles: list[RawArticleData],
        n: int = 5,
    ) -> list[RawArticleData]:
        scored = [(self.score(a), a) for a in articles]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [a for _, a in scored[:n]]

    def _recency_weight(self, published_at: datetime | None) -> float:
        if not published_at:
            return 0.3
        now = datetime.now(timezone.utc)
        hours_ago = (now - published_at).total_seconds() / 3600
        return max(0.0, 1.0 - (hours_ago / 168))

    def _relevance_weight(self, title: str, content: str) -> float:
        combined = f"{title} {content}".lower()
        matches = sum(1 for kw in AI_KEYWORDS if kw in combined)
        return min(1.0, matches * 0.2)

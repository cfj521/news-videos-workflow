import json
import math
import re
from datetime import datetime, timezone

from app.logging import get_logger
from app.prompts import resolve_prompt
from app.providers.base import RawArticleData

log = get_logger("service.scoring")

# ── Keyword lists ────────────────────────────────────────

AI_KEYWORDS = [
    "ai", "artificial intelligence", "llm", "gpt", "claude", "machine learning",
    "deep learning", "neural network", "transformer", "openai", "anthropic", "gemini",
    "diffusion", "agent", "rag", "fine-tune", "benchmark", "open source",
    "人工智能", "大模型", "深度学习", "机器学习", "神经网络", "开源",
]

NEGATIVE_KEYWORDS = [
    "crypto", "nft", "blockchain", "bitcoin", "meme", "casino", "gambling",
    "加密货币", "比特币", "赌博",
]

DEFAULT_SOURCE_WEIGHTS = {
    "Hacker News": 0.9, "MarkTechPost": 1.0, "TechCrunch": 0.9, "机器之心": 1.0,
    "36氪": 0.8, "量子位": 0.9, "Tavily": 0.7, "Brave Search": 0.7,
    "Google News": 0.6, "Serper": 0.7, "DuckDuckGo": 0.5,
}

# ── upvoteRate constants (from quality-news) ─────────────

FATIGUE_FACTOR = 0.003462767
PRIOR_WEIGHT = 0.75

# ── JSON parsing (5-layer fallback, from Horizon) ────────

def _parse_json_response(text: str) -> dict | None:
    text = text.strip()
    # Layer 1: direct parse
    try:
        return json.loads(text)
    except Exception:
        pass
    # Layer 2: ```json ... ``` block
    m = re.search(r"```json\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # Layer 3: ``` ... ``` block
    m = re.search(r"```\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # Layer 4: brace matching
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except Exception:
                        break
    # Layer 5: regex
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


class ScoringService:
    def __init__(self, source_weights: dict[str, float] | None = None):
        self.source_weights = source_weights or DEFAULT_SOURCE_WEIGHTS

    def score(self, article: RawArticleData) -> float:
        rule = self._rule_score(article)
        data = self._data_signal_score(article)
        return 0.6 * rule + 0.4 * data

    async def score_with_llm(self, article: RawArticleData, text_provider) -> tuple[float, dict]:
        """Returns (final_score, llm_result_dict). Falls back to rules on failure."""
        data = self._data_signal_score(article)
        try:
            llm_result = await self._llm_score(article, text_provider)
            llm_norm = llm_result.get("score", 5) / 10.0
            final = 0.6 * llm_norm + 0.4 * data
            return final, llm_result
        except Exception:
            log.warning("LLM scoring failed for '%s', falling back to rules", article.title[:40])
            rule = self._rule_score(article)
            return 0.6 * rule + 0.4 * data, {}

    def select_top(self, articles: list[RawArticleData], n: int = 5) -> list[RawArticleData]:
        scored = [(self.score(a), a) for a in articles]
        scored.sort(key=lambda x: x[0], reverse=True)
        for s, a in scored[:n]:
            log.debug("Score %.3f: '%s' (%s)", s, a.title[:50], a.source_name)
        return [a for _, a in scored[:n]]

    async def select_top_with_llm(self, articles: list[RawArticleData], text_provider, n: int = 5) -> list[RawArticleData]:
        scored = []
        for a in articles:
            s, result = await self.score_with_llm(a, text_provider)
            if result.get("tags"):
                a.metadata["ai_tags"] = result["tags"]
            if result.get("reason"):
                a.metadata["ai_reason"] = result["reason"]
            scored.append((s, a))
        scored.sort(key=lambda x: x[0], reverse=True)
        for s, a in scored[:n]:
            log.info("Score %.3f: '%s' (%s) %s", s, a.title[:50], a.source_name, a.metadata.get("ai_reason", ""))
        return [a for _, a in scored[:n]]

    # ── Rule-based score (fallback) ──────────────────────

    def _rule_score(self, article: RawArticleData) -> float:
        source_w = self.source_weights.get(article.source_name, 0.5)
        recency_w = self._recency_weight(article.published_at)
        relevance_w = self._keyword_relevance(article.title, article.content)
        return source_w * 0.3 + recency_w * 0.3 + relevance_w * 0.4

    # ── Data signal (upvoteRate, quality-news style) ─────

    def _data_signal_score(self, article: RawArticleData) -> float:
        meta = article.metadata
        points = meta.get("points", 0)
        if not points:
            return 0.5

        age_hours = 24.0
        if article.published_at:
            delta = (datetime.now(timezone.utc) - article.published_at).total_seconds() / 3600
            age_hours = max(1.0, delta)

        # Estimate expected upvotes from age (simplified position model)
        # A top-30 HN story gets ~5-15 votes/hour in the first few hours
        avg_vote_rate = 8.0
        raw_expected = avg_vote_rate * age_hours

        # Fatigue adjustment (from quality-news)
        adjusted_expected = (1 - math.exp(-FATIGUE_FACTOR * raw_expected)) / FATIGUE_FACTOR

        # Bayesian upvoteRate
        upvote_rate = (points + PRIOR_WEIGHT) / (adjusted_expected + PRIOR_WEIGHT)

        # Comment engagement signal
        num_comments = meta.get("num_comments", 0)
        comment_ratio = num_comments / max(points, 1.0)

        # Normalize to 0-1
        rate_norm = min(1.0, upvote_rate / 3.0)
        comment_norm = min(1.0, comment_ratio * 0.5)

        return rate_norm * 0.7 + comment_norm * 0.3

    # ── LLM score (structured JSON) ──────────────────────

    async def _llm_score(self, article: RawArticleData, text_provider) -> dict:
        meta = article.metadata
        content_section = (article.content or "")[:1000]

        # Build engagement section (like Horizon)
        engagement_parts = []
        if meta.get("points"):
            engagement_parts.append(f"Points: {meta['points']}")
        if meta.get("num_comments"):
            engagement_parts.append(f"Comments: {meta['num_comments']}")
        if meta.get("upvote_ratio"):
            engagement_parts.append(f"Upvote ratio: {meta['upvote_ratio']}")
        engagement_section = "\n".join(engagement_parts)

        prompt_parts = [
            f"标题：{article.title}",
            f"来源：{article.source_name}",
        ]
        if content_section:
            prompt_parts.append(f"内容：{content_section}")
        if engagement_section:
            prompt_parts.append(f"社区互动：\n{engagement_section}")

        result_text = await text_provider.generate(
            prompt="\n".join(prompt_parts),
            system_prompt=resolve_prompt("news_scoring"),
        )

        parsed = _parse_json_response(result_text)
        if parsed and "score" in parsed:
            score = parsed["score"]
            if isinstance(score, (int, float)) and 0 <= score <= 10:
                return parsed
            try:
                parsed["score"] = max(0, min(10, int(float(score))))
                return parsed
            except (ValueError, TypeError):
                pass  # score 非数值（如 "高"）→ 落到下面的数字提取兜底，而非丢弃整条结果

        # Last resort: extract number
        nums = re.findall(r"\b(\d+)\b", result_text)
        for n in nums:
            v = int(n)
            if 0 <= v <= 10:
                return {"score": v, "reason": "", "tags": []}
        return {"score": 5, "reason": "parse_failed", "tags": []}

    # ── Helpers ──────────────────────────────────────────

    def _recency_weight(self, published_at: datetime | None) -> float:
        if not published_at:
            return 0.3
        hours_ago = (datetime.now(timezone.utc) - published_at).total_seconds() / 3600
        return max(0.0, 1.0 - (hours_ago / 168))

    def _keyword_relevance(self, title: str, content: str) -> float:
        combined = f"{title} {content}".lower()
        pos = sum(1 for kw in AI_KEYWORDS if kw in combined)
        neg = sum(1 for kw in NEGATIVE_KEYWORDS if kw in combined)
        return min(1.0, max(0.0, pos * 0.15 - neg * 0.3))

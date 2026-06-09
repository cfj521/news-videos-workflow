import asyncio
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config import get_settings
from app.logging import get_logger
from app.prompts import resolve_prompt
from app.providers.base import RawArticleData
from app.services import scoring_constants as C

log = get_logger("service.scoring")

# ── Keyword lists（旧版兼容，供旧 _legacy_rule_score 使用）────────────────────────────────────────

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

# ── 模块级 LLM 评分缓存（reload_settings() 时清空）────────────────────────────
_LLM_CACHE: dict[str, dict] = {}

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


# ── ScoringResult 数据类 ───────────────────────────────────────────────────────

@dataclass
class ScoringResult:
    selected: list
    report: dict = field(default_factory=dict)


class ScoringService:
    def __init__(self, source_weights: dict[str, float] | None = None):
        # source_weights 参数保留以向后兼容旧调用方，但新子评分器统一走 cfg
        self.source_weights = source_weights or DEFAULT_SOURCE_WEIGHTS
        self.cfg = get_settings().scoring

    # ── 新子评分器（0–1 纯函数）────────────────────────────────────────────────

    def _source_score(self, a: RawArticleData) -> float:
        hay = f"{a.source_url} {a.source_name}".lower()
        for pat, w in C.SOURCE_TIERS:
            if re.search(pat, hay):
                return w
        return C.DEFAULT_SOURCE_WEIGHT

    def _recency_score(self, published_at: datetime | None) -> float:
        if not published_at:
            return self.cfg.fresh_floor
        days = (datetime.now(timezone.utc) - published_at).total_seconds() / 86400
        full, we, floor_d, floor = (self.cfg.fresh_full_days, self.cfg.fresh_week_end,
                                    self.cfg.fresh_floor_days, self.cfg.fresh_floor)
        if days <= 0:
            return 1.0
        if days <= full:
            return 1.0 - (1.0 - we) * (days / full)
        if days <= floor_d:
            return we - (we - floor) * ((days - full) / (floor_d - full))
        return floor

    def _keyword_score(self, title: str, content: str, language: str) -> float:
        text = f"{title} {content}".lower()
        is_en = (language or "zh").lower().startswith("en")
        score = C.KW_BASE
        for kw in C.POSITIVE_ENTITIES + C.POSITIVE_LEADERS:
            if kw in text:
                score += C.KW_ENTITY
        for kw in C.TECH_TERMS:
            if kw in text:
                score += C.KW_TERM
        if not is_en:
            for kw in C.CHINA_TERMS:
                if kw in text:
                    score += C.KW_ENTITY
        for kw in C.NEGATIVE_TERMS:
            if kw in text:
                score -= C.KW_NEG
        return max(0.0, min(1.0, score))

    def _rule_score(self, a: RawArticleData, language: str) -> float:
        """新版规则评分（接受 language 参数），0–1。"""
        ws, wr, wk = self.cfg.w_source, self.cfg.w_recency, self.cfg.w_keyword
        tot = ws + wr + wk or 1.0
        return (ws * self._source_score(a)
                + wr * self._recency_score(a.published_at)
                + wk * self._keyword_score(a.title, a.content or "", language)) / tot

    # ── 旧版方法（保留以兼容 stage1/stage2 调用的 select_top）────────────────────

    def score(self, article: RawArticleData) -> float:
        rule = self._legacy_rule_score(article)
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
            rule = self._legacy_rule_score(article)
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

    # ── 旧版规则评分（内部，供旧 score() 调用）───────────────────────────────────

    def _legacy_rule_score(self, article: RawArticleData) -> float:
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

    # ── LLM score (structured JSON, with cache + language + timeout/retry) ────

    async def _llm_score(self, a: RawArticleData, text_provider, language: str = "zh") -> dict:
        sys_prompt = resolve_prompt("news_scoring", language)
        content = (a.content or "")[:1000]
        key = hashlib.sha256(f"{a.title}{content}{language}{sys_prompt}".encode()).hexdigest()
        if key in _LLM_CACHE:
            return {**_LLM_CACHE[key], "_cached": True}
        parts = [f"标题：{a.title}", f"来源：{a.source_name}"]
        if content:
            parts.append(f"内容：{content}")
        meta = a.metadata or {}
        eng = [f"{k}: {meta[k]}" for k in ("points", "num_comments", "upvote_ratio") if meta.get(k)]
        if eng:
            parts.append("社区互动：\n" + "\n".join(eng))
        last_exc = None
        for _ in range(C.LLM_RETRIES + 1):
            try:
                resp = await asyncio.wait_for(
                    text_provider.generate(prompt="\n".join(parts), system_prompt=sys_prompt),
                    timeout=C.LLM_TIMEOUT_S)
                parsed = _parse_json_response(resp) or {}
                score = parsed.get("score")
                if not isinstance(score, (int, float)) or not (0 <= score <= 10):
                    nums = [int(x) for x in re.findall(r"\b(\d+)\b", resp or "") if 0 <= int(x) <= 10]
                    score = nums[0] if nums else 5
                out = {"score": float(score), "reason": parsed.get("reason", ""), "tags": parsed.get("tags", [])}
                _LLM_CACHE[key] = out
                return out
            except Exception as e:
                last_exc = e
        raise last_exc or RuntimeError("llm score failed")

    # ── Helpers（旧版，供 _legacy_rule_score 使用）────────────────────────────────

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

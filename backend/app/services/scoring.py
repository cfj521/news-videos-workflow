import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.logging import get_logger
from app.prompts import resolve_prompt
from app.providers.base import RawArticleData
from app.services import scoring_constants as C

log = get_logger("service.scoring")

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
    # ── 新子评分器（0–1 纯函数）────────────────────────────────────────────────

    def _source_score(self, a: RawArticleData) -> float:
        hay = f"{a.source_url} {a.source_name}".lower()
        for pat, w in C.SOURCE_TIERS:
            if re.search(pat, hay):
                return w
        return C.DEFAULT_SOURCE_WEIGHT

    def _recency_score(self, published_at: datetime | None) -> float:
        if not published_at:
            return C.FRESH_FLOOR
        days = (datetime.now(timezone.utc) - published_at).total_seconds() / 86400
        full, we, floor_d, floor = (C.FRESH_FULL_DAYS, C.FRESH_WEEK_END,
                                    C.FRESH_FLOOR_DAYS, C.FRESH_FLOOR)
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
        ws, wr, wk = C.W_SOURCE, C.W_RECENCY, C.W_KEYWORD
        tot = ws + wr + wk or 1.0
        return (ws * self._source_score(a)
                + wr * self._recency_score(a.published_at)
                + wk * self._keyword_score(a.title, a.content or "", language)) / tot

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

    # ── 核心编排：async select_top ────────────────────────────────────────────

    async def select_top(self, articles, text_provider=None, language="zh", n=5, on_progress=None) -> ScoringResult:
        """on_progress(done, total)：LLM 评分每完成一条回调一次（供上层刷新 run 进度）。"""
        if not articles:
            return ScoringResult(selected=[], report={"candidates": [], "n": n, "k": 0, "pool": 0,
                                 "min_score": C.MIN_SCORE, "source_type": ""})
        pool = len(articles)
        cap = C.LLM_CANDIDATE_CAP
        ws, wr, wk = C.W_SOURCE, C.W_RECENCY, C.W_KEYWORD
        wtot = (ws + wr + wk) or 1.0
        scored = []
        for a in articles:
            src = self._source_score(a)
            rec = self._recency_score(a.published_at)
            kw = self._keyword_score(a.title, a.content or "", language)
            rule = (ws * src + wr * rec + wk * kw) / wtot
            scored.append({"art": a, "source_w": src, "recency": rec, "keyword": kw, "rule": rule})
        # 选 LLM 评分集：小池子(≤2·cap)全量；大池子按 rule 取前 cap
        if text_provider is not None and pool > 2 * cap:
            scored.sort(key=lambda x: x["rule"], reverse=True)
            llm_set = scored[:cap]
        else:
            llm_set = scored if text_provider is not None else []
        if llm_set:
            total = len(llm_set)
            done = 0
            log.info("[scoring] start — LLM 评分 %d 条候选 (pool=%d, concurrency=%d)", total, pool, C.LLM_CONCURRENCY)
            sem = asyncio.Semaphore(C.LLM_CONCURRENCY)
            async def run_one(item):
                nonlocal done
                async with sem:
                    try:
                        r = await self._llm_score(item["art"], text_provider, language)
                        item["llm"] = r["score"] / 10.0
                        item["reason"], item["tags"], item["llm_ran"] = r.get("reason", ""), r.get("tags", []), True
                    except Exception:
                        item["llm_ran"] = False
                    finally:
                        done += 1
                        # 评分并发完成，逐条进度（每 5 条或末条打 INFO，便于观察「正在评分」不卡死）
                        if done % 5 == 0 or done == total:
                            log.info("[scoring] LLM 评分进度 %d/%d", done, total)
                        if on_progress is not None:
                            try:
                                on_progress(done, total)
                            except Exception:
                                pass
            await asyncio.gather(*(run_one(it) for it in llm_set))
        for it in scored:
            if it.get("llm_ran"):
                it["final"] = C.W_FINAL_LLM * it["llm"] + C.W_FINAL_RULE * it["rule"]
            else:
                it["final"] = it["rule"]
        scored.sort(key=lambda x: x["final"], reverse=True)
        passed = [it for it in scored if it["final"] >= C.MIN_SCORE]
        chosen = (passed or scored[:1])[:n]
        chosen_ids = {id(it) for it in chosen}
        for it in scored:
            it["selected"] = id(it) in chosen_ids
        report = {
            "source_type": (articles[0].metadata or {}).get("aihot_method") or "normal",
            "n": n, "k": cap, "pool": pool, "min_score": C.MIN_SCORE,
            "candidates": [self._row(it) for it in scored],
        }
        log.info("[scoring] pool=%d llm=%d selected=%d (min=%.2f)", pool, len(llm_set), len(chosen), C.MIN_SCORE)
        for it in chosen:
            it["art"].metadata["score_final"] = round(it["final"], 4)
            it["art"].metadata["score_reason"] = it.get("reason", "")
        return ScoringResult(selected=[it["art"] for it in chosen], report=report)

    @staticmethod
    def _row(it) -> dict:
        a = it["art"]
        return {"title": a.title, "source": a.source_name,
                "final": round(it["final"], 4),
                "llm": (round(it["llm"], 4) if it.get("llm_ran") else None),
                "source_w": round(it["source_w"], 4), "recency": round(it["recency"], 4),
                "keyword": round(it["keyword"], 4), "rule": round(it["rule"], 4),
                "reason": it.get("reason", ""), "tags": it.get("tags", []),
                "llm_ran": bool(it.get("llm_ran")), "selected": bool(it.get("selected"))}

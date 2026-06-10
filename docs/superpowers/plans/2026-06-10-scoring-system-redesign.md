# 评分系统重设计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 ScoringService 重写为「LLM 评分 + (来源+新鲜度+关键词) 规则分」的统一评分器，接入普通源与 AI HOT 两条线，带并发/预筛/缓存/中英视野/质量地板，评分明细落 `scoring.json` 并在前端展示。

**Architecture:** 硬编码集中到 `scoring_constants.py`；标量调参进 `ScoringCfg`（设置页可改）。`ScoringService.select_top` 返回 `ScoringResult{selected, report}`：先规则分（免费）→ 小池子(≤2K)全量 / 大池子按规则取前 K 预筛 → 并发(默认5)跑 LLM(缓存+超时+重试+单篇降级) → `final=0.6·LLM+0.4·rule` → 过 `min_score` 取前 N。runner 把 `report` 写入 `run_dir/scoring.json`。

**Tech Stack:** Python/FastAPI、asyncio、pydantic、pytest（`python -m pytest`，conda 环境 `env_news_videos_wf`，路径 `D:/miniconda/envs/env_news_videos_wf/python.exe`）、React+Vite+TS。

设计依据：`docs/superpowers/specs/2026-06-10-scoring-system-redesign.md`

---

## 共享契约（贯穿全计划，务必一致）

- `ScoringResult`（dataclass，定义在 `scoring.py`）：`selected: list[RawArticleData]`、`report: dict`。
- 主入口：`async def select_top(self, articles: list, text_provider=None, language: str = "zh", n: int = 5) -> ScoringResult`。`text_provider=None` → 纯规则分。
- 分项 dict（report.candidates 每项）键名固定：
  `title, source, final, llm, source_w, recency, keyword, rule, reason, tags, llm_ran, selected`。
- 选中项内联（写入 article.metadata，供卡片角标）：`score_final, score_reason`（best-effort）。
- `report` 结构：`{"source_type": str, "n": int, "k": int, "pool": int, "min_score": float, "candidates": [<分项 dict>...]}`（candidates 按 final 降序、含全部候选）。

---

## 文件结构

- `backend/app/services/scoring_constants.py`（新建）— 词表/来源分层/默认权重/参数
- `backend/app/services/scoring.py`（重写）— 子评分器 + `_llm_score` + `select_top` + `ScoringResult`
- `backend/app/config.py` + `config.yaml.example` — `ScoringCfg` + 校验
- `backend/app/prompts.py` — `news_scoring` 中英（中文加中国视野段）
- `backend/app/pipeline/stage2_script.py` — `_aihot_candidates` 填 published_at；`_run_aihot_direct` 调新评分并上抛 report
- `backend/app/pipeline/stage1_collect.py` — `run_stage1` 加 `text_provider/language`、返回 `(articles, report)`
- `backend/app/pipeline/runner.py` — stage1 前构造 tp；写 `scoring.json`；选中项内联角标
- `backend/app/api/pipeline.py` — 读 `scoring.json` 接口
- `frontend/src/api/client.ts`、`frontend/src/pages/Dashboard.tsx`、`frontend/src/pages/Settings.tsx`

---

## Task 1: const 文件 scoring_constants.py

**Files:** Create `backend/app/services/scoring_constants.py`; Test `backend/tests/test_scoring_constants.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_scoring_constants.py
from app.services import scoring_constants as C


def test_constants_present_and_sane():
    assert isinstance(C.SOURCE_TIERS, list) and C.SOURCE_TIERS
    assert all(isinstance(p, str) and 0 < w <= 1 for p, w in C.SOURCE_TIERS)
    assert 0 < C.DEFAULT_SOURCE_WEIGHT <= 1
    assert "anthropic" in " ".join(p for p, _ in C.SOURCE_TIERS).lower()
    # 词表
    assert "openai" in C.POSITIVE_ENTITIES
    assert "中国" in C.CHINA_TERMS
    assert "crypto" in C.NEGATIVE_TERMS
    # 权重 / 参数
    assert abs(C.W_FINAL_LLM + C.W_FINAL_RULE - 1.0) < 1e-9
    assert C.LLM_CONCURRENCY == 5 and C.LLM_CANDIDATE_CAP == 25
    assert C.FRESH_FLOOR < C.FRESH_WEEK_END <= 1.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_scoring_constants.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 const 文件**

```python
# backend/app/services/scoring_constants.py
"""评分系统硬编码集中存放（词表/来源分层/默认权重/参数）。改这里即可调整规则评分。"""

# 来源分层：正则(小写)自上而下首个命中生效，匹配 source_url|source_name；未命中用 DEFAULT_SOURCE_WEIGHT
SOURCE_TIERS: list[tuple[str, float]] = [
    # T1 一手源
    (r"anthropic\.com|openai\.com|deepmind\.google|ai\.meta\.com|mistral\.ai|arxiv\.org", 1.0),
    (r"@(anthropicai|openai|googledeepmind|aiatmeta)\b", 1.0),
    # T2 权威快讯/半一手
    (r"news\.ycombinator\.com|hn\.algolia|hacker news|机器之心|jiqizhixin|量子位|qbitai|marktechpost|theinformation", 0.88),
    # T3 一般科技媒体
    (r"techcrunch|theverge|venturebeat|arstechnica|technologyreview|36kr|36氪|infoq|leiphone|雷锋网|wired", 0.7),
    # T4 搜索/聚合兜底
    (r"tavily|brave|google news|googlenews|serper|duckduckgo", 0.5),
]
DEFAULT_SOURCE_WEIGHT = 0.5

# 关键词（小写子串匹配）
POSITIVE_ENTITIES = [
    "openai", "anthropic", "claude", "gpt", "google", "deepmind", "gemini", "meta", "llama",
    "microsoft", "copilot", "nvidia", "xai", "grok", "mistral", "cohere", "hugging face", "perplexity",
]
POSITIVE_LEADERS = [
    "sam altman", "altman", "dario amodei", "amodei", "demis hassabis", "hassabis", "ilya",
    "karpathy", "lecun", "hinton", "jensen huang", "elon musk",
]
TECH_TERMS = [
    "agent", "agentic", "mcp", "rag", "multimodal", "reasoning", "world model", "embodied",
    "具身", "robotics", "diffusion", "transformer", "fine-tune", "open weights", "开源", "benchmark", "inference",
]
NEGATIVE_TERMS = [
    "crypto", "nft", "bitcoin", "blockchain", "meme coin", "casino", "gambling",
    "加密货币", "比特币", "赌博", "招聘", "hiring", "软文", "广告", "clickbait", "标题党",
]
# 仅中文视野计正向；英文视野剔除"中国"词且此名单不加分
CHINA_TERMS = [
    "中国", "国产", "国产大模型", "信创", "自主可控",
    "阿里", "通义", "qwen", "字节", "豆包", "doubao", "百度", "文心", "ernie", "腾讯", "混元",
    "deepseek", "深度求索", "月之暗面", "kimi", "智谱", "glm", "chatglm", "minimax", "零一万物", "yi",
    "李彦宏", "王小川", "杨植麟", "梁文锋", "李开复",
]

# 默认权重（ScoringCfg 可覆盖）
W_FINAL_LLM, W_FINAL_RULE = 0.6, 0.4
W_SOURCE, W_RECENCY, W_KEYWORD = 0.4, 0.2, 0.4
# 关键词分：基线 + 增减
KW_BASE, KW_ENTITY, KW_TERM, KW_NEG = 0.4, 0.15, 0.08, 0.25
# 新鲜度：0–FULL_DAYS 由 1.0 弱衰减到 WEEK_END；FULL_DAYS–FLOOR_DAYS 衰减到 FLOOR；之后及无时间 = FLOOR
FRESH_FULL_DAYS, FRESH_WEEK_END, FRESH_FLOOR_DAYS, FRESH_FLOOR = 7, 0.9, 30, 0.3
# LLM / 选取
LLM_CONCURRENCY, LLM_CANDIDATE_CAP, MIN_SCORE = 5, 25, 0.35
LLM_TIMEOUT_S, LLM_RETRIES = 30, 1
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_scoring_constants.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/scoring_constants.py backend/tests/test_scoring_constants.py
git commit -m "feat(scoring): 新增 scoring_constants 集中存放词表/来源分层/参数"
```
（commit message 末尾统一加 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`，后续每个 Commit 同。）

---

## Task 2: ScoringCfg 配置 + 校验

**Files:** Modify `backend/app/config.py`、`config.yaml.example`; Test `backend/tests/test_config.py`

- [ ] **Step 1: 写失败测试**（追加到 `test_config.py` 末尾）

```python
def test_scoring_cfg_defaults():
    from app.config import Settings
    s = Settings()
    assert s.scoring.w_final_llm == 0.6 and s.scoring.w_final_rule == 0.4
    assert s.scoring.concurrency == 5 and s.scoring.llm_candidate_cap == 25
    assert s.scoring.min_score == 0.35
    assert s.scoring.fresh_full_days == 7 and s.scoring.fresh_floor_days == 30
    assert s.scoring.fresh_week_end == 0.9 and s.scoring.fresh_floor == 0.3


def test_scoring_cfg_validation_rejects_bad_curve():
    from app.config import ScoringCfg
    # floor > week_end 非法 → 回退默认
    c = ScoringCfg(fresh_floor=0.95, fresh_week_end=0.9)
    assert c.fresh_floor <= c.fresh_week_end
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_config.py -k scoring -v`
Expected: FAIL（无 scoring 属性 / 无 ScoringCfg）

- [ ] **Step 3: 实现**

`config.py` 新增类（放在 `OverlayCfg` 之后），用 pydantic v2 `model_validator` 做曲线校验：

```python
from pydantic import model_validator  # 顶部已 import BaseModel；补 model_validator

class ScoringCfg(BaseModel):
    w_final_llm: float = 0.6
    w_final_rule: float = 0.4
    w_source: float = 0.4
    w_recency: float = 0.2
    w_keyword: float = 0.4
    concurrency: int = 5
    llm_candidate_cap: int = 25
    min_score: float = 0.35            # 0 = 关闭质量地板（硬保 N、可注水）
    fresh_full_days: int = 7
    fresh_week_end: float = 0.9        # 第 7 天的新鲜度值（弱衰减终点）
    fresh_floor_days: int = 30
    fresh_floor: float = 0.3

    @model_validator(mode="after")
    def _check_curve(self):
        # 非法曲线/天数 → 回退默认，避免调出反向上升
        if not (0 <= self.fresh_floor <= self.fresh_week_end <= 1):
            self.fresh_floor, self.fresh_week_end = 0.3, 0.9
        if not (0 < self.fresh_full_days < self.fresh_floor_days):
            self.fresh_full_days, self.fresh_floor_days = 7, 30
        return self
```

`Settings` 类内 `overlay: OverlayCfg = OverlayCfg()` 之后加：

```python
    scoring: ScoringCfg = ScoringCfg()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: config.yaml.example 追加** `scoring:` 段

```yaml
scoring:
  w_final_llm: 0.6
  w_final_rule: 0.4
  w_source: 0.4
  w_recency: 0.2
  w_keyword: 0.4
  concurrency: 5
  llm_candidate_cap: 25
  min_score: 0.35
  fresh_full_days: 7
  fresh_week_end: 0.9
  fresh_floor_days: 30
  fresh_floor: 0.3
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py config.yaml.example backend/tests/test_config.py
git commit -m "feat(config): 新增 ScoringCfg（评分权重/并发/新鲜度参数 + 曲线校验）"
```

---

## Task 3: news_scoring prompt 中英 + 中国视野

**Files:** Modify `backend/app/prompts.py`; Test `backend/tests/test_prompts.py`

- [ ] **Step 1: 写失败测试**（追加到 `test_prompts.py`）

```python
def test_news_scoring_language_lens():
    from app.prompts import resolve_prompt
    zh = resolve_prompt("news_scoring", "zh")
    en = resolve_prompt("news_scoring", "en")
    assert "中国" in zh          # 中文版含中国视野
    assert "中国" not in en       # 英文版纯国际视野
    assert "0-10" in zh and "0-10" in en
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_prompts.py::test_news_scoring_language_lens -v`
Expected: FAIL（中文版当前不含"中国"视野段）

- [ ] **Step 3: 实现** — 在 `prompts.py` 的 `_NEWS_SCORING`（中文）末尾、`输出纯 JSON` 之前插入中国视野段：

```python
# 在 _NEWS_SCORING 的评分维度后、输出格式前插入：
# 视野（中文）：在国际视野基础上，额外重视中国 AI 生态的重要进展——
# 国产大模型、中国头部 AI 企业/实验室、知名华人技术领袖、相关政策与监管；
# 这类高价值的中国相关新闻应给予与国际重磅新闻相当的分数。
```
英文版 `_NEWS_SCORING_EN` 保持纯国际视野不变（不提中国）。确保中文版字符串里确实含"中国"二字。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_prompts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/prompts.py backend/tests/test_prompts.py
git commit -m "feat(prompts): news_scoring 中文版加中国视野段，英文版纯国际视野"
```

---

## Task 4: scoring.py — 子评分器 + ScoringResult（同步纯函数）

**Files:** Rewrite `backend/app/services/scoring.py`(本任务先建子评分器与骨架)；Test `backend/tests/test_scoring.py`(已存在，将替换内容)

- [ ] **Step 1: 写失败测试** — 用新文件覆盖 `backend/tests/test_scoring.py`

```python
import math
from datetime import datetime, timedelta, timezone
from app.providers.base import RawArticleData
from app.services.scoring import ScoringService


def _art(title="t", content="c", url="", source="", published_at=None):
    return RawArticleData(title=title, content=content, source_url=url,
                          source_name=source, published_at=published_at)


def test_source_score_tiers():
    s = ScoringService()
    assert s._source_score(_art(url="https://www.anthropic.com/news/x")) == 1.0
    assert s._source_score(_art(source="Hacker News")) == 0.88
    assert s._source_score(_art(source="TechCrunch")) == 0.7
    assert s._source_score(_art(source="Tavily")) == 0.5
    assert s._source_score(_art(source="某不知名站")) == 0.5  # 未命中默认


def test_recency_score_piecewise():
    s = ScoringService()
    now = datetime.now(timezone.utc)
    assert s._recency_score(now) == 1.0
    assert abs(s._recency_score(now - timedelta(days=7)) - 0.9) < 1e-6   # 端点连续
    assert abs(s._recency_score(now - timedelta(days=30)) - 0.3) < 1e-6  # 端点连续
    assert s._recency_score(now - timedelta(days=60)) == 0.3
    assert s._recency_score(None) == 0.3
    # 单调不增
    assert s._recency_score(now - timedelta(days=3)) > s._recency_score(now - timedelta(days=15))


def test_keyword_score_language_lens():
    s = ScoringService()
    # 中文视野：中国名单计正向
    zh = s._keyword_score("DeepSeek 发布新模型", "国产大模型突破", "zh")
    en = s._keyword_score("DeepSeek 发布新模型", "国产大模型突破", "en")
    assert zh > en                      # 英文视野中国名单不加分
    # 负向减分、clamp 下界
    assert s._keyword_score("crypto casino 招聘", "赌博", "zh") >= 0.0
    # 正向实体加分高于基线
    assert s._keyword_score("OpenAI agent", "", "en") > 0.4


def test_rule_score_normalized():
    s = ScoringService()
    r = s._rule_score(_art(source="Hacker News", title="OpenAI agent",
                           published_at=datetime.now(timezone.utc)), "en")
    assert 0.0 <= r <= 1.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_scoring.py -v`
Expected: FAIL（旧 scoring.py 无这些方法/签名变了）

- [ ] **Step 3: 实现** — 重写 `scoring.py` 头部 + 子评分器（本任务不含 `_llm_score`/`select_top`，下两任务补）

```python
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config import get_settings
from app.logging import get_logger
from app.providers.base import RawArticleData
from app.services import scoring_constants as C

log = get_logger("service.scoring")


@dataclass
class ScoringResult:
    selected: list
    report: dict = field(default_factory=dict)


class ScoringService:
    def __init__(self):
        self.cfg = get_settings().scoring

    # ── 子评分器（0–1）──────────────────────────
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
        if not is_en:  # 中文视野才计中国名单
            for kw in C.CHINA_TERMS:
                if kw in text:
                    score += C.KW_ENTITY
        for kw in C.NEGATIVE_TERMS:
            # 英文视野剔除"中国"词本身（不作负向、也不正向）；其余负向照常
            if kw in text:
                score -= C.KW_NEG
        return max(0.0, min(1.0, score))

    def _rule_score(self, a: RawArticleData, language: str) -> float:
        ws, wr, wk = self.cfg.w_source, self.cfg.w_recency, self.cfg.w_keyword
        tot = ws + wr + wk or 1.0
        return (ws * self._source_score(a)
                + wr * self._recency_score(a.published_at)
                + wk * self._keyword_score(a.title, a.content or "", language)) / tot
```

> 说明：英文视野"剔除中国词"通过"不把 CHINA_TERMS 计正向"实现；NEGATIVE_TERMS 不含"中国"，故不会误判为负向。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_scoring.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/scoring.py backend/tests/test_scoring.py
git commit -m "feat(scoring): 重写子评分器（来源正则分层/分段新鲜度/中英关键词）+ ScoringResult"
```

---

## Task 5: scoring.py — _llm_score（异步 + 缓存 + 语言）

**Files:** Modify `backend/app/services/scoring.py`; Test `backend/tests/test_scoring.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_llm_score_parses_and_passes_language():
    import app.services.scoring as scoring
    scoring._LLM_CACHE.clear()
    tp = AsyncMock()
    tp.generate.return_value = '{"score": 8, "reason": "重要", "tags": ["模型"]}'
    s = ScoringService()
    out = await s._llm_score(_art(title="GPT-5", content="发布"), tp, "zh")
    assert out["score"] == 8 and out["tags"] == ["模型"]
    assert "news_scoring" or True  # system_prompt 已传
    assert "中国" in tp.generate.call_args.kwargs["system_prompt"]  # zh rubric


@pytest.mark.asyncio
async def test_llm_score_cache_hits():
    import app.services.scoring as scoring
    scoring._LLM_CACHE.clear()
    tp = AsyncMock()
    tp.generate.return_value = '{"score": 5, "reason": "", "tags": []}'
    s = ScoringService()
    a = _art(title="same", content="same")
    await s._llm_score(a, tp, "zh")
    await s._llm_score(a, tp, "zh")
    assert tp.generate.call_count == 1   # 第二次命中缓存


@pytest.mark.asyncio
async def test_llm_score_bad_json_fallback():
    import app.services.scoring as scoring
    scoring._LLM_CACHE.clear()
    tp = AsyncMock()
    tp.generate.return_value = "评分：7 分，不错"
    s = ScoringService()
    out = await s._llm_score(_art(), tp, "zh")
    assert out["score"] == 7   # 正则兜底抠数字
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_scoring.py -k llm_score -v`
Expected: FAIL（无 `_llm_score` / `_LLM_CACHE`）

- [ ] **Step 3: 实现** — `scoring.py` 顶部加缓存与解析工具，类内加 `_llm_score`

```python
import asyncio, hashlib, json
from app.prompts import resolve_prompt

_LLM_CACHE: dict[str, dict] = {}   # 模块级；reload_settings() 时清空（见 config.py 改动）

def _parse_json_response(text: str) -> dict | None:
    text = (text or "").strip()
    for attempt in (text,):
        try:
            return json.loads(attempt)
        except Exception:
            pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None
```

类内方法：

```python
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
```

并在 `config.py` 的 `reload_settings()` 里加清缓存（避免改 rubric/配置后缓存脏）：
```python
# reload_settings() 内、重置 _settings 后加：
try:
    from app.services.scoring import _LLM_CACHE
    _LLM_CACHE.clear()
except Exception:
    pass
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_scoring.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/scoring.py backend/app/config.py backend/tests/test_scoring.py
git commit -m "feat(scoring): _llm_score 异步+语言条件+进程内缓存(混入prompt)+超时重试"
```

---

## Task 6: scoring.py — select_top 编排

**Files:** Modify `backend/app/services/scoring.py`; Test `backend/tests/test_scoring.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
@pytest.mark.asyncio
async def test_select_top_small_pool_all_llm(monkeypatch):
    import app.services.scoring as scoring
    scoring._LLM_CACHE.clear()
    tp = AsyncMock()
    tp.generate.return_value = '{"score": 7, "reason": "r", "tags": []}'
    arts = [_art(title=f"t{i}", content="OpenAI agent", source="Hacker News") for i in range(6)]
    s = ScoringService()
    res = await s.select_top(arts, tp, "en", n=3)
    assert len(res.selected) == 3
    assert tp.generate.call_count == 6           # 小池子(≤2K)全量跑 LLM
    assert len(res.report["candidates"]) == 6    # 全候选都在报告里
    assert sum(c["selected"] for c in res.report["candidates"]) == 3
    assert res.report["candidates"][0]["final"] >= res.report["candidates"][-1]["final"]


@pytest.mark.asyncio
async def test_select_top_large_pool_preshortlist(monkeypatch):
    import app.services.scoring as scoring
    scoring._LLM_CACHE.clear()
    monkeypatch.setattr(scoring.C, "LLM_CANDIDATE_CAP", 5)
    # cap=5 → 2K=10；构造 12 篇(>10)触发预筛
    tp = AsyncMock()
    tp.generate.return_value = '{"score": 6, "reason": "", "tags": []}'
    arts = [_art(title=f"t{i}", content="x", source="Tavily") for i in range(12)]
    s = ScoringService()
    s.cfg.llm_candidate_cap = 5
    res = await s.select_top(arts, tp, "en", n=3)
    assert tp.generate.call_count == 5           # 只对预筛 K=5 跑 LLM
    assert len(res.report["candidates"]) == 12   # 但报告含全部，预筛外 llm_ran=false
    assert any(not c["llm_ran"] for c in res.report["candidates"])


@pytest.mark.asyncio
async def test_select_top_min_score_floor(monkeypatch):
    import app.services.scoring as scoring
    scoring._LLM_CACHE.clear()
    tp = AsyncMock()
    tp.generate.return_value = '{"score": 0, "reason": "", "tags": []}'  # 全低分
    s = ScoringService()
    s.cfg.min_score = 0.9
    res = await s.select_top([_art(source="Tavily") for _ in range(4)], tp, "en", n=3)
    assert len(res.selected) == 1                # 全低于地板 → 至少保 1 条


@pytest.mark.asyncio
async def test_select_top_rule_only_when_no_provider():
    s = ScoringService()
    res = await s.select_top([_art(title="OpenAI", source="Hacker News") for _ in range(3)], None, "en", n=2)
    assert len(res.selected) == 2
    assert all(not c["llm_ran"] for c in res.report["candidates"])


@pytest.mark.asyncio
async def test_select_top_llm_all_fail_degrades():
    import app.services.scoring as scoring
    scoring._LLM_CACHE.clear()
    tp = AsyncMock()
    tp.generate.side_effect = Exception("provider down")
    s = ScoringService()
    res = await s.select_top([_art(source="Hacker News") for _ in range(3)], tp, "en", n=2)
    assert len(res.selected) == 2               # 整批失败 → 退回纯规则，不抛
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_scoring.py -k select_top -v`
Expected: FAIL（无 select_top）

- [ ] **Step 3: 实现** — 类内加 `select_top`，并删除旧死代码

```python
    async def select_top(self, articles, text_provider=None, language="zh", n=5) -> ScoringResult:
        if not articles:
            return ScoringResult(selected=[], report={"candidates": [], "n": n, "k": 0, "pool": 0,
                                                      "min_score": self.cfg.min_score, "source_type": ""})
        pool = len(articles)
        cap = self.cfg.llm_candidate_cap
        ws, wr, wk = self.cfg.w_source, self.cfg.w_recency, self.cfg.w_keyword
        wtot = (ws + wr + wk) or 1.0
        # 规则分（全候选），同时留存分项供 report 展示
        scored = []
        for a in articles:
            src = self._source_score(a)
            rec = self._recency_score(a.published_at)
            kw = self._keyword_score(a.title, a.content or "", language)
            rule = (ws * src + wr * rec + wk * kw) / wtot
            scored.append({"art": a, "source_w": src, "recency": rec, "keyword": kw, "rule": rule})
        # 选 LLM 评分集：小池子(≤2K)全量；大池子按 rule 取前 K
        if text_provider is not None and pool > 2 * cap:
            scored.sort(key=lambda x: x["rule"], reverse=True)
            llm_set = scored[:cap]
        else:
            llm_set = scored if text_provider is not None else []
        # 并发跑 LLM
        if llm_set:
            sem = asyncio.Semaphore(self.cfg.concurrency)
            async def run_one(item):
                async with sem:
                    try:
                        r = await self._llm_score(item["art"], text_provider, language)
                        item["llm"] = r["score"] / 10.0
                        item["reason"], item["tags"], item["llm_ran"] = r.get("reason", ""), r.get("tags", []), True
                    except Exception:
                        item["llm_ran"] = False  # 单篇失败 → 仅用规则
            await asyncio.gather(*(run_one(it) for it in llm_set))
        # 合成 final
        for it in scored:
            if it.get("llm_ran"):
                it["final"] = self.cfg.w_final_llm * it["llm"] + self.cfg.w_final_rule * it["rule"]
            else:
                it["final"] = it["rule"]
        scored.sort(key=lambda x: x["final"], reverse=True)
        # 质量地板 + 取前 N（地板后为空则至少保 1 条）
        passed = [it for it in scored if it["final"] >= self.cfg.min_score]
        chosen = (passed or scored[:1])[:n]
        chosen_ids = {id(it) for it in chosen}
        for it in scored:
            it["selected"] = id(it) in chosen_ids
        report = {
            "source_type": (articles[0].metadata or {}).get("aihot_method") or "normal",
            "n": n, "k": cap, "pool": pool, "min_score": self.cfg.min_score,
            "candidates": [self._row(it) for it in scored],
        }
        log.info("[scoring] pool=%d llm=%d selected=%d (min=%.2f)", pool, len(llm_set), len(chosen), self.cfg.min_score)
        # 选中项内联角标写回 metadata（best-effort 展示用）
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
```

> `_row` 直接输出 `source_w/recency/keyword/rule` 四个分项 + `llm` + `final`，满足 spec §8 前端"分项条"。

删除旧代码：`_data_signal_score`、旧 `score`/`score_with_llm`/`select_top`(同步版)/`select_top_with_llm`/`_rule_score`(旧)/`_recency_weight`/`_keyword_relevance`/`_llm_score`(旧)、`DEFAULT_SOURCE_WEIGHTS`/`AI_KEYWORDS`/`NEGATIVE_KEYWORDS`/`FATIGUE_FACTOR`/`PRIOR_WEIGHT`。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_scoring.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/scoring.py backend/tests/test_scoring.py
git commit -m "feat(scoring): select_top 编排(预筛/并发/混合/地板/报告) + 删旧死代码"
```

---

## Task 7: stage2 — _aihot_candidates 填 published_at

**Files:** Modify `backend/app/pipeline/stage2_script.py`; Test `backend/tests/test_stage2_multi.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
def test_aihot_candidates_fill_published_at():
    from app.pipeline.stage2_script import _aihot_candidates
    daily = RawArticleData(title="日报", content="c", source_url="u", source_name="AI HOT 日报",
        metadata={"source_group": "aihot", "aihot_method": "daily", "report_date": "2026-06-01",
                  "daily_sections": [{"label": "模型", "items": [{"title": "x", "summary": "s"}]}]})
    cands = _aihot_candidates([daily])
    assert cands and cands[0].published_at is not None
    assert cands[0].published_at.year == 2026 and cands[0].published_at.month == 6
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_stage2_multi.py -k published_at -v`
Expected: FAIL（published_at 为 None）

- [ ] **Step 3: 实现** — `_aihot_candidates` 内，daily/weekly 分支构造 RawArticleData 时按文章级日期填 published_at

```python
# stage2_script.py 顶部加：
from datetime import datetime, timezone

def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
```
在 `_aihot_candidates` 里，进入循环后取文章级日期：
```python
    for art in articles:
        method = art.metadata.get("aihot_method", "items")
        sections = art.metadata.get("daily_sections")
        pub = _parse_date(art.metadata.get("report_date") or art.metadata.get("week_end")) or art.published_at
        if method in ("daily", "weekly") and sections:
            for sec in sections:
                label = sec.get("label", "")
                for it in sec.get("items", []):
                    out.append(RawArticleData(
                        title=it.get("title", ""), content=it.get("summary", ""),
                        summary=it.get("summary", ""), source_url=art.source_url,
                        source_name=art.source_name, published_at=pub,
                        category=label, metadata={}))
        else:
            out.append(art)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_stage2_multi.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/stage2_script.py backend/tests/test_stage2_multi.py
git commit -m "feat(stage2): AI HOT 候选用文章级日期(report_date/week_end)填 published_at"
```

---

## Task 8: stage2 — _run_aihot_direct 调新评分 + 上抛 report

**Files:** Modify `backend/app/pipeline/stage2_script.py`; Test `backend/tests/test_stage2_multi.py`

- [ ] **Step 1: 写失败测试**（替换原 `test_aihot_daily_direct_use`/`test_aihot_items_direct_use` 中对 `ScoringService` 的隐式假设；新增）

```python
@pytest.mark.asyncio
async def test_aihot_direct_uses_scoring_and_reports(monkeypatch):
    monkeypatch.setattr(config, "_settings",
                        config.Settings(pipeline=config.PipelineCfg(aihot_top_n=2)))
    import app.services.scoring as scoring
    scoring._LLM_CACHE.clear()
    tp = AsyncMock()
    # _llm_score 用 JSON；_gen_image_prompt/_gen_summary_meta 也走 tp.generate
    tp.generate.side_effect = ['{"score": 9, "reason": "a", "tags": []}',
                               '{"score": 5, "reason": "b", "tags": []}',
                               '{"score": 7, "reason": "c", "tags": []}',
                               "画面A", "画面B",
                               json.dumps({"title": "汇总", "description": "d", "tags": []})]
    daily = RawArticleData(title="日报", content="c", source_url="u", source_name="AI HOT 日报",
        metadata={"source_group": "aihot", "aihot_method": "daily", "report_date": "2026-06-01",
                  "daily_sections": [{"label": "模型", "items": [{"title": f"i{i}", "summary": f"s{i}"} for i in range(3)]}]})
    script = await run_stage2_multi([daily], tp)
    assert len(script["scenes"]) == 2                 # top_n=2
    assert script.get("scoring_report") and len(script["scoring_report"]["candidates"]) == 3
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_stage2_multi.py -k reports -v`
Expected: FAIL（仍用旧同步 select_top / 无 scoring_report）

- [ ] **Step 3: 实现** — `_run_aihot_direct` 改用 `await select_top(...)`，从 `ScoringResult.selected` 建 scene，并把 `report` 放进返回 script

```python
async def _run_aihot_direct(articles, tp, language="zh"):
    candidates = _aihot_candidates(articles)
    top_n = config.get_settings().pipeline.aihot_top_n
    res = await ScoringService().select_top(candidates, tp, language, n=top_n)
    selected = res.selected
    scenes, groups, titles = [], [], []
    for i, cand in enumerate(selected, start=1):
        image_prompt = await _gen_image_prompt(cand, tp, language)
        scenes.append({"id": i, "group_id": i, "group_title": cand.title, "title": cand.title,
                       "narration": cand.summary or cand.content, "image_prompt": image_prompt,
                       "motion_prompt": "", "duration_hint": 5})
        groups.append({"id": i, "title": cand.title, "source_index": 0})
        titles.append(cand.title)
    meta = await _gen_summary_meta(titles, tp, language)
    return {"title": meta["title"], "description": meta["description"], "tags": meta["tags"],
            "groups": groups, "scenes": scenes, "scoring_report": res.report}
```
（`ScoringService` 已在 Task 3 import；确认 stage2 顶部 `from app.services.scoring import ScoringService` 在。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_stage2_multi.py -v`
Expected: PASS（旧 aihot 测试若因 tp.generate.side_effect 顺序变化失败，按"_llm_score 先于 image_prompt/meta"的新调用顺序更新它们的 side_effect）

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/stage2_script.py backend/tests/test_stage2_multi.py
git commit -m "feat(stage2): AI HOT 直用接入新评分(LLM+规则)，report 随 script 上抛"
```

---

## Task 9: stage1 — run_stage1 加 tp/language、返回 (articles, report)

**Files:** Modify `backend/app/pipeline/stage1_collect.py`; Test `backend/tests/test_stage1.py`

- [ ] **Step 1: 写失败测试**（追加；并把已有 `test_aihot_items_passthrough_all` 的返回改为解包元组）

```python
@pytest.mark.asyncio
async def test_run_stage1_normal_scores_and_returns_report():
    from app.pipeline.stage1_collect import run_stage1
    tp = AsyncMock()
    tp.generate.return_value = '{"score": 8, "reason": "r", "tags": []}'
    arts = [RawArticleData(title=f"OpenAI {i}", content="agent", source_url="u", source_name="Hacker News") for i in range(4)]

    class Col:
        async def collect(self, source_config, time_range): return arts

    selected, report = await run_stage1(sources=[{"type": "rss", "name": "x"}],
        collectors={"rss": Col()}, max_articles=2, text_provider=tp, language="en")
    assert len(selected) == 2
    assert report and report["pool"] == 4
```
并把现有 `test_aihot_items_passthrough_all` 末尾改为：
```python
    selected, report = await run_stage1(sources=[{"type": "aihot", "name": "AI HOT"}],
                           collectors={"aihot": Col()}, max_articles=5)
    assert len(selected) == 15
    assert report is None        # AI HOT passthrough 不在 stage1 评分
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_stage1.py -v`
Expected: FAIL（run_stage1 返回 list、无 text_provider 形参）

- [ ] **Step 3: 实现** — `run_stage1` 改签名与返回

```python
from app.services.scoring import ScoringService  # 顶部已 import？没有则加

async def run_stage1(sources, collectors, time_range="7d", max_articles=5,
                     history_fingerprints=None, text_provider=None, language="zh"):
    # ... 采集逻辑不变，得到 all_articles ...
    # AI HOT 分支：return all_articles, None（daily/weekly: [:1]；items: 全量）
    # 普通源分支末尾改为：
    dedup = DedupService()
    deduplicated = dedup.deduplicate(all_articles, history_fingerprints)
    compliant = _filter_compliant(deduplicated)
    res = await ScoringService().select_top(compliant, text_provider, language, n=max_articles)
    log.info("Selected top %d (from %d compliant)", len(res.selected), len(compliant))
    return res.selected, res.report
```
AI HOT 的两个 `return` 改为 `return all_articles[:1], None` / `return all_articles, None`。**所有 return 都改成返回二元组**（包括"全部源失败"前的早退，如果有 return 也要带 None；ProviderError 抛出不受影响）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_stage1.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/stage1_collect.py backend/tests/test_stage1.py
git commit -m "feat(stage1): run_stage1 接入新评分，返回 (selected, report)"
```

---

## Task 10: runner — 提前构造 tp、写 scoring.json、内联角标

**Files:** Modify `backend/app/pipeline/runner.py`、`backend/app/api/pipeline.py`; Test `backend/tests/test_runner_articles.py`

- [ ] **Step 1: 写失败测试**（runner 写 scoring.json 的轻量单测 + API）

```python
# test_runner_articles.py 追加：scoring.json 写盘工具
def test_write_scoring_json(tmp_path):
    from app.pipeline.runner import _write_scoring_json
    _write_scoring_json(tmp_path, {"pool": 3, "candidates": []})
    import json
    data = json.loads((tmp_path / "scoring.json").read_text(encoding="utf-8"))
    assert data["pool"] == 3
    # None 不写文件、不报错
    _write_scoring_json(tmp_path / "nope", None)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_runner_articles.py -k scoring_json -v`
Expected: FAIL（无 `_write_scoring_json`）

- [ ] **Step 3: 实现** — runner

(a) 新增工具：
```python
def _write_scoring_json(run_dir, report):
    if not report:
        return
    import json
    try:
        (Path(run_dir) / "scoring.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        log.warning("write scoring.json failed", exc_info=True)
```

(b) stage1 调用处（约 544）：先提前构造 tp，并解包二元组、写 scoring.json
```python
            text_provider = _build_text_provider()   # 提前到 stage1 前构造，供评分用；stage2 复用此变量
            articles, scoring_report = await run_stage1(
                sources=source_configs, collectors=collectors,
                time_range=run.time_range, max_articles=run.max_articles,
                history_fingerprints=history_fps,
                text_provider=text_provider, language=(run.language or cfg.pipeline.default_language))
            _write_scoring_json(run_dir, scoring_report)   # 普通源评分明细
```
把 stage2 处（约 591）的 `text_provider = _build_text_provider()` 删除（复用上面的变量；注意作用域——若 stage1 在 `if` 分支内构造，需把 `text_provider` 提到外层，或 stage2 仍兜底构造一次：`text_provider = text_provider or _build_text_provider()`）。

(c) stage2 之后：AI HOT 的 report 在 `script["scoring_report"]`，写盘
```python
        # run_stage2_multi 返回 script 后：
        _write_scoring_json(run_dir, script.get("scoring_report"))
```

(d) 内联角标落库：`_save_articles` 的 dict 增 `"score_final": a.metadata.get("score_final")`、`"score_reason": a.metadata.get("score_reason")`；`_article_from_dict` 对应恢复（`if d.get("score_final") is not None: metadata["score_final"] = d["score_final"]`，score_reason 同）。在 `test_runner_articles.py` 加一条 round-trip 断言：带 `score_final` 的 article 经 `_save_articles`→`_load_articles` 后仍在。

(e) API（`api/pipeline.py`）新增读接口：
```python
@router.get("/runs/{run_id}/scoring")
def get_scoring(run_id: int):
    run_dir = get_settings().runs_root() / str(run_id)
    p = run_dir / "scoring.json"
    if not p.exists():
        return {"candidates": []}
    return json.loads(p.read_text(encoding="utf-8"))
```
（按该文件现有 router/依赖/鉴权风格写；run_dir 取法参照 `get_articles`。）

- [ ] **Step 4: 跑测试 + 全回归**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest -q`
Expected: PASS（全绿；重点 test_runner_*、test_stage1、test_stage2_multi、test_scoring*）

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/runner.py backend/app/api/pipeline.py backend/tests/test_runner_articles.py
git commit -m "feat(runner): 提前构造 tp 供评分；两接入点写 scoring.json；新增读取接口"
```

---

## Task 11: 前端 — 评分明细面板 + 内联角标 + 评分设置 tab

**Files:** Modify `frontend/src/api/client.ts`、`frontend/src/pages/Dashboard.tsx`、`frontend/src/pages/Settings.tsx`

- [ ] **Step 1: client.ts 加类型与读取**

```ts
// AppSettings.scoring 类型
scoring: { w_final_llm: number; w_final_rule: number; w_source: number; w_recency: number;
  w_keyword: number; concurrency: number; llm_candidate_cap: number; min_score: number;
  fresh_full_days: number; fresh_week_end: number; fresh_floor_days: number; fresh_floor: number; };
// runs 接口加：
scoring: (id: number) => fetchJSON<{ candidates: { title: string; source: string; final: number;
  llm: number | null; rule: number; source_w?: number; recency?: number; keyword?: number;
  reason: string; tags: string[]; llm_ran: boolean; selected: boolean }[]; pool?: number; n?: number }>(`/runs/${id}/scoring`),
```

- [ ] **Step 2: Dashboard 评分明细面板**

在 `S1Panel`（搜索整理页）加一个可折叠「评分明细」区块：`useSWR(\`scoring-${runId}\`, () => api.runs.scoring(runId))`，按 `final` 降序列出候选——每行显示 `最终分徽标 + 标题 + 来源 + (LLM/来源/新鲜/关键词 分项小条) + 理由 + tags + 选中标记`。仿现有卡片样式（`cardCls` 等）。文章卡上对"已选中"项加一个 `score_final` 小角标（来自 articles.json 的 `score_final` 内联字段，可空）。

- [ ] **Step 3: Settings 评分 tab**

参照现有 `overlay`/`hyperframes` 表单写法，新增「评分」分组，暴露 `scoring` 的标量：权重(w_*)、concurrency、llm_candidate_cap、min_score、fresh_* 数字输入；保存走现有 `api.settings.save` 通道。词表/来源分层不在此（const 文件）。

- [ ] **Step 4: 校验**

Run: `cd frontend && pnpm build`（pnpm 不可用试 npm run build）
Expected: build 成功，无类型错误；`pnpm lint` 不引入新错误。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/pages/Dashboard.tsx frontend/src/pages/Settings.tsx
git commit -m "feat(ui): 评分明细面板 + 内联分数角标 + 评分设置 tab"
```

---

## 收尾验证

- [ ] 全后端：`cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest -q` 全绿
- [ ] 前端：`cd frontend && pnpm build` 通过
- [ ] 手动冒烟（用户自跑后端）：建一个普通源 run + 一个 AI HOT 日报 run，确认搜索整理页「评分明细」面板有数据、分项合理、选中项与 N/min_score 一致；改设置页权重后重跑生效；中/英语言下中国相关条目排序差异符合预期。

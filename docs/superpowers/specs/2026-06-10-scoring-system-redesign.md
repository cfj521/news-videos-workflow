# 评分系统重设计

> 设计日期：2026-06-10
> 状态：待评审

## 背景与问题

当前 `ScoringService`（`backend/app/services/scoring.py`）只有规则分在生效，存在硬伤：

- **数据信号只对 Hacker News 有效**（只有 HN 采集器写 `points`/`num_comments`），其余源恒 0.5；且归一化使真实热文常落到 0.5 以下，反而拖低 HN 文章。
- **对 AI HOT 几乎失效**：item 包成 RawArticleData 后来源不在权重表(0.5)、无 points(数据信号 0.5)、无 `published_at`(新鲜度 0.3)，只有关键词在变 → "取前 N" 近乎原序。
- **LLM 评分建好但没人调用**（`score_with_llm`/`select_top_with_llm`/`_llm_score` 全是死代码），且永远用中文 prompt。
- 新鲜度衰减过猛（7 天线性归零），不适合非时效类内容。
- 硬编码（来源权重、词表）散落、难管理；评分过程对用户不透明。

## 目标

1. **统一评分公式**：`final = 0.6·LLM_norm + 0.4·rule`，`rule = 0.4·来源 + 0.2·新鲜度 + 0.4·关键词`（均归一 0–1，权重可配）。
2. **来源权重分层**（按域名/正则匹配，4 层 + 未知兜底）。
3. **新鲜度弱衰减**：0–7 天近乎不衰减，7–30 天加大衰减，>30 天及无时间触底。
4. **关键词中英"视野"条件化**：中文视野含中国正向名单；英文视野剔除"中国"且中国名单不加分。
5. **抛弃数据信号**这条规则。
6. **LLM 评分接入为主力**，rubric 保持"AI 技术重要性"导向、按语言条件化（国际视野 / +中国视野），**默认 5 并发**。
7. **统一两个接入点**（普通源 + AI HOT）走同一评分，并加**规则预筛**控成本。
8. **透明化**：分项分数落库 + 详细日志 + 前端展示。
9. **硬编码集中到 const 文件**；标量调参进设置页。

## 非目标

- 多样性 / 防偏科 / 按 section 配额（沿用"全局按分取前 N"，留接口位，本次不做）。
- 词表 / 来源分层进设置页 UI（放 const 文件，改文件即可）。
- 跨进程持久化的 LLM 评分缓存（本次只做进程内缓存）。

---

## 核心数据流

```
候选 articles[]
  → 规则分(免费): rule = 0.4·source + 0.2·recency + 0.4·keyword   （全部候选都算）
  → 选 LLM 评分集：池子 ≤ 2·K → 全部跑 LLM；池子 > 2·K → 按 rule 取前 K 篇预筛
  → 对评分集并发(默认5)跑 LLM（带缓存、超时+重试、单篇失败回退规则）
  → final = 0.6·(LLM/10) + 0.4·rule
  → 过质量地板 min_score（默认 0.35），按 final 降序取前 N（N 为上限，条数可浮动）
  → 全候选分项 + 选中标记 → 写一份 run 级 scoring.json（透明化载体）；选中项内联分数随各自载体落库；输出日志
```

预筛把 LLM 调用数钉死在 K。**小池子（≤ 2·K）直接全量跑 LLM**，规避"规则分判别力被削弱（AI HOT recency 恒地板、同源同档）导致漏召回"的风险；只有大池子才预筛。

---

## 组件设计

### 1. const 文件（`backend/app/services/scoring_constants.py`，新建）

集中存放所有硬编码默认值：

```python
# 来源分层：按域名/正则匹配（自上而下首个命中生效），未命中用 DEFAULT_SOURCE_WEIGHT
SOURCE_TIERS: list[tuple[str, float]] = [
    # T1 一手源 0.95–1.0
    (r"anthropic\.com|openai\.com|deepmind\.google|ai\.meta\.com|mistral\.ai|arxiv\.org", 1.0),
    (r"@(AnthropicAI|OpenAI|GoogleDeepMind|AIatMeta)\b", 1.0),
    # T2 权威快讯/半一手 0.85–0.9
    (r"news\.ycombinator\.com|hn\.algolia|机器之心|jiqizhixin|量子位|qbitai|marktechpost|theinformation", 0.88),
    # T3 一般科技媒体 0.65–0.75
    (r"techcrunch|theverge|venturebeat|arstechnica|technologyreview|36kr|36氪|infoq|leiphone|雷锋网|wired", 0.7),
    # T4 搜索/聚合兜底 0.45–0.55
    (r"tavily|brave|google news|googlenews|serper|duckduckgo", 0.5),
]
DEFAULT_SOURCE_WEIGHT = 0.5

# 关键词表（命中用小写子串匹配；中英分列）
POSITIVE_ENTITIES = ["openai","anthropic","google","deepmind","meta","microsoft","nvidia","xai","mistral","cohere", ...]
POSITIVE_LEADERS  = ["altman","amodei","hassabis","ilya","karpathy","lecun","hinton","jensen huang","musk", ...]
TECH_TERMS        = ["agent","mcp","rag","multimodal","reasoning","world model","robotics","具身","diffusion","开源", ...]
NEGATIVE_TERMS    = ["crypto","nft","bitcoin","赌博","招聘","clickbait","软文", ...]
# 仅中文视野计正向；英文视野剔除"中国"词且此名单不加分
CHINA_TERMS       = ["中国","国产大模型","信创","阿里","通义","字节","豆包","百度","文心","腾讯","混元",
                     "deepseek","深度求索","月之暗面","kimi","智谱","glm","minimax","零一万物",
                     "李彦宏","王小川","杨植麟","梁文锋","李开复", ...]

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

（以上 `...` 在实现时按设计的扩展词表补全，spec 末尾「词表清单」给出完整内容。）

### 2. `ScoringCfg`（`config.py` + `config.yaml` 新 `scoring` 段）

只镜像**标量可调项**，默认值取自 const，设置页可编辑：

```python
class ScoringCfg(BaseModel):
    w_final_llm: float = 0.6
    w_final_rule: float = 0.4
    w_source: float = 0.4
    w_recency: float = 0.2
    w_keyword: float = 0.4
    concurrency: int = 5
    llm_candidate_cap: int = 25
    min_score: float = 0.35       # 0 = 关闭质量地板（退化为硬保 N、可注水）
    fresh_full_days: int = 7
    fresh_week_end: float = 0.9   # 第 7 天的新鲜度值（弱衰减终点）
    fresh_floor_days: int = 30
    fresh_floor: float = 0.3
```

词表、来源分层不进此处（在 const 文件）。
**加载时校验**：`0 ≤ fresh_floor ≤ fresh_week_end ≤ 1`、`fresh_full_days < fresh_floor_days`，违反则回退默认值并记 warning（防止调出反向上升的曲线）。

### 3. `ScoringService` 重写（`services/scoring.py`）

**对外主入口**：
```python
async def select_top(self, articles, text_provider=None, language="zh", n=5) -> list[RawArticleData]:
    """规则预筛 → LLM 并发评分 → final 混合 → 过地板取前 N。
    text_provider 为 None 时退回纯规则分（向后兼容/降级）。"""
```

**内部单元（各自可单测）**：
- `_source_score(article) -> float`：按 `SOURCE_TIERS` 正则匹配 `source_url`/`source_name`，未命中 `DEFAULT_SOURCE_WEIGHT`。
- `_recency_score(published_at) -> float`：分段线性插值，无时间 → `fresh_floor`。设 `d` 为天数：
  - `d ≤ fresh_full_days`：`1.0 - (1.0 - fresh_week_end)·(d / fresh_full_days)`（1.0→0.9 弱衰减）
  - `fresh_full_days < d ≤ fresh_floor_days`：`fresh_week_end - (fresh_week_end - fresh_floor)·((d - fresh_full_days)/(fresh_floor_days - fresh_full_days))`（0.9→0.3）
  - `d > fresh_floor_days`：`fresh_floor`。两段在 d=7、d=30 端点连续。
- `_keyword_score(title, content, language) -> float`：基线 + 实体/领袖/技术词加分 − 负向减分，clamp 0–1；`language` 决定中国名单是否计入（en：剔除"中国"词、中国名单不加分）。
- `_rule_score(article, language) -> float`：`w_source·source + w_recency·recency + w_keyword·keyword`（权重归一）。
- `_llm_score(article, tp, language) -> dict`：拼 `标题+来源+正文前1000字+(若有)社区互动`，`system_prompt=resolve_prompt("news_scoring", language)`（**修掉恒中文 bug**），5 层兜底 JSON 解析；带**进程内缓存**（key = `sha256(title + content[:1000] + language + 当前 news_scoring prompt 文本)`——混入 prompt 文本，**编辑 rubric 后旧缓存自动失效**；缓存为模块级 dict，`reload_settings()` 时清空）、超时 `LLM_TIMEOUT_S`、重试 `LLM_RETRIES`。
- `select_top`：编排上面的数据流，`asyncio.Semaphore(concurrency)` 控并发；回填分项；输出日志。

**删除**：`_data_signal_score`、`score`/`score_with_llm`/`select_top_with_llm`（旧接口）、`FATIGUE_FACTOR`/`PRIOR_WEIGHT`/`DEFAULT_SOURCE_WEIGHTS`/`AI_KEYWORDS`/`NEGATIVE_KEYWORDS`（迁入 const）。

### 4. 分项落库：统一的 `scoring.json` 透明化载体

评分横跨两种载体（普通源进 articles.json、AI HOT 进 stage2 临时候选→scenes），直接塞进各自载体既不统一、又有"前端编辑文章丢分""AI HOT 候选不落 articles.json"的问题。**改为：每个 run 额外落一份 `scoring.json` 作为唯一权威的评分明细载体。**

`scoring.json`（`run_dir/scoring.json`）：
```json
{
  "source_type": "aihot-daily | aihot-weekly | aihot-items | normal",
  "n": 10, "k": 25, "pool": 42, "min_score": 0.35,
  "candidates": [
    {"title": "...", "source": "...",
     "final": 0.81, "llm": 0.9, "source_w": 0.88, "recency": 0.9, "keyword": 0.55,
     "reason": "...", "tags": ["..."], "llm_ran": true, "selected": true},
    ...   // 全部候选，按 final 降序；预筛外的 llm=null/llm_ran=false/final=rule/selected=false
  ]
}
```
- 由 `select_top` 返回结构化结果，runner 在调用后写盘（普通源 stage1、AI HOT stage2 各写一次；后写覆盖/合并由实现决定，单源场景天然唯一）。
- **不入 articles.json / scenes 的白名单**，因此不受"文章被人工编辑"影响——评分明细恒在。
- **次要内联**：选中项可顺带把 `score_final`/`score_reason` 写到各自载体（articles.json 普通源、script.json scenes 的 AI HOT）供卡片/分镜内联角标；这是 best-effort 展示，不作为权威，编辑丢了也不影响 scoring.json。
- articles API **无需改**（articles.json 原样透传）；新增一个读 `scoring.json` 的轻量接口或复用 run 详情接口给前端。

### 5. 新鲜度真正生效（关键）

⚠️ 评审纠正：**daily_sections 的 item 没有 `date` 字段**（weekly 经 distill 提炼后也丢了 date），按 item.date 填 published_at 会落空。改用**文章级日期**——这些字段确实在 `art.metadata` 里：
- **daily**：`art.metadata["report_date"]`（该日日报的日期），同篇所有 item 共用。
- **weekly**：`art.metadata["week_end"]`（该周结束日），整周主题共用（跨天主题本无单一日期，按周末算合理）。
- **items**：`art.published_at` 本就存在，原样用。

`_aihot_candidates` 据此给每个候选填 `published_at = parse(report_date or week_end or art.published_at)`。无需改采集器。否则 AI HOT 新鲜度恒为地板、本设计形同虚设。

### 6. LLM rubric 语言条件化（`prompts.py`）

`news_scoring` 中英两版：
- 主体 rubric（0–10 档位 + AI 技术重要性维度）**不变**。
- **中文版**追加"中国视野"段：在国际视野基础上，额外重视中国 AI 生态（国产大模型、中国企业/人物/政策）的重要进展。
- **英文版**为纯国际视野（不含中国偏向）。
- `_llm_score` 传 `language` → `resolve_prompt("news_scoring", language)`。

### 7. 接入点（同一个 `select_top`，但在两个不同 stage）

两接入点用同一方法，但所处 stage 与 tp 来源不同，需分别处理：

- **普通源**（`stage1_collect.run_stage1`，**stage1**）：增 `text_provider`/`language` 形参；去重→合规后 `await select_top(compliant, text_provider, language, n=max_articles)`。
  - ⚠️ runner 里文本 provider 现在到 **stage2 才构造**（`runner.py` 约 591），需**提前到 stage1 调用前**构造一次 `_build_text_provider()` 并传入；仅实例化、无 API 调用，代价小。tp 构造失败时传 None → 纯规则降级。
  - 注意 `run_stage1` 内 AI HOT 是 passthrough（不在此评分），故此处加 tp **只对普通源生效**。
- **AI HOT 直用**（`stage2._run_aihot_direct`，**stage2**）：该函数已有 `tp`/`language`；候选归一(并按 §5 补 published_at)后 `await select_top(candidates, tp, language, n=aihot_top_n)`（现状是同步规则版，改为 await 新版）。
- 两者沿用"全局按分取前 N"；各自评分后写 `scoring.json`（§4）。

### 8. 日志 + 前端

- **日志**：每篇一行 `S? score=.. (llm=../src=../fresh=../kw=..) '标题'`；run 级一条汇总（候选数/预筛 K/选中 N/分数 min·max·均值/LLM 失败数/缓存命中数/全量或预筛）。
- **前端**：读 `scoring.json`，在搜索整理页（或 run 详情）加一个**可折叠「评分明细」面板**——按 final 降序列出全部候选的 `最终分 + LLM/来源/新鲜/关键词 分项条 + 理由 + tags + 选中标记`。这是统一展示，覆盖普通源与 AI HOT 三模式。
- **内联（次要）**：选中项卡片/分镜上显示 `最终分徽标 + 一句理由`（来自内联角标，best-effort）。`client.ts` 加 scoring.json 的类型与读取接口。

### 9. 健壮性

- LLM provider 不可用 / 全部失败 → 整批退回纯规则分，流水线不中断。
- 权重防御性归一（和为 0 时回退等权）。
- `min_score` 过滤后若为空，至少返回 final 最高的 1 条（避免空视频）。

---

## 测试

- `scoring_constants` 加载、来源正则分层匹配（各 tier + 未知兜底）。
- `_recency_score` 分段（0/3/7/15/30/60 天、无时间）。
- `_keyword_score` 中英条件化（中国名单中文计入、英文不计入；正负向增减、clamp）。
- `_rule_score` 权重归一。
- `_llm_score`：mock provider，断言传入 `language` 对应 prompt；JSON 解析兜底；缓存命中不二次调用。
- `select_top`：小池子(≤2K)全量跑 LLM、大池子预筛只跑前 K（mock 断言调用次数）；并发；单篇失败降级；整批 LLM 失败→纯规则；min_score 过滤 + 取前 N；空结果至少 1 条；`text_provider=None` 纯规则；返回结构化结果含全候选分项。
- AI HOT 候选 `published_at` 由 `report_date`/`week_end`/`art.published_at` 填充（三模式各一例）。
- `scoring.json` 写盘内容正确（全候选、selected 标记、预筛外 llm_ran=false/final=rule）。
- 新鲜度分段端点连续（d=7、d=30）；ScoringCfg 非法值（floor>week_end 等）回退默认。
- 缓存：编辑 prompt 后 key 变化、不命中旧值。

## 影响文件

- 新建：`backend/app/services/scoring_constants.py`
- 重写：`backend/app/services/scoring.py`（select_top 返回结构化全候选结果）
- 改：`config.py`(ScoringCfg + 加载校验)、`config.yaml.example`、`prompts.py`(news_scoring 中英 + 中国视野段)、
  `pipeline/stage1_collect.py`(run_stage1 加 tp/language 形参、调新 select_top)、
  `pipeline/stage2_script.py`(_run_aihot_direct 调新 select_top + _aihot_candidates 按 report_date/week_end 补 published_at)、
  `pipeline/runner.py`(stage1 前提前构造 tp 并传入；评分后写 scoring.json；选中项内联角标 best-effort)、
  `api/pipeline.py`(新增读 scoring.json 的接口)、
  `frontend/src/api/client.ts`(scoring.json 类型+读取)、`frontend/src/pages/Dashboard.tsx`(评分明细面板+内联角标)、`frontend/src/pages/Settings.tsx`(评分 tab)
- 删除：scoring.py 内数据信号与旧接口相关代码
- **不改**：articles API（articles.json 原样透传，scoring 走独立 scoring.json）

## 附：扩展词表清单（const 文件最终内容）

实现时按此填充（可在 const 文件继续增删）：
- **POSITIVE_ENTITIES**：openai, anthropic, google, deepmind, gemini, meta, llama, microsoft, copilot, nvidia, xai, grok, mistral, cohere, stability, hugging face, perplexity, midjourney（中文视野另加：阿里/通义/qwen, 字节/豆包/doubao, 百度/文心/ernie, 腾讯/混元, deepseek/深度求索, 月之暗面/kimi, 智谱/glm/chatglm, minimax, 零一万物/yi, 商汤, 科大讯飞）
- **POSITIVE_LEADERS**：sam altman, dario amodei, demis hassabis, ilya sutskever, andrej karpathy, yann lecun, geoffrey hinton, jensen huang, elon musk, mira murati, noam shazeer（中文：李彦宏, 王小川, 杨植麟, 梁文锋, 李开复, 周鸿祎, 王坚）
- **TECH_TERMS**：agent, agentic, mcp, rag, multimodal, reasoning, o1, o3, world model, embodied/具身智能, robotics, diffusion, transformer, fine-tune, open weights/开源权重, benchmark, context window, inference, training
- **NEGATIVE_TERMS**：crypto, nft, bitcoin, blockchain, meme coin, casino, gambling, 加密货币, 比特币, 赌博, 招聘, hiring, 软文, 广告, clickbait, 标题党
- **CHINA_TERMS**（仅中文视野计正向）：中国, 国产, 国产大模型, 信创, 自主可控 + 上述中文企业/人物名单

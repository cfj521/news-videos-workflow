# AI HOT 周报模式 — 设计文档

## 背景与目标

AI HOT (`aihot.virxact.com`) 现有两种采集模式：`items`（动态/精选）与 `daily`（每日日报，整份日报生成一条汇总视频，详见 [`2026-05-28-aihot-source-group-design.md`](2026-05-28-aihot-source-group-design.md)）。

现在新增第三种模式 `weekly`（周报）。**AI HOT 没有官方周报 API**，只有日报。所以周报由我们自己把**上一个完整自然周（周一~周日）**的每日日报聚合、再经文本 AI **跨天提炼成几个本周热点主题**后生成一条"本周 AI 热点回顾"汇总视频。

目标：

1. 新增 `weekly` 模式，与 `items` / `daily` 并列、三选一。
2. 周报覆盖**上一个完整自然周**（今天若是周一，则取上周一~上周日）。该周缺失的某天直接跳过。
3. 周报视频内容是**AI 提炼的本周热点主题**（不是一周资讯的机械堆砌）：归纳成 3-5 个主题，每主题 1-3 条代表性资讯，总分镜 ≤10，复用 daily 的"主题分组→分镜"布局。

## 非目标 (YAGNI)

- 不加 DB 列、不引入迁移（沿用 `config_json.method` 字段，组身份仍由 collector 派生）。
- 不改 collector 持有/注入文本 provider 的契约——collector 保持纯抓取，AI 提炼放在 Stage1 整理层。
- 不支持自定义周范围（固定"上一个完整自然周"）。
- 不缓存/持久化周报中间结果（每次运行重新聚合）。
- 不动 daily / items 的现有行为。

## 关键设计决策

### D1 — 分层：提炼属于「整理(Processor/Stage1)」层，不属于「脚本(Stage2)」层

Pipeline 实际编号：**Stage1 采集 → Stage2 脚本(分镜)生成 → Stage3 图片/配音 → Stage4 合成 → Stage5 发布**。

"把一周日报跨天提炼成几个主题热点"本质是**内容整理/摘要**，对应架构中的 **Processor** 职责，与普通源的 `_summarize_articles` 同一层（Stage1 采集之后）。因此：

- **Collector** 只负责抓取与扁平汇总，**不调 AI**。
- **提炼**放在 runner 的 Stage1 整理阶段（与 `_summarize_articles` 平行），产出主题 `sections` 写回 article。
- **Stage2** 拿到的 weekly article 已带 `daily_sections`，与 daily 走**完全相同**的分组→分镜路径，仅放宽一处分支判断。

职责干净：提炼=整理层，分镜=脚本层；daily 的分镜逻辑零改动复用。

### D2 — 复用 daily 的 `daily_sections` 形状

提炼输出的主题结构形状与 daily 的 `daily_sections` 一致：`[{label, items:[{title, summary}]}]`。写回 `article.metadata["daily_sections"]` 后，`run_stage2_multi` 的现有 daily 分支直接接管，无需新的分镜代码。

### D3 — 采集+整理共享 helper，杜绝主流程 / reroll 分叉

提炼这步必须同时作用于 runner 主流程（`_run_inner`）与 `api/pipeline._reroll_articles_async`（"重新采集文章"）。沿用原 aihot 设计文档 §10 的建议，把"weekly 提炼"封装成一个共享 helper（如 `_distill_weekly_if_needed(articles, cfg, ...)`），两处都调，避免行为分叉。

## AI HOT API 参考（本设计用到的端点）

| 端点 | 方法 | 返回（节选） | 本设计用途 |
|---|---|---|---|
| `/api/public/dailies` | GET | `{count, items:[{date, generatedAt, leadTitle, leadParagraph}]}` | 发现该周**实际存在**的日报日期 |
| `/api/public/daily/{YYYY-MM-DD}` | GET | `{date, lead:{title,leadParagraph}, sections:[{label, items:[{title,summary,...}]}], flashes:[...]}` | 逐天拉取日报全文 |

> daily 的 section.item 字段为 `{title, summary, sourceUrl, sourceName}`；提炼只用到 `title` / `summary`（外加来源天的 `date`、原 `label` 作为分类线索）。

## 详细设计

### 1. Collector — `backend/app/providers/collector/aihot.py`

`AIHotCollector.collect()` 增加 `method == "weekly"` 分支 → 新方法 `_collect_weekly(source_config)`。

**周范围计算**：取"上一个完整自然周"。

```
today = date.today()                         # 本地日期
this_monday = today - timedelta(days=today.weekday())
week_start  = this_monday - timedelta(days=7)   # 上周一
week_end    = this_monday - timedelta(days=1)   # 上周日
```

**抓取流程**：

1. `GET /api/public/dailies` 拿归档列表；筛出 `week_start <= date <= week_end` 的日期（升序）。
2. 对每个日期 `GET /api/public/daily/{date}`（404 / 异常 → 跳过该天，记 warning，不中断）。
3. 汇总成**一篇** `RawArticleData`：
   - `title` = `f"本周 AI 热点回顾 {week_start}~{week_end}"`
   - `content` = 结构化兜底文本：各天 `lead.leadParagraph` + 该天各 section 下 `「title」summary`（供预览 / 提炼失败兜底）
   - `summary` = 第一天或综合的 leadParagraph（取首个可用）
   - `source_name` = `"AI HOT 周报"`，`aggregator_url` = `https://aihot.virxact.com`，`category` = `"ai"`
   - `metadata` = `{"source_group":"aihot", "aihot_method":"weekly", "week_start":<iso>, "week_end":<iso>, "weekly_items":[{title, summary, category, date}...]}`
     - `weekly_items` 为**全周扁平条目**（含 flashes，category 用原 section.label 或 item.category）。供 Stage1 提炼输入。
4. 该周一份日报都没有（`weekly_items` 为空）→ 返回 `[]`，由 runner 给周报专属错误文案（见 §4）。

`time_range` / `max_items` 在 weekly 下无意义，忽略（同 daily）。

### 2. Stage1 整理层 — weekly 提炼 helper（runner + reroll 共享）

文件落点（固定，避免循环依赖）：

- **提示词 `WEEKLY_DIGEST_SYSTEM_PROMPT` + 纯提炼函数 `distill_weekly_sections(weekly_items, text_provider) -> sections`** 放 `backend/app/pipeline/stage2_script.py`（与其它提示词/AI 函数同处）。
- **编排 helper `_distill_weekly_if_needed(articles, text_provider, log)`**（检测 weekly → 调上面的提炼函数 → 写回 `daily_sections`）放 `backend/app/pipeline/runner.py`；`api/pipeline._reroll_articles_async` 已从 runner import 其它 helper，照样 import 它。

提炼细节：

- `WEEKLY_DIGEST_SYSTEM_PROMPT`：定位"AI 资讯周报编辑"，输入是一周的全部资讯条目，要求归纳出**本周 3-5 个最重要的热点主题**，每个主题 1-3 条代表性资讯，**总条数 ≤ 9**；体现"本周"视角（趋势/归纳，去重跨天重复报道）。输出纯 JSON：
  ```json
  {"sections":[{"label":"主题名(中文)","items":[{"title":"...","summary":"..."}]}]}
  ```
- 提炼调用：把 `weekly_items` 渲染成带分类线索的文本喂给文本 provider。**输入不做无脑字符截断**——一周条目可能数百条，简单截断会丢掉后半周、让周报偏向前几天。改为**结构化采样**：按天保留 lead + 每个 section 取前 N 条（再设总字符上限兜底，约 12000），保证全周覆盖。
- 解析失败兜底：退回到按 `weekly_items` 原 category 简单分组（取前若干条）。**兜底产出形状必须与 D2 完全一致** `[{label, items:[{title, summary}]}]`，保证下游 `_gen_daily_batch_scenes` 能取到 `title`/`summary`，不阻断流水线。
- 把结果写回 `article.metadata["daily_sections"] = sections`（复用 daily 的下游路径）。

**持久化约束（关键）**：`runner._save_articles` / `_article_from_dict` 只透传 `aihot_method` 与 `daily_sections` 两个 metadata 字段——`weekly_items` / `week_start` / `week_end` **不会被序列化**，仅作内存中转。因此：

- **提炼必须发生在 `_save_articles`（runner.py:389）之前**，且结果只写进 `daily_sections`。否则 manual review 模式存盘再重载，weekly 的 sections 会丢。§下方调用点位置（紧跟 `_summarize_articles`、早于 save）已满足该时序。
- `regen-script` / `add-scene` 端点经 `_article_from_dict` 从 `articles.json` 重建 article 后跑 `run_stage2_multi`：weekly **不重新提炼**，直接复用已存的 `daily_sections`（因此这两个端点无需调提炼 helper）。

`_distill_weekly_if_needed` 的两处调用点：

- `runner._run_inner` 的 Stage1 段，紧跟 `_summarize_articles` 之后（普通源走 summary，weekly 走提炼，互斥）。
- `api/pipeline._reroll_articles_async` 同一位置。

> 触发判定：`articles and articles[0].metadata.get("aihot_method") == "weekly"`。

### 3. Stage1 采集分流 — `backend/app/pipeline/stage1_collect.py`

`run_stage1` 对 AI HOT 组按 `aihot_method` 分流（现有代码，约行 60-70）：

```python
if method == "daily":
    return compliant[:1]          # 单篇直通
return compliant[:max_articles]   # items 分支
```

weekly 同样是"单篇直通"（一周聚合成一篇），但 `aihot_method == "weekly"` 会落进 items 的 `compliant[:max_articles]` 分支。当 `max_articles ≥ 1` 时碰巧能返回这唯一一篇，但若前端在 digest 模式把文章数置为 0，`[:0]` 会返回空、误触发"无数据"失败。

**改动**：把判断从 `if method == "daily"` 放宽为 `if method in ("daily", "weekly")` → weekly 也走 `compliant[:1]` 单篇直通。`compliance` 仍跑、跳过 dedup/scoring（与 daily 一致）。

### 4. Stage2 — `backend/app/pipeline/stage2_script.py`

`run_stage2_multi` 现有 daily 分支判断：

```python
if article.metadata.get("aihot_method") == "daily" and sections:
```

放宽为：

```python
if article.metadata.get("aihot_method") in ("daily", "weekly") and sections:
```

`sections` 仍读 `article.metadata.get("daily_sections")`（weekly 已在 Stage1 写好）。**其余分组批处理 / 分镜生成逻辑完全不变。** 这是 Stage2 唯一改动。

### 5. Runner 失败文案 — `backend/app/pipeline/runner.py`

现有 `daily_mode`（bool）仅区分 daily。**合并为单变量**，避免并行两个 bool：

```python
digest_method = next((sc.get("method") for sc in source_configs
                      if sc.get("method") in ("daily", "weekly")), None)
```

无文章时按 `digest_method` 三分支选文案：

- `"weekly"`：`"上周 AI 日报数据不足，无法生成周报，请改用日报(daily)或动态(items)模式"`
- `"daily"`：保持原日报文案。
- 其它（`None`）：`"No articles collected"`。

### 6. 前端

- **`frontend/src/pages/Sources.tsx`**（`AIHotGroupCard`，行 167-175）：模式切换数组从 `["items","daily"]` 扩为 `["items","daily","weekly"]`，标签映射 `items→动态 / daily→日报 / weekly→周报`。`category` 筛选仍只在 `items` 显示。
- **`frontend/src/components/CreateRunDialog.tsx`**（行 71、214）：`isAihotDaily` 泛化为 `isAihotDigest = aihotMethod === "daily" || aihotMethod === "weekly"`，引用处同步改名（周报同样忽略时间范围 / 文章数）。
- **`frontend/src/components/SourceSummary.tsx`**（行 26）：标签映射增加 `weekly → "每周周报"`（`daily → "每日日报"`、其它 → "动态聚合"）。

### 7. config / schema

`config_json.method` 是自由字符串，无枚举校验，**无需 schema/config 改动**。种子 AI HOT 源默认仍为 `items`，用户在前端切到 `weekly`。

## 数据流

```
AI HOT weekly:
  /dailies → 筛上周一~上周日 → 逐天 /daily/{date}(404跳过) → 扁平汇总 weekly_items → 一篇 article(aihot_method=weekly)
    → [Stage1 整理] 文本AI 提炼成 3-5 主题 sections → 写回 metadata.daily_sections
    → [Stage2] 复用 daily 的分组→分镜(≤10) → 一条「本周 AI 热点回顾」汇总视频
```

对照 daily：

```
AI HOT daily:
  /daily → 渲染单篇(daily_sections 来自 API) → [Stage1 直通] → [Stage2 分组→分镜] → 一条日报汇总视频
```

差异仅在：weekly 多一步 Stage1 跨天提炼；daily 的 sections 来自 API，weekly 的 sections 来自 AI 提炼。Stage2 及之后完全一致。

## 边界与错误处理

- **上周无任何日报**：collector 返回空 → runner 周报专属失败文案（§4）。
- **某天日报 404 / 异常**：跳过该天，记 warning，不中断（只要该周至少 1 天有数据即可生成）。
- **提炼 AI 解析失败 / 返回 sections 为空**：兜底按原 category 简单分组（§2，形状同 D2），不阻断流水线。
- **输入超长**：结构化采样（按天 lead + 每 section 前 N 条）+ 总字符上限兜底 + 提示词限制主题/条数共同约束，避免偏向前半周（§2）。
- **weekly 下 `time_range` / `max_articles` 无意义**：采集层忽略；前端 `isAihotDigest` 置灰这两项。
- **互斥**：沿用现有"有启用的 AI HOT 源即只用 AI HOT 组"机制，weekly 无新增。

## 测试计划

- **`AIHotCollector` weekly**（`tests/test_collector_aihot.py`）：
  - mock `/dailies` + 多个 `/daily/{date}` → 断言返回单篇、周范围正确（上周一~上周日）、`weekly_items` 汇总全周条目、metadata 标记 `aihot_method=weekly`。
  - 某天 404 → 跳过该天，其余仍汇总。
  - 该周无日报 → 返回 `[]`。
- **weekly 提炼 helper**：mock TextProvider 返回主题 JSON → 断言写回 `daily_sections`、主题数 3-5、总条数 ≤9；解析失败 → 走兜底分组。
- **`run_stage2_multi` weekly**（`tests/test_stage2_multi.py`）：带 `aihot_method=weekly` + `daily_sections` 的 article → 断言命中分组分支、groups/scenes 正确、分镜 ≤10。
- **runner**：weekly 无数据 → 断言周报专属错误文案。
- **回归**：daily / items 行为不变；reroll 与主流程提炼一致（共享 helper）。

## 影响文件

- `backend/app/providers/collector/aihot.py`（`_collect_weekly` + 周范围 + 扁平汇总）
- `backend/app/pipeline/stage1_collect.py`（AI HOT 分流：weekly 也走 `compliant[:1]` 单篇直通）
- `backend/app/pipeline/runner.py`（`_distill_weekly_if_needed` helper + Stage1 调用 + `digest_method` 失败文案）
- `backend/app/api/pipeline.py`（`_reroll_articles_async` 调同一提炼 helper；`regen-script`/`add-scene` 不变，复用已存 sections）
- `backend/app/pipeline/stage2_script.py`（`WEEKLY_DIGEST_SYSTEM_PROMPT` + `distill_weekly_sections` 提炼函数；分支判断放宽到 `in ("daily","weekly")`）
- `frontend/src/pages/Sources.tsx`（模式切换加 `weekly`）
- `frontend/src/components/CreateRunDialog.tsx`（`isAihotDaily` → `isAihotDigest`）
- `frontend/src/components/SourceSummary.tsx`（weekly 标签）
- 测试：`backend/tests/test_collector_aihot.py`、`backend/tests/test_stage2_multi.py`（新增 weekly 用例）

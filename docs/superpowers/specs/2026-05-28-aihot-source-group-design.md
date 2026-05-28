# AI HOT 信息源分组与方法 — 设计文档

## 背景与目标

AI HOT (`aihot.virxact.com`) 是一个**聚合型**新闻源，本身已聚合并精选了多个 AI 资讯源。把它和普通的单一信息源（RSS / 搜索 / HN 等）混在一起采集会重复、语义混乱。

之前为流水线加的 **去重 / 评分排序 / 摘要** 三个开关，本意就是为了对付 AI HOT 这类源的噪声。现在把 AI HOT 显式分模式处理后，这套通用机制对 AI HOT 不再需要，开关也可以撤掉。

目标：

1. 把 AI HOT 单独作为一个**组**，与普通信息源组**互斥**——一次采集只用其中一组
2. AI HOT 组支持两种**方法/模式**（二选一）：
   - `items` — 动态/精选，调 `/api/public/items`，扁平文章列表，走现有单条视频流程
   - `daily` — 日报，调 `/api/public/daily`，整份日报生成一条"今日 AI 日报"汇总视频
3. **移除** `pipeline.enable_summary / enable_dedup / enable_scoring` 三个开关，改为按"组 + 模式"自动决定处理逻辑

## 非目标 (YAGNI)

- 不重写 runner 主流程为真正的多文章 collection 编排（daily 用"单篇富文本 + 汇总提示词"达成同等效果）
- daily 暂只取**最新日报**，按日期回溯（`/daily/{date}` + `/dailies` 归档）作为后续
- 不新增 DB 列、不引入迁移（组身份由 collector 类型派生）
- 不动 `summary.*` 这组摘要 **provider 配置**（普通源摘要仍要用它）；只删 `pipeline.enable_summary` 这个**门控开关**

## 设计决策

- **A1 — 单条 AI HOT 源 + method 字段**：一条 `AI HOT` 源，`config_json` 存 `{"provider":"aihot","method":"items"|"daily","category":"<可选>"}`。组身份 = collector 解析为 `aihot` 的源。
- **B1 — 复用单文章流程 + 汇总提示词**：daily collector 把整份日报渲染成单篇 `RawArticleData`，Stage2 在 daily 模式下换用"资讯汇总播报"系统提示词。不动 runner/Stage3+。
- **C — 处理逻辑按组/模式分流**：撤掉三开关，去重/评分/摘要仅对普通源**始终生效**；AI HOT 走轻量旁路。

## AI HOT API 参考

| 端点 | 方法 | 返回 | 本设计用途 |
|---|---|---|---|
| `/api/public/items` | GET | `{count, hasNext, nextCursor, items:[{id,title,title_en,url,source,publishedAt,summary,category}]}` | items 模式（现状） |
| `/api/public/daily` | GET | `{date, generatedAt, windowStart, windowEnd, lead:{title,leadParagraph}, sections:[{label, items:[{title,summary,sourceUrl,sourceName}]}], flashes:[{title,sourceName,sourceUrl,publishedAt}]}` | daily 模式（最新） |
| `/api/public/daily/{YYYY-MM-DD}` | GET | 同上 | 后续：按日期 |
| `/api/public/dailies` | GET | `{count, items:[{date,generatedAt,leadTitle,leadParagraph}]}` | 后续：日期发现 |

`items` 参数：`mode`(selected/all, 默认 selected)、`category`(ai-models/ai-products/industry/paper/tip)、`since`、`take`(1-100, 默认 50)、`cursor`、`q`(2-200 字)。

> **重要**：`items` 的条目**没有任何数值分数字段**（仅 id/title/title_en/url/source/publishedAt/summary/category）。所谓"按分数排序"只能依赖 `mode=selected` 返回的**平台精选顺序**（即编辑热度排序），外加 `category` 过滤与（兜底）`publishedAt` 时效排序。

## 详细设计

### 1. Collector — `backend/app/providers/collector/aihot.py`

`AIHotCollector.collect()` 按 `source_config["method"]`（默认 `items`）分支。**两种模式都给产出的 `RawArticleData.metadata` 打组标记**，供下游分流：

`metadata = {"source_group": "aihot", "aihot_method": "items"|"daily", ...}`

- **`items`**：调 `/api/public/items`，参数 `mode=selected`、`take=max_items`、`category=<config 可选>`。逐条转 `RawArticleData`（保持 API 返回顺序 = 精选排序）。
- **`daily`**：
  - 调 `GET /api/public/daily`（404 / 无日报 → 返回空列表 + 由 runner 给出明确错误文案，见 §7）
  - 把整份日报渲染成**一篇** `RawArticleData`：
    - `title` = `lead.title`（缺省 `f"今日 AI 日报 {date}"`）
    - `content` = 结构化文本：`lead.leadParagraph` + 各 `section.label` 标题下逐条 `「title」summary`（含 `flashes` 快讯）
    - `summary` = `lead.leadParagraph`
    - `source_name` = `"AI HOT 日报"`，`aggregator_url` = `https://aihot.virxact.com`，`category` = `"ai"`
    - `metadata` 额外含 `{"report_date": date}`

### 2. 分组判定与互斥

**判定谓词（前后端统一口径）**：一个源属于 AI HOT 组 ⇔ `config_json.provider === "aihot"` 或 `url` 含 `aihot.virxact.com`。

**互斥（双保险）**：
- 前端（主）：源管理页组级开关，复用 `POST /api/sources/batch`——启用 AI HOT 组 → AI HOT 源 `enabled=true` + 普通源全部 `enabled=false`；启用普通组 → AI HOT 源 `enabled=false`（普通组内各源仍由单条开关控制）。
- 服务端（兜底）：runner 组装采集源时，若同时检测到 AI HOT 源与普通源都 enabled，则**只保留 AI HOT 组**（AI HOT 优先）并记 warning。保证无论 enabled 怎么设，采集层任意时刻只用一组。

### 3. Stage1 改造 — `backend/app/pipeline/stage1_collect.py`

移除 `enable_dedup` / `enable_scoring` 入参。改为按采集结果的组标记分流（互斥保证全部同组）：

- **普通源**（无 `source_group=="aihot"` 标记）：`dedup → compliance → scoring.select_top(n=max_articles)`，**始终执行**（不再有开关）。
- **AI HOT `items`**：跳过 dedup / scoring；`compliance` 仍跑；取前 `max_articles` 条（API 已 selected 排序 + category 过滤）。
- **AI HOT `daily`**：单篇直通；跳过 dedup / scoring；`compliance` 仍跑。

`compliance`（内容安全）对所有路径保留——它不属于被撤的 3 个性能开关。

### 4. 摘要门控 — `backend/app/pipeline/runner.py`（及 `api/pipeline.py`，见 §10）

- 移除 `cfg.pipeline.enable_summary` 判断。
- 改为：仅当**普通源**路径才跑 `_summarize_articles`（通过 `articles[0].metadata.get("source_group") != "aihot"` 判断）。AI HOT 两模式都不跑摘要。
- 摘要所用的 provider 配置（`cfg.summary.*`）保留不动。

### 5. Stage2 — `backend/app/pipeline/stage2_script.py`

- 新增 `DAILY_DIGEST_SYSTEM_PROMPT`：定位"今日 AI 资讯汇总播报"，要求 `lead` 作开场分镜、**每条资讯一个分镜**、结尾总结分镜；输出 JSON 结构同现有 `SCRIPT_SYSTEM_PROMPT`。**限制总分镜数 ≤ 10**（每 section 最多取 2-3 条），避免视频过长 / Stage3 成本失控。
- `run_stage2(article, text_provider, language, style="single")`：`style="daily"` 时用 daily 提示词，且 content 截断上限放宽（如 `[:8000]`，覆盖整份日报）；否则保持原 `[:3000]` 单文章逻辑。
- runner 在 `article = articles[0]` 后读 `metadata.get("aihot_method")`，daily 时传 `style="daily"`。

### 6. 前端 Sources 页 — `frontend/src/pages/Sources.tsx`

- 按 §2 判定谓词把列表分两块渲染：**AI HOT 聚合** 与 **自定义信息源**，各带组级启用开关（互斥）。
- AI HOT 组块内嵌控件：`动态(items) / 日报(daily)` 分段切换；items 模式下再给一个**分类筛选**下拉（全部 / ai-models / ai-products / industry / paper / tip）。切换写回 AI HOT 源 `config_json` 的 `method` / `category`（`PATCH /api/sources/{id}`）。
- 普通源组维持现有表格（排序 / 置顶 / 拖拽 / 单条启用）。

### 7. 前端 Settings 页 — `frontend/src/pages/Settings.tsx`

- 删除"流水线默认值"里的 **文章去重 / 评分排序 / 摘要生成** 三个 toggle（行 413-427）。
- `dedup_lookback` 保留（普通源去重仍用）；"文章摘要" provider 配置 Section 保留。

### 8. config / schema 改动

- `backend/app/config.py`：`PipelineCfg` 删 `enable_summary` / `enable_dedup` / `enable_scoring`（保留 `dedup_lookback`）。`SummaryCfg.enabled` 为死字段（前端未暴露、runner 未用）——一并清理或留注释，不影响行为。
- `frontend/src/api/client.ts`：`AppSettings.pipeline` 类型删这 3 个布尔字段。
- `frontend/src/pages/Settings.tsx`：`EMPTY_SETTINGS.pipeline` 删这 3 个字段。

### 9. 种子 AI HOT 源

- 应用启动时若不存在 aihot 源，自动种子一条：
  `{name:"AI HOT", type:"api", url:"https://aihot.virxact.com/api/public", config_json:{"provider":"aihot","method":"items"}, enabled:false}`
- 保证 AI HOT 组始终存在、可切换。（`provider:"aihot"` 在 `_resolve_collector_type` 中优先级最高，正确解析为 aihot collector。）

## 数据流

```
普通源组:    [多源采集] → dedup → compliance → scoring(top N) → summary → Stage2(single) → 单条视频
AI HOT items: /items(selected+category) → compliance → 取前 N → Stage2(single) → 单条视频
AI HOT daily: /daily → 渲染单篇富文本(metadata) → compliance → Stage2(daily 汇总提示词, ≤10 分镜) → 一条日报汇总视频
```

## 边界与错误处理

- **daily 当日无日报（404）**：collector 返回空 → runner 以**明确文案**失败（"今日 AI 日报尚未生成，请稍后或切换为动态模式"），而非泛化的 `No articles collected`。
- **daily 内容超长**：靠 §5 的放宽截断 + 提示词分镜上限共同约束。
- **互斥被绕过**：靠 §2 服务端兜底。
- **daily 模式下 `time_range` / `max_articles` 无意义**：采集层忽略；前端可在 daily 模式置灰这两项（可选）。

## 测试计划

- `AIHotCollector`：
  - items：mock `/items` → 断言条目顺序保留、metadata 标记 `source_group=aihot, aihot_method=items`、category 透传到请求参数。
  - daily：mock `/daily` → 断言返回单篇、content 含各 section 条目与 flashes、metadata 标记正确；404 → 返回空。
- `run_stage1`：
  - 普通源：断言 dedup + scoring 始终执行（无开关）。
  - AI HOT items / daily：断言跳过 dedup/scoring、compliance 仍跑、daily 单篇直通。
- `run_stage2(style="daily")`：mock TextProvider → 断言用 daily 系统提示词、放宽截断。
- 回归：移除开关后普通源全流程仍跑通；items 模式产出与旧 AI HOT 行为一致。
- 互斥：服务端兜底——两组都 enabled 时只采 AI HOT。

## 影响文件

- `backend/app/providers/collector/aihot.py`（items category + metadata 标记；daily 分支 + 渲染）
- `backend/app/pipeline/stage1_collect.py`（移除开关入参；按组分流）
- `backend/app/pipeline/runner.py`（移除 enable_* 引用；摘要仅普通源；daily 传 style；互斥兜底）
- `backend/app/pipeline/stage2_script.py`（DAILY_DIGEST 提示词 + style 参数 + 放宽截断 + 分镜上限）
- `backend/app/config.py`（`PipelineCfg` 删 3 字段；清理 `SummaryCfg.enabled`）
- `backend/app/api/pipeline.py`（见 §10：同样引用了 3 开关，需同步处理）
- `backend/app/main.py` 或启动钩子（种子 AI HOT 源）
- `frontend/src/pages/Sources.tsx`（分组渲染 + 模式/分类控件 + 组互斥开关）
- `frontend/src/pages/Settings.tsx`（删 3 个 toggle + EMPTY_SETTINGS）
- `frontend/src/api/client.ts`（AppSettings 类型删 3 字段）
- 测试：`backend/tests/` 新增 collector / stage1 / stage2 用例

## §10 两处采集逻辑必须同步（已核实）

两处都引用这 3 个开关、且都各自跑 `run_stage1` + 摘要，**都是活代码、各有用途**：

- `runner._run_inner`（经 `execute_pipeline` ← `create_run`）：完整流水线主路径。
- `api/pipeline._reroll_articles_async`（行 366-373，← `POST /runs/{id}/reroll-articles`）："重新采集文章"功能，只重跑 Stage1。**复制了**同一套"采集 + 摘要"逻辑。

两处的"移除开关 + 按组分流 + 摘要仅普通源 + 互斥兜底"必须一致，否则 reroll 与正常采集行为分叉。
**建议**：把"采集 → (普通源)摘要"抽成一个共享 helper（如 `collect_and_prepare(...)`），runner 与 reroll 都调它，从根上杜绝分叉。

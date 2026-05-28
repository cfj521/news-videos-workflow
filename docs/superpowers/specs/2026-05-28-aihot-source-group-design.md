# AI HOT 信息源分组与方法 — 设计文档

## 背景与目标

AI HOT (`aihot.virxact.com`) 是一个**聚合型**新闻源，本身已聚合多个 AI 资讯源。把它和普通的单一信息源（RSS / 搜索 / HN 等）混在一起采集会重复、语义混乱。

目标：

1. 把 AI HOT 单独作为一个**组**，与普通信息源组**互斥**——一次采集只用其中一组
2. AI HOT 组支持两种**方法/模式**（二选一）：
   - `items` — 动态/精选，调 `/api/public/items`，返回扁平文章列表，走现有单条视频流程
   - `daily` — 日报，调 `/api/public/daily`，整份日报生成一条"今日 AI 日报"汇总视频

## 非目标 (YAGNI)

- 不重写 runner 主流程为真正的多文章 collection 编排（daily 用"单篇富文本 + 汇总提示词"达成同等效果）
- daily 暂只取**最新日报**，按日期回溯（`/daily/{date}` + `/dailies` 归档）作为后续
- items 模式暂用默认 `mode=selected`，不把 `mode`/`category`/`q` 暴露到前端编辑
- 不新增 DB 列、不引入迁移（组身份由 collector 类型派生）

## 设计决策

- **A1 — 单条 AI HOT 源 + method 字段**：一条 `AI HOT` 源，`config_json` 存 `{"provider":"aihot","method":"items"|"daily"}`。组身份 = collector 解析为 `aihot` 的源。
- **B1 — 复用单文章流程 + 汇总提示词**：daily collector 把整份日报渲染成单篇 `RawArticleData`，Stage2 在 daily 模式下换用"资讯汇总播报"系统提示词。不动 runner/Stage3+。

## AI HOT API 参考

| 端点 | 方法 | 返回 | 本设计用途 |
|---|---|---|---|
| `/api/public/items` | GET | `{count, hasNext, nextCursor, items:[{id,title,title_en,url,source,publishedAt,summary,category}]}` | items 模式（现状） |
| `/api/public/daily` | GET | `{date, generatedAt, windowStart, windowEnd, lead:{title,leadParagraph}, sections:[{label, items:[{title,summary,sourceUrl,sourceName}]}], flashes:[{title,sourceName,sourceUrl,publishedAt}]}` | daily 模式（最新） |
| `/api/public/daily/{YYYY-MM-DD}` | GET | 同上 | 后续：按日期 |
| `/api/public/dailies` | GET | `{count, items:[{date,generatedAt,leadTitle,leadParagraph}]}` | 后续：日期发现 |

`items` 参数：`mode`(selected/all, 默认 selected)、`category`(ai-models/ai-products/industry/paper/tip)、`since`、`take`(1-100, 默认 50)、`cursor`、`q`(2-200 字)。

## 详细设计

### 1. Collector — `backend/app/providers/collector/aihot.py`

`AIHotCollector.collect()` 按 `source_config["method"]`（默认 `items`）分支：

- **`items`**：维持现状，调 `/api/public/items`，逐条转 `RawArticleData`。
- **`daily`**：
  - 调 `GET /api/public/daily`（404/无日报 → 返回空列表，让 runner 走"无文章"失败分支）
  - 把整份日报渲染成**一篇** `RawArticleData`：
    - `title` = `lead.title`（或 `f"今日 AI 日报 {date}"`）
    - `content` = 结构化文本：`lead.leadParagraph` + 各 `section.label` 标题下逐条 `「title」summary`（可选附 `flashes` 快讯）
    - `summary` = `lead.leadParagraph`
    - `source_name` = `"AI HOT 日报"`
    - `aggregator_url` = `https://aihot.virxact.com`
    - `category` = `"ai"`
    - `metadata` = `{"aihot_method": "daily", "report_date": date}` ← 给 Stage2 的信号

### 2. method 信号透传

- runner `build_collectors_from_db()` 已把 `config_json` 合并进 `source_config`，故 `method` 自动传到 collector。
- daily 模式下 collector 在 `RawArticleData.metadata["aihot_method"]="daily"` 打标。
- runner Stage2 处 `article = articles[0]`，读取 `article.metadata.get("aihot_method")` 决定传给 `run_stage2` 的提示词风格。

### 3. Stage2 — `backend/app/pipeline/stage2_script.py`

- 新增 `DAILY_DIGEST_SYSTEM_PROMPT`：定位为"今日 AI 资讯汇总播报"，要求 `lead` 作开场分镜、**每条资讯一个分镜**、结尾总结分镜；输出 JSON 结构同现有 `SCRIPT_SYSTEM_PROMPT`。
- `run_stage2(article, text_provider, language, style="single")`：`style="daily"` 时用 `DAILY_DIGEST_SYSTEM_PROMPT`，否则用现有提示词。runner 根据 metadata 传 `style`。

### 4. 互斥机制（源管理页驱动）

- Stage1 采集 = 所有 `enabled==True` 的源，故"组互斥"= 同一时刻只有一组的源 `enabled`。
- 复用现有 `POST /api/sources/batch`：
  - 启用 AI HOT 组 → AI HOT 源 `enabled=true`，普通源全部 `enabled=false`
  - 启用普通组 → AI HOT 源 `enabled=false`（普通组内各源仍由其单条开关独立控制；切到普通组只负责关掉 AI HOT，不强行批量开启普通源）
- 由前端 toggle 处理器触发 batch；保证采集层任意时刻只有一组的源 `enabled`。

### 5. 前端 — `frontend/src/pages/Sources.tsx`

- 列表按组分块渲染：**AI HOT 聚合** 与 **自定义信息源** 两段，各带组级启用开关（互斥）。
- AI HOT 组块内嵌 `动态 / 日报` 分段控件，切换时 `PATCH` AI HOT 源的 `config_json.method`。
- 普通源组维持现有表格（排序/置顶/拖拽/单条启用）。

### 6. 种子 AI HOT 源（可选）

- 应用启动或首次进源管理页时，若不存在 aihot 源，自动种子一条：
  `{name:"AI HOT", type:"api", url:"https://aihot.virxact.com/api/public", config_json:{"provider":"aihot","method":"items"}, enabled:false}`
- 保证 AI HOT 组始终存在、可切换。

## 数据流

```
items 模式:  /items  → [文章...] → Stage2(single) → 单条视频
daily 模式:  /daily  → 渲染为单篇富文本(metadata.aihot_method=daily) → Stage2(daily 汇总提示词) → 一条日报汇总视频
```

## 测试计划

- `AIHotCollector` daily 分支：mock `/api/public/daily` 响应 → 断言返回单篇、content 含各 section 条目、metadata 标记正确；404 → 返回空。
- `run_stage2(style="daily")`：mock TextProvider → 断言使用 daily 系统提示词。
- 互斥：batch 调用后断言两组 enabled 状态互补（可在前端交互或 API 层验证）。

## 影响文件

- `backend/app/providers/collector/aihot.py`（daily 分支 + 日报渲染）
- `backend/app/pipeline/stage2_script.py`（DAILY_DIGEST 提示词 + style 参数）
- `backend/app/pipeline/runner.py`（Stage2 读 metadata 传 style）
- `frontend/src/pages/Sources.tsx`（分组渲染 + 组互斥开关 + method 分段控件）
- `frontend/src/components/EditSourceDialog.tsx` / `api/client.ts`（如需，method 字段写回）
- 测试：`backend/tests/` 新增 collector / stage2 用例

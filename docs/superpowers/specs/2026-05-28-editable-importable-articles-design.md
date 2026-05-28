# S1 文章列表可编辑 + 多格式导入（Phase A）— 设计文档

## 背景与目标

这是一个更大功能的**第一期（Phase A）**。完整目标分两期：

- **Phase A（本文）**：S1 文章列表可自由增删改，并支持从 Word/PDF/Markdown/网页 URL 导入；创建任务时可选「不采集，纯等待人工导入」。
- **Phase B（后续）**：S2 多文章分组脚本（每篇文章一组分镜、AI HOT daily 按 category 2~4 条成组）+ 自由增删分镜。

Phase A 的独立价值：让用户完全掌控喂给脚本生成的文章内容（自动采集只是来源之一），并支持纯人工导入工作流。**Phase A 不改 Stage2**——脚本仍按现状从 `articles.json` 生成（多文章分组留到 B 期）。

## 非目标（YAGNI / 留给 B 期）

- 不改 Stage2 的脚本生成逻辑（单/多文章分组是 B 期）
- 不做分镜增删（B 期）
- 导入：1 个文件 / 1 个 URL = 1 篇文章，不做"一份文档拆多篇"
- Markdown 保留原文文本，不做渲染/结构化解析

## 数据模型与持久化

- `articles.json`（每个 run 目录下）是该 run 文章清单的**唯一真源**，结构维持现状：dict 列表，字段含 `title`、`url`、`aggregator_url`、`source`、`content`、`summary`、`aihot_method`。
- **可编辑字段**：`title`、`content`（喂脚本的关键）、`summary`、`source`、`url`。
- **内部字段必须保活**：`aggregator_url`、`aihot_method` 等不在编辑面，但**必须随整份列表原样回传**。当前 `ArticleData`（client.ts）不含 `aihot_method`，若直接按该类型回传会丢字段、破坏 daily 检测。
  - 对策：前端把每篇文章当作**透传记录**保存——保留 GET 拿到的原始对象，编辑时只覆盖被改字段（`{...原始, ...编辑}`），PUT 回传完整对象；`ArticleData` 增加可选 `aihot_method?` 以显式带上。
  - 后端 PUT 直接写入收到的数组（不做基于 index 的服务端合并，因无 id）；校验每篇至少有 `title` 或 `content`。
  - 测试须断言：含 `aihot_method` 的文章经一次 PUT 往返后该字段仍在。
- 采用「前端管列表 + 整体覆盖保存」（方案 A1）：无需给文章加 id。

### 新增/变更的后端接口（`backend/app/api/pipeline.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/pipeline/runs/{id}/articles` | 现状，返回 articles.json 列表 |
| PUT | `/api/pipeline/runs/{id}/articles` | 接收完整文章数组，校验（每篇至少有 `title` 或 `content`）后覆盖写 articles.json |
| POST | `/api/pipeline/runs/{id}/articles/import/file` | multipart 上传，按扩展名解析为 1 篇文章，追加到 articles.json，返回更新后的完整列表 |
| POST | `/api/pipeline/runs/{id}/articles/import/url` | JSON `{url}`，抓取解析为 1 篇文章，追加，返回完整列表 |

- 写入复用一个内部 helper（如 `_write_articles(run_id, list)`）。
- 错误：不支持的扩展名 / 空内容 / 文件超限（如 >20MB）→ 400；URL 抓取失败 → 502 并带原因。

## 导入解析（新增 `backend/app/services/document_import.py`）

单一职责：把"上传文件 / URL"解析成一篇文章 dict `{title, content, summary:"", source, url}`。

**懒加载**：`python-docx` / `pymupdf` 在各自解析函数**内部 import**（不在模块顶层），缺库时只让对应格式报错、不拖垮应用启动（参考现有 scraping collector 的懒加载/try-except 模式）。

| 来源 | 解析方式 | 依赖 |
|---|---|---|
| `.docx` | `python-docx` 读所有段落文本拼接 | 新增 `python-docx` |
| `.md` / `.txt` | 按 UTF-8 直接读文本（md 保留原文） | 无 |
| `.pdf` | **视觉模型**：`PyMuPDF` 把每页渲染为 PNG → 以 OpenAI 兼容视觉对话发给配置的视觉模型，提示「提取正文为纯文本」。**优先一次调用塞入所有页图片**（多个 image 块），而非逐页 N 次调用，降低时延/成本 | 新增 `pymupdf` |
| URL | 复用 `FullTextFetcher`（httpx + HTML 抽取），并新增 `<title>` 提取 | 无 |

**标题派生**：docx → 首个非空段落；md → 首个 `# ` 标题；URL → `<title>`；pdf/txt 或取不到 → 文件名 / 域名。
**字段映射**：`content`=解析正文；`source`=文件名或 URL 域名；`url`=导入的 URL（文件导入留空）；`summary`=空。

**PDF 视觉解析控成本/时延**：限制页数（如 ≤20 页，超出截断并告警）与单页图片分辨率（如 150 DPI）。import 端点同步执行，前端导入对话框须显式 loading 态；若实测耗时常超 HTTP 超时，则把 PDF 导入改为后台任务 + 轮询（实现时按实测决定，接口保持幂等可重试）。

## 视觉模型配置（与文本/图片模型解耦）

- `backend/app/config.py`：新增 `vision: ProviderCfg`（`provider`/`base_url`/`model`/`api_key`），`Settings` 加该字段。默认 `provider="openai"`、`model="gpt-4o"`、`base_url="https://api.openai.com/v1"`。
- PDF 解析调用 OpenAI 兼容的 `chat/completions`（`messages` 含 `image_url` 块，base64 data URL）。本期按 **OpenAI 兼容图片输入**实现（覆盖 gpt-4o / Qwen-VL 等）。
- `frontend/src/api/client.ts`：`AppSettings` 加 `vision` 类型。
- `frontend/src/pages/Settings.tsx`：加「文档解析模型」一节（沿用 `ProviderSection` 组件），预设给 OpenAI / DashScope(Qwen-VL) 等视觉模型；并在 `EMPTY_SETTINGS` 补 `vision` 默认值（与后端默认一致）。

## 创建任务：可选「不采集，纯等待人工导入」

### 数据
- `backend/app/models/pipeline_run.py`：`PipelineRun` 加列 `auto_collect: Mapped[bool] = mapped_column(Boolean, default=True)`。
- `backend/app/schemas/pipeline.py`：`PipelineRunCreate` 加 `auto_collect: bool = True`；`PipelineRunRead` 加 `auto_collect: bool`。
- **兼容旧库**：在 lifespan 启动时做一次「确保列存在」校验——对 sqlite 用 `PRAGMA table_info(pipeline_runs)` 检查，缺列则 `ALTER TABLE pipeline_runs ADD COLUMN auto_collect BOOLEAN DEFAULT 1`。

### runner 行为（`backend/app/pipeline/runner.py`）
- `auto_collect=True`：维持现状（Stage1 自动采集）。
- `auto_collect=False`：Stage1 跳过采集 → 写空 `articles.json` → `status="review"`、`progress_detail="等待人工导入文章…"` → `_wait_for_resume`，**不因空文章判失败**。（无论 `mode` 是 auto 还是 manual，不采集都会在 S1 暂停等待导入。）
- **S1 review 暂停并 resume 后，从 `articles.json` 重新加载文章**再进入后续阶段（让人工导入/编辑生效；现状用内存旧列表会忽略编辑）。适用于所有进入 S1 review 的情况（含 auto 采集后手动编辑）。
  - 需一个 `articles.json dict → RawArticleData` 映射（注意字段名：`url→source_url`、`source→source_name`，`aihot_method` 放入 `metadata`），与 regen-script 端点重建文章的逻辑保持一致，可抽公共 helper 复用。
- **resume 守卫**：resume 后重载 `articles.json`，若仍为空 → **不进 S2**：把 `status` 重新置 `review`、`progress_detail="请先导入至少 1 篇文章"`，并重新进入 `_wait_for_resume` 等待（不判失败、不无限快转）。

### 前端 CreateRunDialog（`frontend/src/components/CreateRunDialog.tsx`）
- 加「采集方式」单选：`自动采集`（默认）/ `不采集（人工导入）`，对应 `auto_collect`。
- 选「不采集」时，`时间范围` / `最大文章数` 置灰（无关）。
- create 请求体加 `auto_collect`（`frontend/src/api/client.ts` 的 `runs.create` 类型同步）。

## 前端 S1 面板（`frontend/src/pages/Dashboard.tsx` 的 `S1Panel`）

只读列表 → 可编辑列表：
- 顶部按钮：`重新采集`（保留）、`+ 添加文章`、`导入`。
- 每篇文章卡片：增加 `编辑` / `删除`。
- 新增 `ArticleDialog`（增/改，复用对话框样式）：字段 `标题`、`正文`(大 textarea)、`摘要`、`来源`、`原文链接`；保存 → 整份列表 `PUT` → `mutate` 刷新。
- 新增 `ImportArticleDialog`：① 文件上传（accept `.docx,.pdf,.md,.txt`，pdf 提示"走视觉模型，较慢"）② 粘贴 URL；调对应 import 端点 → `mutate` 刷新。
- 删除 → 从列表移除 → `PUT` 保存。
- 列表底部提示：「编辑文章后，到"脚本/图片"标签点【重生成脚本】以应用」。
- `frontend/src/api/client.ts`：`api.runs` 加 `saveArticles(id, list)`、`importArticleFile(id, file)`、`importArticleUrl(id, url)`。

## 数据流

```
建任务(auto_collect=true)  → S1 自动采集 → (可编辑/导入增删) → resume → 重载 articles.json → S2
建任务(auto_collect=false) → S1 写空+暂停 → 人工导入/新增文章   → resume(≥1篇) → 重载 articles.json → S2
导入文件/URL → document_import 解析为 1 篇 → 追加 articles.json
```

## 测试计划

- `document_import` 单测：
  - docx：mock `python-docx` 文档对象 → 断言段落拼接 + 标题取首段
  - md/txt：字节 → 文本、md 取首个 `#` 标题
  - pdf：mock PyMuPDF 渲染 + mock 视觉模型 HTTP → 断言逐页图片入参、返回拼接文本
  - url：mock `FullTextFetcher` + `<title>` 提取
  - 不支持扩展名 / 空内容 → 抛错（端点转 400）
- 端点：`PUT /articles` 覆盖写且保留内部字段；`import/file`、`import/url` 追加并返回完整列表（临时 run_dir + mock 解析）
- config：`vision` 默认值加载 + Settings 往返；`auto_collect` schema 默认值
- runner：`auto_collect=False` → 写空 + 进 review 不失败；resume 后重载 articles.json；空文章 resume 守卫（用 mock/最小 run）
- 「确保列存在」：对缺列的临时 sqlite 跑一次，断言列被补上且不报错
- 前端：`npx tsc --noEmit` 通过；手动核对增/改/删/导入/不采集流程（用户启服务）

## 影响文件

- `backend/app/services/document_import.py`（新）
- `backend/app/api/pipeline.py`（articles PUT + import 端点）
- `backend/app/config.py`（`vision: ProviderCfg`）
- `backend/app/models/pipeline_run.py`（`auto_collect` 列）
- `backend/app/schemas/pipeline.py`（`auto_collect`）
- `backend/app/main.py`（lifespan「确保列存在」校验）
- `backend/app/pipeline/runner.py`（不采集分支 + S1 resume 后重载 articles.json + 空文章守卫）
- `backend/pyproject.toml`（依赖 `python-docx`、`pymupdf`）
- `frontend/src/pages/Dashboard.tsx`（S1Panel 可编辑 + ArticleDialog + ImportArticleDialog）
- `frontend/src/components/CreateRunDialog.tsx`（采集方式选项）
- `frontend/src/pages/Settings.tsx`（文档解析模型一节）
- `frontend/src/api/client.ts`（articles 编辑/导入 API + AppSettings.vision + runs.create.auto_collect）
- 测试：`backend/tests/` 新增 document_import / articles 端点 / runner 用例

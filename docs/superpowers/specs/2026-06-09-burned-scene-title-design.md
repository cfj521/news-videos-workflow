# 分镜画面标题烧录 + AI HOT 内容直用（复用评分系统）

> 设计日期：2026-06-09
> 状态：待评审（第 2 版，已纳入 subagent 评审意见）

## 背景与问题

成片画面上没有任何文字，观看者不知道"在说什么"。现有旁白字幕（narration）只在预览里出现，
**成片不烧录、走外挂 SRT**（`composition.html.j2` 顶层渲染 `display:none` 隐藏 `.subtitle`），
所以成片实际是"零文字层"。

AI HOT 信息源（日报 daily / 周报 weekly / 动态 items）本身已是**提炼好的"标题 + 摘要"结构**，
现状 stage2 却仍对它调 AI 生成脚本（daily/weekly 走 `_gen_daily_batch_scenes` 按 2~4 条分组、
items 走 `_gen_article_scenes`），属重复劳动。真正缺的是：(1) 把标题**烧进画面**；(2) 从一堆
item 里按价值**选几条**进视频。

## 目标

1. **标题烧录**：每个分镜对应标题烧到画面右上角，整组常驻、组间淡切，贯穿三条成片路线。
2. **AI HOT 直用**：AI HOT 三种模式都改为 item.title→烧录、item.summary→旁白、1 item→1 分镜，
   **不再 AI 生成旁白/脚本**（仅出图 prompt 保留一次轻量 AI 调用，见 §3）。
3. **复用评分系统选取**：用既有 `ScoringService.select_top` 选 AI HOT 的 top N，**不新造抽象**。

## 非目标（本次不做）

- 评分**算法**增强（本次只把 AI HOT 接进既有 `ScoringService`，算法另议）。
- 提要的 AI 生成（取消，源 summary 已够）。
- 普通源（RSS/网页抓取）的脚本生成流程（维持现状不变）。

---

## 关键事实校正（基于代码核对，纠正第 1 版错误假设）

| 第 1 版的错误假设 | 实际情况（代码依据） |
|---|---|
| AI HOT 直用是"分叉新增" | daily/weekly **本来就调 AI**（`stage2_script.py:163` `_gen_daily_batch_scenes`），本次是**替换**该路径 |
| 要新造 `NewsCandidate`/`ItemSelector` | 已有 `ScoringService`（`services/scoring.py:84-125`，`select_top`/`select_top_with_llm`），普通源已在用（`stage1_collect.py:78`）。**复用它** |
| 只处理 daily/weekly | 还有 **items 模式**：多篇独立 article、无 daily_sections（`aihot.py:55-63`），也要直用 |
| AI HOT 已经过评分 | AI HOT 现状**完全跳过评分**（`stage1_collect.py:65-71`：daily/weekly 取 1 篇、items 取前 N） |
| FFmpeg 也能做圆角 pill | drawtext 的 box 是**直角矩形**，圆角只有 HTML 路能做 |
| 字体是三路通用依赖 | 仅 **FFmpeg 两路**依赖字体文件；HTML 路走 CSS `font-family`（`composition.html.j2:15`） |

---

## 核心抽象：用 RawArticleData + ScoringService 作统一接缝

"把对象抽象好、评分系统能无缝接入"——其实仓库里**已有这套对象与接缝**，无需另造：

- **对象** = `RawArticleData`（全仓通用文章对象，含 title/content/summary/source_name/published_at/category/metadata）。
- **评分接缝** = `ScoringService`。AI HOT 选取直接调 `select_top(candidates, n)`；将来评分增强
  **全部发生在 `ScoringService` 内部**（一处），上层不改。

渲染层只认每个 scene 的两个字段：

- `title`：烧到画面的文字
- `group_id`：标题"常驻"的单元边界（组内不动、跨组淡切）

两类来源各自填这两个字段，渲染层不区分：

| 来源 | group（常驻单元） | title | 旁白 | 旁白脚本生成 |
|---|---|---|---|---|
| **AI HOT**（`aihot_method` 有值） | = 每条 item（1 item→1 镜） | item.title | item.summary | **不调 AI** |
| 普通源 | 现有 group（多镜共用） | group_title | 现有 narration | 维持现有 AI 生成 |

对 AI HOT 每组 1 镜 → 画面上"每镜换标题"（已确认要的效果）；普通源仍是组内常驻、组间换。

---

## 组件设计

### 1. AI HOT 候选归一 + 评分选取（stage1 + stage2）

**stage1（`stage1_collect.py`）**：仅放开 items 模式的硬截断，让 stage2 拿到完整候选池去评分。
- items 模式：`return all_articles[:max_articles]` → 改为 `return all_articles`（全量透传，选取交给 stage2）。
- daily/weekly：维持返回单篇 doc（items 在 doc 内，必须 stage2 摊平后才能评分）。

**stage2（`stage2_script.py`）新增 AI HOT 直用路径**，对 `metadata.source_group == "aihot"` 的文章：

1. **归一为候选 `list[RawArticleData]`**：
   - items 模式：article 本身即候选。
   - daily 模式：摊平 `metadata["daily_sections"]` 的每个 item，包成
     `RawArticleData(title=item["title"], content=item["summary"], summary=item["summary"],
     source_name=<父 doc 源>, published_at=<父 doc 日期>, category=section.label, metadata={})`。
   - weekly 模式：复用现有 `distill_weekly_sections` 产出的 sections，同 daily 摊平。
2. **评分选取**：`selected = ScoringService().select_top(candidates, n=cfg.pipeline.aihot_top_n)`
   （规则分，与普通源一致；零额外 LLM 调用）。**全局按分取前 N**，不按 section 配额（已确认）。
   - 将来升级：原地换成 `select_top_with_llm(...)` 即接入 LLM 评分，无其它改动。
3. **每条选中 → 1 个 scene**（按分数序）：
   - `narration = candidate.summary`
   - `title = candidate.title`，`group_title = candidate.title`，`group_id` 每条唯一、连续递增
   - `image_prompt = await _gen_image_prompt(candidate, tp)`（§3）
   - `duration_hint = 5`（默认占位，实际时长由 TTS 音频决定，见 §4 容错说明）
4. **清理**：AI HOT 不再走 `_gen_daily_batch_scenes`。该函数、`_batch_items`、`daily_batch`
   prompt 若无其它调用方则删除（`distill_weekly_sections` 保留，作为 weekly 摊平来源）。
5. **普通源分支不动**，仅在其 scene 上补 `sc["title"] = sc.get("group_title", "")`。
6. `_gen_summary_meta`（视频级 title/desc/tags）保留——一次轻量汇总调用，非逐条脚本。

### 2. 标题进 timeline（`stage4_timeline.py`）

`run_stage4` 给每个 entry 补两字段（数据已在 `narration_map` 内）：

```python
entry["title"] = scene_data.get("title") or scene_data.get("group_title", "")
entry["group_id"] = scene_data.get("group_id")
```

**不变量（显式声明）**：同 `group_id` 的 entries 在 timeline 中**必须连续**。当前成立
（scene 按 group 顺序 append、stage4 按 scene 顺序建 entry），渲染层依赖它做 group 聚合；
将来若 selector/重排打乱顺序需同步维护该不变量。

### 3. 出图 prompt：保留一次轻量 AI 生成（§目标 2 例外）

新增 `_gen_image_prompt(candidate, text_provider) -> str`：把 title+summary 转成**一句视觉画面
描述**（不是重写旁白/摘要），供文生图。每条选中 item 一次调用（≤ N 次）。

> 理由：新闻陈述句（人名/数字/政策词）直接喂文生图易出"文字海报感/无关具象物"，抽象新闻
> （政策、财报）更无可视主体，原样喂会让出图质量断崖。故保留这一步轻量转换。
> 失败兜底：返回 `candidate.title`（退化为原文，至少不挂）。

### 4. 标题烧录（三条成片路线，样式按路线分级）

**样式目标**：右上角文字块，压在任何画面上都可读。注意**圆角只有 HTML 路能做**：

- **hyperframes（HTML，`composition.html.j2` + `hyperframes_composer.py`）**——**圆角 pill**
  - composer 端按 `group_id` 把 entries 聚合为 `title_overlays = [{title, start_s, end_s}]`
    （start=组内首镜 start、end=组内末镜 end，依赖 §2 连续性不变量），传入模板。
  - 模板新增 `.group-title` 图层（右上角、半透明圆角底、白字）；每个 overlay 一个 div。
  - GSAP：在 `start_s` 淡入、`end_s - 0.3` 淡出；与现有 0.6s crossfade 转场（`j2:64-66` 在
    `entry.start_s` 触发）**对齐组边界**——组首镜 start_s 同时是旧组末镜的淡出点。
  - **关键**：`.group-title` 不进顶层渲染的隐藏列表（现隐藏逻辑按 class 只选 `.subtitle`，
    `j2:103`，天然不误伤），所以成片烧进标题；旁白仍走外挂 SRT 不变。S4 预览用同模板即可见。

- **comfyui（默认，`comfyui_composer.py` 的 `_mux_segment`）**——**直角半透明底**
  - 每段在 `vf` 中、**`tpad` 之后**追加 drawtext（否则克隆的末帧不带字）。
  - 有音频分支 `[0:v]{vf}[v]`（`comfyui_composer.py:66-68`）与无音频分支 `-vf`（`:72-74`）都要改。
  - composer 需接收 overlay 配置 + 每 entry 的 `title`。

- **FFmpeg 兜底（`runner.py` 的 `_ffmpeg_compose`）**——**直角半透明底**
  - 注意其结构是"每图一输入 + concat"（`runner.py:1021-1034`），drawtext 必须插进**每个**
    per-scene 子链 `[{vi}:v]scale...,drawtext=...[v{idx}]`，**每镜文本不同、不能共用一句**。

**drawtext 具体写法（Windows，subprocess 列表参数、非 shell）**：

```
drawtext=fontfile=C\:/Windows/Fonts/msyh.ttc:textfile=<seg.txt>:reload=0
:fontcolor=white:fontsize=H*0.035:box=1:boxcolor=black@0.45:boxborderw=12
:x=w-tw-(W*0.03):y=(H*0.03)
```
- 盘符冒号 `C:` 必须转义为 `C\:`（textfile 解决的是**文本内容**转义，**不解决路径冒号**）。
- 文本走 `textfile=`（每段写一个临时 .txt），避免 CJK / 标点在 filter 里的转义地狱。
- 字号/边距用表达式相对画面高/宽，免去逐分辨率换算。
- box 为直角（FFmpeg 无圆角），与 HTML 路的圆角 pill 视觉略有差异——接受路线分级。

### 5. 配置（`config.py` + `config.yaml.example`）

```python
class OverlayCfg(BaseModel):
    enabled: bool = True
    font_file: str = "C:/Windows/Fonts/msyh.ttc"  # 仅 FFmpeg 两路使用
    font_size_ratio: float = 0.035   # 相对画面高度
    color: str = "white"
    bg_opacity: float = 0.45
    margin_ratio: float = 0.03
```
- 新增 `overlay` 顶层段；`PipelineCfg` 增 `aihot_top_n: int = 10`。

#### CJK 字体：正式系统依赖（仅 FFmpeg 两路），写入依赖清单

FFmpeg 路烧中文**必须有真实 CJK 字体文件**，与 FFmpeg、Node.js 同级的**系统依赖**，写入
`CLAUDE.md` 的 Dependencies 段与 README：

> **CJK 字体（标题烧录，仅 FFmpeg 路）**：comfyui / FFmpeg 兜底路用 drawtext 烧标题，需一个
> 可用 CJK 字体文件。Windows 默认 `C:/Windows/Fonts/msyh.ttc`（微软雅黑，系统自带）；其它
> 平台在 `config.yaml` 的 `overlay.font_file` 指定（如 `NotoSansCJK-Regular.ttc`）。
> hyperframes(HTML) 路不依赖此项（走 CSS 字体）。

- **运行期容错（与依赖声明并存）**：字体缺失时 composer 记 warning、跳过烧录，不让整段渲染挂掉。

### 6. 前端设置页

「画面标题」开关（`overlay.enabled`）+ `aihot_top_n` 输入框，写回 `config.yaml`。

---

## 数据流（AI HOT）

```
AI HOT 文章
  ├ items：多篇 article（stage1 全量透传）
  └ daily/weekly：单篇 doc（含 sections）
  → stage2 归一为 RawArticleData 候选池
  → ScoringService.select_top(候选, n=aihot_top_n)  ← 评分接缝，将来在此升级
  → 每条 → 1 scene {title=item.title, narration=item.summary, image_prompt=轻量AI, group_id 唯一}
  → S3 出图 / TTS 读 summary
  → S4 timeline entry 带 title+group_id（output.srt 旁白不变）
  → S5 三路渲染：右上角烧 title（HTML 圆角 / FFmpeg 直角），AI HOT 每镜换
```

## 容错

- 候选为空 / 不足 N：`select_top` 返回实际条数，不报错。
- AI HOT 文章无 daily_sections 且非 items：回退普通源分支。
- `_gen_image_prompt` 失败：退化为用 `candidate.title` 当 image_prompt。
- 字体缺失：FFmpeg 两路记 warning、跳过烧录，照常出片；HTML 路不受影响。
- 标题为空：该镜不绘制 drawtext / 不生成 overlay div。
- `duration_hint` 在有 TTS 音频时不生效（时长跟随音频，`stage4_timeline.py:48-50`），仅占位。

## 测试

- `stage2` AI HOT：三模式各构造候选并选 min(N, 候选数) 条；每 scene 字段齐全
  （title/narration/group_id 连续）；**旁白未调 text_provider**（mock 断言 narration 直接等于
  summary；注意 `_gen_image_prompt` 与 `_gen_summary_meta` 仍会调 AI，断言时区分）。
- `stage2` 普通源：仍调 AI 且补了 `sc["title"]`。
- `stage1`：items 模式全量透传（不再 `[:max_articles]`）。
- `stage4`：entry 带 title + group_id；同 group 连续性。
- composer：drawtext 参数拼装（含 Windows 路径 `C\:` 转义、字体缺失容错分支）；
  hyperframes `title_overlays` 在"每组 1 镜"与"每组多镜"两种下聚合正确。
- 集成 smoke：用真实 `msyh.ttc` 跑 1 帧 drawtext，断言 ffmpeg 退出码 0（最高风险点必测）。

## 影响文件

- 改：`stage1_collect.py`（items 透传）、`stage2_script.py`（AI HOT 直用 + 调 ScoringService +
  `_gen_image_prompt`）、`stage4_timeline.py`、`comfyui_composer.py`、`hyperframes_composer.py`、
  `templates/composition.html.j2`、`runner.py`(`_ffmpeg_compose`)、`config.py`、
  `config.yaml.example`、前端设置页。
- 复用（不改）：`services/scoring.py`、`news_scoring` prompt。
- 可能删除：`_gen_daily_batch_scenes` / `_batch_items` / `daily_batch` prompt（确认无其它调用方后）。
- 文档：`CLAUDE.md` Dependencies + README，新增 CJK 字体依赖（仅 FFmpeg 路）条目。
```

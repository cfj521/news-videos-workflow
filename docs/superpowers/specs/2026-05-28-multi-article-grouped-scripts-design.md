# S2 多文章分组脚本 + 自由增删分镜（Phase B）— 设计文档

## 背景与目标

更大功能的 **Phase B**（接续 Phase A：S1 文章可编辑/导入）。当前 Stage2 只给 `articles[0]`（top-1 文章）生成一份扁平脚本——不符合预期。本期改为：

- 一次运行采集/导入的**全部文章**（最多 `max_articles`）都生成分镜，每篇一组。
- AI HOT daily：按 category 把 items 批成 **2~4 条/组（不跨类目）**，每组每条 **1 分镜**。
- S2 面板按组展示分镜；每组可**自由增删分镜**，每组 **≥1**。
- 整条视频是多条资讯的**汇总片**，标题/简介由 LLM 综合生成。

**前置依赖**：本分支叠在 Phase A 分支（`feat/editable-importable-articles`）之上，会扩展 A 期的 aihot daily collector 与文章持久化链路。

## 非目标 (YAGNI)

- 不改 Stage3/4/5：它们已按扁平 `script["scenes"]` + `scene["id"]` 工作；分组只是展示/生成层的元数据。
- 新增分镜不自动生成图片/配音：生成 narration+提示词后，由现有 SceneEditor 的「重新配音/重新生成图片」按钮产出资产。
- daily 分组采用**结构化持久化（方案 A）**，不依赖 LLM 临场分组。

## 数据模型（script.json）

仍是扁平 `scenes`，新增分组元数据：

```json
{
  "title": "汇总标题（LLM 综合）",
  "description": "汇总简介",
  "tags": ["..."],
  "groups": [{"id": 1, "title": "文章标题/类目标签", "source_index": 0}],
  "scenes": [
    {"id": 1, "group_id": 1, "group_title": "...", "narration": "...", "image_prompt": "...", "motion_prompt": "...", "duration_hint": 5}
  ]
}
```

- `scene.id` 全局唯一（资产命名 `scene_{id:02d}` 不变，Stage3/4/5 不改）。
- `scene.group_id` / `group_title`：分组归属与显示名。
- 顶层 `groups[].source_index`：指向该组对应的 articles.json 下标，供「新增分镜」取该组源内容。
- `title/description/tags`：汇总级（LLM 综合生成）。

## Stage2 编排（`backend/app/pipeline/stage2_script.py`）

- **保留** `run_stage2(article, …, style="single")`（单篇→完整视频脚本；现有测试不破，但 Phase B 主流程不再用它——避免删除引发的连带改动）。
- **新增紧凑提示词** `ROUNDUP_ARTICLE_SYSTEM_PROMPT`：定位"汇总片里的单条资讯"，明确要求**每篇只出 1~3 个分镜**（不是 30-90 秒完整片）。`run_stage2_multi` 的普通/items 分支用它，**不复用** `SCRIPT_SYSTEM_PROMPT`（那个会产出过多分镜）。
- **新增** `run_stage2_multi(articles, text_provider, language) -> dict`：
  - **普通/items 文章**：每篇 = 一组。对每篇用 `ROUNDUP_ARTICLE_SYSTEM_PROMPT` 调 LLM（限 1~3 分镜）→ 分镜；分配全局递增 `id` 与 `group_id`，`group_title = article.title`，`groups[].source_index = 该文章下标`。
  - **daily 文章**（`metadata["aihot_method"] == "daily"`）：读 `metadata["daily_sections"]`（结构化，见下）。对每个 section（类目），把 `items` 按顺序切成 **2~4 条/批**（不跨类目）；每批 = 一组（`group_title` = 类目标签，若一个类目拆多批则加序号如「类目 (2)」）。每批一次 LLM 调用，产出该批每条 items 对应 **1 个分镜**（narration + image_prompt + motion_prompt）。`source_index` 指向该 daily 文章下标（0）。
  - **汇总元数据**：末尾一次 LLM 综合调用，依据所有分镜/文章标题生成汇总 `title`/`description`/`tags`。
  - 分镜 `id` 全局唯一、连续分配；`groups` 按生成顺序。
- **runner** `_run_inner` 的 Stage2：把 `article = articles[0]; run_stage2(article, …)` 改为 `script = await run_stage2_multi(articles, text_provider, language=cfg.pipeline.default_language)`（用全部文章）。`daily_mode`/`style` 的单篇逻辑由 `run_stage2_multi` 内部按 metadata 分流取代。
- **regen-script**（`backend/app/api/pipeline.py` 的 `regen_script`）：A 期它调 `run_stage2(articles_raw[0], …)` 单篇。本期改为读**全部** articles.json → 映射为 RawArticleData 列表（复用 `_article_from_dict`，含 `daily_sections`）→ `run_stage2_multi(articles, …)`，与主流程一致；不再取 `[0]` 单篇。

## daily 结构化持久化（方案 A plumbing）

- **aihot daily collector**（`backend/app/providers/collector/aihot.py`）：`_collect_daily` 除现有扁平 `content` 外，在 `metadata["daily_sections"]` 存 `[{ "label": str, "items": [{"title","summary","sourceUrl","sourceName"}] }]`（即日报 sections 原结构）。
- **`_save_articles`**（`backend/app/pipeline/runner.py`）：保存每篇时，若 `a.metadata.get("daily_sections")` 存在则在 articles.json 该篇 dict 写入 `"daily_sections": [...]`。
- **`_article_from_dict`**（runner.py）：若 dict 含 `daily_sections`，还原到 `metadata["daily_sections"]`。
- 这样 daily 文章经 S1 review/reload 后仍带结构化数据，供 `run_stage2_multi` 确定性分组。

## 分镜增删端点（`backend/app/api/pipeline.py`）

- `POST /runs/{run_id}/scenes` body `{group_id: int, requirement?: str}`：
  - 读 script.json，定位 `groups` 中 `id==group_id` 的组，取其 `source_index` → 读 articles.json 该篇内容。
  - LLM 基于该组源内容 + 用户 `requirement` 生成 **1 个新分镜**（narration + image_prompt + motion_prompt）。
  - 分配新全局 `id = max(existing ids) + 1`，`group_id`/`group_title` 沿用该组；插入到该组最后一个分镜之后。
  - 写回 script.json，返回新分镜对象（图片/配音由前端随后调现有 regen 端点生成）。
- `DELETE /runs/{run_id}/scenes/{scene_id}`：
  - 守卫：若该分镜是其 `group_id` 组内**最后 1 个** → 400「每组至少保留 1 个分镜」。
  - 否则从 script.json `scenes` 移除并写回；返回更新后的 script。

## 前端 S2 分组 UI（`frontend/src/pages/Dashboard.tsx` 的 `S2Panel`）

- 按 `group_id`（首次出现顺序）把 `script.scenes` 分组；每组渲染一个**组标题头**（`group_title`）。
- 组内：现有 `SceneEditor` 逐分镜渲染（旁白/提示词/重配音/重生图保持）；每个 SceneEditor 增加「删除」按钮——调 `DELETE /scenes/{id}`，组内仅剩 1 个时禁用并提示。
- 每组底部「+ 新增分镜」：弹小对话框填「新分镜要求（选填）」→ `POST /scenes {group_id, requirement}` → `mutate` 刷新；新分镜出现后用户可点其「重新生成图片/配音」。
- 顶部仍显示汇总 `title`/`description`。
- `frontend/src/api/client.ts`：`api.runs` 加 `addScene(runId, groupId, requirement)`、`deleteScene(runId, sceneId)`；`ScriptData` 类型加 `groups` 与 scene 的 `group_id`/`group_title`。

## 数据流

```
普通源/items run: [文章...] → run_stage2_multi → 每篇一组(1~3分镜) + 汇总标题 → 扁平 scenes(带 group) → Stage3/4/5
AI HOT daily run: [日报(带 daily_sections)] → run_stage2_multi → 按类目 2~4/组、每条1分镜 + 汇总标题 → 扁平 scenes(带 group) → Stage3/4/5
S2 增删: POST/DELETE /scenes → 改 script.json scenes（每组≥1）→ 重生该分镜图片/配音
```

## 测试计划

- `run_stage2_multi`（mock TextProvider 返回固定分镜 JSON）：
  - 多篇普通文章 → 每篇一组、每组 1~3 分镜、`id` 全局唯一且连续、`group_id`/`source_index` 正确。
  - daily（构造 `metadata["daily_sections"]` 多类目多 item）→ 每类目按 2~4 切组、不跨类目、每条 1 分镜。
  - 汇总 `title/description` 来自综合调用。
- daily 持久化：collector 产出含 `daily_sections`；`_save_articles`→articles.json→`_article_from_dict` 往返保活。
- 端点：`POST /scenes` 追加新 id 并归入该组（mock LLM）；`DELETE /scenes` 守卫每组 ≥1（删最后一个→400）。
- 前端：`npx tsc --noEmit` + `pnpm build` 通过；手动核对分组展示、新增（填要求）、删除（≥1 拦截）。
- 回归：`run_stage2`（单篇）现有测试仍通过；Stage3/4 用例不受影响。

## 影响文件

- `backend/app/pipeline/stage2_script.py`（`run_stage2_multi` + daily 分组 + 综合标题）
- `backend/app/pipeline/runner.py`（Stage2 改调 multi；`_save_articles`/`_article_from_dict` 携带 `daily_sections`）
- `backend/app/providers/collector/aihot.py`（daily 存 `daily_sections`）
- `backend/app/api/pipeline.py`（POST/DELETE /scenes）
- `frontend/src/pages/Dashboard.tsx`（S2Panel 分组 + 增删 + 新增对话框）
- `frontend/src/api/client.ts`（addScene/deleteScene + ScriptData 类型）
- 测试：`backend/tests/` 新增 stage2_multi / daily 持久化 / scenes 端点用例

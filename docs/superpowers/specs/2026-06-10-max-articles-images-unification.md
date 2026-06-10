# max_articles 统一 top-N + max_images 按评分裁剪

> 设计日期：2026-06-10
> 状态：待评审

## 背景与问题

评分系统接入后，"控制进入视频的内容条数"出现两处不一致：

1. **top-N 旋钮分裂**：普通源 stage1 用 `run.max_articles` 作 `select_top` 的 n；但 AI HOT 直用（stage2 `_run_aihot_direct`）用的是另一个全局配置 `pipeline.aihot_top_n`（默认 10），且创建弹窗在 AI HOT 摘要模式下**隐藏了"最大文章数"**。一个语义两个旋钮，覆盖不准确。
2. **max_images 超限靠 AI 合并**：当分镜数 > `max_images` 时，runner 调 `replan_scenes_to_limit` 用 AI 把分镜合并到上限。对 AI HOT 这会把"1 item→1 镜 + 右上角标题"的映射合并掉、破坏标题；且没有复用刚建好的评分系统。

## 目标

1. **统一 top-N**：`run.max_articles` 作为唯一的内容条数旋钮，普通源与 AI HOT 都用它；删除 `aihot_top_n`。
2. **max_images 按评分裁剪**：分镜数超 `max_images` 时，按评分**重取 top N**（丢弃低分整组），不再 AI 合并。
3. **弹窗布局调整**：右列重排，"最大文章数"不再对 AI HOT 隐藏。

## 非目标

- 不改评分公式 / 选取逻辑本身（沿用现有 `ScoringService.select_top`）。
- scoring.json 不回溯标注被 max_images 裁掉的分镜（它反映评分阶段选取；max_images 是下游成本裁剪，二者解耦）。

---

## 组件设计

### 1. max_articles 统一为 top-N

- **`run_stage2_multi`（stage2_script.py）增形参 `max_articles`**；`_run_aihot_direct` 的 `top_n` 改为该 `max_articles`（不再读 `config.get_settings().pipeline.aihot_top_n`）。
- **runner** 调 `run_stage2_multi(articles, text_provider, language=..., max_articles=run.max_articles)`。
- **删除 `aihot_top_n`**：`PipelineCfg`（config.py）、`config.yaml.example`；更新引用它的 stage2 测试（改用 `run_stage2_multi(..., max_articles=N)` 注入）。
- 普通源 stage1 已用 `max_articles`，不变。

语义：`run.max_articles` = "进入视频的内容条数上限"（普通源=文章数，AI HOT=item 数）。

### 2. 分镜携带分数

S2 构造每个 scene 时附 `score` 字段（float，缺省 0.0）：
- **AI HOT**（`_run_aihot_direct`）：`score = cand.metadata.get("score_final", 0.0)`（`select_top` 已把 `score_final` 写入选中候选 metadata）。
- **普通源**（`run_stage2_multi` 文章分支 `_gen_article_scenes` 回填处）：`sc["score"] = article.metadata.get("score_final", 0.0)`（`score_final` 现随 articles.json 往返持久化，stage2 重载后仍在）。

### 3. `cap_scenes_by_score(script, limit)` 替换 `replan_scenes_to_limit`

新函数（stage2_script.py，同步纯函数，无 AI 调用）：
1. `limit <= 0` 或 `len(scenes) <= limit` → 原样返回。
2. 按 `group_id` 聚合分镜成组（保持组内顺序）；每组分数 = 组内分镜 `score` 的最大值。
3. 按组分数降序决定**保留哪些组**：累计分镜数 + 该组分镜数 ≤ limit 才保留，否则淘汰整组（不拆组）。
   - 边界：若按分数排最高的组分镜数就 > limit（极端，如该组 5 镜但 limit=3），则保留该组并截断到 limit 镜（避免空结果）。
4. **保留原始顺序**输出：被保留的分镜按它们在原 script 中的先后排列（只是把被淘汰组的分镜剔除，不打乱叙事/不按分数重排）；`id`/`group_id` 从 1 连续重编；同步重建 `groups` 列表。
5. 返回新 script（其余字段如 title/description/tags/scoring_report 透传）。

- AI HOT（1 item→1 镜）：等价于取前 `limit` 高分 item。
- 普通源（1 文章→1~3 镜）：丢掉低分整篇文章的分镜，文章内分镜不拆。

### 4. runner 接线

`runner.py` 约 634-639 把：
```python
limit = run.max_images if run.max_images is not None else cfg.pipeline.max_images
if run.video_route != "audio" and limit and len(script.get("scenes", [])) > limit:
    from app.pipeline.stage2_script import replan_scenes_to_limit
    script = await replan_scenes_to_limit(script, limit, text_provider, language=...)
```
换成：
```python
limit = run.max_images if run.max_images is not None else cfg.pipeline.max_images
if run.video_route != "audio" and limit and len(script.get("scenes", [])) > limit:
    from app.pipeline.stage2_script import cap_scenes_by_score
    _update(db, run, progress_detail=f"S2 分镜 {len(script['scenes'])} 超图片上限 {limit}，按评分裁剪...")
    script = cap_scenes_by_score(script, limit)   # 同步、无 AI
```
（不再需要 text_provider/language。）

### 5. 删除死代码

`replan_scenes_to_limit`（stage2_script.py）+ `scene_replan` 的 `PromptDef`（prompts.py，确认无其它调用方后）。相关 `_batch_items` 早已删。

### 6. 创建弹窗右列布局（CreateRunDialog.tsx）

现状右列：运行模式|路线 → 最多图片|语言 → 分辨率 → 采集方式 → (非AI HOT摘要时) 时间范围|最大文章数。

调整为：
- **运行模式 | 音视频路线**（不变）
- **最多图片数 | 最大文章数**（最大文章数移到此行右侧，加 hint，如"评分后进入视频的内容条数上限"）
- **分辨率**（不变）
- **采集方式**（不变）
- **语言 | 时间范围**（语言下移到此行左侧；时间范围上移到此行右侧）

规则：
- **"最大文章数"始终显示**（去掉 `isAihotDigest` 隐藏；AI HOT 摘要模式也能设）。
- **"时间范围"仍对 AI HOT 摘要模式隐藏**（该模式选具体日/周，时间范围无意义）；隐藏时"语言"独占该行（右侧留空或语言占满）。
- 最多图片数的 hint 文案由"超过则生图前 AI 重规划，合并零碎/短文章"改为"超过则按评分裁掉低分内容到此数量"。

---

## 数据流（max_images 裁剪）

```
S2 产出 scenes（每镜带 score，已大致按源评分降序）
  → runner: len(scenes) > min 隐含的 max_images?
  → cap_scenes_by_score(script, max_images)：按组分数降序贪心保留 ≤ limit
  → S3 出图/TTS 只处理保留的分镜
```
AI HOT 生效条数 = `min(max_articles, max_images)`（max_images 为硬性成本上限）。

## 容错

- `score` 缺失默认 0.0（不崩，排序退化为原序靠后）。
- 单组分镜数 > limit 的极端：保留该组前 limit 镜，不返回空。
- limit=0（不限制）：cap 不触发（runner 的 `limit and ...` 守卫）。

## 测试

- `cap_scenes_by_score`：
  - AI HOT 形态（每组 1 镜）→ 取前 limit 高分。
  - 普通源形态（每组多镜）→ 丢低分整组、组内不拆、id/group_id 连续。
  - `len ≤ limit` 原样返回；单组超 limit 截断保 1 组；空/limit≤0。
- `run_stage2_multi(max_articles=N)`：AI HOT 选 min(N, 候选) 条；scene 带 `score`。
- 普通源 scene 带 `score`（来自 article.score_final）。
- 删除 `aihot_top_n` 后 config 默认与旧测试更新。

## 影响文件

- 改：`backend/app/pipeline/stage2_script.py`（run_stage2_multi 加 max_articles + scene 附 score + cap_scenes_by_score + 删 replan_scenes_to_limit）、
  `backend/app/pipeline/runner.py`（传 max_articles + 换 cap 调用）、
  `backend/app/config.py`（删 PipelineCfg.aihot_top_n）、`config.yaml.example`（删 aihot_top_n）、
  `backend/app/prompts.py`（删 scene_replan PromptDef）、
  `frontend/src/components/CreateRunDialog.tsx`（右列布局 + 最大文章数不隐藏 + hint）
- 测试：`test_stage2_multi.py`（aihot 测试改用 max_articles 注入 + 新 cap 测试）、`test_prompts.py`（prompt 数量）、`test_config.py`（无 aihot_top_n）
- 删除：`replan_scenes_to_limit` + `scene_replan` prompt

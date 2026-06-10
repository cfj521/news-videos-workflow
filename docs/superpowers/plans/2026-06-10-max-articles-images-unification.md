# max_articles 统一 + max_images 按评分裁剪 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `run.max_articles` 成为唯一的内容条数旋钮（含 AI HOT，删 `aihot_top_n`），并把 max_images 超限处理从"AI 合并分镜"改为"按评分丢弃低分整组"（复用评分），同时调整创建弹窗右列布局。

**Architecture:** 新增同步纯函数 `cap_scenes_by_score(script, limit)` 替换 `replan_scenes_to_limit`（按 group_id 聚合→组分数降序→保留高分组前缀直到 ≤limit→保留原序、id 重编）。分镜在 S2 携带 `score`（来自源 `score_final`）。`run_stage2_multi` 增 `max_articles` 形参贯通到 AI HOT 选取。

**Tech Stack:** Python/FastAPI、pytest（`D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest`，conda env env_news_videos_wf）、React+Vite+TS。

设计依据：`docs/superpowers/specs/2026-06-10-max-articles-images-unification.md`

---

## 文件结构

- `backend/app/pipeline/stage2_script.py` — 新增 `cap_scenes_by_score`；删 `replan_scenes_to_limit`；`run_stage2_multi` 加 `max_articles` 形参；scene 附 `score`；`_run_aihot_direct` 用 max_articles
- `backend/app/pipeline/runner.py` — 传 max_articles；max_images 处换 `cap_scenes_by_score`
- `backend/app/api/pipeline.py` — `regen_script` 传 max_articles（AI HOT top-N 正确）
- `backend/app/config.py` + `config.yaml.example` — 删 `aihot_top_n`
- `backend/app/prompts.py` — 删 `scene_replan` PromptDef
- `frontend/src/components/CreateRunDialog.tsx` — 右列布局 + 最大文章数不隐藏 + hint

---

## Task 1: cap_scenes_by_score + 删 replan + 删 scene_replan prompt

**Files:** Modify `backend/app/pipeline/stage2_script.py`、`backend/app/prompts.py`; Test `backend/tests/test_stage2_multi.py`、`backend/tests/test_prompts.py`

- [ ] **Step 1: 写失败测试**（追加到 `test_stage2_multi.py`）

```python
from app.pipeline.stage2_script import cap_scenes_by_score


def _scene(i, gid, score, gtitle="g"):
    return {"id": i, "group_id": gid, "group_title": gtitle, "title": gtitle,
            "narration": f"n{i}", "image_prompt": "p", "motion_prompt": "", "duration_hint": 5, "score": score}


def test_cap_noop_when_within_limit():
    script = {"scenes": [_scene(1, 1, 0.9), _scene(2, 2, 0.8)], "groups": []}
    assert cap_scenes_by_score(script, 5) is script         # ≤limit 原样返回
    assert cap_scenes_by_score(script, 0) is script         # limit=0 不裁


def test_cap_aihot_takes_top_by_score():
    # 每组 1 镜（AI HOT 形态）→ 取前 limit 高分
    scenes = [_scene(i, i, score) for i, score in [(1, 0.3), (2, 0.9), (3, 0.5), (4, 0.7)]]
    out = cap_scenes_by_score({"scenes": scenes, "groups": []}, 2)
    assert len(out["scenes"]) == 2
    # 保留的是 score 0.9 与 0.7 那两组，且按原始顺序（id2 在 id4 之前）
    assert [s["score"] for s in out["scenes"]] == [0.9, 0.7]
    assert [s["id"] for s in out["scenes"]] == [1, 2]        # id 连续重编
    assert [s["group_id"] for s in out["scenes"]] == [1, 2]


def test_cap_normal_drops_whole_low_group():
    # 三组多镜（普通源形态）：A组(score0.9,2镜) B组(0.5,2镜) C组(0.8,1镜)，limit=3
    scenes = [_scene(1, 1, 0.9), _scene(2, 1, 0.9), _scene(3, 2, 0.5), _scene(4, 2, 0.5), _scene(5, 3, 0.8)]
    out = cap_scenes_by_score({"scenes": scenes, "groups": []}, 3)
    # 按组分数降序前缀：A(0.9,2镜)→累计2；C(0.8,1镜)→累计3；B(0.5) 放不下→停。保留 A、C，丢整个 B。
    assert len(out["scenes"]) == 3
    kept_titles = {(s["narration"]) for s in out["scenes"]}
    assert "n3" not in kept_titles and "n4" not in kept_titles   # B 组(原 id3/4)被整组丢弃
    assert [s["id"] for s in out["scenes"]] == [1, 2, 3]          # 连续重编
    # 保留原序：A 的两镜在 C 之前
    assert [s["narration"] for s in out["scenes"]] == ["n1", "n2", "n5"]


def test_cap_single_group_over_limit_truncates():
    # 最高分组单组就超 limit → 截断该组到 limit（避免空结果）
    scenes = [_scene(1, 1, 0.9), _scene(2, 1, 0.9), _scene(3, 1, 0.9), _scene(4, 2, 0.2)]
    out = cap_scenes_by_score({"scenes": scenes, "groups": []}, 2)
    assert len(out["scenes"]) == 2
    assert all(s["score"] == 0.9 for s in out["scenes"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_stage2_multi.py -k cap_ -v`
Expected: FAIL（`cap_scenes_by_score` 不存在）

- [ ] **Step 3: 实现 `cap_scenes_by_score`**（替换 `replan_scenes_to_limit`）

在 `stage2_script.py` 删除整个 `async def replan_scenes_to_limit(...)` 函数，新增：

```python
def cap_scenes_by_score(script: dict, limit: int) -> dict:
    """分镜数超 limit 时，按组分数降序保留高分组前缀(不拆组)，淘汰低分整组；保留原序、id/group_id 连续重编。

    无 AI 调用。≤limit 或 limit<=0 原样返回。最高分组单组就超 limit 时截断该组到 limit（避免空）。
    """
    from collections import OrderedDict
    scenes = script.get("scenes", [])
    if limit <= 0 or len(scenes) <= limit:
        return script

    groups_map: "OrderedDict[object, list]" = OrderedDict()
    for sc in scenes:
        groups_map.setdefault(sc.get("group_id"), []).append(sc)
    # (gid, members, 组分数=组内最大 score)
    group_list = [(gid, members, max((s.get("score", 0.0) for s in members), default=0.0))
                  for gid, members in groups_map.items()]

    # 按分数降序取前缀：累计 ≤ limit 才保留，遇到放不下的组即停（丢弃它及其后更低分的组）
    kept_gids: set = set()
    total = 0
    for gid, members, _ in sorted(group_list, key=lambda x: x[2], reverse=True):
        if total + len(members) > limit:
            break
        kept_gids.add(gid)
        total += len(members)

    if kept_gids:
        kept_scenes = [sc for sc in scenes if sc.get("group_id") in kept_gids]   # 保留原序
    else:
        # 最高分组单组就超 limit → 截断该组到 limit
        top_gid, top_members, _ = max(group_list, key=lambda x: x[2])
        kept_scenes = top_members[:limit]

    # id/group_id 连续重编；重建 groups
    new_scenes: list[dict] = []
    new_groups: list[dict] = []
    gid_remap: dict = {}
    for sc in kept_scenes:
        old_gid = sc.get("group_id")
        if old_gid not in gid_remap:
            gid_remap[old_gid] = len(gid_remap) + 1
            new_groups.append({"id": gid_remap[old_gid], "title": sc.get("group_title", ""),
                               "source_index": len(new_groups)})
        new_scenes.append({**sc, "id": len(new_scenes) + 1, "group_id": gid_remap[old_gid]})

    log.info("[S2] cap scenes %d → %d (limit %d)", len(scenes), len(new_scenes), limit)
    return {**script, "scenes": new_scenes, "groups": new_groups}
```

- [ ] **Step 4: 删 scene_replan prompt** — `prompts.py` 删除 `scene_replan` 的 `PromptDef`（确认 `grep -rn "scene_replan\|replan_scenes_to_limit" backend/app backend/tests` 除测试外无残留调用）。`config.py` 的 `PromptsCfg` 若有 `scene_replan`/`scene_replan_en` 字段也删（仿之前 daily_batch 清理）。`test_prompts.py` 里若断言 prompt 数量/含 scene_replan 的地方同步更新（数量 -1）。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_stage2_multi.py tests/test_prompts.py -v`
Expected: PASS（cap 测试 + prompt 测试；原 `test_replan_*` 测试若存在需删除，因 replan 已删）

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline/stage2_script.py backend/app/prompts.py backend/app/config.py backend/tests/test_stage2_multi.py backend/tests/test_prompts.py
git commit -m "feat(stage2): cap_scenes_by_score 按评分裁剪分镜，替换 AI 合并 replan"
```
（commit message 末尾统一加 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`，后续同。）

---

## Task 2: scene 附 score + run_stage2_multi(max_articles) + AI HOT 用 max_articles

**Files:** Modify `backend/app/pipeline/stage2_script.py`; Test `backend/tests/test_stage2_multi.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
@pytest.mark.asyncio
async def test_run_stage2_max_articles_controls_aihot_topn(monkeypatch):
    import app.services.scoring as scoring
    scoring._LLM_CACHE.clear()
    tp = AsyncMock()
    # 3 候选评分 + 选中 2 条出图 + meta（top_n 由 max_articles=2 控制）
    tp.generate.side_effect = ['{"score": 9, "reason": "", "tags": []}',
                               '{"score": 5, "reason": "", "tags": []}',
                               '{"score": 7, "reason": "", "tags": []}',
                               "画面A", "画面B",
                               json.dumps({"title": "汇总", "description": "d", "tags": []})]
    daily = RawArticleData(title="日报", content="c", source_url="u", source_name="AI HOT 日报",
        metadata={"source_group": "aihot", "aihot_method": "daily", "report_date": "2026-06-01",
                  "daily_sections": [{"label": "模型", "items": [{"title": f"i{i}", "summary": f"s{i}"} for i in range(3)]}]})
    script = await run_stage2_multi([daily], tp, max_articles=2)
    assert len(script["scenes"]) == 2                       # max_articles 控制 top-N
    assert all("score" in s for s in script["scenes"])      # AI HOT 分镜带 score


@pytest.mark.asyncio
async def test_run_stage2_normal_scene_carries_score():
    tp = AsyncMock()
    tp.generate.side_effect = [_scenes_json("a1"), json.dumps({"title": "t", "description": "d", "tags": []})]
    art = RawArticleData(title="文章1", content="c", source_url="u", source_name="s",
                         metadata={"score_final": 0.66})
    script = await run_stage2_multi([art], tp)
    assert script["scenes"][0]["score"] == 0.66             # 普通源 scene 取 article.score_final
```
（`_scenes_json` 助手在该文件已存在；若 aihot_top_n 还被旧测试引用，本任务会删它们的依赖——见下。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_stage2_multi.py -k "max_articles or carries_score" -v`
Expected: FAIL（run_stage2_multi 无 max_articles 形参 / scene 无 score）

- [ ] **Step 3: 实现** —
(a) `run_stage2_multi` 签名加 `max_articles`：
```python
async def run_stage2_multi(articles: list, text_provider, language: str = "zh", max_articles: int = 5) -> dict:
    if articles and articles[0].metadata.get("source_group") == "aihot":
        return await _run_aihot_direct(articles, text_provider, language, max_articles)
```
(b) 普通源分支：scene 回填处加 score（`stage2_script.py` 约 207 行 `sc["title"] = article.title` 之后）：
```python
            sc["score"] = float(article.metadata.get("score_final") or 0.0)
```
(c) `_run_aihot_direct` 签名加 `max_articles`，用它当 top_n，并给 scene 附 cand 分数：
```python
async def _run_aihot_direct(articles, tp, language="zh", max_articles=5):
    candidates = _aihot_candidates(articles)
    res = await ScoringService().select_top(candidates, tp, language, n=max_articles)
    selected = res.selected
    scenes, groups, titles = [], [], []
    for i, cand in enumerate(selected, start=1):
        image_prompt = await _gen_image_prompt(cand, tp, language)
        scenes.append({"id": i, "group_id": i, "group_title": cand.title, "title": cand.title,
                       "narration": cand.summary or cand.content, "image_prompt": image_prompt,
                       "motion_prompt": "", "duration_hint": 5,
                       "score": float(cand.metadata.get("score_final") or 0.0)})
        groups.append({"id": i, "title": cand.title, "source_index": 0})
        titles.append(cand.title)
    meta = await _gen_summary_meta(titles, tp, language)
    return {"title": meta["title"], "description": meta["description"], "tags": meta["tags"],
            "groups": groups, "scenes": scenes, "scoring_report": res.report}
```
（删除原来读 `config.get_settings().pipeline.aihot_top_n` 那行；`config` import 若不再使用可保留——下面 Task 3 删 aihot_top_n 字段，stage2 不再引用它。）

(d) 更新引用 `aihot_top_n` 的旧测试：把 `test_aihot_daily_direct_use` / `test_aihot_items_direct_use` / `test_aihot_image_prompt_fallback_to_title` / `test_aihot_direct_uses_scoring_and_reports` 里通过 `config.PipelineCfg(aihot_top_n=N)` 注入 top_n 的写法，改成 `run_stage2_multi(..., max_articles=N)` 注入（不再依赖 aihot_top_n）。逐个修到断言成立。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_stage2_multi.py -v`
Expected: PASS（含旧 aihot 测试改用 max_articles 后）

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/stage2_script.py backend/tests/test_stage2_multi.py
git commit -m "feat(stage2): max_articles 统一控制 AI HOT top-N；分镜携带 score"
```

---

## Task 3: 删除 aihot_top_n 配置

**Files:** Modify `backend/app/config.py`、`config.yaml.example`; Test `backend/tests/test_config.py`

- [ ] **Step 1: 确认无残留引用**

Run: `cd backend && grep -rn "aihot_top_n" app/ ../config.yaml.example ../frontend/src`
Expected: 仅 `config.py:113`（定义）+ `config.yaml.example`。stage2 在 Task 2 已不再引用。若 frontend 有引用，记录待 Task 5 处理（大概率没有）。

- [ ] **Step 2: 写/改测试** — `test_config.py` 若有断言 `aihot_top_n` 的测试，删除该断言。新增一条确保它不存在：
```python
def test_pipeline_cfg_has_no_aihot_top_n():
    from app.config import PipelineCfg
    assert not hasattr(PipelineCfg(), "aihot_top_n")
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_config.py -k aihot_top_n -v`
Expected: FAIL（字段仍存在）

- [ ] **Step 4: 实现** — 删 `config.py` 的 `PipelineCfg.aihot_top_n` 那一行（约 113）；删 `config.yaml.example` 里 `pipeline:` 段的 `aihot_top_n` 行（若有）。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py config.yaml.example backend/tests/test_config.py
git commit -m "refactor(config): 删除 aihot_top_n（top-N 统一由 max_articles 控制）"
```

---

## Task 4: runner / regen_script 接线

**Files:** Modify `backend/app/pipeline/runner.py`、`backend/app/api/pipeline.py`; Test `backend/tests/test_runner_articles.py`（回归即可，主要靠全量）

- [ ] **Step 1: 实现 runner**（`runner.py` 约 630-640）

把 stage2 调用与 max_images 处理改为：
```python
        from app.pipeline.stage2_script import run_stage2_multi
        script = await run_stage2_multi(
            articles, text_provider, language=(run.language or cfg.pipeline.default_language),
            max_articles=run.max_articles)

        # 图片数量上限：分镜数超过则按评分裁掉低分整组（仅出图路线需要）
        limit = run.max_images if run.max_images is not None else cfg.pipeline.max_images
        if run.video_route != "audio" and limit and len(script.get("scenes", [])) > limit:
            from app.pipeline.stage2_script import cap_scenes_by_score
            _update(db, run, progress_detail=f"S2 分镜 {len(script['scenes'])} 超图片上限 {limit}，按评分裁剪...")
            log.info("[S2] %d scenes > limit %d → cap by score", len(script["scenes"]), limit)
            script = cap_scenes_by_score(script, limit)
```
（去掉对 `replan_scenes_to_limit` 的 import 与 await；`cap_scenes_by_score` 是同步函数。）

- [ ] **Step 2: 实现 regen_script**（`api/pipeline.py` 的 `regen_script`，约 355-375）

把 `run_stage2_multi(arts, tp, language=...)` 调用加上 `max_articles=run.max_articles`；并在写 script.json 前同样按 max_images 裁剪（保持与主流程一致）：
```python
        script = await run_stage2_multi(arts, tp, language=lang, max_articles=run.max_articles)
        limit = run.max_images if run.max_images is not None else cfg.pipeline.max_images
        if run.video_route != "audio" and limit and len(script.get("scenes", [])) > limit:
            from app.pipeline.stage2_script import cap_scenes_by_score
            script = cap_scenes_by_score(script, limit)
```
（按 regen_script 现有变量名 `arts`/`tp`/`lang`/`run`/`cfg`/`rd` 调整；`cfg` 若没有则 `get_settings()`。`_write_scoring_json(rd, script.get("scoring_report"))` 那行保持。）

- [ ] **Step 3: 全量回归**

Run: `cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest -q`
Expected: PASS（重点 test_runner_*、test_stage2_multi、test_api_pipeline；replan 相关旧测试已在 Task 1 删除）

- [ ] **Step 4: Commit**

```bash
git add backend/app/pipeline/runner.py backend/app/api/pipeline.py
git commit -m "feat(runner): 传 max_articles 控制 top-N；max_images 改按评分裁剪"
```

---

## Task 5: 创建弹窗右列布局

**Files:** Modify `frontend/src/components/CreateRunDialog.tsx`

- [ ] **Step 1: 调整右列布局**

先读 `CreateRunDialog.tsx` 右列（约 357-439）。把右列改为以下顺序（仿现有 `grid grid-cols-2 gap-3` / `Select` / `input` 写法，不引新依赖）：

1. **运行模式 | 音视频路线**（不变）
2. **最多图片数 | 最大文章数**（同一 `grid grid-cols-2`）：
   - 最多图片数：input 不变，hint 文案改为 `超过则按评分裁掉低分内容到此数量`。
   - 最大文章数：把原来 `时间范围|最大文章数` 行里的"最大文章数" input 移来此处右侧，**去掉 `isAihotDigest` 隐藏**（始终显示），加 hint `评分后进入视频的内容条数上限`（min 1 / max 20）。
3. **分辨率**（不变）
4. **采集方式**（不变）
5. **语言 | 时间范围**（同一 `grid grid-cols-2`）：
   - 语言：把原来 `最多图片|语言` 里的"语言" Select + hint 移来此处左侧。
   - 时间范围：把原"时间范围"移来此处右侧；**仍仅在 `autoCollect && !isAihotDigest` 时显示**（AI HOT 摘要模式选具体日/周，时间范围无意义）。当时间范围不显示时，让"语言"占满该行（如外层条件渲染：显示时 `grid-cols-2` 两列、不显示时语言单列）。

实现提示：原 `{autoCollect && !isAihotDigest && (<div>时间范围|最大文章数</div>)}` 整块拆解——最大文章数移到第 2 行（无条件显示）、时间范围移到第 5 行（条件 `autoCollect && !isAihotDigest`）。第 5 行可写成：
```tsx
<div className="grid grid-cols-2 gap-3 mb-5">
  <div>{/* 语言 Select + hint */}</div>
  {autoCollect && !isAihotDigest && (
    <div>{/* 时间范围 Select */}</div>
  )}
</div>
```

- [ ] **Step 2: 校验**

Run: `cd frontend && pnpm build`（pnpm 不可用试 npm run build）
Expected: build 成功、无类型错误；`pnpm lint` 不引入新错误（对比改动前）。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/CreateRunDialog.tsx
git commit -m "feat(ui): 创建弹窗右列重排——最大文章数不再隐藏、语言/时间范围同行"
```

---

## 收尾验证

- [ ] 全后端：`cd backend && D:/miniconda/envs/env_news_videos_wf/python.exe -m pytest -q` 全绿
- [ ] 前端：`cd frontend && pnpm build` 通过
- [ ] 手动冒烟（用户自跑后端）：AI HOT 日报 run 设 max_articles=N → 出 N 个分镜；设 max_images < N → 裁到 max_images 个高分；普通源 run 分镜超 max_images → 丢低分整篇文章而非 AI 合并；弹窗右列布局正确、AI HOT 摘要模式也显示"最大文章数"。
